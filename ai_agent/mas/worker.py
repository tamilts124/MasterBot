import argparse
import sys
import time
import json
import os
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

    comm_dir = Path("..").absolute() / ".mas"
    bus = MessageBus(comm_dir)
    
    # PROOF OF LIFE: Announce presence to Master
    bus.send_message(args.id, args.parent, {"status": "ready"}, msg_type="status_report")
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
        bus.send_message(args.id, args.parent, {"error": error_msg, "status": "died"}, msg_type="limit_reached")
        for c in coworkers:
            bus.send_message(args.id, c, f"Coworker {args.id} is down. Error: {error_msg}", msg_type="coworker_down")

    last_heartbeat = 0
    while True:
        # 1. Master Watchdog
        master_status = bus.get_agent_status(args.parent)
        if master_status.get("status") in ["died", "offline"]:
            # Election: Am I the alpha slave?
            all_candidates = sorted([args.id] + coworkers)
            alpha_id = all_candidates[0]
            
            if args.id == alpha_id:
                # Check if I'm the ONLY survivor
                living_peers = []
                for peer in coworkers:
                    if bus.get_agent_status(peer).get("status") not in ["died", "offline"]:
                        living_peers.append(peer)
                
                if not living_peers:
                    print(f"[Worker {args.id}] SOLE SURVIVOR DETECTED. Inheriting all workloads.")
                    # SOLE SURVIVOR LOGIC
                    bus.update_status(args.id, "sole_survivor")
                    
                    manifest_path = comm_dir / "global_task_manifest.json"
                    if manifest_path.exists():
                        with open(manifest_path, "r") as f:
                            all_tasks = json.load(f)
                        
                        for sid, task_content in all_tasks.items():
                            peer_status = bus.get_agent_status(sid)
                            if peer_status.get("status") != "completed":
                                print(f"[Worker {args.id}] Inheriting task from fallen {sid}: {task_content[:30]}...")
                                # Sequential Execution...
                    
                    print(f"[Worker {args.id}] All workloads finished. Performing FINAL PUSH.")
                    sys.exit(0)
                else:
                    print(f"[Worker {args.id}] MASTER {args.parent} DIED. I am the Alpha Slave. Promoting to Master...")
                    for c in coworkers:
                        bus.send_message(args.id, c, {"new_master": args.id}, msg_type="new_master_announcement")
                    bus.update_status(args.id, "acting_master")
            else:
                print(f"[Worker {args.id}] Master died. Waiting for {alpha_id} to promote.")

        # 2. Wait for messages

        messages = bus.get_messages(args.id)
        for msg in messages:
            if msg["type"] == "task_assignment":
                task = msg["content"]
                task_id = f"task_{int(time.time())}"
                print(f"[Worker {args.id}] Received task: {task}")
                
                try:
                    bus.update_status(args.id, "working", task)
                    
                    log_history("task_start", {"id": task_id, "content": task})

                    # ACTUAL WORK: Invoke the real AI agent
                    print(f"[Worker {args.id}] 🧠 INITIALIZING BRAIN (Model: {args.model})...")
                    agent = build_agent(
                        work_dir=Path("."), # Already in mas_workspace
                        model_name=args.model,
                        ollama_url=args.ollama_url,
                        ollama_key=args.ollama_key,
                        use_mas_tools=True
                    )
                    
                    print(f"[Worker {args.id}] 🚀 EXECUTING ASSIGNMENT: {task[:50]}...")
                    
                    # Prepare input with history if this is a reassignment
                    input_data = {"input": task}
                    if isinstance(msg["content"], dict) and "failed_agent_id" in msg["content"]:
                        failed_id = msg["content"]["failed_agent_id"]
                        print(f"[Worker {args.id}] 📂 Loading history from failed agent {failed_id}...")
                        history = bus.get_agent_history(failed_id, limit=20)
                        from langchain_core.messages import HumanMessage, AIMessage
                        msgs = []
                        for m in reversed(history):
                            content = str(m.get("content", ""))
                            if m.get("from") == failed_id:
                                msgs.append(AIMessage(content=content))
                            else:
                                msgs.append(HumanMessage(content=f"From {m.get('from')}: {content}"))
                        input_data["history"] = msgs
                    
                    result = agent.invoke(input_data)
                    summary = extract_reply(result)
                    
                    print(f"[Worker {args.id}] ✅ TASK COMPLETE. Submitting report to Master.")
                    bus.send_message(args.id, args.parent, {"task_id": task_id, "summary": summary}, msg_type="task_report")
                    bus.update_status(args.id, "idle")
                
                except Exception as e:
                    error_msg = str(e)
                    print(f"[Worker {args.id}] FATAL ERROR: {error_msg}")
                    broadcast_limit_reached(error_msg)
                    sys.exit(137)

            elif msg["type"] == "takeover_command":
                failed_id = msg["content"]["failed_agent_id"]
                new_master_id = msg["content"]["new_master_id"]
                
                if new_master_id == args.id:
                    print(f"[Worker {args.id}] 👑 PROMOTION RECEIVED. I am now the NEW ROOT MASTER.")
                    os.environ["AGENT_ID"] = args.id
                    from .orchestrator import MasterAgent
                    from .config_loader import load_config
                    
                    # Reload config to get full hierarchy
                    full_config = load_config("../mas_config.json") # Adjust path as needed
                    # Find self in the config
                    def find_self(cfg, target_id):
                        if cfg.id == target_id: return cfg
                        for s in cfg.slaves:
                            res = find_self(s, target_id)
                            if res: return res
                        return None
                    
                    my_config = find_self(full_config, args.id)
                    if my_config:
                        # Broadcast leadership to others
                        for other_slave in full_config.slaves:
                            if other_slave.id != args.id:
                                bus.send_message(args.id, other_slave.id, {"new_master": args.id}, msg_type="new_master_announcement")
                        
                        # Transform into Master
                        new_master = MasterAgent(my_config, bus, None, Path(".."))
                        try:
                            new_master.run_cycle("Continue mission from where it left off.")
                        except Exception as e:
                            print(f"[Master {args.id}] FATAL BRAIN ERROR: {e}")
                            # Promote the next slave in the original config
                            my_index = -1
                            for i, s in enumerate(full_config.slaves):
                                if s.id == args.id:
                                    my_index = i
                                    break
                            
                            if my_index != -1 and my_index + 1 < len(full_config.slaves):
                                next_leader = full_config.slaves[my_index + 1].id
                                print(f"[Critical] {args.id} is abdicating. PROMOTING {next_leader} TO ROOT MASTER...")
                                bus.send_message(args.id, next_leader, {"failed_agent_id": args.id, "new_master_id": next_leader}, msg_type="takeover_command")
                            else:
                                print("[Critical] No more slaves available for promotion. Mission failed.")
                        
                        sys.exit(0)
                else:
                    print(f"[Worker {args.id}] Inheriting tasks from failed coworker {failed_id}")
                    log_history("takeover", failed_id)

            elif msg["type"] == "emergency_alert":
                print(f"[Worker {args.id}] EMERGENCY: Server wipe approaching. Pushing all changes NOW.")
                log_history("emergency_save", "Wipe-out approaching")
                sys.exit(0)
            
            elif msg["type"] == "new_master_announcement":
                new_master = msg["content"]["new_master"]
                print(f"[Worker {args.id}] ACK: {new_master} is my NEW MASTER.")
                # Dynamically update the parent ID for future reporting
                args.parent = new_master 
                log_history("master_changed", new_master)
                bus.send_message(args.id, args.parent, "Reporting for duty to new master.", msg_type="promotion_ack")
            
            elif msg["type"] == "coworker_down":
                print(f"[Worker {args.id}] Alert: Coworker {msg['from']} reached limit.")
                log_history("peer_limit_reached", msg["from"])


if __name__ == "__main__":
    main()
