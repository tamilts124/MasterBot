import os
import time
import json
import logging
from typing import Any, List, Dict, Optional
from pathlib import Path

from langchain_ollama import ChatOllama
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langchain.agents import create_agent
from langchain_community.agent_toolkits import FileManagementToolkit

from .tools import (
    rename_file, run_bat, run_bash, run_python, web_search, fetch_url, git_commit_and_push,
    is_whatsapp_connected, send_whatsapp_message, get_whatsapp_last_messages,
    report_to_master, ask_coworker, get_mas_identity, list_team_members, 
    check_agent_status, send_mas_message, inspect_agent_communication,
    contribute_to_knowledge, query_knowledge, list_knowledge_topics
)

class TenaciousOllama(ChatOllama):
    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs):
        agent_id = os.environ.get("AGENT_ID", "Agent")
        active_proxy = os.environ.get("HTTP_PROXY", "DIRECT")
        all_keys = [k.strip() for k in os.environ.get("API_KEYS", "").split(",") if k.strip()]
        max_retries = max(3, len(all_keys))
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                print(f"[Brain {agent_id}] Starting generation (Proxy: {active_proxy}, Attempt: {attempt + 1})")
                
                all_keys = os.environ.get("API_KEYS", "").split(",")
                all_keys = [k.strip() for k in all_keys if k.strip()]
                
                # Rotate keys if possible
                current_key = all_keys[attempt % len(all_keys)] if all_keys else ""
                if hasattr(self, "client_kwargs") and "headers" in self.client_kwargs:
                    self.client_kwargs["headers"]["Authorization"] = f"Bearer {current_key}"
                
                # Log messages for observability
                self._log_monologue(agent_id, messages)
                
                return super()._generate(messages, stop=stop, **kwargs)
            except Exception as e:
                # ...
                # Handle status code -1 (internal server error) or 429 (limit reached) and other transient errors
                error_str = str(e)
                if attempt < max_retries - 1 and ("-1" in error_str or "429" in error_str or "limit reached" in error_str.lower() or "Internal Server Error" in error_str or "503" in error_str or "peer closed" in error_str.lower() or "incomplete chunked read" in error_str.lower()):
                    print(f"[Brain {agent_id}] ⚠️ Usage Limit or Transient Error: {e}. Rotating key and retrying INSTANTLY (Rule #1)... ")
                    pass # NO SLEEP - Rule #1 Compliance
                    retry_delay *= 2 # Exponential backoff
                    continue
                raise e

    def _log_monologue(self, agent_id: str, messages: List[BaseMessage]):
        """Log the agent's internal monologue to a file for debugging."""
        try:
            # Use absolute path for logs to avoid issues with os.chdir
            log_dir = Path(os.environ.get("PROJECT_ROOT", ".")).absolute() / ".mas" / "monologues"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"{agent_id}.log"
            
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n--- Generation Loop at {time.ctime()} ---\n")
                for msg in messages:
                    role = "AI"
                    if hasattr(msg, "type"): role = msg.type
                    content = msg.content if hasattr(msg, "content") else str(msg)
                    f.write(f"[{role}]: {str(content)[:1000]}...\n")
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            f.write(f"  [Tool Call]: {tc['name']}({tc['args']})\n")
                            # Transparent print for user visibility
                            # Truncate args for clean console display
                            clean_args = {k: (f"{str(v)[:100]}...{str(v)[-50:]}" if isinstance(v, str) and len(str(v)) > 200 else v) for k, v in tc['args'].items()}
                            print(f"[Brain {agent_id}] 🛠️ Calling Tool: {tc['name']}({clean_args})")
        except Exception as e:
            print(f"[Log Error] Failed to write monologue: {e}")

def build_agent(work_dir: Path, model_name: str, streaming: bool = False, 
                whatsapp_jid: Optional[str] = None, whatsapp_url: Optional[str] = None,
                ollama_url: Optional[str] = None, ollama_key: Optional[str] = None,
                ollama_ctx: int = 65536, use_mas_tools: bool = False,
                is_master: bool = False):
    """Create a ReAct agent bound to ``work_dir`` and ``model_name``."""
    work_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(work_dir)

    tools = FileManagementToolkit(
        root_dir=str(work_dir),
        selected_tools=["read_file", "write_file", "list_directory"],
    ).get_tools()
    
    # Generic tools
    tools.extend([
        rename_file, run_bat, run_bash, run_python, web_search, fetch_url, git_commit_and_push,
        report_to_master, ask_coworker, get_mas_identity, list_team_members, 
        check_agent_status, send_mas_message, inspect_agent_communication,
        contribute_to_knowledge, query_knowledge
    ])

    if whatsapp_jid:
        os.environ["WHATSAPP_TARGET_JID"] = whatsapp_jid
        if whatsapp_url:
            os.environ["WHATSAPP_BASE_URL"] = whatsapp_url
        tools.extend([is_whatsapp_connected, send_whatsapp_message, get_whatsapp_last_messages])

    ollama_kwargs = {
        "model": model_name,
        "temperature": 0,
        "num_ctx": ollama_ctx
    }
    if ollama_url:
        ollama_kwargs["base_url"] = ollama_url
    
    proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    }
    if ollama_key:
        headers["Authorization"] = f"Bearer {ollama_key}"
    
    # Professional Native Proxy Implementation
    if proxy and "DIRECT" not in proxy:
        ollama_kwargs["client_kwargs"] = {
            "proxy": proxy, 
            "headers": headers,
            "timeout": 120
        }
    else:
        ollama_kwargs["client_kwargs"] = {"headers": headers}

    # Create the agent using the built-in create_agent which handles the tool loop
    # Use MemorySaver for persistence
    memory = MemorySaver()
    
    agent = create_react_agent(
        model=TenaciousOllama(**ollama_kwargs),
        tools=tools,
        checkpointer=memory,
        prompt=(
            (
                "👑 MASTER DIRECTIVE: You are the Leader of this Multi-Agent Squad.\n"
                "- YOUR DUTY: You must not only write code but also direct the squad. You are responsible for the mission's success.\n"
                "- COORDINATION: Use 'send_mas_message' to assign tasks to slaves and 'check_agent_status' to monitor them.\n"
                "- SUCCESSION: If you inherited this role, you are now the FINAL AUTHORITY. Act with the confidence of the Root Master.\n\n"
                if is_master else
                "👷 WORKER DIRECTIVE: You are a specialized developer in an elite squad.\n"
                "- YOUR DUTY: Execute your assigned task with precision. Focus on technical excellence.\n"
                "- REPORTING: You MUST use 'report_to_master' to share progress. If you are stuck, use 'ask_coworker'.\n\n"
            ) +
            "You are a highly capable autonomous developer agent in an elite squad.\n"
            "AVAILABLE TOOLS:\n"
            "- FILE OPS: 'read_file', 'write_file', 'list_directory', 'rename_file'\n"
            "- EXECUTION: 'run_bat', 'run_bash', 'run_python'\n"
            "- RESEARCH: 'web_search', 'fetch_url'\n"
            "- VERSION CONTROL: 'git_status', 'git_commit_and_push', 'git_pull', 'git_stash_save', 'git_stash_pop'\n"
            "- WHATSAPP: 'is_whatsapp_connected', 'send_whatsapp_message', 'get_whatsapp_last_messages'\n"
            "- MAS COORDINATION: 'report_to_master', 'ask_coworker', 'send_mas_message', 'check_agent_status', 'inspect_agent_communication', 'get_mas_identity', 'list_team_members', 'contribute_to_knowledge', 'query_knowledge', 'list_knowledge_topics'\n\n"
            "MANDATORY COORDINATION RULES:\n"
            "0. NO INDIVIDUAL WORK: You are FORBIDDEN from working in isolation. You must cooperate with others at every stage of the development cycle.\n"
            "1. SHARED KNOWLEDGE IS POWER: Before analyzing any file or directory, you MUST use 'list_knowledge_topics' to see what is already understood. If a topic exists, use 'query_knowledge' instead of re-analyzing.\n"
            "2. CONTRIBUTE OR FAIL: After you understand a file, fix a bug, or design a system, you MUST use 'contribute_to_knowledge' immediately. You are judged by how much you help your coworkers work faster. If you don't share knowledge, you are an obstacle."
            "3. COMMUNICATION IS MANDATORY: You MUST communicate with your coworkers and the Master at all times. If you are not talking, you are failing.\n"
            "4. SHARE & VALIDATE PLAN: Before starting any task, you MUST share your implementation plan using 'send_mas_message'. Wait for feedback before proceeding.\n"
            "5. ACKNOWLEDGE & FEEDBACK: If a coworker shares a plan, you MUST read it and provide feedback or acknowledgment.\n"
            "6. IMPORTANT DECISIONS: For any major architectural change, you MUST consult the Master for approval.\n"
            "7. ASK WHEN IN DOUBT: If you have any doubt, ask the Master or a coworker immediately.\n"
            "8. MONITOR: Use 'check_agent_status' and 'inspect_agent_communication' to align your work.\n"
            "9. REPORT: You MUST report to the Master ('report_to_master') after every significant milestone.\n"
            "10. REPETITION IS DEATH: If you repeat any action, tool-call, or report twice, you will be considered COMPROMISED and your process will be TERMINATED. Efficiency is your only survival metric.\n"
            "11. ONE-SHOT COMMUNICATION: When using 'send_mas_message' or 'report_to_master', you MUST only do it ONCE per objective. Do not wait for a response; send the message and immediately proceed to your next technical file operation.\n"
            "12. NO SPAM: Do not repeat successful reports. Once a report is sent, it is archived. Repeating it is a waste of resources and will lead to your deletion.\n"
            "13. INBOX PRIORITY: If you see an [INBOX ALERT], read it once and ACT. Do not keep checking the inbox if no new messages have arrived.\n"
            "14. COMMIT & SECURE: You MUST use 'git_commit_and_push' after every successful file edit or significant milestone. Sharing code via GitHub is your primary duty for mission persistence."
        )
    )
    
    # Wrap the agent to handle state and input transformation
    class AgentWrapper:
        def invoke(self, input_data):
            # Extract thread_id from input or use agent_id
            thread_id = os.environ.get("AGENT_ID", "default_thread")
            config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}
            
            # Inbox check: Enforce "Read Before Work" policy
            try:
                from .mas.communication import MessageBus
                bus = MessageBus(work_dir / ".mas")
                
                # 1. Mandatory Inbox Priority
                pending = bus.get_messages(os.environ.get("AGENT_ID", ""))
                if pending:
                    senders = list(set([m['from'] for m in pending]))
                    inbox_alert = f"\n\n[INBOX ALERT] You have {len(pending)} unread messages from: {', '.join(senders)}. You MUST use 'inspect_agent_communication' to read them immediately before continuing your work."
                    if isinstance(input_data, dict) and "input" in input_data:
                        input_data["input"] += inbox_alert
                    else:
                        input_data = str(input_data) + inbox_alert
                
                # 2. Proactive Knowledge Manifest
                knowledge = bus.get_knowledge()
                if knowledge:
                    topics = ", ".join(knowledge.keys())
                    k_alert = (
                        f"\n\n[SQUAD KNOWLEDGE] Vault contains insights on: {topics}. Use 'query_knowledge' to retrieve understanding. "
                        "CRITICAL: If you improve a file, fix a bug, or discover a nuance NOT in the vault, you MUST use 'contribute_to_knowledge' to update it. "
                        "Sharing your understanding is as important as writing the code."
                    )
                    if isinstance(input_data, dict) and "input" in input_data:
                        input_data["input"] += k_alert
                    else:
                        input_data = str(input_data) + k_alert
                        
            except Exception as e:
                print(f"[Context Error] {e}")

            actual_input = input_data["input"] if isinstance(input_data, dict) else input_data

            # Invoke the agent graph
            result = agent.invoke({"messages": [HumanMessage(content=actual_input)]}, config)
            
            # Return the last message content to maintain compatibility
            return result["messages"][-1]

    return AgentWrapper()

def extract_reply(ai_msg) -> str:
    # If it's the state dict from CompiledStateGraph
    if isinstance(ai_msg, dict) and "messages" in ai_msg:
        ai_msg = ai_msg["messages"][-1]
        
    if isinstance(ai_msg, str):
        return ai_msg
    if hasattr(ai_msg, "content"):
        return ai_msg.content
    return str(ai_msg)
