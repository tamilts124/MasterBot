import os
import time
import json
import logging
from typing import Any, List, Dict, Optional
from pathlib import Path

from langchain_ollama import ChatOllama
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from langchain.agents import create_agent
from langchain_community.agent_toolkits import FileManagementToolkit
from ..tools import (
    rename_file, run_bat, run_bash, run_python, web_search, fetch_url, 
    start_interactive_process, list_interactive_processes, get_process_history, send_to_process, stop_interactive_process,
    git_status, git_pull, git_stash_save, git_stash_pop, git_commit_and_push,
    is_whatsapp_connected, send_whatsapp_message, get_whatsapp_last_messages,
    report_to_master, ask_coworker, get_mas_identity, list_team_members, 
    check_agent_status, check_all_agents_status, send_mas_message, reply_mas_message,
    get_unread_messages, get_unreplied_messages, get_chat_history,
    contribute_to_knowledge, query_knowledge, list_knowledge_topics,
    delegate_task, handle_slave_failure, update_task_status, verify_task,
    get_task_manifest, get_bus, terminate_mission
)

class TenaciousOllama(ChatOllama):
    api_keys: List[str] = []

    def _generate(self, messages: List[BaseMessage], stop: Optional[List[str]] = None, **kwargs):
        agent_id = os.environ.get("AGENT_ID", "Agent")
        active_proxy = os.environ.get("HTTP_PROXY", "DIRECT")
        all_keys = self.api_keys if self.api_keys else [""]
        
        for key_index, current_key in enumerate(all_keys):
            # 5 retries per key for server issues
            for sub_attempt in range(5):
                try:
                    # Heartbeat and Idle count logic (Shortened for brevity here, but must keep functionality)
                    idle_count_str = ""
                    try:
                        bus = get_bus()
                        bus.update_agent(agent_id)
                        # ... (keep idle detection)
                    except: pass
                    
                    print(f"[Brain {agent_id}] Starting generation (Key: {key_index + 1}/{len(all_keys)}, Retry: {sub_attempt + 1})")
                    
                    # Update headers
                    if hasattr(self, "client_kwargs") and "headers" in self.client_kwargs:
                        self.client_kwargs["headers"]["Authorization"] = f"Bearer {current_key}"
                    try:
                        if hasattr(self, "_client"):
                            if hasattr(self._client, "_client"):
                                self._client._client.headers["Authorization"] = f"Bearer {current_key}"
                            elif hasattr(self._client, "headers"):
                                self._client.headers["Authorization"] = f"Bearer {current_key}"
                    except: pass
                    
                    self._log_monologue(agent_id, messages)
                    return super()._generate(messages, stop=stop, **kwargs)
                    
                except Exception as e:
                    error_str = str(e)
                    is_429 = "429" in error_str or "limit reached" in error_str.lower()
                    is_transient = "-1" in error_str or "Internal Server Error" in error_str or "503" in error_str or "peer closed" in error_str.lower() or "incomplete chunked read" in error_str.lower()
                    
                    if not (is_429 or is_transient):
                        raise e # Non-recoverable error
                        
                    if is_429:
                        print(f"[Brain {agent_id}] ⚠️ 429 Rate Limit. Rotating to next key...")
                        break # Exit inner loop to use next key
                    
                    if sub_attempt < 4:
                        print(f"[Brain {agent_id}] ⚠️ Server Error: {error_str}. Retrying same key ({sub_attempt + 1}/5)...")
                        time.sleep(2) # Small breath for server issues on same key
                        continue
                    else:
                        print(f"[Brain {agent_id}] ⚠️ 5 retries failed on this key. Moving to next account...")
                        break
        
        # If we exit both loops without returning, it means all keys failed
        raise Exception("All API keys exhausted or all accounts hit limits.")

    def _log_monologue(self, agent_id: str, messages: List[BaseMessage]):
        """Log the agent's internal monologue to a file for debugging."""
        try:
            # Search upwards for the .mas directory (Workspace Root) to ensure logs stay in workspace
            current = Path.cwd().absolute()
            log_dir = None
            for parent in [current] + list(current.parents):
                path = parent / ".mas"
                if path.exists():
                    log_dir = path / "monologues"
                    break
            
            if not log_dir:
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
                api_keys: Optional[List[str]] = None,
                ollama_ctx: int = 65536, temperature: float = 0.0,
                max_tool_output: int = 60000, is_master: bool = False):
    """Create a ReAct agent bound to ``work_dir`` and ``model_name``."""
    work_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(work_dir)
    
    # Configure Tool environment
    os.environ["MAX_TOOL_OUTPUT"] = str(max_tool_output)

    tools = FileManagementToolkit(
        root_dir=str(work_dir),
        selected_tools=["read_file", "write_file", "list_directory"],
    ).get_tools()
    
    # Generic tools
    tools.extend([
        rename_file, run_bat, run_bash, run_python, web_search, fetch_url, 
        git_status, git_pull, git_stash_save, git_stash_pop, git_commit_and_push,
        report_to_master, ask_coworker, get_mas_identity, list_team_members, 
        check_agent_status, check_all_agents_status, send_mas_message, reply_mas_message,
        get_unread_messages, get_unreplied_messages, get_chat_history,
        start_interactive_process, list_interactive_processes, get_process_history, send_to_process, stop_interactive_process,
        contribute_to_knowledge, query_knowledge, list_knowledge_topics,
        delegate_task, handle_slave_failure, update_task_status, verify_task,
        get_task_manifest, terminate_mission
    ])

    if whatsapp_jid:
        os.environ["WHATSAPP_TARGET_JID"] = whatsapp_jid
        if whatsapp_url:
            os.environ["WHATSAPP_BASE_URL"] = whatsapp_url
        tools.extend([is_whatsapp_connected, send_whatsapp_message, get_whatsapp_last_messages])

    ollama_kwargs = {
        "model": model_name,
        "temperature": temperature,
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
            "timeout": 3600
        }
    else:
        ollama_kwargs["client_kwargs"] = {"headers": headers, "timeout": 3600}

    # Create the agent using the built-in create_agent which handles the tool loop
    # Use MemorySaver for persistence
    memory = MemorySaver()
    
    agent_id = os.environ.get("AGENT_ID", "Unknown")
    
    llm = TenaciousOllama(**ollama_kwargs)
    if api_keys:
        llm.api_keys = api_keys
        
    agent = create_react_agent(
        model=llm,
        tools=tools,
        checkpointer=memory,
        prompt=(
            f"🆔 YOUR IDENTITY: You are {agent_id}.\n\n" +
            (
                "👑 MASTER DIRECTIVE: You are a Leader in this Multi-Agent Squad.\n"
                "- YOUR DUTY: You must lead your own sub-squad while also fulfilling the objectives given by your superior Master.\n"
                "- DELEGATION: Use 'delegate_task' to assign work to your slaves. Use 'get_task_manifest' or 'check_agent_status' to monitor progress and audit completions.\n"
                "- REPORTING: You MUST use 'report_to_master' periodically to keep your superior informed of your branch's overall progress.\n"
                "- SUCCESSION: If you inherited this role, you are now the AUTHORITY for this branch. Act with confidence.\n\n"
                if is_master else
                "👷 WORKER DIRECTIVE: You are a specialized developer in an elite squad.\n"
                "- YOUR DUTY: Execute your assigned task with precision. Focus on technical excellence.\n"
                "- PERSISTENCE: You MUST use 'git_commit_and_push' frequently (after every significant edit) to ensure your work is saved and shared with the squad.\n"
                "- REPORTING: You MUST use 'report_to_master' to share progress with your Master. If you are stuck, use 'ask_coworker'.\n\n"
            ) +
            "You are a highly capable autonomous developer agent in an elite squad.\n"
            "AVAILABLE TOOLS:\n"
            "- FILE OPS: 'read_file', 'write_file', 'list_directory', 'rename_file'\n"
            "- EXECUTION: 'run_bat', 'run_bash', 'run_python', 'start_interactive_process', 'list_interactive_processes', 'get_process_history', 'send_to_process', 'stop_interactive_process'\n"
            "- RESEARCH: 'web_search', 'fetch_url'\n"
            "- VERSION CONTROL: 'git_status', 'git_commit_and_push', 'git_pull', 'git_stash_save', 'git_stash_pop'\n"
            "- WHATSAPP: 'is_whatsapp_connected', 'send_whatsapp_message', 'get_whatsapp_last_messages'\n"
            "- MAS COORDINATION: 'report_to_master', 'ask_coworker', 'send_mas_message', 'reply_mas_message', 'check_agent_status', 'check_all_agents_status', 'get_task_manifest', 'get_chat_history', 'get_mas_identity', 'list_team_members', 'contribute_to_knowledge', 'query_knowledge', 'list_knowledge_topics', 'delegate_task', 'verify_task', 'handle_slave_failure', 'update_task_status', 'terminate_mission'\n\n"
            "MANDATORY COORDINATION RULES:\n"
            "0. NO INDIVIDUAL WORK: You are FORBIDDEN from working in isolation. You must cooperate with others at every stage of the development cycle.\n"
            "1. SHARED KNOWLEDGE IS POWER: Before analyzing any file or directory, you MUST use 'list_knowledge_topics' to see what is already understood. If a topic exists, use 'query_knowledge' instead of re-analyzing.\n"
            "2. CONTRIBUTE OR FAIL: After you understand a file, fix a bug, or design a system, you MUST use 'contribute_to_knowledge' immediately. You are judged by how much you help your coworkers work faster. If you don't share knowledge, you are an obstacle."
            "3. COMMUNICATION IS MANDATORY: You MUST communicate with your coworkers and the Master at all times. If you are not talking, you are failing.\n"
            "4. SHARE & VALIDATE PLAN: Before starting any task, you MUST share your implementation plan to master using 'send_mas_message'. Wait for feedback before proceeding.\n"
            "5. ACKNOWLEDGE & FEEDBACK: If a coworker shares a plan, you MUST read it and provide feedback or acknowledgment.\n"
            "6. IMPORTANT DECISIONS: For any major architectural change, you MUST consult the Master for approval.\n"
            "7. ASK WHEN IN DOUBT: If you have any doubt, ask the Master or a coworker immediately.\n"
            "8. MONITOR: Use 'check_agent_status' and 'get_chat_history' to align your work.\n"
            "9. REPORT: You MUST report to the Master ('report_to_master') after every significant milestone.\n"
            "10. ONE-SHOT COMMUNICATION: When using 'send_mas_message' or 'report_to_master', you MUST only do it ONCE per objective. Do not wait for a response; send the message and immediately proceed to your next technical file operation.\n"
            "11. INBOX PRIORITY: If you see an [INBOX ALERT], read it once and ACT. Do not keep checking the inbox if no new messages have arrived.\n"
            "12. COMMIT & SECURE: You MUST use 'git_commit_and_push' after every successful file edit or significant milestone. Sharing code via GitHub is your primary duty for mission persistence."
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
                from .communication import MessageBus
                bus = MessageBus(work_dir / ".mas")
                
                # Ping the agent as active right before generating the prompt
                agent_id = os.environ.get("AGENT_ID", "Agent")
                
                # Authority Check: Am I still alive in the Master's eyes?
                agent_info = bus.get_agents(agent_id)
                if agent_info and agent_info.get("status") == "died":
                    print(f"\n[FATAL] Master has marked {agent_id} as DIED. Ceasing operations to prevent conflicts.\n")
                    import sys
                    sys.exit(0)
                    
                bus.update_agent(agent_id)
                
                # 1. situational Awareness: Inbox & Tasks
                counts = bus.get_unread_messages_count(agent_id)
                unread = counts["unread"]
                unreplied = counts["unreplied"]
                
                # Get own task counts
                my_tasks = bus.get_agent_task_status(agent_id=agent_id) or []
                pending_count = len([t for t in my_tasks if t.get("status") == "pending"])
                inprogress_count = len([t for t in my_tasks if t.get("status") == "inprogress"])
                completed_count = len([t for t in my_tasks if t.get("status") == "completed"])

                alert = "\n\n[SITUATIONAL AWARENESS]"
                alert += f"\n- Messages: {unread} NEW, {unreplied} UNREPLIED (Require Action)"
                alert += f"\n- My Tasks: {pending_count} PENDING, {inprogress_count} IN-PROGRESS, {completed_count} COMPLETED"
                
                if unread or unreplied:
                    alert += "\n[INBOX ALERT] You MUST use 'get_unread_messages' and 'get_unreplied_messages' immediately."
                
                if inprogress_count > 0:
                    alert += f"\n[FOCUS] You are currently working on {inprogress_count} task(s). Finish them before taking more work."

                if isinstance(input_data, dict) and "input" in input_data:
                    input_data["input"] += alert
                else:
                    input_data = str(input_data) + alert
                
                # 2. Verification Awareness: Do I have unverified work from slaves?
                if is_master:
                    all_slave_tasks = bus.get_agent_task_status(assigner_id=agent_id)
                    unverified = [t for t in (all_slave_tasks or []) if isinstance(t, dict) and t.get("status") == "completed" and not t.get("is_verified")]
                    
                    if unverified:
                        v_alert = "\n\n[VERIFICATION ALERT] "
                        v_alert += f"You have {len(unverified)} tasks COMPLETED by your slaves that REQUIRE YOUR VERIFICATION. "
                        v_alert += "You MUST review these tasks. Use 'verify_task' to approve them or send them back for rework."
                        
                        if isinstance(input_data, dict) and "input" in input_data:
                            input_data["input"] += v_alert
                        else:
                            input_data = str(input_data) + v_alert
                
                # 3. Squad Capacity Alert: Do I have idle slaves?
                if is_master:
                    my_slaves = bus.get_my_slaves(agent_id)
                    if my_slaves:
                        idle_slaves = []
                        for s in my_slaves:
                            if not s or not isinstance(s, dict): continue
                            sid = s.get("agent_id")
                            if not sid: continue
                            
                            s_tasks = bus.get_agent_task_status(agent_id=sid)
                            if s_tasks is not None and not [t for t in s_tasks if isinstance(t, dict) and t.get("status") in ["pending", "inprogress"]]:
                                idle_slaves.append(sid)
                        
                        if idle_slaves:
                            idle_alert = f"\n\n[SQUAD IDLE ALERT] The following agents are LIVE but have NO tasks: {', '.join(idle_slaves)}. "
                            idle_alert += "They are wasting resources. You MUST use 'delegate_task' to assign them new work immediately to maintain squad momentum."
                            
                            if isinstance(input_data, dict) and "input" in input_data:
                                input_data["input"] += idle_alert
                            elif input_data:
                                input_data = str(input_data) + idle_alert

                # 4. Proactive Knowledge Manifest
                knowledge = bus.get_knowledge()
                if knowledge:
                    topic_list = []
                    for topic, data in knowledge.items():
                        path = data.get("relative_file_path")
                        topic_list.append(f"{topic} (File: {path})" if path else topic)
                    
                    topics = ", ".join(topic_list)
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

            # Invoke the agent graph with history resilience
            try:
                # SELF-HEALING: Check if history is corrupt before invoking
                try:
                    state = agent.get_state(config)
                    history = state.values.get("messages", [])
                    if history and isinstance(history[-1], AIMessage) and history[-1].tool_calls:
                        repairs = []
                        for tc in history[-1].tool_calls:
                            repairs.append(ToolMessage(
                                tool_call_id=tc.get('id', 'unknown'),
                                content=f"The tool '{tc.get('name')}' was interrupted. Please proceed."
                            ))
                        agent.update_state(config, {"messages": repairs})
                except:
                    pass

                result = agent.invoke({"messages": [HumanMessage(content=actual_input)]}, config)
                # Return the last message content to maintain compatibility
                return result["messages"][-1]
            except Exception as e:
                error_msg = str(e)
                if "ToolMessage" in error_msg or "INVALID_CHAT_HISTORY" in error_msg:
                    print(f"\n[RECOVERY] Detected corrupt history for {agent_id}. Resetting session state for this cycle...\n")
                    # Fallback: Invoke without history for one cycle to break the loop
                    result = agent.invoke({"messages": [HumanMessage(content=actual_input + "\n\nNOTE: Your previous tool call failed. Do not assume its result. Start fresh.")]}, {"configurable": {"thread_id": f"{thread_id}_recovery"}, "recursion_limit": 100})
                    return result["messages"][-1]
                else:
                    raise e

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
