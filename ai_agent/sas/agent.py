import os
import time
import json
import re
from pathlib import Path
from typing import List, Optional, Union, Dict, Any, ClassVar

from langchain_ollama import ChatOllama
from langchain_community.agent_toolkits import FileManagementToolkit
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

# Import tools (Technical & WhatsApp, no MAS)
from ..tools import (
    rename_file, run_bat, run_bash, run_python, web_search, fetch_url, 
    start_interactive_process, list_interactive_processes, get_process_history, send_to_process, stop_interactive_process,
    git_status, git_pull, git_stash_save, git_stash_pop, git_commit_and_push,
    is_whatsapp_connected, send_whatsapp_message, get_whatsapp_last_messages,
    capture_screenshot, get_mouse_position, mouse_move, mouse_click, keyboard_type, keyboard_press, get_screen_size, analyze_screenshot, image_to_array
)

class TenaciousOllama(ChatOllama):
    internal_api_keys: str = ""
    last_successful_key_index: ClassVar[int] = 0
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Store keys in the validated field
        self.internal_api_keys = kwargs.get("api_key", "")

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        agent_id = os.environ.get("AGENT_ID", "Agent")
        active_proxy = os.environ.get("ACTIVE_PROXY", "DIRECT")
        
        # Use only the keys passed during initialization
        all_keys = []
        if hasattr(self, "internal_api_keys") and self.internal_api_keys:
            all_keys = [k.strip() for k in self.internal_api_keys.split(",") if k.strip()]
            
        max_retries = max(3, len(all_keys))
        for attempt in range(max_retries):
            # Start from the last successful index and cycle through
            key_idx = (TenaciousOllama.last_successful_key_index + attempt) % len(all_keys) if all_keys else 0
            current_key = all_keys[key_idx] if all_keys else ""
            
            try:
                if current_key:
                    # Create a fresh internal instance to ensure the new key is used by the client
                    temp_llm = ChatOllama(
                        model=self.model,
                        base_url=self.base_url,
                        api_key=current_key,
                        num_ctx=getattr(self, "num_ctx", 65536),
                        temperature=getattr(self, "temperature", 0),
                        streaming=getattr(self, "streaming", False),
                        client_kwargs={"headers": {"Authorization": f"Bearer {current_key}"}}
                    )
                    res = temp_llm._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
                    # Success! Remember this key index for the next turn
                    TenaciousOllama.last_successful_key_index = key_idx
                    return res
                
                return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            except Exception as e:
                error_msg = str(e).lower()
                is_limit = any(term in error_msg for term in ["limit", "expiry", "429", "401", "unauthorized", "quota", "503", "overloaded"])
                
                if is_limit:
                    print(f"[Brain {agent_id}] Key/Provider limit reached or Unauthorized (Attempt {attempt+1}/{max_retries}).")
                    print("Error:", error_msg)
                    
                    # If we have more keys in the pool that we haven't tried yet, rotate to the next one
                    if len(all_keys) > 1 and attempt < len(all_keys) - 1:
                        print(f"[Brain {agent_id}] Rotating to next key in internal pool...")
                        continue
                    
                    # No more keys to try or only one key was provided
                    raise e
                else:
                    print(f"[Brain {agent_id}] Unexpected Generation Error: {e}")
                    if attempt < max_retries - 1:
                        continue
                    raise e
        raise Exception(f"Failed to generate response after {max_retries} attempts.")

def build_agent(work_dir: Path, model_name: str, streaming: bool = False, 
                whatsapp_jid: Optional[str] = None, whatsapp_url: Optional[str] = None,
                ollama_url: Optional[str] = None, ollama_key: Optional[str] = None,
                ollama_ctx: int = 65536, temperature: float = 0.0,
                max_tool_output: int = 60000):
    """Create a clean Standalone ReAct agent."""
    work_dir.mkdir(parents=True, exist_ok=True)
    
    # Configure WhatsApp and Tool environment
    if whatsapp_url:
        os.environ["WHATSAPP_BASE_URL"] = whatsapp_url
    if whatsapp_jid:
        os.environ["WHATSAPP_TARGET_JID"] = whatsapp_jid
    
    os.environ["MAX_TOOL_OUTPUT"] = str(max_tool_output)

    tools = FileManagementToolkit(
        root_dir=str(work_dir),
        selected_tools=["read_file", "write_file", "list_directory"],
    ).get_tools()
    
    tools.extend([
        rename_file, run_bat, run_bash, run_python, web_search, fetch_url, 
        start_interactive_process, list_interactive_processes, get_process_history, send_to_process, stop_interactive_process,
        capture_screenshot, get_mouse_position, mouse_move, mouse_click, keyboard_type, keyboard_press, get_screen_size, analyze_screenshot, image_to_array,
        git_status, git_pull, git_stash_save, git_stash_pop, git_commit_and_push
    ])

    if whatsapp_jid:
        tools.extend([is_whatsapp_connected, send_whatsapp_message, get_whatsapp_last_messages])

    # If multiple keys are passed, use the first one for initial construction
    first_key = [k.strip() for k in ollama_key.split(",") if k.strip()][0] if ollama_key else None
    
    llm = TenaciousOllama(
        model=model_name,
        base_url=ollama_url,
        api_key=ollama_key,
        num_ctx=ollama_ctx,
        temperature=temperature,
        streaming=streaming,
        client_kwargs={"headers": {"Authorization": f"Bearer {first_key}"}} if first_key else {}
    )

    system_prompt = (
        "You are an autonomous AI Agent. You work in the directory provided.\n"
        "Use your tools to accomplish the task effectively.\n"
    )

    memory = MemorySaver()
    agent = create_react_agent(
        llm, 
        tools, 
        checkpointer=memory,
        prompt=system_prompt
    )
    
    return agent

def extract_reply(ai_msg) -> str:
    if isinstance(ai_msg, dict) and "messages" in ai_msg:
        ai_msg = ai_msg["messages"][-1]
    if isinstance(ai_msg, str):
        return ai_msg
    if hasattr(ai_msg, "content"):
        return ai_msg.content
    return str(ai_msg)
