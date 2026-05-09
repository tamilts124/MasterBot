import os
import urllib.parse
from langchain_core.tools import tool
from .common import _whatsapp_request, _get_whatsapp_config, _truncate_output

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
    
    # Fallback to own JID if none specified
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
