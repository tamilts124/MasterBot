import os
import re
import sys
import signal
import subprocess
import tempfile
from typing import Optional
from langchain_core.tools import tool
from .common import _truncate_output


def _run_subprocess(cmd: list, timeout: Optional[int], script_path: str) -> str:
    """Run a subprocess with an optional hard timeout.

    Pass timeout=None (default) to wait forever.
    On expiry the process group is sent SIGKILL (Unix) or taskkill (Windows)
    so child processes spawned by the script don't linger.
    """
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            # Create a new process group so we can kill the whole tree
            **( {"start_new_session": True} if os.name != "nt"
                else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} ),
        )
        try:
            # timeout=None means wait indefinitely
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Kill the entire process group / job
            if os.name != "nt":
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    proc.kill()
            else:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
            proc.wait()
            return (
                f"[Timeout] Script exceeded the {timeout}s limit and was forcefully terminated.\n"
                f"Tip: increase the timeout parameter or pass timeout=None to wait forever."
            )

        output = (stdout + stderr).strip()
        if proc.returncode != 0:
            return _truncate_output(
                f"[Error] Script exited with code {proc.returncode}.\n{output}"
            )
        return _truncate_output(output if output else "[Info] Script produced no output.")

    finally:
        if script_path and os.path.exists(script_path):
            try:
                os.unlink(script_path)
            except Exception:
                pass


@tool
def run_bat(script: str, timeout: Optional[int] = None) -> str:
    """Execute a Windows batch (.bat) script and capture its output.
    Use this for Windows-specific automation, environment setup, or running legacy CMD commands.
    Args:
        script: The full multi-line text of the batch script to execute.
        timeout: Maximum seconds to wait before force-killing the script.
                 Default is None (wait forever). Set a value to guard against runaway scripts.
    """
    if os.name != "nt":
        return "[Error] BAT execution is only supported on Windows."
    bat_path = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".bat", mode="w", encoding="utf-8"
        ) as tf:
            tf.write(script)
            bat_path = tf.name
        return _run_subprocess([bat_path], timeout, bat_path)
    except Exception as exc:
        if bat_path and os.path.exists(bat_path):
            try:
                os.unlink(bat_path)
            except Exception:
                pass
        return f"[Error] Failed to launch batch script: {exc}"


@tool
def run_bash(script: str, timeout: Optional[int] = None) -> str:
    """Execute a bash shell script and return the combined stdout + stderr output.
    This is the primary tool for Unix-like systems for file system operations,
    git commands, and running system utilities.
    Args:
        script: The command or multi-line bash script to run.
        timeout: Maximum seconds to wait before force-killing the script.
                 Default is None (wait forever). Set a value to guard against runaway scripts.
    """
    if os.name == "nt":
        return "[Error] Bash execution is not supported on Windows."
    bash_path = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".sh", mode="w", encoding="utf-8"
        ) as tf:
            tf.write(script)
            bash_path = tf.name
        os.chmod(bash_path, 0o755)
        return _run_subprocess(["bash", bash_path], timeout, bash_path)
    except Exception as exc:
        if bash_path and os.path.exists(bash_path):
            try:
                os.unlink(bash_path)
            except Exception:
                pass
        return f"[Error] Failed to launch bash script: {exc}"


@tool
def run_python(script: str, timeout: Optional[int] = None) -> str:
    """Execute a Python script in a separate process and return its output.
    Use this for complex data processing, performing calculations, or executing
    independent Python logic.
    Args:
        script: The complete Python source code to execute.
        timeout: Maximum seconds to wait before force-killing the script.
                 Default is None (wait forever). Set e.g. timeout=60 to guard against hangs.
    """
    py_path = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".py", mode="w", encoding="utf-8"
        ) as tf:
            tf.write(script)
            py_path = tf.name
        return _run_subprocess([sys.executable, py_path], timeout, py_path)
    except Exception as exc:
        if py_path and os.path.exists(py_path):
            try:
                os.unlink(py_path)
            except Exception:
                pass
        return f"[Error] Failed to launch Python script: {exc}"


@tool
def process_status(pid: int) -> str:
    """Check whether a process is still running and return its details.
    Use this after run_bat / run_bash / start_interactive_process to confirm a
    background job is alive, or to check if a server you started is still up.
    Args:
        pid: The process ID to inspect.
    """
    try:
        import psutil
    except ImportError:
        return "[Error] psutil is not installed. Run: pip install psutil"
    try:
        proc = psutil.Process(pid)
        info = proc.as_dict(attrs=[
            "pid", "name", "status", "cmdline",
            "cpu_percent", "memory_info", "create_time"
        ])
        import datetime
        created = datetime.datetime.fromtimestamp(info["create_time"]).strftime("%Y-%m-%d %H:%M:%S")
        mem_mb = info["memory_info"].rss / 1024 / 1024 if info["memory_info"] else 0
        cmd = " ".join(info["cmdline"]) if info["cmdline"] else "(unknown)"
        return (
            f"PID     : {info['pid']}\n"
            f"Name    : {info['name']}\n"
            f"Status  : {info['status']}\n"
            f"Command : {cmd}\n"
            f"Memory  : {mem_mb:.1f} MB\n"
            f"Started : {created}"
        )
    except psutil.NoSuchProcess:
        return f"[Dead] No process found with PID {pid} — it has already exited."
    except psutil.AccessDenied:
        return f"[AccessDenied] PID {pid} exists but cannot be inspected (insufficient permissions)."
    except Exception as exc:
        return f"[Error] process_status failed: {exc}"


@tool
def process_kill(pid: int, force: bool = False) -> str:
    """Terminate a running process by PID.
    Use this to stop a runaway script, kill a hung server, or clean up a
    background job started with run_bash or start_interactive_process.
    Args:
        pid: The process ID to terminate.
        force: If False (default), send SIGTERM / taskkill — allows graceful shutdown.
               If True, send SIGKILL / taskkill /F — immediate hard kill.
               Try False first; escalate to True only if the process refuses to exit.
    """
    try:
        import psutil
    except ImportError:
        return "[Error] psutil is not installed. Run: pip install psutil"
    try:
        proc = psutil.Process(pid)
        name = proc.name()
        if force:
            proc.kill()   # SIGKILL on Unix, TerminateProcess on Windows
            action = "force-killed (SIGKILL)"
        else:
            proc.terminate()  # SIGTERM on Unix, TerminateProcess on Windows
            action = "terminated (SIGTERM)"
        # Wait briefly to confirm
        try:
            proc.wait(timeout=3)
            return f"OK — PID {pid} ({name}) {action} and has exited."
        except psutil.TimeoutExpired:
            return (
                f"Signal sent to PID {pid} ({name}) but it has not exited yet.\n"
                f"Call process_kill(pid={pid}, force=True) to hard-kill it."
            )
    except psutil.NoSuchProcess:
        return f"[Dead] PID {pid} does not exist — already exited."
    except psutil.AccessDenied:
        return f"[AccessDenied] Cannot kill PID {pid} — insufficient permissions."
    except Exception as exc:
        return f"[Error] process_kill failed: {exc}"
