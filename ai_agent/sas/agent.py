import os
import time
import json
import re
from pathlib import Path
from typing import List, Optional, Union, Dict, Any

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
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        agent_id = os.environ.get("AGENT_ID", "Agent")
        active_proxy = os.environ.get("ACTIVE_PROXY", "DIRECT")
        
        all_keys = [k.strip() for k in os.environ.get("API_KEYS", "").split(",") if k.strip()]
        max_retries = max(3, len(all_keys))
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                # Silent generation for SAS
                
                all_keys = os.environ.get("API_KEYS", "").split(",")
                all_keys = [k.strip() for k in all_keys if k.strip()]
                current_key = all_keys[attempt % len(all_keys)] if all_keys else ""
                
                if hasattr(self, "client_kwargs") and "headers" in self.client_kwargs:
                    self.client_kwargs["headers"]["Authorization"] = f"Bearer {current_key}"
                
                return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            except Exception as e:
                error_msg = str(e).lower()
                is_limit = any(term in error_msg for term in ["limit", "expiry", "429", "401", "unauthorized", "quota", "503", "overloaded"])
                
                if is_limit:
                    print(f"[Brain {agent_id}] ⚠️ Key/Provider limit reached. Rotating key... (Attempt {attempt+1}/{max_retries})")
                    time.sleep(1)
                    continue
                else:
                    print(f"[Brain {agent_id}] ❌ Unexpected Generation Error: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    raise e
        raise Exception(f"Failed to generate response after {max_retries} attempts.")

def build_agent(work_dir: Path, model_name: str, streaming: bool = False, 
                whatsapp_jid: Optional[str] = None, whatsapp_url: Optional[str] = None,
                ollama_url: Optional[str] = None, ollama_key: Optional[str] = None,
                ollama_ctx: int = 65536, is_master: bool = False):
    """Create a clean Standalone ReAct agent."""
    work_dir.mkdir(parents=True, exist_ok=True)
    
    tools = FileManagementToolkit(
        root_dir=str(work_dir),
        selected_tools=["read_file", "write_file", "list_directory"],
    ).get_tools()
    
    tools.extend([
        rename_file, run_bat, run_bash, run_python, web_search, fetch_url, 
        start_interactive_process, list_interactive_processes, get_process_history, send_to_process, stop_interactive_process,
        capture_screenshot, get_mouse_position, mouse_move, mouse_click, keyboard_type, keyboard_press, get_screen_size, analyze_screenshot, image_to_array,
        git_status, git_pull, git_stash_save, git_stash_pop, git_commit_and_push,
        is_whatsapp_connected, send_whatsapp_message, get_whatsapp_last_messages
    ])

    llm = TenaciousOllama(
        model=model_name,
        base_url=ollama_url,
        api_key=ollama_key,
        num_ctx=ollama_ctx,
        temperature=0,
        streaming=streaming
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
