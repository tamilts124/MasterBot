import os
import time
import json
from pathlib import Path
from typing import Optional
from langchain_core.tools import tool
from .git_tools import git_commit_and_push

def get_bus():
    from ..mas.communication import MessageBus
    # Search upwards for the .mas directory (Workspace Root) to ensure connectivity from subdirs
    current = Path.cwd().absolute()
    for parent in [current] + list(current.parents):
        path = parent / ".mas"
        if path.exists():
            return MessageBus(path)
            
    # Fallback for initialization or if not in a workspace subdir
    comm_path = Path(os.environ.get("PROJECT_ROOT", ".")).absolute() / ".mas"
    return MessageBus(comm_path)

@tool
def report_to_master(summary: str, task_id: int) -> str:
    """Submit the final completion results for a SPECIFIC assigned task to your Master.
    MANDATORY: Use this ONLY when you have finished a task that was formally assigned to you in the 'get_task_manifest'.
    Do NOT use this tool for general status updates or to say you are 'ready' for work.
    Args:
        summary: The detailed results, achievements, and technical details of the completed work.
        task_id: The unique numeric ID of the task you are closing.
    """
    agent_id = os.environ.get("AGENT_ID")
    parent_id = os.environ.get("PARENT_ID")
    if not (agent_id and parent_id): return "[Error] MAS context missing."
    
    print(f"\n[REPORT] {agent_id} -> Master {parent_id}: {summary[:100]}...\n", flush=True)
    get_bus().send_message(agent_id, parent_id, {"summary": summary, "task_id": task_id})
    return f"[SUCCESS] Report for task '{task_id}' has been delivered to Master {parent_id}. This task is now officially REPORTED. Do NOT repeat this report."

@tool
def ask_coworker(coworker_id: str, question: str) -> str:
    """Send a collaborative query or coordination request to a same-level colleague.
    Use this to request information or assistance from peers without bothering your Master.
    Args:
        coworker_id: The target agent ID to communicate with.
        question: The request or question text.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    print(f"\n[COMM] {agent_id} -> Coworker {coworker_id}: {question[:100]}...\n", flush=True)
    get_bus().send_message(agent_id, coworker_id, question)
    return f"Message sent to coworker {coworker_id}"

@tool
def get_mas_identity() -> str:
    """Retrieve your current operational parameters within the Multi-Agent System.
    This includes your unique ID, your depth level in the hierarchy, and your assigned Master.
    """
    agent_id = os.environ.get("AGENT_ID", "Unknown")
    parent_raw = os.environ.get("PARENT_ID", "")
    parent_id = "None (You are the ROOT MASTER)" if (not parent_raw or parent_raw == "" or parent_raw == "NoParentForYou") else parent_raw
    level = os.environ.get("AGENT_LEVEL", "0")
    return f"My ID: {agent_id} | My Level: {level} | My Master: {parent_id}"

@tool
def list_team_members() -> str:
    """Discover the structure of your immediate squad, including coworkers and subordinates.
    This tool provides a structural map of WHO you can collaborate with or delegate to.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id:
        return "[Error] MAS context missing."
        
    master = os.environ.get("PARENT_ID", "None")
    bus = get_bus()
    
    # --- SCREEN OBSERVABILITY ---
    all_agents = bus.get_agents()
    print("\n" + "="*40)
    print("📋 SQUAD VITALITY MANIFEST (SCREEN ONLY)")
    for a in all_agents:
        stat = a.get("status", "unknown")
        icon = "🟢" if stat == "live" else "🔴"
        print(f" {icon} {a['agent_id']} (Parent: {a['parent_id']}) -> Status: {stat}")
    print("="*40 + "\n")
    # ----------------------------

    coworkers = [c["agent_id"] for c in bus.get_my_coworkers(agent_id)]
    slaves = [s["agent_id"] for s in bus.get_my_slaves(agent_id)]
    
    output = f"Master: {master} | Coworkers: {', '.join(coworkers) if coworkers else 'None'} | Slaves: {', '.join(slaves) if slaves else 'None'}"
    
    hierarchy = bus.get_live_hierarchy()
    if hierarchy:
        return f"Full Live Squad Hierarchy: {json.dumps(hierarchy, indent=2)}\n{output}"
            
    return output

@tool
def check_agent_status(agent_id: str) -> str:
    """Retrieve the real-time operational status and current activity of a specific agent.
    Use this to see if an agent is 'live' or 'died', and what specific task they are currently processing.
    Args:
        agent_id: The unique ID of the agent to inspect.
    """
    tasks = get_bus().get_agent_task_status(agent_id)
    # Get the most recent task if available
    latest = tasks[-1] if tasks else {}
    
    # Get system status
    info = get_bus().get_agents(agent_id)
    sys_status = info.get("status", "unknown") if info else "unknown"
    
    return f"Agent {agent_id} System Status: {sys_status} | Latest Task Status: {latest.get('status', 'None')} | Task: {latest.get('task', 'None')[:100]}..."

@tool
def get_task_manifest(agent_id: Optional[str] = None) -> str:
    """Read the central mission registry (SOE - Source of Everything) for the entire squad or a specific agent.
    This provides a complete history of assignments, their current status, and verification state.
    Args:
        agent_id: Optional. Filter to show tasks only for this specific agent.
    """
    bus = get_bus()
    if agent_id:
        tasks = bus.get_agent_task_status(agent_id)
        label = f"Tasks for {agent_id}"
    else:
        tasks = bus.get_all_agents_task_status()
        label = "Global Task Manifest"

    if not tasks:
        return f"No tasks found for {label}."

    # --- SCREEN OBSERVABILITY ---
    print(f"\n📋 {label.upper()} (SCREEN ONLY)")
    for t in tasks:
        v_icon = "✅" if t.get("is_verified") else "⏳"
        status = t.get("status") or "unknown"
        task_str = t.get("task") or "None"
        print(f" [{status.upper()}] {v_icon} {t['agent_id']}: {task_str[:100]}...")
    print()
    # ----------------------------

    output = f"--- {label} ---\n"
    for t in tasks:
        verified = " (Verified)" if t.get("is_verified") else " (Unverified)"
        status = t.get("status") or "unknown"
        task_str = t.get("task") or "None"
        t_id = t.get("id") or t.get("task_id") or "?"
        output += f"- ID: {t_id} | {t['agent_id']}: [{status}] {task_str[:150]}{verified}\n"
    
    return output

@tool
def check_all_agents_status() -> str:
    """Perform a global vitality check on all agents in the Multi-Agent System.
    This is the primary tool for Masters to monitor their entire hierarchy's health and task distribution.
    """
    statuses = get_bus().get_all_agents_task_status()
    if not statuses:
        return "No agents found in the system."
        
    # --- SCREEN OBSERVABILITY ---
    print("\n" + "="*40)
    print("🛰️ GLOBAL SQUAD OVERSIGHT (SCREEN ONLY)")
    for s in statuses:
        stat = s.get("agent_status", "unknown")
        icon = "🟢" if stat == "live" else "🔴"
        task_str = s.get("task") or "None"
        print(f" {icon} {s['agent_id']} (Parent: {s.get('parent_id', 'None')})")
        print(f"    - Task Status: {s.get('task_status', 'None')}")
        print(f"    - Current Task: {task_str[:100]}...")
    print("="*40 + "\n")
    # ----------------------------

    output = "--- All Agents Status ---\n"
    for s in statuses:
        task_str = s.get("task") or "None"
        output += f"\nAgent: {s['agent_id']} (Parent: {s.get('parent_id', 'None')})\n"
        output += f"System State: {s['agent_status']} (Last Active: {s['last_active_time']})\n"
        output += f"Task Status: {s.get('task_status', 'None')}\n"
        output += f"Current Task: {task_str[:200]}...\n"
    
    from .common import _truncate_output
    return _truncate_output(output)

@tool
def send_mas_message(to_id: str, message: str) -> str:
    """Send a private message to another agent in the squad.
    MANDATORY: Before sending, use 'get_chat_history' to ensure you aren't flooding the recipient with redundant messages.
    If your last message to this agent hasn't been replied to yet, wait for their response before messaging again.
    Use this to communicate with your Master, coordinate with coworkers, or give specific ad-hoc instructions to subordinates.
    Args:
        to_id: The ID of the agent you want to message (e.g., 'rootMaster', 'slave1').
        message: The text content of the message.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    
    print(f"\n[COMM] {agent_id} -> {to_id}: {message[:100]}...\n", flush=True)
    bus.send_message(agent_id, to_id, message)
    return f"Message sent to {to_id}"

@tool
def get_unread_messages() -> str:
    """Check your incoming inbox and retrieve all new, unread messages. 
    MANDATORY: Run this frequently to stay synchronized with Master directives and Coworker requests.
    Reading messages via this tool marks them as 'read' in the system.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    # Unread (marks as read)
    unread_grouped = bus.read_unread_messages(agent_id)
    unread = [m for msgs in unread_grouped.values() for m in msgs] if isinstance(unread_grouped, dict) else unread_grouped
    
    if not unread:
        return "You have no new unread messages."
        
    # --- SCREEN OBSERVABILITY ---
    print(f"\n📩 {agent_id} READ {len(unread)} NEW MESSAGES:")
    for m in unread:
        ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(m['timestamp']))
        print(f"  [{ts}] FROM {m['from']}: {m.get('content')}")
    print()
    # ----------------------------
        
    output = "--- NEW UNREAD MESSAGES ---\n"
    for m in unread:
        output += f"  (Sno: {m['sno']}) FROM {m['from']}: {m.get('content')}\n"
                
    return output

@tool
def get_unreplied_messages() -> str:
    """Identify which incoming messages in your history still require an explicit response from you.
    Use this to ensure no coordination request or Master inquiry is left unanswered.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    unreplied = bus.read_unreplied_messages(agent_id)
    
    if not unreplied:
        return "You have no unreplied messages."
        
    # --- SCREEN OBSERVABILITY ---
    print(f"\n⚠️ {agent_id} HAS {len(unreplied)} UNREPLIED MESSAGES:")
    for m in unreplied:
        ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(m['timestamp']))
        print(f"  [{ts}] FROM {m['from']}: {m.get('content')}")
    print()
    # ----------------------------
        
    output = "--- UNREPLIED MESSAGES (REPLY REQUIRED) ---\n"
    for m in unreplied:
        output += f"  (Sno: {m['sno']}) FROM {m['from']}: {m.get('content')}\n"
                
    return output

@tool
def reply_mas_message(chat_sno: int, message: str) -> str:
    """Submit a response to a specific message identified by its serial number (chat_sno).
    MANDATORY: Before replying, use 'get_chat_history' to review your chat history and ensure you haven't already responded to this message.
    If you have already replied, do NOT message again; wait for the other agent to respond to you, as they may be busy working.
    Args:
        chat_sno: The serial number of the message you are responding to.
        message: Your response text.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    
    original_msg = bus.get_message_by_sno(chat_sno)
    if not original_msg:
        return f"[Error] Message with Sno {chat_sno} not found."
    
    # Reply to the sender of the original message
    to_id = original_msg["from"]
    
    # --- SCREEN OBSERVABILITY ---
    print(f"\n💬 {agent_id} REPLIED to {to_id} (Ref #{chat_sno}): {message[:100]}...\n")
    # ----------------------------

    bus.reply_message(agent_id, to_id, message, chat_sno)
    return f"Reply sent to {to_id} for message {chat_sno}"

@tool
def get_chat_history(peer_id: str = None) -> str:
    """Retrieve your communication logs. 
    If peer_id is provided, it returns the history between you and that specific agent.
    If peer_id is omitted, it returns your complete chat history with everyone.
    Args:
        peer_id: Optional ID of the agent whose specific chat history you wish to review.
    """
    my_id = os.environ.get("AGENT_ID")
    if not my_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    history = bus.get_chat_history(my_id, peer_id)
    
    if not history:
        if peer_id: return f"No recorded communication between {my_id} and {peer_id}."
        return f"No recorded communication for {my_id}."
    
    # If peer_id was provided, history is a List. If not, it's a Dict[peer, List].
    if peer_id:
        history_grouped = {peer_id: history}
    else:
        history_grouped = history

    output = f"--- Communication Logs for {my_id} ---\n"
    for peer, msgs in history_grouped.items():
        output += f"\n[Chat with {peer}]:\n"
        for msg in msgs:
            output += f"  (Sno: {msg['sno']}) {msg['from']} -> {msg['to']}: {str(msg.get('content', ''))[:500]}\n"
    return output

@tool
def delegate_task(to_id: str, task_description: str) -> str:
    """Formally issue a new assignment to a subordinate agent.
    MANDATORY: Check 'get_task_manifest' before delegating. Do NOT assign a task that the agent is already working on (pending/inprogress). 
    Re-assigning the same task disturbs the agent's focus; you MUST wait for their official reply, acknowledgement, or completion.
    You may assign multiple different tasks, but understand that the agent will process them sequentially (one by one).
    Args:
        to_id: The ID of the slave agent you are assigning the work to.
        task_description: A detailed, actionable description of the work required.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    
    # --- CHECK FOR DUPLICATE TASKS ---
    all_tasks = bus.get_agent_task_status(agent_id=to_id)
    if all_tasks:
        desc_new = task_description.strip().lower()
        duplicates = [
            t for t in all_tasks 
            if isinstance(t, dict) 
            and t.get("status") in ["pending", "inprogress"]
            and t.get("task", "").strip().lower() == desc_new
        ]
        if duplicates:
            return f"[REJECTED] Task already assigned to {to_id} and is currently {duplicates[0]['status']}. Do not send redundant assignments."
    
    # --- SCREEN OBSERVABILITY ---
    print(f"\n🤝 DELEGATION: {agent_id} -> {to_id}")
    print(f"   Task: {task_description[:100]}...\n")
    # ----------------------------

    # 1. Update Database
    bus.update_agent_task_status(to_id, "pending", task_description, assigner_id=agent_id)
    # 2. Send Message
    bus.send_message(agent_id, to_id, task_description, need_reply=True)
    
    return f"[SUCCESS] Task delegated to {to_id}. It is now tracked in the system as 'pending' for that agent."

@tool
def handle_slave_failure(failed_agent_id: str) -> str:
    """Execute the emergency succession and task reassignment protocol for a non-responsive or 'died' agent.
    This tool can trigger 'Sacrificial Promotion' (drafting a slave to lead) or direct task takeover.
    Args:
        failed_agent_id: The ID of the agent who has failed or gone silent.
    """
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
    active_tasks = [t for t in (tasks or []) if isinstance(t, dict) and t.get("status") == "inprogress"]
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
def update_task_status(status: str, task_id: Optional[int] = None) -> str:
    """Update your current task status and progress in the central mission registry.
    Args:
        status: Must be one of: 'inprogress', 'completed', or 'pending'.
        task_id: The unique numeric ID of the task from the manifest.
    """
    agent_id = os.environ.get("AGENT_ID")
    if not agent_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    bus.update_agent_task_status(agent_id, status, row_id=task_id)
    return f"[SUCCESS] Your status has been updated to '{status}' for task {task_id or 'latest'} in the system database."

@tool
def verify_task(agent_id: str, task_id: int, approved: bool, feedback: str = "") -> str:
    """Conduct a formal quality assurance audit on a subordinate's work.
    If approved, the task is finalized. If rejected, the slave is automatically notified to perform rework.
    Args:
        agent_id: The ID of the slave whose work you are auditing.
        task_id: The unique numeric ID of the task from the manifest.
        approved: True to finalize/close the task, False to reject it.
        feedback: Mandatory if rejected; explain exactly what needs to be fixed.
    """
    my_id = os.environ.get("AGENT_ID")
    if not my_id: return "[Error] MAS context missing."
    
    bus = get_bus()
    
    # --- SCREEN OBSERVABILITY ---
    v_icon = "✅" if approved else "❌"
    print(f"\n{v_icon} VERIFICATION: {my_id} reviewed Task {task_id} for {agent_id}")
    print(f"   Result: {'APPROVED' if approved else 'REJECTED'}")
    print(f"   Feedback: {feedback[:100]}...\n")
    # ----------------------------
    if approved:
        bus.update_agent_task_status(agent_id, "completed", is_verified=1, verified_by=my_id, row_id=task_id)
        bus.send_message(my_id, agent_id, f"TASK APPROVED: Your work on task {task_id} has been verified. Great job!")
        return f"[SUCCESS] Task {task_id} for {agent_id} has been VERIFIED and CLOSED."
    else:
        # Revert to inprogress
        bus.update_agent_task_status(agent_id, "inprogress", is_verified=0, row_id=task_id)
        bus.send_message(my_id, agent_id, f"TASK REJECTED: Your work on task {task_id} needs improvement. Feedback: {feedback}. Please rework and report again.")
        return f"[REJECTED] Task {task_id} for {agent_id} has been sent back for rework with feedback."

@tool
def contribute_to_knowledge(topic: str, insight: str, relative_file_path: Optional[str] = None) -> str:
    """Record an important architectural discovery or code analysis into the collective squad memory.
    Use this to save peers from repeating expensive research or analysis.
    Args:
        topic: A concise title for the insight.
        insight: The detailed explanation or finding.
        relative_file_path: Optional. If the insight relates to a specific file, include its relative path.
    """
    agent_id = os.environ.get("AGENT_ID", "Unknown")
    # --- SCREEN OBSERVABILITY ---
    print(f"\n🧠 KNOWLEDGE ADDED by {agent_id}:")
    print(f"   Topic: {topic}")
    print(f"   Path: {relative_file_path or 'Global'}")
    print(f"   Insight: {insight[:200]}...\n")
    # ----------------------------

    get_bus().update_knowledge(topic, insight, agent_id, relative_file_path)
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
    
    # --- SCREEN OBSERVABILITY ---
    print("\n📚 SQUAD KNOWLEDGE VAULT (INDEX)")
    for line in topic_lines:
        print(f" - {line}")
    print()
    # ----------------------------

    return f"SQUAD KNOWLEDGE VAULT TOPICS:\n - {topics}"

@tool
def query_knowledge(topic: Optional[str] = None, relative_file_path: Optional[str] = None) -> str:
    """Retrieve shared insights from the squad's knowledge vault. 
    You can query by 'topic' or 'relative_file_path' to see if anyone has analyzed a file before you do.
    If you provide neither, it returns everything."""
    knowledge = get_bus().get_knowledge(topic=topic, relative_file_path=relative_file_path)
    
    # --- SCREEN OBSERVABILITY ---
    if knowledge:
        print(f"\n🔍 KNOWLEDGE QUERY result for '{topic or relative_file_path}':")
        for t, data in knowledge.items():
            print(f"   > {t}: {data.get('insight', '')[:300]}...")
        print()
    # ----------------------------

    if not knowledge:
        return "No shared knowledge found for this query."
    
    output = "--- Shared Knowledge Vault ---\n"
    for t, data in knowledge.items():
        output += f"\nTopic: {t}\nContributor: {data.get('contributor_id', 'unknown')}\nLast Updated By: {data.get('updated_agent_id', 'unknown')}\nInsight: {data['insight']}\n"
        if data.get("is_stale"):
            output += "⚠️ WARNING: This insight is STALE. The file has been modified since this was written. Please re-analyze the file and use 'contribute_to_knowledge' to update this vault.\n"
    return output

@tool
def terminate_mission(reason: str) -> str:
    """Terminate the entire Multi-Agent mission and shut down all agents.
    MANDATORY: This tool is ONLY available to the ROOT MASTER. 
    Before calling this, you MUST confirm that all tasks in the 'get_task_manifest' are 'completed' and 'verified'.
    This tool will perform a final 'git_commit_and_push' before shutting down.
    Args:
        reason: A final summary of why the mission is being terminated (e.g., 'Project fully completed and verified').
    """
    agent_id = os.environ.get("AGENT_ID")
    parent_id = os.environ.get("PARENT_ID", "")
    
    # Root Master is identified by "NoParentForYou"
    is_root = parent_id == "NoParentForYou"
    
    if not is_root:
        return f"[REJECTED] Termination failed. You are {agent_id} (Sub-Master under {parent_id}). ONLY the ROOT MASTER can terminate the mission."
        
    print(f"\n[SYSTEM] 🏁 MISSION TERMINATION INITIATED BY ROOT MASTER ({agent_id})")
    print(f"   Reason: {reason}\n")
    
    # 1. Final Git Push
    print("[SYSTEM] Performing final mission persistence (Git Push)...")
    try:
        push_res = git_commit_and_push(f"🏁 Mission Complete: {reason}")
        print(f"[SYSTEM] Git Push Status: {push_res}")
    except Exception as e:
        print(f"[Warning] Final git push failed: {e}")

    print("[SYSTEM] Shutting down. Mission End.")
    # Exit the entire process tree
    os._exit(0)
    return "Mission Terminated."
