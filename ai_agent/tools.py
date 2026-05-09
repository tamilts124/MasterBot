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
    """Rename a file within the current working directory safely."""
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
    """Execute a Windows batch script and return its output."""
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
    """Execute a Bash script on Unix-like systems and return its output."""
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
    """Execute a Python script using the same interpreter and return its output."""
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
    """Check if the WhatsApp API is currently connected to a session."""
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
    """Send a WhatsApp message to the target JID specified during startup."""
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
    """Retrieve the last N messages from the target WhatsApp history."""
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
    """Search the web for a query using DuckDuckGo and return top results."""
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
    """Fetch raw content from a URL and return it as text."""
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
    """Check the current status of the git repository, including staged, unstaged, and untracked files."""
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
    """Stash the current local changes to allow for a clean pull or context switch."""
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
    """Pop the most recent stash back into the working directory."""
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
    """Pull the latest changes from the remote repository (origin main).
    Use this if git_commit_and_push fails because the remote repository has changes.
    If conflicts occur, you must manually resolve them by editing the files."""
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
    """Commit all current changes and push them to the remote repository. 
    Ensure you are in the root or a subdirectory of the git repository before calling this.
    If this fails due to remote changes, you MUST use git_pull first."""
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
    # Use the absolute path to .mas to ensure it works from any subdirectory
    comm_path = Path(os.environ.get("PROJECT_ROOT", ".")).absolute() / ".mas"
    return MessageBus(comm_path)

@tool
def report_to_master(summary: str, task_id: str) -> str:
    """Report task completion and a summary of achievements to the Master agent."""
    agent_id = os.environ.get("AGENT_ID")
    parent_id = os.environ.get("PARENT_ID")
    if not (agent_id and parent_id): return "[Error] MAS context missing."
    
    print(f"\n[REPORT] {agent_id} -> Master {parent_id}: {summary[:100]}...\n", flush=True)
    get_bus().send_message(agent_id, parent_id, {"summary": summary, "task_id": task_id})
    return f"[SUCCESS] Report for task '{task_id}' has been delivered to Master {parent_id}. This task is now officially REPORTED. Do NOT repeat this report."

@tool
def ask_coworker(coworker_id: str, question: str) -> str:
    """Send a coordination request to a same-level coworker."""
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    print(f"\n[COMM] {agent_id} -> Coworker {coworker_id}: {question[:100]}...\n", flush=True)
    get_bus().send_message(agent_id, coworker_id, question)
    return f"Message sent to coworker {coworker_id}"

@tool
def get_mas_identity() -> str:
    """Retrieve the agent's own MAS ID, hierarchical level, and parent Master ID."""
    agent_id = os.environ.get("AGENT_ID", "Unknown")
    parent_id = os.environ.get("PARENT_ID", "None")
    level = os.environ.get("AGENT_LEVEL", "0")
    return f"My ID: {agent_id} | My Level: {level} | My Master: {parent_id}"

@tool
def list_team_members() -> str:
    """List the IDs of the direct Master, all Coworkers, and any active Slaves.
    The Root Master will see the entire recursive hierarchy of the squad."""
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id:
        return "[Error] MAS context missing."
        
    master = os.environ.get("PARENT_ID", "None")
    bus = get_bus()
    coworkers = [c["agent_id"] for c in bus.get_my_coworkers(agent_id)]
    slaves = [s["agent_id"] for s in bus.get_my_slaves(agent_id)]
    
    output = f"Master: {master} | Coworkers: {', '.join(coworkers) if coworkers else 'None'} | Slaves: {', '.join(slaves) if slaves else 'None'}"
    
    hierarchy = bus.get_live_hierarchy()
    if hierarchy:
        return f"Full Live Squad Hierarchy: {json.dumps(hierarchy, indent=2)}\n{output}"
            
    return output

@tool
def check_agent_status(agent_id: str) -> str:
    """Check the real-time status and current task of a specific agent."""
    status = get_bus().get_agent_task_status(agent_id)
    return f"Agent {agent_id} Status: {status.get('status')} | Current Task: {status.get('current_task')}"

@tool
def check_all_agents_status() -> str:
    """Check the real-time system state and current tasks of all agents in the squad."""
    statuses = get_bus().get_all_agents_task_status()
    if not statuses:
        return "No agents found in the system."
        
    output = "--- All Agents Status ---\n"
    for s in statuses:
        output += f"\nAgent: {s['agent_id']} (Parent: {s['parent_id']})\n"
        output += f"System State: {s['agent_status']} (Last Active: {s['last_active_time']})\n"
        output += f"Task Status: {s.get('task_status', 'None')}\n"
        output += f"Current Task: {s.get('task', 'None')[:200]}...\n"
    
    return _truncate_output(output)

@tool
def send_mas_message(to_id: str, message: str) -> str:
    """Send a coordination message to any direct Master, Coworker, or Slave."""
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    # Permission Logic removed: Anyone can communicate to anyone!
    print(f"\n[COMM] {agent_id} -> {to_id}: {message[:100]}...\n", flush=True)
    get_bus().send_message(agent_id, to_id, message)
    return f"Message sent to {to_id}"

@tool
def get_unread_messages() -> str:
    """Retrieve all NEW unread messages addressed to you. This marks them as read."""
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    # Unread (marks as read)
    unread_grouped = bus.read_unread_messages(agent_id)
    unread = [m for msgs in unread_grouped.values() for m in msgs] if isinstance(unread_grouped, dict) else unread_grouped
    
    if not unread:
        return "You have no new unread messages."
        
    output = "--- NEW UNREAD MESSAGES ---\n"
    for m in unread:
        output += f"  (Sno: {m['sno']}) FROM {m['from']}: {m.get('content')}\n"
                
    return output

@tool
def get_unreplied_messages() -> str:
    """Retrieve all messages addressed to you that still require a response."""
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    unreplied = bus.read_unreplied_messages(agent_id)
    
    if not unreplied:
        return "You have no unreplied messages."
        
    output = "--- UNREPLIED MESSAGES (REPLY REQUIRED) ---\n"
    for m in unreplied:
        output += f"  (Sno: {m['sno']}) FROM {m['from']}: {m.get('content')}\n"
                
    return output

@tool
def reply_mas_message(chat_sno: int, message: str) -> str:
    """Reply to a specific message using its serial number (chat_sno)."""
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    original_msg = bus.get_message_by_sno(chat_sno)
    if not original_msg:
        return f"[Error] Message with Sno {chat_sno} not found."
    
    # Reply to the sender of the original message
    to_id = original_msg["from"]
    bus.reply_message(agent_id, to_id, message, chat_sno)
    return f"Reply sent to {to_id} for message {chat_sno}"

@tool
def inspect_agent_communication(agent_id: str) -> str:
    """Read the complete chat history for a specific agent (Auditing)."""
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
    """Assign a specific task to a slave and track it in the system database.
    This both sends a message to the agent and updates their status to 'pending'."""
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    # 1. Update Database
    bus.update_agent_task_status(to_id, "pending", task_description, assigner_id=agent_id)
    # 2. Send Message
    bus.send_message(agent_id, to_id, task_description, need_reply=True)
    
    return f"[SUCCESS] Task delegated to {to_id}. It is now tracked in the system as 'pending' for that agent."

@tool
def handle_slave_failure(failed_agent_id: str) -> str:
    """Initiate the emergency reassignment of all tasks from a failed/died agent to a healthy coworker.
    Use this if you see an agent's status is 'died' or if they have gone silent for too long."""
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
    active_tasks = [t for t in tasks if t["status"] == "inprogress"]
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
def update_task_status(status: str, task_description: Optional[str] = None) -> str:
    """Update your own current task status and description in the system database.
    Use this to inform the squad and your Master about what you are currently doing.
    Valid statuses: 'inprogress', 'completed', 'pending'."""
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    get_bus().update_agent_task_status(agent_id, status, task_description)
    return f"[SUCCESS] Your status has been updated to '{status}' in the system database."

@tool
def verify_task(agent_id: str, task_description: str, approved: bool, feedback: str = "") -> str:
    """Review and verify a completed task from a slave.
    If approved=True, the task is marked as officially 'verified' and closed.
    If approved=False, the task is moved back to 'inprogress' and feedback is sent to the slave."""
    my_id = os.environ.get("AGENT_ID")
    if not my_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    if approved:
        bus.update_agent_task_status(agent_id, "completed", task_description, is_verified=1, verified_by=my_id)
        bus.send_message(my_id, agent_id, f"TASK APPROVED: Your work on '{task_description}' has been verified. Great job!")
        return f"[SUCCESS] Task '{task_description}' for {agent_id} has been VERIFIED and CLOSED."
    else:
        # Revert to inprogress
        bus.update_agent_task_status(agent_id, "inprogress", task_description, is_verified=0)
        bus.send_message(my_id, agent_id, f"TASK REJECTED: Your work on '{task_description}' needs improvement. Feedback: {feedback}. Please rework and report again.")
        return f"[REJECTED] Task '{task_description}' for {agent_id} has been sent back for rework with feedback."

@tool
def contribute_to_knowledge(topic: str, insight: str, relative_file_path: Optional[str] = None) -> str:
    """Add a significant architectural insight, file analysis, or mission finding to the shared knowledge base.
    Other agents can query this instead of re-analyzing the same code/data.
    If this insight is about a specific file, provide its relative path so the vault can track if the file changes."""
    agent_id = os.environ.get("AGENT_ID", "Unknown")
    get_bus().update_knowledge(topic, insight, agent_id, relative_file_path)
    print(f"\n[KNOWLEDGE] {agent_id} contributed insight on '{topic}'\n", flush=True)
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
    return f"SQUAD KNOWLEDGE VAULT TOPICS:\n - {topics}"

@tool
def query_knowledge(topic: Optional[str] = None, relative_file_path: Optional[str] = None) -> str:
    """Retrieve shared insights from the squad's knowledge vault. 
    You can query by 'topic' or 'relative_file_path' to see if anyone has analyzed a file before you do.
    If you provide neither, it returns everything."""
    knowledge = get_bus().get_knowledge(topic=topic, relative_file_path=relative_file_path)
    if not knowledge:
        return "No shared knowledge found for this query."
    
    output = "--- Shared Knowledge Vault ---\n"
    for t, data in knowledge.items():
        output += f"\nTopic: {t}\nContributor: {data.get('contributor_id', 'unknown')}\nLast Updated By: {data.get('updated_agent_id', 'unknown')}\nInsight: {data['insight']}\n"
        if data.get("is_stale"):
            output += "⚠️ WARNING: This insight is STALE. The file has been modified since this was written. Please re-analyze the file and use 'contribute_to_knowledge' to update this vault.\n"
    return output
