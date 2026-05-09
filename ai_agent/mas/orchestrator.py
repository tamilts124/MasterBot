from typing import Optional
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
from ai_agent.mas.agent import build_agent, extract_reply
import re

class MasterAgent:
    @staticmethod
    def get_leader_directive(goal: str, is_succession: bool = False, leader_id: str = None) -> str:
        header = f"Leadership Succession to {leader_id} complete. " if (is_succession and leader_id) else "Initial Mission Start. "
        succession_clause = (
            "\n[SUCCESSION PROTOCOL ACTIVE]\n"
            "You have inherited this leadership role. You must immediately run 'get_task_manifest' to see the full state of the squad. "
            "Some tasks from your predecessor may have been moved to you personally. Check your task list and lead the remaining squad to victory."
            if is_succession else ""
        )
        return (
            f"URGENT: {header}You are the Root Master of a Multi-Agent Resilient System. Your goal: {goal}\n"
            f"{succession_clause}\n"
            "MANDATORY ARCHITECTURE PROTOCOL:\n"
            "1. SLAVE COMMAND & INDIVIDUAL MONITORING: If you have slaves, you must command them with clear, detailed requirements. You are responsible for monitoring their progress INDIVIDUALLY by frequently checking 'get_task_manifest' and 'check_agent_status'.\n"
            "2. TEAM COLLABORATION: Instruct your slaves to work together and communicate directly using 'ask_coworker' or 'send_mas_message'. They should not operate in silos; encourage them to share findings and coordinate their efforts.\n"
            "3. REVIEW & FEEDBACK: When a worker reports their work, review it carefully. If there are issues, explain the corrections clearly so they can fix them.\n"
            "4. PERSONAL RESPONSIBILITY: You may also be assigned direct coding tasks. Be attentive to your own coding responsibilities while monitoring the squad.\n"
            "5. TOOL UTILIZATION: You have access to many powerful tools. Use them extensively to accomplish most of the work.\n\n"
            "You are the authority. LEAD."
        )

    def __init__(self, config: AgentConfig, bus: MessageBus, tor: TorManager, workspace: Path, config_path: str = None, parent_id: str = None):
        self.config = config
        self.bus = bus
        self.tor = tor
        self.workspace = workspace
        self.config_path = config_path
        self.parent_id = parent_id
        self.slave_processes: Dict[str, subprocess.Popen] = {}
        self.reassignment_counts: Dict[str, int] = {} # task_description -> count
        self.abdicated = False
        self.master_row_id = None
        self.project_root = str(Path(__file__).parent.parent.parent.absolute())
        
        existing_pythonpath = os.environ.get("PYTHONPATH", "")
        self.target_pythonpath = f"{self.project_root}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else self.project_root

    def discover_slaves(self):
        """Used by promoted Masters to find existing slave processes without re-launching them."""
        print(f"[Master {self.config.id}] 🔍 RECONNECTING WITH SQUAD...")
        for slave_config in self.config.slaves:
            info = self.bus.get_agents(slave_config.id)
            if info and info.get("status") == "live":
                print(f"[Master {self.config.id}] Re-linked with active slave: {slave_config.id}")
                # Mark as known. The cycle will monitor via status if proc is None
                self.slave_processes[slave_config.id] = None

    def launch_slaves(self):
        for i, slave_config in enumerate(self.config.slaves):
            # Slaves are level + 1 relative to Master
            proxy = self.tor.get_proxy_for_agent(slave_config.id, self.config.level + 1, i) if self.tor else None
            env = setup_agent_env(proxy) if proxy else os.environ.copy()
            
            # Ensure the worker can find the ai_agent module
            env["PYTHONPATH"] = self.target_pythonpath
            
            if slave_config.slaves:
                # Sub-masters run run_mas.py
                cmd = [sys.executable, str(Path(self.project_root) / "run_mas.py"), "--id", slave_config.id, "--parent", self.config.id, "--level", str(slave_config.level)]
                if self.config_path:
                    cmd.extend(["--config", self.config_path])
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
                "--ollama-key", ",".join(slave_config.api_keys)
            ]
                if not self.tor: cmd.append("--no-tor")
            
            # Set parent for all slaves
            env["PARENT_ID"] = self.config.id
            
            print(f"[Master {self.config.id}] Launching Slave {slave_config.id} {'on ' + proxy if proxy else '(Direct)'}")
            
            proc = subprocess.Popen(cmd, env=env, cwd=self.workspace)
            self.slave_processes[slave_config.id] = proc

    def split_task(self, task_description: str) -> List[Dict[str, Any]]:
        """Use the Master's LLM to split the task into sub-tasks."""
        print(f"[Master {self.config.id}] 🏛️ CALCULATING MISSION ARCHITECTURE...")
        
        # Ensure brain is ready
        self._ensure_brain()
        
        # Get real-time status from DB for all agents
        manifest = self.bus.get_all_agents_task_status()
        leader_prompt = self.get_leader_directive(task_description)
        
        prompt = (
            f"{leader_prompt}\n\n"
            f"LIVE SQUAD STATUS (Real-time Database Manifest):\n{json.dumps(manifest, indent=2)}\n\n"
            f"AVAILABLE SLAVES (Static Config): {[s.id for s in self.config.slaves]}\n"
        )
        
        try:
            print(f"[Master {self.config.id}] 🧠 CONSULTING BRAIN FOR STRATEGY...")
            result = self.master_agent.invoke({"input": prompt})
            reply = extract_reply(result)
            # Try to parse JSON from the reply
            json_match = re.search(r"\[.*\]", reply, re.DOTALL)
            if json_match:
                sub_tasks = json.loads(json_match.group(0))
                print(f"[Master {self.config.id}] 📋 STRATEGY ARCHITECTED. Preparing for deployment.")
                return sub_tasks
            
            print(f"[Master {self.config.id}] ⚠️ ARCHITECTURE WARNING: No valid task JSON found in brain reply. Retrying...")
            return []
        except Exception as e:
            print(f"[Master {self.config.id}] ⚠️ ARCHITECTURE FATAL ERROR: {e}")
            return [] # Return empty instead of raising to allow the cycle to retry or wait

    def _ensure_brain(self):
        """Ensure the Master's AI brain is initialized."""
        if not hasattr(self, 'master_agent') or self.master_agent is None:
            os.environ["AGENT_ID"] = self.config.id
            self.master_agent = build_agent(
                work_dir=self.workspace,
                model_name=self.config.model,
                ollama_url=self.config.api_url,
                ollama_key=self.config.api_key,
                api_keys=self.config.api_keys,
                is_master=True
            )

    def run_cycle(self, main_task: Optional[str] = None):
        self._ensure_brain()
        self.start_time = time.time()
        
        # 2. Autonomous Leadership Cycle
        last_cycle_time = 0
        while True:
            # Busy-Wait Throttle
            if time.time() - last_cycle_time < 2:
                continue
            last_cycle_time = time.time()

            # Check Pulse: Detect hardware/OS failures of managed slaves
            for slave_id, proc in list(self.slave_processes.items()):
                if proc and proc.poll() is not None:
                    print(f"[Master {self.config.id}] ⚠️ Slave {slave_id} process DIED. Initiating automatic recovery...")
                    self.bus.update_agent(slave_id, status="died")
                    
                    # AUTOMATIC RECOVERY: Find tasks and reassign before the next brain cycle
                    tasks = self.bus.get_agent_task_status(agent_id=slave_id)
                    active = [t for t in (tasks or []) if isinstance(t, dict) and t.get("status") == "inprogress"]
                    task_to_resume = active[-1]["task"] if active else None
                    
                    self.handle_slave_failure(slave_id, task_to_resume)
                    del self.slave_processes[slave_id]

            # 2. Consult Brain (Autonomous Leadership)
            manifest = self.bus.get_agent_task_status(assigner_id=self.config.id)
            leader_directive = self.get_leader_directive(main_task)
            
            prompt = (
                f"{leader_directive}\n\n"
                f"SQUAD MANIFEST:\n"
                f"{json.dumps(manifest, indent=2)}\n\n"
                "SQUAD STATUS ALERT:\n"
                "1. If any slave is 'died', reassign their work immediately using 'handle_slave_failure'.\n"
                "2. Lead the squad toward the mission goal. You have total authority."
            )
            
            print(f"[Master {self.config.id}] 🧠 COMMANDER is leading...")
            try:
                self.master_agent.invoke({"input": prompt})
            except Exception as e:
                print(f"[Master {self.config.id}] 🧠 Brain Error during leadership: {e}")
                # Don't abdicate yet, let the loop retry unless it's fatal
                if "status code: 429" in str(e).lower():
                    # If we have no more keys to rotate, then we abdicate
                    if len(self.config.api_keys) <= 1:
                         raise e # This will trigger abdication in the outer runner
                time.sleep(5)
                continue

            # 3. Check for Mission Completion
            all_tasks = self.bus.get_agent_task_status(assigner_id=self.config.id)
            if all_tasks: # Only complete if we actually assigned something
                incomplete = [t for t in all_tasks if isinstance(t, dict) and t.get("status") != "completed"]
                if not incomplete:
                    print(f"[Master {self.config.id}] MISSION COMPLETE. All sub-tasks verified as COMPLETED in Database.")
                    self.bus.update_agent_task_status(self.config.id, "completed", row_id=self.master_row_id)
                    break

    def handle_slave_failure(self, failed_id: str, task_to_resume: str = None):
        # Find healthy coworkers, handling both managed subprocesses and inherited agents
        healthy_coworkers = []
        for sid, proc in self.slave_processes.items():
            if sid == failed_id:
                continue
            if proc is None:
                # Inherited agent: check DB status
                agent_info = self.bus.get_agents(sid)
                if agent_info.get("status") != "died":
                    healthy_coworkers.append(sid)
            elif proc.poll() is None:
                # Managed subprocess: check OS poll
                healthy_coworkers.append(sid)
        
        if not healthy_coworkers:
            print(f"[Master {self.config.id}] ⚠️ NO HEALTHY COWORKERS. Taking over all tasks from {failed_id} personally.")
            self.bus.reassign_all_tasks(failed_id, self.config.id)
            return

        target_id = healthy_coworkers[0]
        
        # BULK TAKEOVER: Move all incomplete tasks in the database
        print(f"[Master {self.config.id}] 📂 BULK TAKEOVER: Moving all pending work from {failed_id} to {target_id}")
        self.bus.reassign_all_tasks(failed_id, target_id)
        
        if task_to_resume:
            print(f"[Master {self.config.id}] Reassigning primary task '{task_to_resume[:30]}...' to {target_id}")
            msg_text = (
                f"The agent {failed_id} is died. As Master, I have assigned his in-progress and pending tasks to you. "
                f"Please finish your current tasks first, then proceed with these inherited tasks. The primary inherited task is: {task_to_resume}. "
                "Once you complete all your own and these inherited tasks, your mission is complete."
            )
            self.bus.send_message(self.config.id, target_id, msg_text, need_reply=True)
        else:
            # Generic takeover for complex roles
            msg_text = (
                f"The agent {failed_id} is died. As Master, I have assigned all his responsibilities and pending tasks to you in the database. "
                "Finish your current responsibilities first, then check your task list to take over for that branch of the squad."
            )
            self.bus.send_message(self.config.id, target_id, msg_text, need_reply=True)

    def trigger_emergency_save(self, reason: str = "Unknown"):
        """Force all slaves to save and push work immediately."""
        print(f"[Master {self.config.id}] TRIGGERING EMERGENCY SAVE. Reason: {reason}")
        for sid in self.slave_processes:
            self.bus.send_message(self.config.id, sid, {"reason": reason})
        
        # Master's own save
        
        # Give slaves a moment to push
        print(f"[Master {self.config.id}] Emergency Save complete. Shutting down system safely.")

    def shutdown_squad(self):
        """Normal shutdown when mission is complete."""
        print(f"[Master {self.config.id}] Shutting down squad normally.")
        for sid in list(self.slave_processes.keys()):
            self.bus.send_message(self.config.id, sid, "Mission Complete")
            proc = self.slave_processes.pop(sid)
            proc.terminate()

    def resolve_conflicts(self, slave_a: str, slave_b: str):
        """Logic for two slaves to discuss and fix overlaps."""
        print(f"[Master {self.config.id}] Initiating conflict resolution between {slave_a} and {slave_b}")
        self.bus.send_message(self.config.id, slave_a, f"Conflict detected with {slave_b}. Discuss.")
        self.bus.send_message(self.config.id, slave_b, f"Conflict detected with {slave_a}. Discuss.")
