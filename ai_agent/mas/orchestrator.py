import subprocess
import sys
import time
import os
import json
from pathlib import Path
from typing import List, Dict, Any
from .config_loader import AgentConfig
from .communication import MessageBus
from .network_manager import TorManager, setup_agent_env
from ..agent import TenaciousOllama, build_agent, extract_reply

class MasterAgent:
    def __init__(self, config: AgentConfig, bus: MessageBus, tor: TorManager, workspace: Path):
        self.config = config
        self.bus = bus
        self.tor = tor
        self.workspace = workspace
        self.slave_processes: Dict[str, subprocess.Popen] = {}
        self.task_assignments: Dict[str, str] = {} # slave_id -> task_description
        self.reassignment_counts: Dict[str, int] = {} # task_description -> count

    def discover_slaves(self):
        """Used by promoted Masters to find existing slave processes without re-launching them."""
        print(f"[Master {self.config.id}] 🔍 RECONNECTING WITH SQUAD...")
        for slave_config in self.config.slaves:
            status = self.bus.get_agent_status(slave_config.id)
            if status.get("status") not in ["died", "offline"]:
                print(f"[Master {self.config.id}] Re-linked with active slave: {slave_config.id}")
                # Mark as known. The cycle will monitor via status if proc is None
                self.slave_processes[slave_config.id] = None

    def launch_slaves(self):
        for i, slave_config in enumerate(self.config.slaves):
            # Slaves are level + 1 relative to Master
            proxy = self.tor.get_proxy_for_agent(slave_config.id, self.config.level + 1, i) if self.tor else None
            env = setup_agent_env(proxy) if proxy else os.environ.copy()
            
            # Pass Coworker List
            coworkers = [s.id for s in self.config.slaves if s.id != slave_config.id]
            env["COWORKERS"] = ",".join(coworkers)
            
            # Launch as a module to handle relative imports correctly
            engine_root = Path(__file__).parent.parent.parent.resolve()
            env["PYTHONPATH"] = str(engine_root)
            
            proxy = self.tor.get_proxy_for_agent(slave_config.id, slave_config.level, i) if self.tor else None
            env = setup_agent_env(proxy) if proxy else env
            
            if slave_config.slaves:
                # Sub-masters run run_mas.py
                cmd = [sys.executable, str(engine_root / "run_mas.py"), "--id", slave_config.id, "--parent", self.config.id, "--level", str(slave_config.level)]
                if not self.tor: cmd.append("--no-tor")
            else:
                # Workers run as modules
                cmd = [
                sys.executable, "-m", "ai_agent.mas.worker",
                "--id", slave_config.id,
                "--parent", self.config.id,
                "--level", str(slave_config.level),
                "--model", slave_config.model,
                "--ollama-url", slave_config.api_url,
                "--ollama-key", slave_config.api_key
            ]
                if not self.tor: cmd.append("--no-tor")
            
            print(f"[Master {self.config.id}] Launching Slave {slave_config.id} {'on ' + proxy if proxy else '(Direct)'}")
            # print(f"[Debug] Command: {' '.join(cmd)}")
            # print(f"[Debug] Env Proxy: {env.get('HTTP_PROXY')}")
            
            # Ensure the worker can find the ai_agent module
            project_root = str(Path(__file__).parent.parent.parent.absolute())
            existing_pythonpath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{project_root}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else project_root
            
            proc = subprocess.Popen(cmd, env=env, cwd=self.workspace)
            self.slave_processes[slave_config.id] = proc

    def split_task(self, task_description: str) -> List[Dict[str, Any]]:
        """Use the Master's LLM to split the task into sub-tasks."""
        print(f"[Master {self.config.id}] 🏛️ CALCULATING MISSION ARCHITECTURE...")
        
        # Ensure brain is ready
        self._ensure_brain()
        
        manifest = self.task_assignments
        prompt = (
            f"You are the Root Master of a Multi-Agent Resilient System. Your goal: {task_description}\n\n"
            f"CURRENT TASK MANIFEST (Status of Slaves):\n{json.dumps(manifest, indent=2)}\n\n"
            f"AVAILABLE SLAVES: {[s.id for s in self.config.slaves]}\n\n"
            "MANDATORY ARCHITECTURE PROTOCOL:\n"
            "1. CHECK THE MANIFEST: If a slave is already in the manifest, they are WORKING. Do NOT re-assign them. Simply note their task as 'PENDING'.\n"
            "2. ASSIGN ONLY IDLE SLAVES: Only create NEW tasks for slaves who are not in the manifest.\n"
            "3. ANALYZE & SUMMARIZE: Analyze the project structure and write your architectural summary to 'project_analysis.md' ONLY if it needs update.\n"
            "4. OUTPUT FORMAT: Return ONLY a JSON list of NEW objects for idle slaves: [{\"slave_id\": \"id\", \"task\": \"detailed instruction\"}].\n"
            "If all slaves are busy, return an empty list []."
        )
        
        try:
            print(f"[Master {self.config.id}] 🧠 CONSULTING BRAIN FOR STRATEGY...")
            result = self.master_agent.invoke({"input": prompt})
            reply = extract_reply(result)
            # Try to parse JSON from the reply
            import re
            json_match = re.search(r"\[.*\]", reply, re.DOTALL)
            if json_match:
                sub_tasks = json.loads(json_match.group(0))
                print(f"[Master {self.config.id}] 📋 STRATEGY ARCHITECTED. Preparing for deployment.")
                return sub_tasks
        except Exception as e:
            print(f"[Master {self.config.id}] ⚠️ ARCHITECTURE FATAL ERROR: {e}")
            raise e

    def _ensure_brain(self):
        """Ensure the Master's AI brain is initialized."""
        if not hasattr(self, 'master_agent') or self.master_agent is None:
            self.master_agent = build_agent(
                work_dir=self.workspace,
                agent_id=self.config.id,
                model=self.config.model,
                api_url=self.config.api_url,
                api_key=self.config.api_key,
                parent_id="USER"
            )

    def run_cycle(self, main_task: str):
        self._ensure_brain()
        self.start_time = time.time()
        self.wipeout_limit = 6 * 3600 # 6 hours
        self.emergency_threshold = 5.5 * 3600 # 5.5 hours
        
        self.bus.update_status(self.config.id, "active", main_task)
        
        print(f"[Master {self.config.id}] 🛡️ SQUAD VERIFICATION: Waiting for Slaves to report in...")
        active_slaves = set()
        v_start = time.time()
        # Wait up to 60 seconds for roll-call to allow for Tor proxy latency
        while len(active_slaves) < len(self.slave_processes) and (time.time() - v_start) < 60:
            # We check ALL pending messages
            messages = self.bus.get_messages(self.config.id)
            for msg in messages:
                if msg.get("type") == "status_report":
                    sid = msg.get("from")
                    if sid not in active_slaves:
                        print(f"[Master {self.config.id}] ✅ PROOF OF LIFE: {sid} is ACTIVE and COORDINATED.")
                        active_slaves.add(sid)
            time.sleep(0.5)

        print(f"[Master {self.config.id}] 🚀 SQUAD READY ({len(active_slaves)}/{len(self.slave_processes)}).")
        
        # RESUMPTION LOGIC: Check if this is a continuation of a previously saved mission
        manifest_path = self.bus.base_dir / "global_task_manifest.json"
        if manifest_path.exists():
            print(f"[Master {self.config.id}] 📂 EXISTING MISSION DETECTED. Resuming from manifest...")
            with open(manifest_path, "r") as f:
                self.task_assignments = json.load(f)
            # Restore personal task
            self.master_task = self.task_assignments.get(self.config.id)
            print(f"[Master {self.config.id}] Successfully restored {len(self.task_assignments)} active assignments. Waking up squad...")
            # Re-notify slaves of their tasks so they can start immediately on the new VM
            for sid, task in self.task_assignments.items():
                if sid != self.config.id:
                    self.bus.send_message(self.config.id, sid, task, msg_type="task_assignment")
        else:
            print(f"[Master {self.config.id}] 🏛️ COMMENCING NEW MISSION ARCHITECTURE...")
            sub_tasks = self.split_task(main_task)
            self.master_task = None
            for sub in sub_tasks:
                sid = sub["slave_id"]
                if sid == self.config.id:
                    self.master_task = sub["task"]
                    print(f"[Master {self.config.id}] 🛠️ Internalizing personal task: {self.master_task}")
                    continue
                
                self.task_assignments[sid] = sub["task"]
                self.bus.send_message(self.config.id, sid, sub["task"], msg_type="task_assignment")
            
            # Save manifest for future resumption
            with open(manifest_path, "w") as f:
                json.dump(self.task_assignments, f)
        
        while True:
            # Check for wipe-out (with 10-minute safety buffer for false alarms)
            elapsed = time.time() - self.start_time
            if elapsed > 600 and elapsed > self.emergency_threshold:
                self.trigger_emergency_save(reason=f"6-hour wipe-out approaching ({int(elapsed)}s elapsed)")
                break

            # Check for failed processes
            failed_slaves = []
            for slave_id, proc in list(self.slave_processes.items()):
                if proc is None:
                    # Promoted Master path: Monitor via status timestamp
                    status = self.bus.get_agent_status(slave_id)
                    last_update = status.get("last_update", 0)
                    if last_update > 0 and (time.time() - last_update > 30):
                        print(f"[Master {self.config.id}] Inherited slave {slave_id} has gone SILENT (30s). Reassigning.")
                        failed_slaves.append(slave_id)
                        del self.slave_processes[slave_id]
                    continue

                ret = proc.poll()
                if ret is not None:
                    print(f"[Master {self.config.id}] Slave {slave_id} exited with code {ret}. Task needs reassignment.")
                    failed_slaves.append(slave_id)
                    del self.slave_processes[slave_id]

            for failed_id in failed_slaves:
                task_to_resume = self.task_assignments.pop(failed_id, None)
                if task_to_resume:
                    count = self.reassignment_counts.get(task_to_resume, 0)
                    if count >= 3:
                        print(f"[Critical] Task '{task_to_resume[:30]}' failed {count} times. CIRCUIT BREAKER TRIGGERED.")
                        # Alert user via WhatsApp if possible
                        self.bus.send_message(self.config.id, "USER", f"CRITICAL: Task '{task_to_resume}' failed too many times. Manual intervention required.", msg_type="emergency_alert")
                        continue
                    self.reassignment_counts[task_to_resume] = count + 1
                
                self.handle_slave_failure(failed_id, task_to_resume)

            # 1. Check for incoming reports
            new_reports = self.bus.get_messages(self.config.id)
            if new_reports:
                print(f"[Master {self.config.id}] 📝 PROCESSING NEW REPORTS FROM SQUAD...")
                for msg in new_reports:
                    if msg["type"] == "task_report":
                        slave_id = msg["from"]
                        print(f"[Master {self.config.id}] Received report from {slave_id}")
                        self.bus.send_message(self.config.id, slave_id, "Task Approved", msg_type="task_approval")
                        # Remove from assignments once approved
                        if slave_id in self.task_assignments:
                            del self.task_assignments[slave_id]
                    elif msg["type"] == "limit_reached":
                        error_reason = msg.get("content", {}).get("error", "Unknown Limit")
                        print(f"[Master {self.config.id}] Slave {msg['from']} DIED. Reason: {error_reason}")
                        task_to_resume = self.task_assignments.pop(msg["from"], None)
                        self.handle_slave_failure(msg["from"], task_to_resume)
                
                # PASSIVE MONITORING MODE: Forbid the Master from re-architecting
                manifest = self.task_assignments
                prompt = (
                    f"PASSIVE MONITORING MODE ACTIVE:\n"
                    f"- Active Assignments: {json.dumps(manifest, indent=2)}\n"
                    f"- New Reports: {json.dumps(new_reports, indent=2)}\n\n"
                    "RULES:\n"
                    "1. CHECK ASSIGNMENTS: Compare the list of team members with the 'Active Assignments'. If a slave is NOT in the active manifest, you MUST assign them a modular task using 'send_mas_message'.\n"
                    "2. NO REDUNDANCY: You are FORBIDDEN from re-assigning or messaging slaves who are already in the 'Active Assignments' list with the same task.\n"
                    "3. If a slave is DONE or FAILED, remove them from the manifest and assign a NEW objective.\n"
                    "4. COMMIT ENFORCEMENT: Remind slaves to use 'git_commit_and_push' (or commit) after every successful change.\n"
                    "5. NO OVER-ANALYSIS: Do NOT re-analyze the project structure. Focus on keeping all slaves productive and their code committed."
                )
                if self.master_task:
                    prompt += f"\nALSO, continue your personal task: {self.master_task}. Use tools to write code."
                
                result = self.master_agent.invoke({"input": prompt})
                print(f"[Master {self.config.id}] Monitoring cycle complete.")
            
            # Periodically work on personal task even if no reports (every 10 minutes to avoid spam)
            elif self.master_task and (time.time() - getattr(self, 'last_personal_work', 0) > 600):
                self.last_personal_work = time.time()
                print(f"[Master {self.config.id}] 🛠️ Working on personal task...")
                result = self.master_agent.invoke({"input": f"Continue working on your personal task: {self.master_task}. Keep improving the code based on the project analysis."})
                print(f"[Master {self.config.id}] Task progress: {extract_reply(result)[:100]}...")

            # Prevent CPU/API spam with a loop sleep
            time.sleep(5)

            # 2. Update Master heartbeat
            self.bus.update_status(self.config.id, "active")

            # 3. Check if all tasks are completed
            if not self.task_assignments and not self.slave_processes:
                print(f"[Master {self.config.id}] MISSION COMPLETE. All sub-tasks finished and verified.")
                self.bus.update_status(self.config.id, "completed")
                break


    def handle_slave_failure(self, failed_id: str, task_to_resume: str = None):
        healthy_coworkers = [sid for sid, proc in self.slave_processes.items() if proc.poll() is None]
        
        if not healthy_coworkers:
            print(f"[Critical] No healthy coworkers to take over for {failed_id}!")
            return

        target_id = healthy_coworkers[0]
        
        if task_to_resume:
            print(f"[Master {self.config.id}] Reassigning task '{task_to_resume[:30]}...' to {target_id}")
            # Pass the failed agent's ID so the new one can load history
            self.bus.send_message(self.config.id, target_id, {
                "failed_agent_id": failed_id,
                "task": task_to_resume,
                "instruction": "Resume this task using the history from the failed agent."
            }, msg_type="task_assignment")
            self.task_assignments[target_id] = task_to_resume
        else:
            # Generic takeover for sub-masters
            self.bus.send_message(self.config.id, target_id, {
                "failed_agent_id": failed_id,
                "new_master_id": target_id,
                "instruction": "Inherit slaves and tasks from the failed coworker."
            }, msg_type="takeover_command")

    def trigger_emergency_save(self, reason: str = "Unknown"):
        """Force all slaves to save and push work immediately."""
        print(f"[Master {self.config.id}] TRIGGERING EMERGENCY SAVE. Reason: {reason}")
        for sid in self.slave_processes:
            self.bus.send_message(self.config.id, sid, {"reason": reason}, msg_type="emergency_alert")
        
        # Master's own save
        
        # Give slaves a moment to push
        print(f"[Master {self.config.id}] Emergency Save complete. Shutting down system safely.")

    def shutdown_squad(self):
        """Normal shutdown when mission is complete."""
        print(f"[Master {self.config.id}] Shutting down squad normally.")
        for sid in list(self.slave_processes.keys()):
            self.bus.send_message(self.config.id, sid, "Mission Complete", msg_type="shutdown")
            proc = self.slave_processes.pop(sid)
            proc.terminate()

    def resolve_conflicts(self, slave_a: str, slave_b: str):
        """Logic for two slaves to discuss and fix overlaps."""
        print(f"[Master {self.config.id}] Initiating conflict resolution between {slave_a} and {slave_b}")
        self.bus.send_message(self.config.id, slave_a, f"Conflict detected with {slave_b}. Discuss.", msg_type="conflict_notice")
        self.bus.send_message(self.config.id, slave_b, f"Conflict detected with {slave_a}. Discuss.", msg_type="conflict_notice")
