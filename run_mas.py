import argparse
import sys
import os
import json
import subprocess
import time
import io
from pathlib import Path

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
    class Result:
        def __init__(self, returncode, stdout):
            self.returncode = returncode
            self.stdout = stdout
    return Result(process.returncode, "".join(full_output))

def main():
    parser = argparse.ArgumentParser(description="Run Hierarchical Multi-Agent System")
    parser.add_argument("--config", required=True, help="Path to mas_config.json")
    parser.add_argument("--prompt", required=True, help="The main task for the MAS")
    parser.add_argument("--workspace", default="mas_workspace", help="Root directory for MAS work")
    parser.add_argument("--repo-url", help="Target GitHub repository URL")
    parser.add_argument("--repo-token", help="GitHub Personal Access Token")
    parser.add_argument("--no-tor", action="store_true", help="Disable Tor isolation and use direct connection")
    args = parser.parse_args()

    # 1. Setup Environment
    root_dir = Path(args.workspace).resolve()
    root_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. Communication Infrastructure (Workspace Local)
    comm_dir = root_dir / ".mas"
    bus = MessageBus(comm_dir)
    
    # 2. Prepare Codebase (Safe Workspace Sync)
    if args.repo_url and args.repo_token:
        authenticated_url = args.repo_url.replace("https://", f"https://x-access-token:{args.repo_token}@")
        if not (root_dir / ".git").exists():
            print(f"📥 Initializing and fetching target repository: {args.repo_url}")
            # Instead of 'git clone .' which fails on non-empty dirs, we init and fetch
            run_command(["git", "init"], cwd=root_dir, label="Init Git")
            run_command(["git", "remote", "add", "origin", authenticated_url], cwd=root_dir, label="Adding Remote")
            
            fetch_res = run_command(["git", "fetch", "origin"], cwd=root_dir, label="Fetching Data")
            if fetch_res.returncode == 0:
                # Try to reset to the default branch (usually main or master)
                ls_remote = run_command(["git", "ls-remote", "--symref", "origin", "HEAD"], cwd=root_dir)
                default_branch = "main"
                for line in ls_remote.stdout.splitlines():
                    if line.startswith("ref: refs/heads/") and "HEAD" in line:
                        default_branch = line.split("refs/heads/")[1].split()[0]
                        break
                print(f"📦 Populating workspace from branch: {default_branch}")
                run_command(["git", "reset", "--hard", f"origin/{default_branch}"], cwd=root_dir, label="Resetting to Remote")
            else:
                print("⚠️ Remote repository appears to be empty or inaccessible. Proceeding with local init.")
        else:
            print("🔄 Safe Workspace Sync & Populate...")
            run_command(["git", "remote", "set-url", "origin", authenticated_url], cwd=root_dir, label="Updating Remote URL")
            run_command(["git", "fetch", "origin"], cwd=root_dir, label="Fetching Data")
            
            # If the workspace is empty (only .git/.mas), force a reset to populate it
            files = [f for f in os.listdir(root_dir) if f not in [".git", ".mas"]]
            if not files:
                print("📭 Workspace is empty. Force-populating from remote...")
                # Detect branch and reset
                ls_remote = run_command(["git", "ls-remote", "--symref", "origin", "HEAD"], cwd=root_dir)
                default_branch = "main"
                for line in ls_remote.stdout.splitlines():
                    if line.startswith("ref: refs/heads/") and "HEAD" in line:
                        default_branch = line.split("refs/heads/")[1].split()[0]
                        break
        # 3. Handle Empty Repository (Day Zero)
        files = [f for f in os.listdir(root_dir) if f not in [".git", ".mas"]]
        if not files:
            print("🆕 Empty repository detected. Initializing first commit...")
            gitignore_path = root_dir / ".gitignore"
            with open(gitignore_path, "w") as f:
                f.write("__pycache__/\n*.py[cod]\nnode_modules/\n.venv/\nvenv/\n.DS_Store\nmas_workspace/\nmas_config.json\n")
            
            run_command(["git", "add", ".gitignore"], cwd=root_dir, label="Staging Initial Files")
            run_command(["git", "commit", "-m", "Initial commit: MARS Environment Setup"], cwd=root_dir, label="First Commit")
            run_command(["git", "branch", "-M", "main"], cwd=root_dir, label="Naming Branch Main")
            # We don't push yet, let the agents work first
        
        # Configure Git Identity
        run_command(["git", "config", "user.name", "MARS Root Master"], cwd=root_dir)
        run_command(["git", "config", "user.email", "master@mars.ai"], cwd=root_dir)

    # PERSISTENCE POLICY: We keep the .mas folder to continue progress across runs.
    # The Master will resume by reading the manifest and status from this directory.
    comm_dir.mkdir(parents=True, exist_ok=True)
        
    msg_dir = comm_dir / "messages"
    status_dir = comm_dir / "status"
    msg_dir.mkdir(parents=True, exist_ok=True)
    status_dir.mkdir(parents=True, exist_ok=True)

    # 3. Load Config
    try:
        config = load_config(args.config)
        # Master only uses its own dedicated keys
        os.environ["API_KEYS"] = config.api_key if config.api_key else ""
    except Exception as e:
        print(f"[Error] Critical configuration failure: {e}")
        sys.exit(1)

    # Set Project Root for all agents
    os.environ["PROJECT_ROOT"] = str(Path.cwd().absolute())
    
    # Initialize Message Bus
    bus = MessageBus(comm_dir)
    tor = TorManager() if not args.no_tor else None

    # 5. Initialize Root Master
    proxy = tor.get_proxy_for_agent(config.id, config.level, 0) if tor else None
    os.environ["AGENT_ID"] = config.id
    os.environ["PARENT_ID"] = "USER"
    
    def get_hierarchy_map(cfg):
        return {cfg.id: [get_hierarchy_map(s) for s in cfg.slaves]}
    os.environ["MAS_HIERARCHY"] = json.dumps(get_hierarchy_map(config))
    
    if proxy:
        os.environ.update(setup_agent_env(proxy))
    else:
        # Clear any existing proxy vars
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("HTTPS_PROXY", None)

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
    
    root_master = MasterAgent(config, bus, tor, root_dir)
    root_master.launch_slaves()
    
    # 6. Start Processing
    try:
        root_master.run_cycle(args.prompt)
        print("\n[System] Mission complete. Shutting down squad.")
    except Exception as e:
        print(f"[Master {config.id}] FATAL BRAIN ERROR: {e}")
        if config.slaves:
            next_leader = config.slaves[0].id
            print(f"[Critical] {config.id} is abdicating. PROMOTING {next_leader} TO ROOT MASTER...")
            root_master.abdicated = True
            bus.send_message(config.id, next_leader, {"failed_agent_id": config.id, "new_master_id": next_leader}, msg_type="takeover_command")
        else:
            print("[Critical] No slaves available for promotion. Mission failed.")
        
    # 7. Shutdown & Final Sync
    if 'root_master' in locals() and not getattr(root_master, 'abdicated', False):
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
            run_command(["git", "commit", "-m", "MARS: Final mission sync and consolidation"], cwd=root_dir, label="Final Commit")
            # Get current branch
            branch_res = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root_dir)
            branch = branch_res.stdout.strip() or "main"
            run_command(["git", "push", "origin", branch], cwd=root_dir, label="Final Push")
        else:
            print("✅ No changes to push. Workspace is clean.")

if __name__ == "__main__":
    main()
