import os
import sys
import json
import urllib.request
from langchain_core.tools import tool

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
