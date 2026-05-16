import os
import sys
import platform
import subprocess
import shutil
from pathlib import Path
from langchain_core.tools import tool
from .common import _truncate_output


@tool
def system_info() -> str:
    """Get comprehensive information about the current system environment.
    Returns OS, Python version, CPU, memory, disk usage, hostname, and key environment variables.
    Use this at the start of a session to understand the execution environment.
    """
    try:
        import psutil
        has_psutil = True
    except ImportError:
        has_psutil = False

    lines = []

    # OS & Python
    lines.append("=== System Info ===")
    lines.append(f"OS:           {platform.system()} {platform.release()} ({platform.machine()})")
    lines.append(f"Platform:     {sys.platform}")
    lines.append(f"Hostname:     {platform.node()}")
    lines.append(f"Python:       {sys.version.split()[0]} at {sys.executable}")
    lines.append(f"CWD:          {os.getcwd()}")

    # CPU & Memory (psutil preferred)
    if has_psutil:
        import psutil
        cpu_count = psutil.cpu_count(logical=True)
        cpu_pct = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        lines.append(f"\n=== CPU ===")
        lines.append(f"Cores:        {cpu_count} logical")
        lines.append(f"Usage:        {cpu_pct}%")
        lines.append(f"\n=== Memory ===")
        lines.append(f"Total:        {mem.total / 1e9:.2f} GB")
        lines.append(f"Available:    {mem.available / 1e9:.2f} GB")
        lines.append(f"Used:         {mem.used / 1e9:.2f} GB ({mem.percent}%)")
        lines.append(f"Swap Total:   {swap.total / 1e9:.2f} GB")
        lines.append(f"Swap Used:    {swap.used / 1e9:.2f} GB ({swap.percent}%)")
    else:
        lines.append("\n[Note] Install psutil for CPU/memory info: pip install psutil")

    # Disk usage
    lines.append(f"\n=== Disk (CWD partition) ===")
    try:
        disk = shutil.disk_usage(os.getcwd())
        lines.append(f"Total:        {disk.total / 1e9:.2f} GB")
        lines.append(f"Used:         {disk.used / 1e9:.2f} GB")
        lines.append(f"Free:         {disk.free / 1e9:.2f} GB ({disk.free / disk.total * 100:.1f}% free)")
    except Exception as exc:
        lines.append(f"[Error reading disk] {exc}")

    # Key env vars
    lines.append(f"\n=== Key Environment Variables ===")
    important_vars = [
        "PATH", "HOME", "USER", "USERNAME", "SHELL", "TERM",
        "PYTHONPATH", "VIRTUAL_ENV", "CONDA_DEFAULT_ENV",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
        "AGENT_ID", "PARENT_ID", "MAX_TOOL_OUTPUT"
    ]
    for var in important_vars:
        val = os.environ.get(var, "")
        if val:
            # Truncate very long vars like PATH
            display = val if len(val) <= 120 else val[:120] + "..."
            lines.append(f"{var:<22}: {display}")

    return _truncate_output("\n".join(lines))


@tool
def list_processes(filter: str = "") -> str:
    """List currently running processes on the system.
    Args:
        filter: Optional keyword to filter processes by name (case-insensitive). Leave empty for all.
    """
    try:
        import psutil

        procs = []
        for p in psutil.process_iter(["pid", "name", "status", "cpu_percent", "memory_info"]):
            try:
                info = p.info
                if filter and filter.lower() not in info["name"].lower():
                    continue
                mem_mb = info["memory_info"].rss / 1e6 if info["memory_info"] else 0
                procs.append(
                    f"PID {info['pid']:<8} {info['name']:<35} {info['status']:<12} "
                    f"CPU: {info['cpu_percent']:>5.1f}%  MEM: {mem_mb:>7.1f} MB"
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not procs:
            return f"[Info] No processes found matching '{filter}'." if filter else "[Info] No processes found."

        header = f"{'PID':<12} {'Name':<35} {'Status':<12} {'CPU':>10}  {'Memory':>12}"
        return _truncate_output(f"[{len(procs)} processes]\n{header}\n" + "\n".join(procs))

    except ImportError:
        # Fallback without psutil
        if sys.platform == "win32":
            result = subprocess.run(["tasklist"], capture_output=True, text=True)
        else:
            result = subprocess.run(["ps", "aux"], capture_output=True, text=True)

        output = result.stdout
        if filter:
            lines = [l for l in output.splitlines() if filter.lower() in l.lower()]
            output = "\n".join(lines)

        return _truncate_output(output or "[Info] No matching processes.")
    except Exception as exc:
        return f"[Error] Failed to list processes: {exc}"


@tool
def get_env_vars(prefix: str = "") -> str:
    """List environment variables, optionally filtered by a prefix.
    Args:
        prefix: Only return variables whose names start with this prefix (case-insensitive).
                Leave empty to return all variables.
    """
    try:
        items = sorted(os.environ.items())
        if prefix:
            items = [(k, v) for k, v in items if k.upper().startswith(prefix.upper())]

        if not items:
            msg = f"No environment variables found with prefix '{prefix}'." if prefix else "No environment variables found."
            return f"[Info] {msg}"

        lines = [f"[{len(items)} variables]\n"]
        for k, v in items:
            display = v if len(v) <= 200 else v[:200] + "..."
            lines.append(f"{k:<35} = {display}")

        return _truncate_output("\n".join(lines))
    except Exception as exc:
        return f"[Error] Failed to get environment variables: {exc}"


@tool
def check_disk_space(path: str = ".") -> str:
    """Check disk space usage for a given path or drive.
    Args:
        path: The directory or drive to check (default: current working directory).
    """
    try:
        resolved = Path(path).expanduser().resolve()
        if not resolved.exists():
            return f"[Error] Path not found: {path}"

        disk = shutil.disk_usage(str(resolved))
        used_pct = disk.used / disk.total * 100
        free_pct = disk.free / disk.total * 100

        lines = [
            f"[Disk Usage: {resolved}]",
            f"Total:  {disk.total / 1e9:.2f} GB",
            f"Used:   {disk.used / 1e9:.2f} GB ({used_pct:.1f}%)",
            f"Free:   {disk.free / 1e9:.2f} GB ({free_pct:.1f}%)",
        ]

        if free_pct < 10:
            lines.append("⚠️  WARNING: Less than 10% disk space remaining!")

        return "\n".join(lines)
    except Exception as exc:
        return f"[Error] Failed to check disk space: {exc}"
