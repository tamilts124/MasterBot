import os
from pathlib import Path
from langchain_core.tools import tool

@tool
def rename_file(old_path: str, new_path: str) -> str:
    """Rename or move a file within the current working directory.
    This tool is safer than 'run_bash' for moving files as it performs path validation to ensure operations remain within the permitted workspace.
    Args:
        old_path: The current relative or absolute path of the file.
        new_path: The desired new path or name for the file.
    """
    try:
        old_resolved = Path(old_path).expanduser().resolve()
        new_resolved = Path(new_path).expanduser().resolve()
        cwd = Path.cwd().resolve()
        
        if not str(old_resolved).startswith(str(cwd)) or not str(new_resolved).startswith(str(cwd)):
            return "[Error] Rename operation outside working directory is prohibited."
            
        if not old_resolved.exists():
            return f"[Error] Source file does not exist: {old_path}"
            
        new_resolved.parent.mkdir(parents=True, exist_ok=True)
        old_resolved.rename(new_resolved)
        return f"File renamed from {old_path} to {new_path}"
    except Exception as exc:
        return f"[Error] {exc}"
