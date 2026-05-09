import time
from langchain_core.tools import tool
from .interactive_process import InteractiveProcess, ACTIVE_PROCESSES

@tool
def start_interactive_process(command: str) -> str:
    """Start a persistent background process for interactive testing.
    Use this to test programs that require 'on the spot' runtime input.
    Returns a process_id and the initial output.
    """
    try:
        proc = InteractiveProcess(command)
        ACTIVE_PROCESSES[proc.id] = proc
        # Wait a bit for initial output
        time.sleep(3)
        initial_out = proc.get_full_log()
        return f"[STARTED] Process ID: {proc.id}\nInitial History:\n{initial_out}\n\nYou can now use 'send_to_process' to provide input."
    except Exception as e:
        return f"[ERROR] Failed to start process: {str(e)}"

@tool
def list_interactive_processes() -> str:
    """List all interactive background processes and their current status.
    Use this to see what programs you have running and get their process IDs.
    """
    if not ACTIVE_PROCESSES:
        return "[INFO] No active or recorded interactive processes found."
    
    report = "--- ACTIVE/RECORDED INTERACTIVE PROCESSES ---\n"
    for pid, proc in ACTIVE_PROCESSES.items():
        status = "RUNNING" if proc.process.poll() is None else f"TERMINATED (Code {proc.process.returncode})"
        report += f"- ID: {pid} | Status: {status} | Command: {proc.command}\n"
    
    return report

@tool
def get_process_history(process_id: str) -> str:
    """Retrieve the complete structured interaction log of an interactive process.
    Use this to audit the entire session context, including processes that have already terminated or crashed.
    By reviewing the chronological sequence of your [INPUT] and the resulting [OUTPUT], you can perfectly understand the current state of the program and whether it is currently waiting for input from you.
    """
    proc = ACTIVE_PROCESSES.get(process_id)
    if not proc:
        return f"[ERROR] Process {process_id} not found."
    
    status = "RUNNING" if proc.process.poll() is None else f"TERMINATED (Code {proc.process.returncode})"
    return f"--- INTERACTION LOG FOR {process_id} (Status: {status}) ---\n{proc.get_full_log()}"

@tool
def send_to_process(process_id: str, input_text: str) -> str:
    """Send input to an active interactive process and retrieve the immediate resulting output.
    MANDATORY: Before sending input, use 'get_process_history' to confirm the program is actually ready/waiting for input. 
    Your input will be logged as [INPUT] and the program's response as [OUTPUT] in the history.
    """
    proc = ACTIVE_PROCESSES.get(process_id)
    if not proc:
        return f"[ERROR] Process {process_id} not found."
    
    if proc.process.poll() is not None:
        return f"[TERMINATED] Process {process_id} has already exited (Code {proc.process.returncode}). You can use 'get_process_history' to see the final output log."

    if proc.send_input(input_text):
        # Wait a bit for the response
        time.sleep(2)
        full_out = proc.get_full_log()
        return f"[HISTORY from {process_id}]:\n{full_out}"
    else:
        return f"[ERROR] Could not send input to {process_id}."

@tool
def stop_interactive_process(process_id: str) -> str:
    """Terminate an active interactive process and remove it from the session.
    """
    proc = ACTIVE_PROCESSES.pop(process_id, None)
    if proc:
        proc.process.terminate()
        return f"[TERMINATED] Process {process_id} has been stopped."
    return f"[ERROR] Process {process_id} not found."
