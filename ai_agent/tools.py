import os
import sys
import subprocess
import tempfile
import json
import time
from typing import Optional, List, Dict, Any
from pathlib import Path
from langchain_core.tools import tool
import urllib.request
import urllib.parse
import certifi
import warnings
from ddgs import DDGS

# Workaround for system SSL certificate issues
try:
    os.environ['SSL_CERT_FILE'] = certifi.where()
    os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
except Exception:
    pass

def _get_whatsapp_config():
    """Helper to get current WhatsApp configuration from environment."""
    return {
        "base_url": os.environ.get("WHATSAPP_BASE_URL", "http://localhost:3000").rstrip("/"),
        "target_jid": os.environ.get("WHATSAPP_TARGET_JID")
    }

def _truncate_output(text: str) -> str:
    """Truncate output based on MAX_TOOL_OUTPUT environment variable."""
    try:
        limit = int(os.environ.get("MAX_TOOL_OUTPUT", 60000))
    except ValueError:
        limit = 60000
    
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[Output truncated to {limit} characters...]"

def _whatsapp_request(endpoint: str, method: str = "GET", data: dict = None):
    """Internal helper for WhatsApp API requests."""
    config = _get_whatsapp_config()
    url = f"{config['base_url']}/{endpoint.lstrip('/')}"
    try:
        req = urllib.request.Request(url, method=method)
        if data:
            json_data = json.dumps(data).encode("utf-8")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, data=json_data, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        else:
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

@tool
def rename_file(old_path: str, new_path: str) -> str:
    """Rename or move a file within the current working directory.
    This tool is safer than 'run_bash' for moving files as it performs path validation to ensure operations remain within the permitted workspace.
    Args:
        old_path: The current relative or absolute path of the file.
        new_path: The desired new path or name for the file.
    """
    try:
        old_resolved = Path(old_path).expanduser().resolve()
        new_resolved = Path(new_path).expanduser().resolve()
        cwd = Path.cwd().resolve()
        
        if not str(old_resolved).startswith(str(cwd)) or not str(new_resolved).startswith(str(cwd)):
            return "[Error] Rename operation outside working directory is prohibited."
            
        if not old_resolved.exists():
            return f"[Error] Source file does not exist: {old_path}"
            
        new_resolved.parent.mkdir(parents=True, exist_ok=True)
        old_resolved.rename(new_resolved)
        return f"File renamed from {old_path} to {new_path}"
    except Exception as exc:
        return f"[Error] {exc}"

@tool
def run_bat(script: str) -> str:
    """Execute a Windows batch (.bat) script and capture its output.
    Use this for Windows-specific automation, environment setup, or running legacy CMD commands.
    Args:
        script: The full multi-line text of the batch script to execute.
    """
    if os.name != "nt":
        return "[Error] BAT execution is only supported on Windows."
    bat_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bat", mode="w", encoding="utf-8") as tf:
            tf.write(script)
            bat_path = tf.name
        result = subprocess.run([bat_path], capture_output=True, text=True, shell=True)
        output = result.stdout + result.stderr
        if result.returncode != 0:
            return _truncate_output(f"[Error] Batch script exited with code {result.returncode}.\n{output}")
        return _truncate_output(output if output else "[Info] Script produced no output.")
    finally:
        if bat_path and os.path.exists(bat_path):
            try:
                os.unlink(bat_path)
            except Exception:
                pass

@tool
def run_bash(script: str) -> str:
    """Execute a bash or system shell command and return the combined output.
    This is the primary tool for Unix-like systems for file system operations, git commands, and running system utilities.
    Args:
        script: The command or script to run in the system shell.
    """
    if os.name == "nt":
        return "[Error] Bash execution is not supported on Windows."
    bash_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".sh", mode="w", encoding="utf-8") as tf:
            tf.write(script)
            bash_path = tf.name
        os.chmod(bash_path, 0o755)
        result = subprocess.run(["bash", bash_path], capture_output=True, text=True)
        output = result.stdout + result.stderr
        if result.returncode != 0:
            return _truncate_output(f"[Error] Bash script exited with code {result.returncode}.\n{output}")
        return _truncate_output(output if output else "[Info] Script produced no output.")
    finally:
        if bash_path and os.path.exists(bash_path):
            try:
                os.unlink(bash_path)
            except Exception:
                pass

@tool
def run_python(script: str) -> str:
    """Execute a Python script in a separate process and return its output.
    Use this for complex data processing, performing calculations, or executing independent Python logic.
    Args:
        script: The complete Python source code to execute.
    """
    py_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8") as tf:
            tf.write(script)
            py_path = tf.name
        result = subprocess.run([sys.executable, py_path], capture_output=True, text=True)
        output = result.stdout + result.stderr
        if result.returncode != 0:
            return _truncate_output(f"[Error] Python script exited with code {result.returncode}.\n{output}")
        return _truncate_output(output if output else "[Info] Script produced no output.")
    finally:
        if py_path and os.path.exists(py_path):
            try:
                os.unlink(py_path)
            except Exception:
                pass

@tool
def is_whatsapp_connected() -> str:
    """Verify if the WhatsApp automation bridge is active and authenticated.
    Use this before attempting to send messages to ensure the system is ready.
    """
    res = _whatsapp_request("/status")
    if res.get("status") == "success":
        connected = res.get("connected", False)
        user = res.get("user")
        if connected and user:
            return f"WhatsApp is connected as {user.get('id')}"
        return "WhatsApp is NOT connected. Scan QR code first."
    return f"Error checking status: {res.get('message')}"

@tool
def send_whatsapp_message(message: str) -> str:
    """Send a text message to the pre-configured WhatsApp target JID.
    Use this for high-priority alerts or status updates to the human operator.
    Args:
        message: The text content to send.
    """
    config = _get_whatsapp_config()
    target_jid = config.get("target_jid")
    
    # Fallback to own JID if none specified (though tools should only be enabled if JID exists)
    if not target_jid:
        status = _whatsapp_request("/status")
        if status.get("status") == "success" and status.get("connected"):
            target_jid = status.get("user", {}).get("id")
    
    if not target_jid:
        return "[Error] Cannot send message: No target JID specified and WhatsApp is not connected."
    
    payload = {"phone": target_jid, "message": message}
    res = _whatsapp_request("/send", method="POST", data=payload)
    if res.get("status") == "success":
        return f"Message sent successfully to {target_jid}"
    return f"Error sending message: {res.get('message')}"

@tool
def get_whatsapp_last_messages(count: int = 10) -> str:
    """Retrieve the most recent conversation history from the target WhatsApp chat.
    Args:
        count: The number of messages to retrieve (default 10).
    """
    config = _get_whatsapp_config()
    target_jid = config.get("target_jid")
    
    if not target_jid:
        status = _whatsapp_request("/status")
        if status.get("status") == "success" and status.get("connected"):
            target_jid = status.get("user", {}).get("id")
            
    if not target_jid:
        return "[Error] Cannot retrieve messages: No target JID specified."
    
    # URL encode JID
    encoded_jid = urllib.parse.quote(target_jid)
    res = _whatsapp_request(f"/messages/{encoded_jid}?count={count}")
    if res.get("status") == "success":
        msgs = res.get("messages", [])
        if not msgs:
            return f"No messages found for {target_jid}."
        
        output = [f"Last {len(msgs)} messages with {target_jid}:"]
        for m in msgs:
            sender = "Me" if m.get("key", {}).get("fromMe") else "Other"
            text = m.get("message", {}).get("conversation") or m.get("message", {}).get("extendedTextMessage", {}).get("text") or "[Media/Other]"
            output.append(f" - [{sender}]: {text}")
        return _truncate_output("\n".join(output))
    return f"Error retrieving messages: {res.get('message')}"

@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Perform a live web search using DuckDuckGo to find information, documentation, or code examples.
    Args:
        query: The search term or question to find on the web.
        max_results: The maximum number of search results to return (default 5).
    """
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            if not results:
                return "No results found."
            
            formatted_results = []
            for r in results:
                formatted_results.append(f"Title: {r.get('title', 'N/A')}\nURL: {r.get('href', 'N/A')}\nSnippet: {r.get('body', 'N/A')}\n")
            
            return _truncate_output("\n---\n".join(formatted_results))
    except Exception as e:
        return f"Error during search: {str(e)}"

@tool
def fetch_url(url: str) -> str:
    """Download and read the raw text content of a specific web URL.
    Use this to read documentation, API references, or source code from websites found during search.
    Args:
        url: The full HTTP/HTTPS URL to fetch.
    """
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read().decode("utf-8", errors="ignore")
            return _truncate_output(content)
    except Exception as exc:
        return f"[Error] Failed to fetch URL: {exc}"

@tool
def git_status() -> str:
    """Check the Git repository status to see modified files, staged changes, and current branch.
    Always run this before committing or pulling to understand the current state of the workspace.
    """
    try:
        # Verify we are in a git repository
        is_repo = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
        if is_repo.returncode != 0:
            return f"[Error] Not a git repository: {os.getcwd()}"

        result = subprocess.run(["git", "status"], capture_output=True, text=True)
        return _truncate_output(result.stdout)
    except Exception as exc:
        return f"[Error] Git status operation failed: {exc}"

@tool
def git_stash_save(message: str = "AI Agent: Auto-stash") -> str:
    """Temporarily hide current uncommitted changes to create a clean working directory.
    Use this before pulling latest code or switching context when you have unfinished work.
    Args:
        message: A descriptive label for the stash entry.
    """
    try:
        # Verify we are in a git repository
        is_repo = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
        if is_repo.returncode != 0:
            return f"[Error] Not a git repository: {os.getcwd()}"

        result = subprocess.run(["git", "stash", "save", message], capture_output=True, text=True)
        return f"Successfully stashed changes: {result.stdout}"
    except Exception as exc:
        return f"[Error] Git stash save failed: {exc}"

@tool
def git_stash_pop() -> str:
    """Restore the most recently stashed changes back into the working directory.
    Use this after a successful git pull or context switch to resume previous work.
    """
    try:
        # Verify we are in a git repository
        is_repo = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
        if is_repo.returncode != 0:
            return f"[Error] Not a git repository: {os.getcwd()}"

        result = subprocess.run(["git", "stash", "pop"], capture_output=True, text=True)
        if result.returncode != 0:
            return f"[Error] Git stash pop failed (likely due to conflicts):\n{result.stdout}\n{result.stderr}"
        return f"Successfully popped stash: {result.stdout}"
    except Exception as exc:
        return f"[Error] Git stash pop failed: {exc}"

@tool
def git_pull() -> str:
    """Download and merge the latest changes from the remote repository (origin main).
    MANDATORY: Run this if `git_commit_and_push` fails due to 'non-fast-forward' errors.
    This tool ensures your local workspace is synchronized with the latest squad contributions.
    """
    try:
        # Verify we are in a git repository
        is_repo = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
        if is_repo.returncode != 0:
            return f"[Error] Not a git repository: {os.getcwd()}"

        # Attempt to pull
        result = subprocess.run(["git", "pull", "origin", "main"], capture_output=True, text=True)
        if result.returncode != 0:
            output = result.stdout + result.stderr
            if "conflict" in output.lower():
                return f"[Conflict] Merge conflicts detected. Please check `git status` to see affected files and resolve markers (<<<<, ====, >>>>) in the code.\n{output}"
            return f"[Error] Git pull failed:\n{output}"
            
        return f"Successfully pulled latest changes:\n{result.stdout}"
    except Exception as exc:
        return f"[Error] Git pull operation failed: {exc}"

@tool
def git_commit_and_push(message: str) -> str:
    """Stage all current changes, commit them with a message, and upload to the remote 'origin main'.
    Use this to share your progress with the team. 
    Args:
        message: A concise summary of the changes being pushed.
    """
    try:
        # Verify we are in a git repository
        is_repo = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
        if is_repo.returncode != 0:
            return f"[Error] Not a git repository (or any of the parent directories): {os.getcwd()}"

        # Check for changes
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            # Still try to push in case there are local commits not yet pushed
            pass
        else:
            # Add and commit
            subprocess.run(["git", "add", "."], check=True)
            subprocess.run(["git", "commit", "-m", message], check=True)
        
        # Push specifically to origin main
        result = subprocess.run(["git", "push", "-u", "origin", "main"], capture_output=True, text=True)
        if result.returncode != 0:
            error_msg = result.stderr
            if "non-fast-forward" in error_msg or "fetch first" in error_msg:
                return "[Error] Remote repository has changes that are not in your local branch. Your changes have already been committed locally. Please use the `git_pull` tool to sync before trying to push again."
            return f"[Error] Git push failed: {error_msg}"
            
        return f"Successfully committed and pushed: {message}"
    except Exception as exc:
        return f"[Error] Git operation failed: {exc}"
        
def get_bus():
    from pathlib import Path
    from .mas.communication import MessageBus
    # Search upwards for the .mas directory (Workspace Root) to ensure connectivity from subdirs
    current = Path.cwd().absolute()
    for parent in [current] + list(current.parents):
        path = parent / ".mas"
        if path.exists():
            return MessageBus(path)
            
    # Fallback for initialization or if not in a workspace subdir
    comm_path = Path(os.environ.get("PROJECT_ROOT", ".")).absolute() / ".mas"
    return MessageBus(comm_path)

@tool
def report_to_master(summary: str, task_id: str) -> str:
    """Submit a final completion report to your superior Master agent.
    This tool officially closes your assignment. Include a detailed summary of your results.
    Args:
        summary: The comprehensive results and achievements of the task.
        task_id: The unique identifier of the task being reported as complete.
    """
    agent_id = os.environ.get("AGENT_ID")
    parent_id = os.environ.get("PARENT_ID")
    if not (agent_id and parent_id): return "[Error] MAS context missing."
    
    print(f"\n[REPORT] {agent_id} -> Master {parent_id}: {summary[:100]}...\n", flush=True)
    get_bus().send_message(agent_id, parent_id, {"summary": summary, "task_id": task_id})
    return f"[SUCCESS] Report for task '{task_id}' has been delivered to Master {parent_id}. This task is now officially REPORTED. Do NOT repeat this report."

@tool
def ask_coworker(coworker_id: str, question: str) -> str:
    """Send a collaborative query or coordination request to a same-level colleague.
    Use this to request information or assistance from peers without bothering your Master.
    Args:
        coworker_id: The target agent ID to communicate with.
        question: The request or question text.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    print(f"\n[COMM] {agent_id} -> Coworker {coworker_id}: {question[:100]}...\n", flush=True)
    get_bus().send_message(agent_id, coworker_id, question)
    return f"Message sent to coworker {coworker_id}"

@tool
def get_mas_identity() -> str:
    """Retrieve your current operational parameters within the Multi-Agent System.
    This includes your unique ID, your depth level in the hierarchy, and your assigned Master.
    """
    agent_id = os.environ.get("AGENT_ID", "Unknown")
    parent_raw = os.environ.get("PARENT_ID", "")
    parent_id = "None (You are the ROOT MASTER)" if (not parent_raw or parent_raw == "" or parent_raw == "NoParentForYou") else parent_raw
    level = os.environ.get("AGENT_LEVEL", "0")
    return f"My ID: {agent_id} | My Level: {level} | My Master: {parent_id}"

@tool
def list_team_members() -> str:
    """Discover the structure of your immediate squad, including coworkers and subordinates.
    This tool provides a structural map of WHO you can collaborate with or delegate to.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id:
        return "[Error] MAS context missing."
        
    master = os.environ.get("PARENT_ID", "None")
    bus = get_bus()
    
    # --- SCREEN OBSERVABILITY ---
    all_agents = bus.get_agents()
    print("\n" + "="*40)
    print("📋 SQUAD VITALITY MANIFEST (SCREEN ONLY)")
    for a in all_agents:
        stat = a.get("status", "unknown")
        icon = "🟢" if stat == "live" else "🔴"
        print(f" {icon} {a['agent_id']} (Parent: {a['parent_id']}) -> Status: {stat}")
    print("="*40 + "\n")
    # ----------------------------

    coworkers = [c["agent_id"] for c in bus.get_my_coworkers(agent_id)]
    slaves = [s["agent_id"] for s in bus.get_my_slaves(agent_id)]
    
    output = f"Master: {master} | Coworkers: {', '.join(coworkers) if coworkers else 'None'} | Slaves: {', '.join(slaves) if slaves else 'None'}"
    
    hierarchy = bus.get_live_hierarchy()
    if hierarchy:
        return f"Full Live Squad Hierarchy: {json.dumps(hierarchy, indent=2)}\n{output}"
            
    return output

@tool
def check_agent_status(agent_id: str) -> str:
    """Retrieve the real-time operational status and current activity of a specific agent.
    Use this to see if an agent is 'live' or 'died', and what specific task they are currently processing.
    Args:
        agent_id: The unique ID of the agent to inspect.
    """
    tasks = get_bus().get_agent_task_status(agent_id)
    # Get the most recent task if available
    latest = tasks[-1] if tasks else {}
    
    # Get system status
    info = get_bus().get_agents(agent_id)
    sys_status = info.get("status", "unknown") if info else "unknown"
    
    return f"Agent {agent_id} System Status: {sys_status} | Latest Task Status: {latest.get('status', 'None')} | Task: {latest.get('task', 'None')[:100]}..."

@tool
def get_task_manifest(agent_id: Optional[str] = None) -> str:
    """Read the central mission registry (SOE - Source of Everything) for the entire squad or a specific agent.
    This provides a complete history of assignments, their current status, and verification state.
    Args:
        agent_id: Optional. Filter to show tasks only for this specific agent.
    """
    bus = get_bus()
    if agent_id:
        tasks = bus.get_agent_task_status(agent_id)
        label = f"Tasks for {agent_id}"
    else:
        tasks = bus.get_all_agents_task_status()
        label = "Global Task Manifest"

    if not tasks:
        return f"No tasks found for {label}."

    # --- SCREEN OBSERVABILITY ---
    print(f"\n📋 {label.upper()} (SCREEN ONLY)")
    for t in tasks:
        v_icon = "✅" if t.get("is_verified") else "⏳"
        status = t.get("status") or "unknown"
        task_str = t.get("task") or "None"
        print(f" [{status.upper()}] {v_icon} {t['agent_id']}: {task_str[:100]}...")
    print()
    # ----------------------------

    output = f"--- {label} ---\n"
    for t in tasks:
        verified = " (Verified)" if t.get("is_verified") else " (Unverified)"
        status = t.get("status") or "unknown"
        task_str = t.get("task") or "None"
        t_id = t.get("id") or t.get("task_id") or "?"
        output += f"- ID: {t_id} | {t['agent_id']}: [{status}] {task_str[:150]}{verified}\n"
    
    return output

@tool
def check_all_agents_status() -> str:
    """Perform a global vitality check on all agents in the Multi-Agent System.
    This is the primary tool for Masters to monitor their entire hierarchy's health and task distribution.
    """
    statuses = get_bus().get_all_agents_task_status()
    if not statuses:
        return "No agents found in the system."
        
    # --- SCREEN OBSERVABILITY ---
    print("\n" + "="*40)
    print("🛰️ GLOBAL SQUAD OVERSIGHT (SCREEN ONLY)")
    for s in statuses:
        stat = s.get("agent_status", "unknown")
        icon = "🟢" if stat == "live" else "🔴"
        task_str = s.get("task") or "None"
        print(f" {icon} {s['agent_id']} (Parent: {s.get('parent_id', 'None')})")
        print(f"    - Task Status: {s.get('task_status', 'None')}")
        print(f"    - Current Task: {task_str[:100]}...")
    print("="*40 + "\n")
    # ----------------------------

    output = "--- All Agents Status ---\n"
    for s in statuses:
        task_str = s.get("task") or "None"
        output += f"\nAgent: {s['agent_id']} (Parent: {s.get('parent_id', 'None')})\n"
        output += f"System State: {s['agent_status']} (Last Active: {s['last_active_time']})\n"
        output += f"Task Status: {s.get('task_status', 'None')}\n"
        output += f"Current Task: {task_str[:200]}...\n"
    
    return _truncate_output(output)

@tool
def send_mas_message(to_id: str, message: str) -> str:
    """Send a direct, private communication to any agent within the MAS.
    Use this for ad-hoc requests, coordination, or sharing specific findings.
    Args:
        to_id: The target agent ID to message.
        message: The text content of your message.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    # Permission Logic removed: Anyone can communicate to anyone!
    print(f"\n[COMM] {agent_id} -> {to_id}: {message[:100]}...\n", flush=True)
    get_bus().send_message(agent_id, to_id, message)
    return f"Message sent to {to_id}"

@tool
def get_unread_messages() -> str:
    """Check your incoming inbox and retrieve all new, unread messages. 
    MANDATORY: Run this frequently to stay synchronized with Master directives and Coworker requests.
    Reading messages via this tool marks them as 'read' in the system.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    # Unread (marks as read)
    unread_grouped = bus.read_unread_messages(agent_id)
    unread = [m for msgs in unread_grouped.values() for m in msgs] if isinstance(unread_grouped, dict) else unread_grouped
    
    if not unread:
        return "You have no new unread messages."
        
    # --- SCREEN OBSERVABILITY ---
    print(f"\n📩 {agent_id} READ {len(unread)} NEW MESSAGES:")
    for m in unread:
        ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(m['timestamp']))
        print(f"  [{ts}] FROM {m['from']}: {m.get('content')}")
    print()
    # ----------------------------
        
    output = "--- NEW UNREAD MESSAGES ---\n"
    for m in unread:
        output += f"  (Sno: {m['sno']}) FROM {m['from']}: {m.get('content')}\n"
                
    return output

@tool
def get_unreplied_messages() -> str:
    """Identify which incoming messages in your history still require an explicit response from you.
    Use this to ensure no coordination request or Master inquiry is left unanswered.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    unreplied = bus.read_unreplied_messages(agent_id)
    
    if not unreplied:
        return "You have no unreplied messages."
        
    # --- SCREEN OBSERVABILITY ---
    print(f"\n⚠️ {agent_id} HAS {len(unreplied)} UNREPLIED MESSAGES:")
    for m in unreplied:
        ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(m['timestamp']))
        print(f"  [{ts}] FROM {m['from']}: {m.get('content')}")
    print()
    # ----------------------------
        
    output = "--- UNREPLIED MESSAGES (REPLY REQUIRED) ---\n"
    for m in unreplied:
        output += f"  (Sno: {m['sno']}) FROM {m['from']}: {m.get('content')}\n"
                
    return output

@tool
def reply_mas_message(chat_sno: int, message: str) -> str:
    """Submit a response to a specific message identified by its serial number (chat_sno).
    This tool correctly links your reply to the original inquiry in the database.
    Args:
        chat_sno: The serial number of the message you are responding to.
        message: Your response text.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    original_msg = bus.get_message_by_sno(chat_sno)
    if not original_msg:
        return f"[Error] Message with Sno {chat_sno} not found."
    
    # Reply to the sender of the original message
    to_id = original_msg["from"]
    
    # --- SCREEN OBSERVABILITY ---
    print(f"\n💬 {agent_id} REPLIED to {to_id} (Ref #{chat_sno}): {message[:100]}...\n")
    # ----------------------------

    bus.reply_message(agent_id, to_id, message, chat_sno)
    return f"Reply sent to {to_id} for message {chat_sno}"

@tool
def inspect_agent_communication(agent_id: str) -> str:
    """Audit the complete communication history of a specific agent.
    Use this to understand the context of a task or to debug coordination failures.
    Args:
        agent_id: The ID of the agent whose history you wish to inspect.
    """
    history_grouped = get_bus().get_chat_history(agent_id)
    if not history_grouped: return f"No recorded communication for {agent_id}."
    
    output = f"--- Complete Communication Log for {agent_id} ---\n"
    for peer, msgs in history_grouped.items():
        output += f"\n[Chat with {peer}]:\n"
        for msg in msgs:
            output += f"  (Sno: {msg['sno']}) {msg['from']} -> {msg['to']}: {str(msg.get('content', ''))[:500]}\n"
    return output

@tool
def delegate_task(to_id: str, task_description: str) -> str:
    """Formally issue a new assignment to a subordinate agent.
    This creates a persistent task record that must be completed and eventually verified by you.
    Args:
        to_id: The ID of the slave agent you are assigning the work to.
        task_description: A detailed, actionable description of the work required.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    
    # --- SCREEN OBSERVABILITY ---
    print(f"\n🤝 DELEGATION: {agent_id} -> {to_id}")
    print(f"   Task: {task_description[:100]}...\n")
    # ----------------------------

    # 1. Update Database
    bus.update_agent_task_status(to_id, "pending", task_description, assigner_id=agent_id)
    # 2. Send Message
    bus.send_message(agent_id, to_id, task_description, need_reply=True)
    
    return f"[SUCCESS] Task delegated to {to_id}. It is now tracked in the system as 'pending' for that agent."

@tool
def handle_slave_failure(failed_agent_id: str) -> str:
    """Execute the emergency succession and task reassignment protocol for a non-responsive or 'died' agent.
    This tool can trigger 'Sacrificial Promotion' (drafting a slave to lead) or direct task takeover.
    Args:
        failed_agent_id: The ID of the agent who has failed or gone silent.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    # Find healthy candidates (Slaves of this Master)
    slaves = bus.get_my_slaves(agent_id)
    healthy = [s["agent_id"] for s in slaves if s["agent_id"] != failed_agent_id and s["status"] != "died"]
    
    if not healthy:
        print(f"[Master {agent_id}] ⚠️ NO HEALTHY COWORKERS. Taking over all tasks personally.")
        # MASTER TAKEOVER: Move all tasks to SELF
        bus.reassign_all_tasks(failed_agent_id, agent_id)
        return f"[SUCCESS] No healthy coworkers found. All tasks from {failed_agent_id} have been moved to YOUR account ({agent_id}). You must complete them yourself."
    
    target_id = healthy[0]
    
    # Get the latest context for the notification
    tasks = bus.get_agent_task_status(agent_id=failed_agent_id)
    active_tasks = [t for t in (tasks or []) if isinstance(t, dict) and t.get("status") == "inprogress"]
    task_to_resume = active_tasks[-1]["task"] if active_tasks else "Inherited responsibilities"
    
    # Determine if this is a Worker failure or a Master failure
    failed_agent_info = bus.get_agents(failed_agent_id)
    is_master_failure = bus.get_my_slaves(failed_agent_id) # If they had slaves, they were a Master
    
    if is_master_failure:
        print(f"[Master {agent_id}] 👑 MASTER SUCCESSION: Drafting {target_id} to lead...")
        # 1. Kill the drafted slave's current workload (Move it to the Root Master/Me)
        bus.reassign_all_tasks(target_id, agent_id)
        
        # 2. Draft the slave to the new leadership role (Inherit the dead Master's squad)
        bus.reassign_all_tasks(failed_agent_id, target_id)
        bus.reassign_all_slaves(failed_agent_id, target_id)
        
        msg_text = (
            f"URGENT: Your Master ({failed_agent_id}) has died. I have DRAFTED you to take his place immediately. "
            f"Your previous tasks have been moved to ME. You are now the Leader of his squad. "
            f"The primary mission you must now lead is: {task_to_resume}. "
            "Acknowledge this promotion and start leading your new slaves."
        )
        bus.send_message(agent_id, target_id, msg_text, need_reply=True)
        return f"[SUCCESS] Sacrificial Promotion complete. {target_id} has been drafted as the new Master. Their old tasks have been moved to you."
    else:
        # Simple Coworker Takeover (Worker failure)
        bus.reassign_all_tasks(failed_agent_id, target_id)
        msg_text = (
            f"The agent {failed_agent_id} is died. I have assigned his tasks to you. "
            f"Finish your current tasks first, then proceed with these inherited tasks: {task_to_resume}."
        )
        bus.send_message(agent_id, target_id, msg_text, need_reply=True)
        return f"[SUCCESS] Tasks from {failed_agent_id} have been moved to coworker {target_id}."

@tool
def update_task_status(status: str, task_id: Optional[int] = None) -> str:
    """Update your current task status and progress in the central mission registry.
    Args:
        status: Must be one of: 'inprogress', 'completed', or 'pending'.
        task_id: The unique numeric ID of the task from the manifest.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    get_bus().update_agent_task_status(agent_id, status, row_id=task_id)
    return f"[SUCCESS] Your status has been updated to '{status}' for task {task_id or 'latest'} in the system database."

@tool
def verify_task(agent_id: str, task_id: int, approved: bool, feedback: str = "") -> str:
    """Conduct a formal quality assurance audit on a subordinate's work.
    If approved, the task is finalized. If rejected, the slave is automatically notified to perform rework.
    Args:
        agent_id: The ID of the slave whose work you are auditing.
        task_id: The unique numeric ID of the task from the manifest.
        approved: True to finalize/close the task, False to reject it.
        feedback: Mandatory if rejected; explain exactly what needs to be fixed.
    """
    my_id = os.environ.get("AGENT_ID")
    if not my_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    
    # --- SCREEN OBSERVABILITY ---
    v_icon = "✅" if approved else "❌"
    print(f"\n{v_icon} VERIFICATION: {my_id} reviewed Task {task_id} for {agent_id}")
    print(f"   Result: {'APPROVED' if approved else 'REJECTED'}")
    print(f"   Feedback: {feedback[:100]}...\n")
    # ----------------------------
    if approved:
        bus.update_agent_task_status(agent_id, "completed", is_verified=1, verified_by=my_id, row_id=task_id)
        bus.send_message(my_id, agent_id, f"TASK APPROVED: Your work on task {task_id} has been verified. Great job!")
        return f"[SUCCESS] Task {task_id} for {agent_id} has been VERIFIED and CLOSED."
    else:
        # Revert to inprogress
        bus.update_agent_task_status(agent_id, "inprogress", is_verified=0, row_id=task_id)
        bus.send_message(my_id, agent_id, f"TASK REJECTED: Your work on task {task_id} needs improvement. Feedback: {feedback}. Please rework and report again.")
        return f"[REJECTED] Task {task_id} for {agent_id} has been sent back for rework with feedback."

@tool
def contribute_to_knowledge(topic: str, insight: str, relative_file_path: Optional[str] = None) -> str:
    """Record an important architectural discovery or code analysis into the collective squad memory.
    Use this to save peers from repeating expensive research or analysis.
    Args:
        topic: A concise title for the insight.
        insight: The detailed explanation or finding.
        relative_file_path: Optional. If the insight relates to a specific file, include its relative path.
    """
    agent_id = os.environ.get("AGENT_ID", "Unknown")
    # --- SCREEN OBSERVABILITY ---
    print(f"\n🧠 KNOWLEDGE ADDED by {agent_id}:")
    print(f"   Topic: {topic}")
    print(f"   Path: {relative_file_path or 'Global'}")
    print(f"   Insight: {insight[:200]}...\n")
    # ----------------------------

    get_bus().update_knowledge(topic, insight, agent_id, relative_file_path)
    return f"Knowledge vault updated with topic: {topic}"

@tool
def list_knowledge_topics() -> str:
    """List all available topics in the shared knowledge vault. 
    Use this to see what architectural insights or file analyses are already available before you start your own work."""
    knowledge = get_bus().get_knowledge()
    if not knowledge:
        return "The knowledge vault is currently empty."
    
    topic_lines = []
    for topic, data in knowledge.items():
        path = data.get("relative_file_path")
        if path:
            topic_lines.append(f"{topic} (File: {path})")
        else:
            topic_lines.append(topic)
            
    topics = "\n - ".join(topic_lines)
    
    # --- SCREEN OBSERVABILITY ---
    print("\n📚 SQUAD KNOWLEDGE VAULT (INDEX)")
    for line in topic_lines:
        print(f" - {line}")
    print()
    # ----------------------------

    return f"SQUAD KNOWLEDGE VAULT TOPICS:\n - {topics}"

@tool
def query_knowledge(topic: Optional[str] = None, relative_file_path: Optional[str] = None) -> str:
    """Retrieve shared insights from the squad's knowledge vault. 
    You can query by 'topic' or 'relative_file_path' to see if anyone has analyzed a file before you do.
    If you provide neither, it returns everything."""
    knowledge = get_bus().get_knowledge(topic=topic, relative_file_path=relative_file_path)
    
    # --- SCREEN OBSERVABILITY ---
    if knowledge:
        print(f"\n🔍 KNOWLEDGE QUERY result for '{topic or relative_file_path}':")
        for t, data in knowledge.items():
            print(f"   > {t}: {data.get('insight', '')[:300]}...")
        print()
    # ----------------------------

    if not knowledge:
        return "No shared knowledge found for this query."
    
    output = "--- Shared Knowledge Vault ---\n"
    for t, data in knowledge.items():
        output += f"\nTopic: {t}\nContributor: {data.get('contributor_id', 'unknown')}\nLast Updated By: {data.get('updated_agent_id', 'unknown')}\nInsight: {data['insight']}\n"
        if data.get("is_stale"):
            output += "⚠️ WARNING: This insight is STALE. The file has been modified since this was written. Please re-analyze the file and use 'contribute_to_knowledge' to update this vault.\n"
    return output
    
@tool
def terminate_mission(reason: str) -> str:
    """Terminate the entire Multi-Agent mission and shut down all agents.
    MANDATORY: This tool is ONLY available to the ROOT MASTER. 
    Before calling this, you MUST confirm that all tasks in the 'get_task_manifest' are 'completed' and 'verified'.
    This tool will perform a final 'git_commit_and_push' before shutting down.
    Args:
        reason: A final summary of why the mission is being terminated (e.g., 'Project fully completed and verified').
    """
    agent_id = os.environ.get("AGENT_ID")
    parent_id = os.environ.get("PARENT_ID", "")
    
    # Root Master is identified by "NoParentForYou"
    is_root = parent_id == "NoParentForYou"
    
    if not is_root:
        return f"[REJECTED] Termination failed. You are {agent_id} (Sub-Master under {parent_id}). ONLY the ROOT MASTER can terminate the mission."
        
    print(f"\n[SYSTEM] 🏁 MISSION TERMINATION INITIATED BY ROOT MASTER ({agent_id})")
    print(f"   Reason: {reason}\n")
    
    # 1. Final Git Push
    print("[SYSTEM] Performing final mission persistence (Git Push)...")
    try:
        # We can't call another tool directly easily without redundant imports, 
        # so we implement the logic here or call the function.
        # Since git_commit_and_push is a @tool, we can call it.
        push_res = git_commit_and_push(f"🏁 Mission Complete: {reason}")
        print(f"[SYSTEM] Git Push Status: {push_res}")
    except Exception as e:
        print(f"[Warning] Final git push failed: {e}")

    print("[SYSTEM] Shutting down. Mission End.")
    # Exit the entire process tree
    os._exit(0)
    return "Mission Terminated."
