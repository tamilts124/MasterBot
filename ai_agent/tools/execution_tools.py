import os
import sys
import subprocess
import tempfile
from langchain_core.tools import tool
from .common import _truncate_output

@tool
def run_bat(script: str) -> str:
    """Execute a Windows batch (.bat) script and capture its output.
    Use this for Windows-specific automation, environment setup, or running legacy CMD commands.
    Args:
        script: The full multi-line text of the batch script to execute.
    """
    if os.name != "nt":
        return "[Error] BAT execution is only supported on Windows."
    bat_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bat", mode="w", encoding="utf-8") as tf:
            tf.write(script)
            bat_path = tf.name
        result = subprocess.run([bat_path], capture_output=True, text=True, shell=True)
        output = result.stdout + result.stderr
        if result.returncode != 0:
            return _truncate_output(f"[Error] Batch script exited with code {result.returncode}.\n{output}")
        return _truncate_output(output if output else "[Info] Script produced no output.")
    finally:
        if bat_path and os.path.exists(bat_path):
            try:
                os.unlink(bat_path)
            except Exception:
                pass

@tool
def run_bash(script: str) -> str:
    """Execute a bash or system shell command and return the combined output.
    This is the primary tool for Unix-like systems for file system operations, git commands, and running system utilities.
    Args:
        script: The command or script to run in the system shell.
    """
    if os.name == "nt":
        return "[Error] Bash execution is not supported on Windows."
    bash_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".sh", mode="w", encoding="utf-8") as tf:
            tf.write(script)
            bash_path = tf.name
        os.chmod(bash_path, 0o755)
        result = subprocess.run(["bash", bash_path], capture_output=True, text=True)
        output = result.stdout + result.stderr
        if result.returncode != 0:
            return _truncate_output(f"[Error] Bash script exited with code {result.returncode}.\n{output}")
        return _truncate_output(output if output else "[Info] Script produced no output.")
    finally:
        if bash_path and os.path.exists(bash_path):
            try:
                os.unlink(bash_path)
            except Exception:
                pass

@tool
def run_python(script: str) -> str:
    """Execute a Python script in a separate process and return its output.
    Use this for complex data processing, performing calculations, or executing independent Python logic.
    Args:
        script: The complete Python source code to execute.
    """
    py_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode="w", encoding="utf-8") as tf:
            tf.write(script)
            py_path = tf.name
        result = subprocess.run([sys.executable, py_path], capture_output=True, text=True)
        output = result.stdout + result.stderr
        if result.returncode != 0:
            return _truncate_output(f"[Error] Python script exited with code {result.returncode}.\n{output}")
        return _truncate_output(output if output else "[Info] Script produced no output.")
    finally:
        if py_path and os.path.exists(py_path):
            try:
                os.unlink(py_path)
            except Exception:
                pass
