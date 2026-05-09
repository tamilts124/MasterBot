import argparse
import sys
import time
import json
import os
import subprocess
from pathlib import Path
from typing import Any, List, Dict, Optional
from .communication import MessageBus
from ..agent import build_agent, extract_reply

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--parent", required=True)
    parser.add_argument("--level", type=int, default=1)
    parser.add_argument("--model", default="qwen3-coder:480b-cloud")
    parser.add_argument("--ollama-url", default="https://ollama.com")
    parser.add_argument("--ollama-key", default="")
    parser.add_argument("--no-tor", action="store_true")
    args = parser.parse_args()
    
    # Set Identity immediately for logging and retries
    os.environ["AGENT_ID"] = args.id

    proxy_url = os.environ.get("HTTP_PROXY")
    if proxy_url:
        print(f"[Worker {args.id}] 🛡️ PROXY ACTIVE: {proxy_url}")

    comm_dir = Path(".mas").absolute()
    bus = MessageBus(comm_dir)
    
    # PROOF OF LIFE: Announce presence to Master
    bus.send_message(args.id, args.parent, {"status": "ready"})
    print(f"[Worker {args.id}] 📣 Sent READY signal to {args.parent}")
    
    print(f"[Worker {args.id}] Started. Reporting to {args.parent}")
    
    # Coworker Discovery
    coworkers = os.environ.get("COWORKERS", "").split(",")
    coworkers = [c for c in coworkers if c]

    history_file = comm_dir / f"history_{args.id}.json"
    if not history_file.exists():
        with open(history_file, "w") as f:
            json.dump([], f)

    def log_history(event_type: str, data: Any):
        with open(history_file, "r") as f:
            history = json.load(f)
        history.append({
            "timestamp": time.time(),
            "type": event_type,
            "data": data
        })
        with open(history_file, "w") as f:
            json.dump(history, f)

    def broadcast_limit_reached(error_msg: str):
        print(f"[Worker {args.id}] Broadcast: LIMIT REACHED. Error: {error_msg}")
        hierarchy_str = os.environ.get("MAS_HIERARCHY")
        agents = set()
        if hierarchy_str:
            try:
                h_map = json.loads(hierarchy_str)
                def extract(d):
                    for k, v in d.items():
                        agents.add(k)
                        for child in v:
                            extract(child)
                extract(h_map)
            except: pass
        agents.update(coworkers)
        agents.add(args.parent)
        if args.id in agents:
            agents.remove(args.id)
            
        for c in agents:
            if c == args.parent:
                bus.send_message(args.id, c, {"error": error_msg, "status": "died"}, need_reply=False)
            else:
                bus.send_message(args.id, c, f"Agent {args.id} is down. Error: {error_msg}", need_reply=False)

    def handle_emergency(msg_type: str, reason: str = "Unknown"):
        """Panic-Commit and Exit."""
        print(f"[Worker {args.id}] 🚨 EMERGENCY SHUTDOWN: {reason}. Pushing changes...")
        try:
            subprocess.run(["git", "add", "."], check=True)
            subprocess.run(["git", "commit", "-m", f"Emergency Save ({args.id}): {reason}"], check=True)
            subprocess.run(["git", "push", "origin", "main"], check=True)
            print(f"[Worker {args.id}] ✅ Panic-Commit successful. Goodbye.")
        except:
            print(f"[Worker {args.id}] ⚠️ Panic-Commit failed. Exiting anyway.")
        sys.exit(0)

    def become_master(bus, coworkers):
        """Transformation logic for a Slave to become a Master."""
        print(f"[Worker {args.id}] 👑 TRANSFORMING INTO ROOT MASTER...")
        from .orchestrator import MasterAgent
        from .config_loader import load_config
        
        # Broadcast leadership
        for c in coworkers:
            bus.send_message(args.id, c, {"new_master": args.id})
        bus.update_agent_task_status(args.id, "inprogress")

        # Load hierarchy and start Master Cycle
        # Path is .. because worker is running in mas_workspace
        config_path = Path("..") / "mas_config.json"
        if not config_path.exists():
            # Fallback for different run configurations
            config_path = Path("mas_config.json")
            
        full_config = load_config(str(config_path))
        def find_self(cfg, target_id):
            if cfg.id == target_id: return cfg
            for s in cfg.slaves:
                res = find_self(s, target_id)
                if res: return res
            return None
        
        my_config = find_self(full_config, args.id)
        if my_config:
            new_master = MasterAgent(my_config, bus, None, Path(".."))
            new_master.discover_slaves()
            try:
                # We need to find the original goal. In worker, we can try to find it from the manifest
                # or just use a generic 'Resume current mission' if not available.
                original_goal = "Resume current mission"
                manifest_path = comm_dir / "global_task_manifest.json"
                if manifest_path.exists():
                    try:
                        with open(manifest_path, "r") as f:
                            manifest = json.load(f)
                            # The Master's task usually represents the main goal or is in the manifest
                            original_goal = manifest.get("MISSION_GOAL", original_goal)
                    except: pass

                succession_directive = MasterAgent.get_leader_directive(original_goal, is_succession=True, leader_id=args.id)
                new_master.run_cycle(succession_directive)
            except Exception as e:
                print(f"[Master {args.id}] Critical transformation failure: {e}")
        sys.exit(0)

    last_heartbeat = 0
    last_cycle_time = 0
    last_log_state = None
    while True:
        # NO SLEEP - Rule #1 Compliance (Busy-Wait Throttle)
        if time.time() - last_cycle_time < 1:
            continue
        last_cycle_time = time.time()
        
        # 1. Master Watchdog (With Stale Detection)
        master_status = bus.get_agent_task_status(args.parent)
        # FAST-TRACK PROMOTION: Assume dead if silent for > 10 seconds
        last_seen = master_status.get("last_update", 0)
        is_stale = (last_seen > 0 and time.time() - last_seen > 10)
        
        if master_status.get("status") in ["died", "offline"] or is_stale:
            # Election: Am I the alpha slave? (Calculated early to avoid NameError)
            all_candidates = sorted([args.id] + coworkers)
            alpha_id = all_candidates[0]
            
            # IMMEDIATE PROMOTION - No wait
            # Use a combined state key so the two messages don't fight and cause spam
            state_key = f"promotion_{args.parent}_{is_stale}_{alpha_id}"
            if last_log_state != state_key:
                print(f"[Worker {args.id}] ⚠️ MASTER {args.parent} FAILURE/SILENCE. Initiating Self-Promotion...")
                last_log_state = state_key
            
            if args.id == alpha_id:
                # Check if I'm the ONLY survivor
                living_peers = []
                for peer in coworkers:
                    if bus.get_agent_task_status(peer).get("status") not in ["died", "offline"]:
                        living_peers.append(peer)
                
                if not living_peers:
                    print(f"[Worker {args.id}] SOLE SURVIVOR DETECTED. Inheriting all workloads.")
                    # SOLE SURVIVOR LOGIC
                    bus.update_agent_task_status(args.id, "inprogress")
                    
                    manifest_path = comm_dir / "global_task_manifest.json"
                    if manifest_path.exists():
                        with open(manifest_path, "r") as f:
                            all_tasks = json.load(f)
                        
                        for sid, task_content in all_tasks.items():
                            peer_status = bus.get_agent_task_status(sid)
                            if peer_status.get("status") != "completed":
                                print(f"[Worker {args.id}] Inheriting task from fallen {sid}: {task_content[:30]}...")
                                # Sequential Execution...
                    
                    print(f"[Worker {args.id}] All workloads finished. Performing FINAL PUSH.")
                    bus.update_agent_task_status(args.id, "completed")
                    sys.exit(0)
                else:
                    print(f"[Worker {args.id}] MASTER {args.parent} DIED. I am the Alpha Slave. Promoting to Master...")
                    become_master(bus, coworkers)
            else:
                # State key is already checked above; no separate key needed to prevent fighting
                if last_log_state != state_key:
                    print(f"[Worker {args.id}] Master died. Waiting for {alpha_id} to promote.")
                    last_log_state = state_key

        # 2. Wait for messages

        messages_grouped = bus.read_unread_messages(args.id)
        messages = [m for msgs in messages_grouped.values() for m in msgs] if isinstance(messages_grouped, dict) else messages_grouped
        for msg in messages:
            if msg["type"] == "task_assignment":
                task_data = msg["content"]
                task = task_data["task"] if isinstance(task_data, dict) else str(task_data)
                task_id = f"task_{int(time.time())}"
                
                # DUPLICATE TASK DETECTION
                is_duplicate = False
                duplicate_owner = None
                manifest_path = comm_dir / "global_task_manifest.json"
                if manifest_path.exists():
                    try:
                        with open(manifest_path, "r") as f:
                            manifest = json.load(f)
                        for aid, assigned_task in manifest.items():
                            if aid != args.id: # Check others
                                existing_content = assigned_task["task"] if isinstance(assigned_task, dict) else str(assigned_task)
                                if task.strip() == existing_content.strip():
                                    is_duplicate = True
                                    duplicate_owner = aid
                                    break
                    except: pass

                if is_duplicate:
                    print(f"[Worker {args.id}] ⚠️ DUPLICATE TASK DETECTED: Already assigned to {duplicate_owner}. Alerting Master...")
                    bus.send_message(args.id, args.parent, {
                        "error": "duplicate_task",
                        "task": task,
                        "already_assigned_to": duplicate_owner
                    })
                    continue

                print(f"[Worker {args.id}] Received task: {task[:50]}...")
                
                # 1. INSTANT ACK: Tell Master immediately that we've started to prevent re-assignment loops
                bus.reply_message(args.id, args.parent, {"task_id": task_id, "status": "acknowledged"}, msg["sno"])
                
                current_row_id = None
                try:
                    current_row_id = bus.update_agent_task_status(args.id, "inprogress", task)
                    log_history("task_start", {"id": task_id, "content": task})

                    # 2. BACKGROUND HEARTBEAT: Keep status alive while the AI brain is thinking
                    import threading
                    stop_heartbeat = threading.Event()
                    def heartbeat_worker():
                        last_hb = 0
                        while not stop_heartbeat.is_set():
                            # ACCOUNT PROTECTION: 1s is the minimum to avoid GitHub blocking you for I/O abuse
                            if time.time() - last_hb < 1:
                                continue
                            last_hb = time.time()
                            bus.update_agent_task_status(args.id, "inprogress", task, row_id=current_row_id)

                    
                    hb_thread = threading.Thread(target=heartbeat_worker, daemon=True)
                    hb_thread.start()

                    # ACTUAL WORK: Invoke the real AI agent
                    print(f"[Worker {args.id}] 🧠 INITIALIZING BRAIN (Model: {args.model})...")
                    agent = build_agent(
                        work_dir=Path("."), # Already in mas_workspace
                        model_name=args.model,
                        ollama_url=args.ollama_url,
                        ollama_key=args.ollama_key
                    )
                    
                    print(f"[Worker {args.id}] 🚀 EXECUTING ASSIGNMENT: {task[:50]}...")
                    
                    # Prepare input with history if this is a reassignment
                    input_data = {"input": task}
                    if isinstance(msg["content"], dict) and "failed_agent_id" in msg["content"]:
                        failed_id = msg["content"]["failed_agent_id"]
                        print(f"[Worker {args.id}] 📂 Loading history from failed agent {failed_id}...")
                        history_grouped = bus.get_chat_history(failed_id)
                        history_flat = [m for msgs in history_grouped.values() for m in msgs] if isinstance(history_grouped, dict) else history_grouped
                        history = sorted(history_flat, key=lambda x: x["sno"])[-20:]
                        from langchain_core.messages import HumanMessage, AIMessage
                        msgs = []
                        for m in history:
                            content = str(m.get("content", ""))
                            if m.get("from") == failed_id:
                                msgs.append(AIMessage(content=content))
                            else:
                                msgs.append(HumanMessage(content=f"From {m.get('from')}: {content}"))
                        input_data["history"] = msgs
                    
                    result = agent.invoke(input_data)
                    summary = extract_reply(result)
                    
                    # Stop Heartbeat
                    stop_heartbeat.set()
                    hb_thread.join(timeout=1)
                    
                    print(f"[Worker {args.id}] ✅ TASK COMPLETE. Submitting report to Master.")
                    bus.send_message(args.id, args.parent, {"task_id": task_id, "summary": summary})
                    bus.update_agent_task_status(args.id, "completed", row_id=current_row_id)
                
                except Exception as e:
                    error_msg = str(e).lower()
                    # Fixed: Removed undefined 'attempt' check.
                    if "-1" in error_msg or "429" in error_msg or "limit reached" in error_msg or "internal server error" in error_msg or "503" in error_msg or "peer closed" in error_msg or "incomplete chunked read" in error_msg:
                        print(f"[Brain {args.id}] ⚠️ Usage Limit or Transient Error: {e}. Rotating key and retrying INSTANTLY (Rule #1)... ")
                        continue
                    
                    print(f"[Worker {args.id}] 🛑 ERROR: {e}. Immediate retry...")
                    broadcast_limit_reached(str(e))
                    bus.update_agent_task_status(args.id, "inprogress", f"Retrying: {str(e)[:50]}")
                    continue

            elif msg["type"] == "takeover_command":
                if hasattr(main, "succession_timer"): del main.succession_timer
                failed_id = msg["content"].get("failed_agent_id")
                new_master_id = msg["content"].get("new_master_id", args.id)
                
                if new_master_id == args.id:
                    print(f"[Worker {args.id}] 👑 PROMOTION RECEIVED via direct command.")
                    become_master(bus, coworkers)
                elif new_master_id == "MAIN_THREAD":
                    print(f"[Worker {args.id}] 👑 SUCCESSION: Parent process (Main Thread) is taking over. Yielding...")
                    sys.exit(0)
                else:
                    print(f"[Worker {args.id}] Inheriting tasks from failed coworker {failed_id}")
                    log_history("takeover", failed_id)

            elif msg["type"] == "emergency_alert":
                # Safe-check content type to prevent 'str' object has no attribute 'get' crash
                content = msg.get("content", {})
                reason = content.get("reason", "General Emergency") if isinstance(content, dict) else str(content)
                handle_emergency("emergency_alert", reason)
            
            elif msg["type"] == "shutdown":
                handle_emergency("shutdown", "Mission Complete")
            
            elif msg["type"] == "new_master_announcement":
                if hasattr(main, "succession_timer"): del main.succession_timer
                new_master = msg["content"]["new_master"]
                print(f"[Worker {args.id}] ACK: {new_master} is my NEW MASTER.")
                # Dynamically update the parent ID for future reporting
                args.parent = new_master 
                log_history("master_changed", new_master)
                bus.send_message(args.id, args.parent, "Reporting for duty to new master.")
            
            elif msg["type"] == "coworker_down":
                print(f"[Worker {args.id}] Alert: Coworker {msg['from']} reached limit.")
                log_history("peer_limit_reached", msg["from"])


if __name__ == "__main__":
    main()
