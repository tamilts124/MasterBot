import os
from pathlib import Path
from typing import Any, List, Optional, Union

from langchain_community.agent_toolkits import FileManagementToolkit
from langchain_ollama import ChatOllama
from langchain.agents import create_agent
from langchain_core.messages import BaseMessage

from .tools import (
    rename_file, run_bat, run_bash, run_python,
    is_whatsapp_connected, send_whatsapp_message, get_whatsapp_last_messages,
    web_search, fetch_url, git_commit_and_push
)

def build_agent(work_dir: Path, model_name: str, streaming: bool = False, 
                whatsapp_jid: Optional[str] = None, whatsapp_url: Optional[str] = None,
                ollama_url: Optional[str] = None, ollama_key: Optional[str] = None,
                ollama_ctx: int = 65536):
    """Create a ReAct agent bound to ``work_dir`` and ``model_name``."""
    work_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(work_dir)

    tools = FileManagementToolkit(
        root_dir=str(work_dir),
        selected_tools=["read_file", "write_file", "list_directory"],
    ).get_tools()
    
    # Generic tools
    tools.extend([rename_file, run_bat, run_bash, run_python, web_search, fetch_url, git_commit_and_push])

    # Conditionally add WhatsApp tools
    if whatsapp_jid:
        os.environ["WHATSAPP_TARGET_JID"] = whatsapp_jid
        if whatsapp_url:
            os.environ["WHATSAPP_BASE_URL"] = whatsapp_url
        tools.extend([is_whatsapp_connected, send_whatsapp_message, get_whatsapp_last_messages])

    # Ollama configuration
    ollama_kwargs = {
        "model": model_name,
        "format": "json",
        "streaming": streaming,
        "temperature": 0,
        "num_ctx": ollama_ctx
    }
    if ollama_url:
        ollama_kwargs["base_url"] = ollama_url
    
    if ollama_key:
        # Pass API key and User-Agent via headers
        ollama_kwargs["client_kwargs"] = {
            "headers": {
                "Authorization": f"Bearer {ollama_key}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            }
        }

    llm = ChatOllama(**ollama_kwargs)
    return create_agent(llm, tools)

def extract_reply(result: Any) -> str:
    """Helper to extract plain-text reply from various LangChain result shapes."""
    if isinstance(result, str):
        return result
    
    if hasattr(result, "content"):
        return str(result.content)

    if isinstance(result, dict):
        if "output" in result and isinstance(result["output"], str):
            return result["output"]
        
        messages = result.get("messages")
        if isinstance(messages, list) and messages:
            for msg in reversed(messages):
                if hasattr(msg, "content") and msg.content:
                    return str(msg.content)
        
        if "model" in result and isinstance(result["model"], dict):
            return extract_reply(result["model"])

        if len(result) == 1:
            val = list(result.values())[0]
            if isinstance(val, str):
                return val

    return str(result)
