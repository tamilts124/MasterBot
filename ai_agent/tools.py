import os
import sys
import subprocess
import tempfile
import json
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
def git_commit_and_push(message: str) -> str:
    """Commit all current changes and push them to the remote repository. 
    Ensure you are in the root or a subdirectory of the git repository before calling this."""
    try:
        # Verify we are in a git repository
        is_repo = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
        if is_repo.returncode != 0:
            return f"[Error] Not a git repository (or any of the parent directories): {os.getcwd()}"

        # Check for changes
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            return "No changes to commit."
            
        # Add and commit
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", message], check=True)
        
        # Push specifically to origin main
        result = subprocess.run(["git", "push", "-u", "origin", "main"], capture_output=True, text=True)
        if result.returncode != 0:
            return f"[Error] Git push failed: {result.stderr}"
            
        return f"Successfully committed and pushed: {message}"
    except Exception as exc:
        return f"[Error] Git operation failed: {exc}"
