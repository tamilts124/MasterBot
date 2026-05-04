import os
import sys
import subprocess
import argparse
import shutil
import time
from pathlib import Path

def run_command(cmd, cwd=None, env=None, label=None):
    """Run a shell command with real-time output while capturing for results."""
    if label:
        print(f"Action: {label}")
    
    # We use Popen to stream output in real-time while still catching it in a variable
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
        print(line, end='') # Real-time print to console
        full_output.append(line)
    
    process.wait()
    
    # Create a mock result object that looks like what subprocess.run returns
    class Result:
        def __init__(self, returncode, stdout):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = "" # Already merged into stdout
            
    return Result(process.returncode, "".join(full_output))

def main():
    parser = argparse.ArgumentParser(description="AI Developer Agent with key cycling.")
    parser.add_argument("--prompt", required=True, help="Task for the agent.")
    parser.add_argument("--keys", required=True, help="Comma-separated Ollama API keys.")
    parser.add_argument("--target-repo", required=True, help="Target GitHub repository URL.")
    parser.add_argument("--target-token", required=True, help="GitHub Personal Access Token for the target repo.")
    parser.add_argument("--model", default="qwen3-coder:480b-cloud", help="Ollama model to use.")
    parser.add_argument("--ollama-url", default="https://ollama.com", help="Ollama API base URL.")
    parser.add_argument("--whatsapp", help="Target WhatsApp number/JID.")
    parser.add_argument("--whatsapp-url", default="http://localhost:3000", help="WhatsApp API base URL.")
    parser.add_argument("--max-tool-output", type=int, default=60000, help="Max characters for tool output.")
    parser.add_argument("--ollama-ctx", type=int, default=65536, help="Ollama context window size.")
    
    args = parser.parse_args()

    keys = [k.strip() for k in args.keys.split(",") if k.strip()]
    if not keys:
        print("Error: No API keys provided.")
        sys.exit(1)

    repo_url = args.target_repo
    target_token = args.target_token
    
    # Workspace setup (Safe reuse)
    workspace = Path("target_repo_workspace")
    authenticated_url = repo_url.replace("https://", f"https://x-access-token:{target_token}@")
    
    if not workspace.exists():
        workspace.mkdir()
        print(f"Cloning target repository: {repo_url}")
        clone_res = run_command(["git", "clone", authenticated_url, "."], cwd=workspace, label="Cloning Repo")
        if clone_res.returncode != 0:
            print("Failed to clone target repository.")
            sys.exit(1)
    else:
        print(f"Safe Workspace Sync...")
        # Ensure origin exists (it might be missing after git init)
        remote_check = run_command(["git", "remote"], cwd=workspace)
        if "origin" not in remote_check.stdout:
            run_command(["git", "remote", "add", "origin", authenticated_url], cwd=workspace, label="Adding Remote Origin")
        else:
            run_command(["git", "remote", "set-url", "origin", authenticated_url], cwd=workspace, label="Updating Remote URL")

    # Ensure .gitignore exists in target repo
    target_gitignore = workspace / ".gitignore"
    if not target_gitignore.exists():
        print("Creating default .gitignore in target repository...")
        with open(target_gitignore, "w") as f:
            f.write("__pycache__/\n*.py[cod]\nnode_modules/\n.venv/\nvenv/\n.DS_Store\n")

    # Configure Git (Uses env vars or defaults)
    git_name = os.environ.get("GIT_USER_NAME", "AI Developer Agent")
    git_email = os.environ.get("GIT_USER_EMAIL", "agent@ai.dev")
    
    run_command(["git", "config", "user.name", git_name], cwd=workspace, label="Configuring Git User")
    run_command(["git", "config", "user.email", git_email], cwd=workspace, label="Configuring Git Email")

    key_index = 0
    while key_index < len(keys):
        current_key = keys[key_index]
        print(f"\n--- Attempting with Ollama API Key {key_index + 1}/{len(keys)} ---")
        
        # Prepare command to run the agent
        agent_cmd = [
            sys.executable, "-m", "ai_agent.main",
            "--workdir", str(workspace.resolve()),
            "--model", args.model,
            "--ollama-url", args.ollama_url,
            "--ollama-key", current_key,
            "--prompt", args.prompt,
            "--max-tool-output", str(args.max_tool_output),
            "--ollama-ctx", str(args.ollama_ctx),
            "--quiet"
        ]

        if args.whatsapp:
            agent_cmd.extend(["--whatsapp", args.whatsapp, "--whatsapp-url", args.whatsapp_url])

        # Run the agent
        agent_res = run_command(agent_cmd, label="Starting AI Agent Session")
        
        if agent_res.returncode != 0:
            # Check for limit/expiry errors in output
            error_output = (agent_res.stdout + agent_res.stderr).lower()
            is_limit = any(term in error_output for term in ["limit", "expiry", "429", "401", "unauthorized", "quota", "503", "overloaded"])
            
            if is_limit:
                # Only auto-push if it was a limit exhaustion
                status_res = run_command(["git", "status", "--porcelain"], cwd=workspace, label="Checking for changes")
                if status_res.stdout.strip():
                    print("\nLimit reached. Saving progress to GitHub...")
                    run_command(["git", "add", "."], cwd=workspace, label="Staging changes")
                    commit_msg = f"AI Developer: Progress saved (Key {key_index + 1} exhausted/interrupted)"
                    run_command(["git", "commit", "-m", commit_msg], cwd=workspace, label="Committing changes")
                    # We use -u origin main to ensure it always finds the destination
                    run_command(["git", "push", "-u", "origin", "main"], cwd=workspace, label="Emergency Push to GitHub")

                print(f"Key {key_index + 1} appears to be exhausted or invalid. Rotating and continuing...")
                key_index += 1
            else:
                print("Agent failed with an unexpected error. Rotating to try next key...")
                key_index += 1
        else:
            # Task completed successfully - keep the loop going with the same key
            print("\n--- Session finished. Starting next development cycle in 5 seconds... ---")
            time.sleep(5)
            continue

    print("\n[CRITICAL] All sessions of Ollama limit excited. No valid keys left.")
    sys.exit(1)

if __name__ == "__main__":
    main()
