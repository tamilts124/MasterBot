import argparse
import sys
import os
import json
import subprocess
import time
import io
from pathlib import Path
import shutil

# Ensure UTF-8 encoding for Windows terminals
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
from ai_agent.mas.config_loader import load_config
from ai_agent.mas.communication import MessageBus
from ai_agent.mas.network_manager import TorManager, setup_agent_env
from ai_agent.mas.orchestrator import MasterAgent

def run_command(cmd, cwd=None, env=None, label=None):
    """Run a shell command with real-time output while capturing for results."""

    class Result:
        def __init__(self, returncode, stdout):
            self.returncode = returncode
            self.stdout = stdout

    if label:
        print(f"Action: {label}")
    process = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.STDOUT, 
        text=True, 
        cwd=cwd, 
        env=env,
        bufsize=1,
        universal_newlines=True
    )
    full_output = []
    for line in process.stdout:
        print(line, end='', flush=True)
        full_output.append(line)
    process.wait()
    return Result(process.returncode, "".join(full_output))

def main():
    parser = argparse.ArgumentParser(description="Run Hierarchical Multi-Agent System")
    parser.add_argument("--config", required=True, help="Path to mas_config.json")
    parser.add_argument("--prompt", help="The main task for the MAS (Optional for Sub-Masters)")
    parser.add_argument("--workspace", default="mas_workspace", help="Root directory for MAS work")
    parser.add_argument("--repo-url", help="Target GitHub repository URL")
    parser.add_argument("--repo-token", help="GitHub Personal Access Token")
    parser.add_argument("--no-tor", action="store_true", help="Disable Tor isolation and use direct connection")
    
    # Sub-Master / Identity Identity
    parser.add_argument("--id", help="Identity of this specific agent")
    parser.add_argument("--parent", help="ID of the parent agent")
    parser.add_argument("--level", type=int, help="Hierarchy level")
    
    args = parser.parse_args()

    # 1. Setup Environment
    root_dir = Path(args.workspace).resolve()
    root_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. Communication Infrastructure (Workspace Local)
    comm_dir = root_dir / ".mas"

    # 2. Prepare Codebase (Safe Workspace Sync)
    if args.repo_url and args.repo_token:
        authenticated_url = args.repo_url.replace("https://", f"https://x-access-token:{args.repo_token}@")
        
        if not (root_dir / ".git").exists():
            print(f"📥 Initializing and fetching target repository: {args.repo_url}")
            # Instead of 'git clone .' which fails on non-empty dirs, we init and fetch
            run_command(["git", "init"], cwd=root_dir, label="Init Git")
            run_command(["git", "branch", "-M", "main"], cwd=root_dir)
            run_command(["git", "remote", "add", "origin", authenticated_url], cwd=root_dir, label="Adding Remote")
            
            fetch_res = run_command(["git", "fetch", "origin", "main"], cwd=root_dir, label="Fetching Data")
        else:
            print("🔄 Safe Workspace Sync & Populate...")
            run_command(["git", "remote", "set-url", "origin", authenticated_url], cwd=root_dir, label="Updating Remote URL")
            run_command(["git", "fetch", "origin", "main"], cwd=root_dir, label="Fetching Data")
                    
        # Configure Git Identity
        run_command(["git", "config", "user.name", "MARS Root Master"], cwd=root_dir)
        run_command(["git", "config", "user.email", "master@mars.ai"], cwd=root_dir)

    # PERSISTENCE POLICY: We keep the .mas folder to continue progress across runs.
    # The Master will resume by reading the manifest and status from this directory.
    comm_dir.mkdir(parents=True, exist_ok=True)
        
    # 3. Load Config
    try:
        config = load_config(args.config)
        
        # If we are a Sub-Master, we need to find our specific node in the config tree
        if args.id:
            def find_agent(cfg, target_id):
                if cfg.id == target_id: return cfg
                for s in cfg.slaves:
                    res = find_agent(s, target_id)
                    if res: return res
                return None
            
            agent_config = find_agent(config, args.id)
            if not agent_config:
                print(f"[Error] Could not find agent {args.id} in configuration.")
                sys.exit(1)
            config = agent_config
            print(f"[System] Identity Confirmed: Running as {config.id} (Level {args.level})")
            
    except Exception as e:
        print(f"[Error] Critical configuration failure: {e}")
        sys.exit(1)

    # Set Project Root for all agents
    os.environ["PROJECT_ROOT"] = str(Path.cwd().absolute())
    bus = MessageBus(comm_dir)
    
    # 4. Register Agents in Database
    config.register_in_db(bus)
    
    tor = TorManager() if not args.no_tor else None
    
    # 5. Initialize Proxies for Entire Squad
    if tor:
        all_ids = config.get_all_identities()
        print(f"[System] 🌐 Pre-warming {len(all_ids)} Tor connections for the entire squad concurrently...")
        tor.prepare_proxies(all_ids)
    proxy = tor.get_proxy_for_agent(config.id, config.level, 0) if tor else None
    os.environ["AGENT_ID"] = config.id
    os.environ["PARENT_ID"] = args.parent if args.parent else "NoParentForYou"
    
    if proxy:
        os.environ.update(setup_agent_env(proxy))
    else:
        # Clear any existing proxy vars
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("HTTPS_PROXY", None)

    if not args.id:
        print(f"""
    ================================================
    MARS (Multi-Agent Resilient System) INITIALIZED
    ================================================
    Root Master: {config.id}
    Goal: {args.prompt[:50]}...
    Timer: 6-Hour Persistence Guard ACTIVE
    Network: {'Tor Isolation ENABLED' if tor else 'Direct Connection (No Tor)'}
    Workspace: {root_dir}
    ================================================
    """)
    
    # 6. Persistent Mission Host (Main Thread)
    current_config = config
    
    # Root Master gets directive from CLI, Sub-Masters wait for bus messages
    mission_prompt = MasterAgent.get_leader_directive(args.prompt) if args.prompt else None
    
    dead_agents = set()
    
    while True:
        # Pass parent_id if we have one (for Sub-Masters)
        os.environ["AGENT_ID"] = current_config.id
        parent_id = args.parent or os.environ.get("PARENT_ID")
        root_master = MasterAgent(current_config, bus, tor, root_dir, config_path=args.config, parent_id=parent_id)
        
        # If a new agent is taking over, we don't launch, we DISCOVER
        if current_config.id != config.id:
            print(f"[System] 👑 BIRTH OF NEW AGENT: main thread adopting identity {current_config.id}...")
            root_master.discover_slaves()
        else:
            root_master.launch_slaves()
            
        try:
            root_master.run_cycle(mission_prompt)
            print("\n[System] Mission complete. Shutting down squad.")
            break # Mission finished successfully
        except Exception as e:
            print(f"[Master {current_config.id}] FATAL BRAIN ERROR: {e}")
            dead_agents.add(current_config.id)
            
            # GLOBAL SUCCESSION LOGIC
            def get_all_agents(cfg):
                agents = [cfg]
                for s in cfg.slaves:
                    agents.extend(get_all_agents(s))
                return agents

            all_squad = get_all_agents(config)
            living_candidates = [a for a in all_squad if a.id not in dead_agents]
            
            if living_candidates:
                # Find the next candidate (BFS/Level-order priority)
                next_leader_cfg = living_candidates[0]
                next_leader_id = next_leader_cfg.id
                
                print(f"[Critical] {current_config.id} is abdicating. PROMOTING {next_leader_id} to GLOBAL MASTER...")
                
                # DB REASSIGNMENT: Move all tasks and slaves from old master to the new leader
                bus.reassign_all_tasks(current_config.id, next_leader_id)
                bus.reassign_all_slaves(current_config.id, next_leader_id)
                # ADOPTION: If the new leader is a leaf or has few slaves, 
                # let it inherit all other living agents as its slaves.
                other_survivors = [a for a in living_candidates if a.id != next_leader_id]
                next_leader_cfg.slaves = other_survivors # Dynamic promotion inheritance
                
                # Update mission prompt to include resumption context
                mission_prompt = MasterAgent.get_leader_directive(args.prompt, is_succession=True, leader_id=next_leader_id)
                
                # Signal the slave that the parent is taking over its identity
                takeover_msg = (
                    f"URGENT: I am your Master. My primary brain has failed, and I am now REINCARNATING using your identity ({next_leader_id}) in my main thread. "
                    "You must CEASE all your local operations and exit your process immediately to prevent a split-brain conflict. "
                    "I am now you. I will finish the mission."
                )
                bus.send_message(current_config.id, next_leader_id, takeover_msg)
                
                current_config = next_leader_cfg
                continue
            else:
                print("[Critical] No agents remain in the squad. Mission failed.")
                break

    # 7. Final Sync & Shutdown (Always try to save progress)
    if 'root_master' in locals():
        # Only shutdown if mission is truly complete or failed
        root_master.shutdown_squad()
        
        print("\n[System] Performing Final Workspace Sync...")
        # Authenticate URL again just in case
        if args.repo_url and args.repo_token:
            authenticated_url = args.repo_url.replace("https://", f"https://x-access-token:{args.repo_token}@")
            run_command(["git", "remote", "set-url", "origin", authenticated_url], cwd=root_dir)
            
        run_command(["git", "add", "."], cwd=root_dir, label="Final Stage")
        status_res = run_command(["git", "status", "--porcelain"], cwd=root_dir)
        if status_res.stdout.strip():
            print("🚀 Changes detected. Pushing to remote...")
            run_command(["git", "commit", "-m", f"MARS: Mission Sync ({current_config.id})"], cwd=root_dir, label="Final Commit")
            run_command(["git", "push", "origin", "main"], cwd=root_dir, label="Final Push")
        else:
            print("✅ No changes to push. Workspace is clean.")

if __name__ == "__main__":
    main()
