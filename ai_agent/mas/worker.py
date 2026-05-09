import os
import sys
import time
import json
import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add project root to sys.path
project_root = str(Path(__file__).parent.parent.parent.absolute())
if project_root not in sys.path:
    sys.path.append(project_root)

from ai_agent.mas.communication import MessageBus
from ai_agent.mas.agent import build_agent, extract_reply

def main():
    parser = argparse.ArgumentParser(description="MARS Autonomous Worker")
    parser.add_argument("--id", required=True, help="Agent ID")
    parser.add_argument("--parent", required=True, help="Parent Master ID")
    parser.add_argument("--level", type=int, default=1, help="Hierarchy level")
    parser.add_argument("--model", default="gemma4:31b-cloud", help="Model name")
    parser.add_argument("--ollama-url", default="https://ollama.com", help="Ollama API URL")
    parser.add_argument("--ollama-key", help="Ollama API Key")
    parser.add_argument("--no-tor", action="store_true", help="Disable Tor proxy")
    args = parser.parse_args()

    # Environment Setup
    os.environ["AGENT_ID"] = args.id
    os.environ["PARENT_ID"] = args.parent
    
    # Initialize Bus pointing to the shared .mas folder
    bus = MessageBus(base_dir=Path(".") / ".mas")
    
    # Register in DB
    bus.update_agent(args.id, parent_id=args.parent)
    
    # Discover coworkers
    coworkers = [c["agent_id"] for c in bus.get_my_coworkers(args.id)]
    
    print(f"[Worker {args.id}] 🚀 Started. Reporting to Master: {args.parent}")
    print(f"[Worker {args.id}] 👥 Coworkers: {', '.join(coworkers) if coworkers else 'None'}")
    
    agent_brain = None
    last_cycle_time = 0
    last_log_state = None
    
    while True:
        # Throttle loop to avoid CPU spikes
        if time.time() - last_cycle_time < 2:
            time.sleep(0.5)
            continue
        last_cycle_time = time.time()
        
        # 1. Master Watchdog (With Dynamic Succession Discovery)
        master_info = bus.get_agents(args.parent)
        current_parent = args.parent
        
        if not master_info or master_info.get("status") == "died":
            # If our parent died, we might have been reassigned!
            my_info = bus.get_agents(args.id)
            new_parent = my_info.get("parent_id")
            if new_parent and new_parent != args.parent:
                print(f"[Worker {args.id}] 🔄 Parent Succession: Moving from {args.parent} to {new_parent}")
                args.parent = new_parent # Update context
                master_info = bus.get_agents(new_parent)
                current_parent = new_parent
            elif not master_info:
                print(f"[Worker {args.id}] ⚠️ CANNOT FIND MASTER {current_parent} IN DB.")
                time.sleep(5)
                continue
            
        last_seen = master_info.get("last_active_time", 0)
        is_stale = (last_seen > 0 and time.time() - last_seen > 120) # 2 minute grace period for slow LLMs
        
        if master_info.get("status") == "died" or is_stale:
            # Election Logic
            all_candidates = sorted([args.id] + coworkers)
            alpha_id = all_candidates[0]
            
            if args.id == alpha_id:
                print(f"[Worker {args.id}] 👑 MASTER FAILURE DETECTED. Promoting to Master...")
                # In a real system, we would relaunch as run_mas.py here
                # For now, we just signal the change
                bus.update_agent(args.id, status="live") # Ensure we are live
                break # Exit worker loop to potentially restart as master
            else:
                if last_log_state != "waiting_for_promotion":
                    print(f"[Worker {args.id}] Master died. Waiting for {alpha_id} to take over.")
                    last_log_state = "waiting_for_promotion"
                continue

        # 2. Autonomous Thinking Cycle
        print(f"[Worker {args.id}] 🧠 Thinking...")
        try:
            if not agent_brain:
                agent_brain = build_agent(
                    work_dir=Path("."),
                    model_name=args.model,
                    ollama_url=args.ollama_url,
                    ollama_key=args.ollama_key
                )
            
            # The AgentWrapper handles situational awareness (Inbox + Tasks)
            agent_brain.invoke({"input": "Check your status and inbox. If you have a task, execute it. If you have finished, update your status and report to your Master."})
        except Exception as e:
            print(f"[Worker {args.id}] Brain Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
