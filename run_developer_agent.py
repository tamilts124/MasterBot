import warnings
# Suppress noisy LangChain/LangGraph deprecation warnings immediately
warnings.filterwarnings("ignore", message=".*allowed_objects.*will change.*")

import os
import sys
import subprocess
import argparse
import shutil
import time
import socket
import io
from pathlib import Path

# Ensure UTF-8 encoding for Windows terminals
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Set environment variables to force UTF-8
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONLEGACYWINDOWSSTDIO'] = 'utf-8'

def safe_print(text):
    """Safely print text, handling encoding issues gracefully"""
    try:
        print(text, end='', flush=True)
    except UnicodeEncodeError:
        # Fallback to printing with replacement characters
        print(text.encode('utf-8', errors='replace').decode('utf-8'), end='', flush=True)

def run_command(cmd, cwd=None, env=None, label=None):
    """Run a shell command with real-time output while capturing for results."""
    if label:
        safe_print(f"Action: {label}\n")
    
    # Prepare environment with UTF-8 settings
    cmd_env = os.environ.copy()
    cmd_env.update({
        'PYTHONIOENCODING': 'utf-8',
        'PYTHONLEGACYWINDOWSSTDIO': 'utf-8'
    })
    if env:
        cmd_env.update(env)
    
    # We use Popen to stream output in real-time while still catching it in a variable
    process = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.STDOUT, 
        text=True, 
        encoding='utf-8', # Force UTF-8 decoding of the child process output
        cwd=cwd, 
        env=cmd_env,
        bufsize=1,
        universal_newlines=True,
        errors='replace'  # Handle encoding errors gracefully
    )
    
    full_output = []
    for line in process.stdout:
        safe_print(line)  # Use safe_print instead of direct print
        full_output.append(line)
    
    process.wait()
    
    # Create a mock result object that looks like what subprocess.run returns
    class Result:
        def __init__(self, returncode, stdout):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = "" # Already merged into stdout
            
    return Result(process.returncode, "".join(full_output))

def rotate_tor_ip():
    """Request a new Tor circuit (NEWNYM) via the control port."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect(("127.0.0.1", 9051))
            s.sendall(b'AUTHENTICATE ""\r\n')
            # Wait for response
            s.recv(1024)
            s.sendall(b'SIGNAL NEWNYM\r\n')
            s.recv(1024)
            s.sendall(b'QUIT\r\n')
        safe_print("Action: Requesting new Tor IP (NEWNYM)\n")
        pass # NO SLEEP - Rule #1 Compliance
    except Exception as e:
        safe_print(f"Warning: Failed to rotate Tor IP: {e}\n")

def main():
    parser = argparse.ArgumentParser(description="AI Developer Agent with key cycling.")
    parser.add_argument("--prompt", required=True, help="Task for the agent.")
    parser.add_argument("--keys", required=True, help="Comma-separated Ollama API keys.")
    parser.add_argument("--target-repo", required=True, help="Target GitHub repository URL.")
    parser.add_argument("--target-token", required=True, help="GitHub Personal Access Token for the target repo.")
    parser.add_argument("--model", default="qwen3-coder:480b-cloud", help="Ollama model to use.")
    parser.add_argument("--ollama-url", default="https://ollama.com", help="Ollama API base URL.")
    parser.add_argument("--provider", default="ollama", choices=["ollama", "anthropic"], help="LLM provider to use.")
    parser.add_argument("--anthropic-key", help="Anthropic API Key(s) (comma-separated).")
    parser.add_argument("--anthropic-url", help="Anthropic API base URL (if using a proxy).")
    parser.add_argument("--whatsapp", help="Target WhatsApp number/JID.")
    parser.add_argument("--whatsapp-url", default="http://localhost:3000", help="WhatsApp API base URL.")
    parser.add_argument("--max-tool-output", type=int, default=60000, help="Max characters for tool output.")
    parser.add_argument("--ollama-ctx", type=int, default=65536, help="Ollama context window size.")
    parser.add_argument("--temperature", type=float, default=0.0, help="Ollama temperature setting.")
    parser.add_argument("--no-tor", action="store_true", help="Disable Tor IP rotation.")
    
    args = parser.parse_args()

    if args.provider == "anthropic":
        keys = [k.strip() for k in (args.anthropic_key or "").split(",") if k.strip()]
        if not keys:
            safe_print("Error: No Anthropic API keys provided.\n")
            sys.exit(1)
    else:
        keys = [k.strip() for k in args.keys.split(",") if k.strip()]
        if not keys:
            safe_print("Error: No Ollama API keys provided.\n")
            sys.exit(1)

    repo_url = args.target_repo
    target_token = args.target_token
    
    # Workspace setup (Safe reuse)
    workspace = Path("target_repo_workspace")
    authenticated_url = repo_url.replace("https://", f"https://x-access-token:{target_token}@")
    
    if not workspace.exists():
        workspace.mkdir()
        safe_print(f"Cloning target repository: {repo_url}\n")
        clone_res = run_command(["git", "clone", authenticated_url, "."], cwd=workspace, label="Cloning Repo")
        if clone_res.returncode != 0:
            safe_print("Failed to clone target repository.\n")
            sys.exit(1)
    else:
        safe_print(f"Safe Workspace Sync...\n")
        # Ensure origin exists (it might be missing after git init)
        remote_check = run_command(["git", "remote"], cwd=workspace)
        if "origin" not in remote_check.stdout:
            run_command(["git", "remote", "add", "origin", authenticated_url], cwd=workspace, label="Adding Remote Origin")
        else:
            run_command(["git", "remote", "set-url", "origin", authenticated_url], cwd=workspace, label="Updating Remote URL")

    # Ensure .gitignore exists in target repo
    target_gitignore = workspace / ".gitignore"
    if not target_gitignore.exists():
        safe_print("Creating default .gitignore in target repository...\n")
        with open(target_gitignore, "w", encoding='utf-8') as f:
            f.write("__pycache__/\n*.py[cod]\nnode_modules/\n.venv/\nvenv/\n.DS_Store\n.sas/\nbrowser_outputs/\n")

    # Configure Git (Uses env vars or defaults)
    git_name = os.environ.get("GIT_USER_NAME", "AI Developer Agent")
    git_email = os.environ.get("GIT_USER_EMAIL", "agent@ai.dev")
    
    run_command(["git", "config", "user.name", git_name], cwd=workspace, label="Configuring Git User")
    run_command(["git", "config", "user.email", git_email], cwd=workspace, label="Configuring Git Email")

    key_index = 0
    while True:
        if key_index >= len(keys):
            safe_print(f"\n[INFO] All {len(keys)} keys processed. restarting cycle...\n")
            break

        current_key = keys[key_index]
        safe_print(f"\n--- Attempting with {args.provider.capitalize()} API Key {key_index + 1}/{len(keys)} ---\n")
        
        # Rotate Tor IP before each key rotation or cycle
        if not args.no_tor:
            rotate_tor_ip()

        # Prepare command to run the agent
        agent_cmd = [
            sys.executable, "-m", "ai_agent.sas.main",
            "--workdir", str(workspace.resolve()),
            "--model", args.model,
            "--provider", args.provider,
            "--prompt", args.prompt,
            "--max-tool-output", str(args.max_tool_output),
        ]

        if args.provider == "anthropic":
            agent_cmd.extend(["--anthropic-key", current_key])
            if args.anthropic_url:
                agent_cmd.extend(["--anthropic-url", args.anthropic_url])
        else:
            agent_cmd.extend(["--ollama-url", args.ollama_url, "--ollama-key", current_key])
            agent_cmd.extend(["--ollama-ctx", str(args.ollama_ctx)])
            agent_cmd.extend(["--temperature", str(args.temperature)])

        agent_cmd.append("--quiet")

        if args.whatsapp:
            agent_cmd.extend(["--whatsapp", args.whatsapp, "--whatsapp-url", args.whatsapp_url])

        # Retry logic for specific errors
        max_retries = 3
        attempt = 0
        while attempt < max_retries:
            if attempt > 0:
                safe_print(f"Retry attempt {attempt}/{max_retries}...\n")
                if not args.no_tor:
                    rotate_tor_ip() # Try a new IP on retry

            agent_res = run_command(agent_cmd, label="Starting AI Agent Session")
            
            if agent_res.returncode == 0:
                # Task completed successfully - keep the loop going with the same key
                safe_print("\n--- Session finished. Starting next development cycle in 5 seconds... ---\n")
                attempt = 0 # Reset retries for next cycle
                continue # Run again with the same key

            # Non-zero return code
            error_output = (agent_res.stdout + agent_res.stderr).lower()
            
            # Specific retry condition
            if "server disconnected without sending a response" in error_output:
                safe_print("Detected 'Server disconnected' error. Retrying with new Tor IP...\n")
                attempt += 1
                continue
            
            # If it's a limit or any other error, rotate key
            is_limit = any(term in error_output for term in ["limit", "expiry", "429", "401", "unauthorized", "quota", "503", "overloaded"])
            
            # Save progress on any rotation-worthy error
            status_res = run_command(["git", "status", "--porcelain"], cwd=workspace, label="Checking for changes")
            if status_res.stdout.strip():
                safe_print("\nSaving progress before key rotation...\n")
                run_command(["git", "add", "."], cwd=workspace, label="Staging changes")
                commit_msg = f"AI Developer: Progress saved (Key {key_index + 1} interrupted/rotated)"
                run_command(["git", "commit", "-m", commit_msg], cwd=workspace, label="Committing changes")
                run_command(["git", "push", "-u", "origin", "main"], cwd=workspace, label="Emergency Push to GitHub")

            if is_limit:
                safe_print(f"Key {key_index + 1} appears to be exhausted. Rotating...\n")
            else:
                safe_print(f"Agent failed with an unexpected error. Rotating key...\n")
            
            key_index += 1
            break # Exit retry loop to move to next key

    safe_print(f"\n[CRITICAL] All sessions of {args.provider.capitalize()} limit excited. No valid keys left.\n")
    sys.exit(1)

if __name__ == "__main__":
    main()