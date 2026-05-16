import os
import time
import json
import re
from pathlib import Path
from typing import List, Optional, Union, Dict, Any, ClassVar

from langchain_ollama import ChatOllama
from langchain_anthropic import ChatAnthropic
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
    get_mouse_position, mouse_move, mouse_click, keyboard_type, keyboard_press, get_screen_size,
    start_browser_session, list_browser_sessions, browser_new_tab, browser_switch_tab, 
    browser_close_tab, browser_navigate, browser_wait_for, browser_scroll, 
    browser_get_view, browser_get_accessibility_tree, browser_click, 
    browser_type, browser_eval, browser_save_cookies, browser_load_cookies,
    browser_get_network_logs, browser_get_console_logs, browser_screenshot, 
    browser_get_local_storage, browser_set_local_storage,
    browser_set_visibility, stop_browser_session,
    browser_security_audit, browser_extract_endpoints, browser_analyze_waf, browser_map_params, browser_fuzz_params,
    start_subfinder, start_httpx, start_nuclei_scan, start_paramspider,
    sas_add_knowledge, sas_list_knowledge, sas_query_knowledge, sas_execute_sql
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
        
        # Log tool calls from history (Inspired by MAS)
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    # Defensive check: ensure tc is a dictionary and has 'args'
                    if isinstance(tc, dict) and 'args' in tc:
                        # Truncate args for clean console display
                        clean_args = {k: (f"{str(v)[:100]}...{str(v)[-50:]}" if isinstance(v, str) and len(str(v)) > 200 else v) for k, v in tc['args'].items()}
                        print(f"\n[Brain {agent_id}] 🛠️ Calling Tool: {tc['name']}({clean_args})")
                    elif isinstance(tc, dict) and 'name' in tc:
                        print(f"\n[Brain {agent_id}] 🛠️ Calling Tool: {tc['name']}(...)")
        
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
                        temperature=getattr(self, "temperature", 0.0),
                        streaming=getattr(self, "streaming", False),
                        client_kwargs={"headers": {"Authorization": f"Bearer {current_key}"}}
                    )
                    # Sync headers to client_kwargs for compatibility
                    if hasattr(self, "client_kwargs"):
                        temp_llm.client_kwargs.update(self.client_kwargs)
                    
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

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        agent_id = os.environ.get("AGENT_ID", "Agent")
        
        # Log tool calls from history (Identical to _generate)
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    clean_args = {k: (f"{str(v)[:100]}...{str(v)[-50:]}" if isinstance(v, str) and len(str(v)) > 200 else v) for k, v in tc['args'].items()}
                    print(f"\n[Brain {agent_id}] 🛠️ Calling Tool: {tc['name']}({clean_args})")

        all_keys = []
        if hasattr(self, "internal_api_keys") and self.internal_api_keys:
            all_keys = [k.strip() for k in self.internal_api_keys.split(",") if k.strip()]
            
        key_idx = TenaciousOllama.last_successful_key_index % len(all_keys) if all_keys else 0
        current_key = all_keys[key_idx] if all_keys else ""

        if current_key:
            temp_llm = ChatOllama(
                model=self.model,
                base_url=self.base_url,
                api_key=current_key,
                num_ctx=getattr(self, "num_ctx", 65536),
                temperature=getattr(self, "temperature", 0.0),
                streaming=True,
                client_kwargs={"headers": {"Authorization": f"Bearer {current_key}"}}
            )
            if hasattr(self, "client_kwargs"):
                temp_llm.client_kwargs.update(self.client_kwargs)
            
            # Use temp_llm to stream
            yield from temp_llm._stream(messages, stop=stop, run_manager=run_manager, **kwargs)
class TenaciousAnthropic(ChatAnthropic):
    internal_api_keys: str = ""
    last_successful_key_index: ClassVar[int] = 0
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Store keys in the validated field
        self.internal_api_keys = kwargs.get("api_key", "")

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        agent_id = os.environ.get("AGENT_ID", "Agent")
        
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    if isinstance(tc, dict) and 'args' in tc:
                        clean_args = {k: (f"{str(v)[:100]}...{str(v)[-50:]}" if isinstance(v, str) and len(str(v)) > 200 else v) for k, v in tc['args'].items()}
                        print(f"\n[Brain {agent_id}] 🛠️ Calling Tool: {tc['name']}({clean_args})")
                    elif isinstance(tc, dict) and 'name' in tc:
                        print(f"\n[Brain {agent_id}] 🛠️ Calling Tool: {tc['name']}(...)")
        
        all_keys = []
        if hasattr(self, "internal_api_keys") and self.internal_api_keys:
            all_keys = [k.strip() for k in self.internal_api_keys.split(",") if k.strip()]
            
        max_retries = max(3, len(all_keys))
        for attempt in range(max_retries):
            key_idx = (TenaciousAnthropic.last_successful_key_index + attempt) % len(all_keys) if all_keys else 0
            current_key = all_keys[key_idx] if all_keys else ""
            
            try:
                if current_key:
                    temp_llm = ChatAnthropic(
                        model=self.model,
                        anthropic_api_url=getattr(self, "anthropic_api_url", None),
                        api_key=current_key,
                        temperature=getattr(self, "temperature", 0.0),
                        streaming=getattr(self, "streaming", False),
                    )
                    res = temp_llm._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
                    TenaciousAnthropic.last_successful_key_index = key_idx
                    return res
                
                return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            except Exception as e:
                error_msg = str(e).lower()
                is_limit = any(term in error_msg for term in ["limit", "429", "401", "unauthorized", "quota", "503", "overloaded"])
                
                if is_limit:
                    print(f"[Brain {agent_id}] Anthropic limit/auth error (Attempt {attempt+1}/{max_retries}).")
                    if len(all_keys) > 1 and attempt < len(all_keys) - 1:
                        print(f"[Brain {agent_id}] Rotating to next Anthropic key...")
                        continue
                    raise e
                else:
                    print(f"[Brain {agent_id}] Unexpected Anthropic Error: {e}")
                    if attempt < max_retries - 1:
                        continue
                    raise e
        raise Exception(f"Failed to generate Anthropic response after {max_retries} attempts.")

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        agent_id = os.environ.get("AGENT_ID", "Agent")
        
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    clean_args = {k: (f"{str(v)[:100]}...{str(v)[-50:]}" if isinstance(v, str) and len(str(v)) > 200 else v) for k, v in tc['args'].items()}
                    print(f"\n[Brain {agent_id}] 🛠️ Calling Tool: {tc['name']}({clean_args})")

        all_keys = []
        if hasattr(self, "internal_api_keys") and self.internal_api_keys:
            all_keys = [k.strip() for k in self.internal_api_keys.split(",") if k.strip()]
            
        key_idx = TenaciousAnthropic.last_successful_key_index % len(all_keys) if all_keys else 0
        current_key = all_keys[key_idx] if all_keys else ""

        if current_key:
            temp_llm = ChatAnthropic(
                model=self.model,
                anthropic_api_url=getattr(self, "anthropic_api_url", None),
                api_key=current_key,
                temperature=getattr(self, "temperature", 0.0),
                streaming=True,
            )
            yield from temp_llm._stream(messages, stop=stop, run_manager=run_manager, **kwargs)
        else:
            yield from super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs)

def build_agent(work_dir: Path, model_name: str, provider: str = "ollama", streaming: bool = False, 
                whatsapp_jid: Optional[str] = None, whatsapp_url: Optional[str] = None,
                ollama_url: Optional[str] = None, ollama_key: Optional[str] = None,
                anthropic_key: Optional[str] = None, anthropic_url: Optional[str] = None,
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
    
    technical_tools = [
        rename_file, run_bat, run_bash, run_python, web_search, fetch_url, 
        start_interactive_process, list_interactive_processes, get_process_history, send_to_process, stop_interactive_process,
        get_mouse_position, mouse_move, mouse_click, keyboard_type, keyboard_press, get_screen_size,
        git_status, git_pull, git_stash_save, git_stash_pop, git_commit_and_push,
    ]
    
    browser_tools = [
        start_browser_session, list_browser_sessions, browser_new_tab, browser_switch_tab, 
        browser_close_tab, browser_navigate, browser_wait_for, browser_scroll, 
        browser_get_view, browser_get_accessibility_tree, browser_click, 
        browser_type, browser_eval, browser_save_cookies, browser_load_cookies, 
        browser_get_local_storage, browser_set_local_storage,
        browser_get_network_logs, browser_get_console_logs, browser_screenshot, 
        browser_set_visibility, stop_browser_session
    ]

    security_tools = [
        browser_security_audit, browser_extract_endpoints, 
        browser_analyze_waf, browser_map_params, browser_fuzz_params,
        start_subfinder, start_httpx, start_nuclei_scan, start_paramspider
    ]
    
    knowledge_tools = [
        sas_add_knowledge, sas_list_knowledge, sas_query_knowledge, sas_execute_sql
    ]
    
    tools.extend(technical_tools)
    tools.extend(browser_tools)
    tools.extend(security_tools)
    tools.extend(knowledge_tools)

    if whatsapp_jid:
        tools.extend([is_whatsapp_connected, send_whatsapp_message, get_whatsapp_last_messages])

    if provider == "anthropic":
        first_key = [k.strip() for k in anthropic_key.split(",") if k.strip()][0] if anthropic_key else None
        llm = TenaciousAnthropic(
            model=model_name,
            anthropic_api_url=anthropic_url,
            api_key=anthropic_key,
            temperature=temperature,
            streaming=streaming,
        )
    else:
        # Default to Ollama
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
        "Use your tools to accomplish the task effectively.\n\n"
        "AVAILABLE TOOLS:\n"
        "- FILE OPERATIONS: read_file, write_file, list_directory, rename_file\n"
        "- EXECUTION: run_bat, run_bash, run_python, start_interactive_process, send_to_process, get_process_history\n"
        "- BROWSER AUTOMATION: start_browser_session, list_browser_sessions, browser_new_tab, browser_switch_tab, browser_close_tab, browser_navigate, browser_wait_for, browser_scroll, browser_get_view, browser_get_accessibility_tree, browser_click, browser_type, browser_eval, browser_save_cookies, browser_load_cookies, browser_get_local_storage, browser_set_local_storage, browser_get_network_logs, browser_get_console_logs, browser_screenshot, stop_browser_session\n"
        "- RESEARCH: web_search, fetch_url\n"
        "- VERSION CONTROL: git_status, git_pull, git_stash_save, git_stash_pop, git_commit_and_push\n"
        "- SYSTEM: get_mouse_position, mouse_move, mouse_click, keyboard_type\n\n"
        "BROWSER GUIDELINES:\n"
        "1. SESSION & TABS: Always start with 'start_browser_session'. Manage tabs with 'browser_new_tab', 'browser_switch_tab', and 'browser_list_tabs'.\n"
        "2. RESILIENCE: Use 'browser_wait_for' to wait for specific elements to appear before clicking. This is much more reliable than guessing.\n"
        "3. NAVIGATION: Use 'browser_navigate' to load URLs. Use 'browser_scroll' (down, up, bottom) to trigger lazy-loading or find off-screen content.\n"
        "4. OBSERVATION: Use 'browser_get_view' (mode='text') for a general overview, or (mode='elements') for selectors. Use 'browser_get_accessibility_tree' for a semantic understanding of complex pages.\n"
        "5. ADVANCED: Use 'browser_eval' for JS injection, 'browser_get_network_logs' for traffic, and 'browser_get_console_logs' to see JavaScript errors/logs. Use 'browser_save_cookies'/'browser_load_cookies' and 'browser_get_local_storage'/'browser_set_local_storage' for full state persistence.\n"
        "6. SNAPSHOTS: Use 'browser_screenshot' if you need a visual record of the current page.\n"
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
