import subprocess
import sys
import json
from langchain_core.tools import tool


def _get_clipboard() -> str:
    """Cross-platform clipboard read."""
    if sys.platform == "win32":
        result = subprocess.run(
            ["powershell", "-Command", "Get-Clipboard"],
            capture_output=True, text=True
        )
        return result.stdout.rstrip("\n")
    elif sys.platform == "darwin":
        result = subprocess.run(["pbpaste"], capture_output=True, text=True)
        return result.stdout
    else:
        # Linux: try xclip, then xsel, then wl-paste (Wayland)
        for cmd in [["xclip", "-selection", "clipboard", "-o"],
                    ["xsel", "--clipboard", "--output"],
                    ["wl-paste"]]:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    return result.stdout
            except FileNotFoundError:
                continue
        return "[Error] No clipboard utility found. Install xclip, xsel, or wl-paste."


def _set_clipboard(text: str) -> str:
    """Cross-platform clipboard write."""
    if sys.platform == "win32":
        # Use clip.exe for reliability; powershell Set-Clipboard struggles with special chars
        result = subprocess.run(
            ["powershell", "-Command", "-"],
            input=f"Set-Clipboard -Value '{text.replace(chr(39), chr(39)*2)}'",
            capture_output=True, text=True
        )
        # Fallback to clip.exe which is more reliable for arbitrary text
        proc = subprocess.run("clip", input=text.encode("utf-16-le"),
                              capture_output=True, shell=True)
        return "ok" if proc.returncode == 0 else f"[Error] clip.exe failed: {proc.stderr}"
    elif sys.platform == "darwin":
        result = subprocess.run(["pbcopy"], input=text, capture_output=True, text=True)
        return "ok" if result.returncode == 0 else f"[Error] {result.stderr.strip()}"
    else:
        for cmd, stdin_text in [
            (["xclip", "-selection", "clipboard"], text),
            (["xsel", "--clipboard", "--input"], text),
            (["wl-copy"], text),
        ]:
            try:
                result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
                if result.returncode == 0:
                    return "ok"
            except FileNotFoundError:
                continue
        return "[Error] No clipboard utility found. Install xclip, xsel, or wl-paste."


@tool
def clipboard_read() -> str:
    """Read the current text content from the system clipboard.
    Use this to retrieve text that was copied from another application or process.
    Returns the clipboard text, or an error if the clipboard is empty or unavailable.
    """
    try:
        content = _get_clipboard()
        if content.startswith("[Error]"):
            return content
        if not content.strip():
            return "[Info] Clipboard is empty."
        return f"[Clipboard Content]:\n{content}"
    except Exception as exc:
        return f"[Error] Failed to read clipboard: {exc}"


@tool
def clipboard_write(text: str) -> str:
    """Write text to the system clipboard, replacing its current content.
    Use this to pass data to other applications or to share output between processes without using files.
    Args:
        text: The text to place on the clipboard.
    """
    try:
        result = _set_clipboard(text)
        if result.startswith("[Error]"):
            return result
        preview = text[:100] + ("..." if len(text) > 100 else "")
        return f"[Success] Clipboard updated ({len(text)} chars). Preview: {preview}"
    except Exception as exc:
        return f"[Error] Failed to write clipboard: {exc}"


def _clipboard_history_win(n: int) -> list[str]:
    """Pull history from common Windows clipboard managers via PowerShell.
    Tries: Ditto (SQLite DB), ClipboardFusion (registry), then falls back
    to returning just the live clipboard as a single-entry list.
    """
    # --- Ditto clipboard manager ---
    ditto_db_candidates = [
        r"%APPDATA%\Ditto\Ditto.db",
        r"%LOCALAPPDATA%\Ditto\Ditto.db",
    ]
    for raw_path in ditto_db_candidates:
        expanded = subprocess.run(
            ["powershell", "-Command", f"[System.Environment]::ExpandEnvironmentVariables('{raw_path}')"],
            capture_output=True, text=True
        ).stdout.strip()
        import os
        if os.path.exists(expanded):
            try:
                import sqlite3
                conn = sqlite3.connect(expanded)
                rows = conn.execute(
                    "SELECT strClipBoardData FROM Main "
                    "WHERE strClipBoardData IS NOT NULL "
                    "ORDER BY lID DESC LIMIT ?", (n,)
                ).fetchall()
                conn.close()
                if rows:
                    return [r[0] for r in rows]
            except Exception:
                pass

    # --- Raw PowerShell Get-Clipboard (current entry only on stock Windows) ---
    result = subprocess.run(
        ["powershell", "-Command", "Get-Clipboard"],
        capture_output=True, text=True
    )
    current = result.stdout.rstrip("\n")
    return [current] if current else []


def _clipboard_history_mac(n: int) -> list[str]:
    """macOS: try Pasta / Flycut / Maccy (all store history in plist / SQLite).
    Falls back to pbpaste (single entry) if no manager is found.
    """
    import os, glob
    # Maccy stores in ~/Library/Application Support/Maccy/Storage.sqlite
    maccy_paths = glob.glob(
        os.path.expanduser("~/Library/Application Support/Maccy/*.sqlite")
    )
    for db_path in maccy_paths:
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT value FROM history_item "
                "ORDER BY updated_at DESC LIMIT ?", (n,)
            ).fetchall()
            conn.close()
            if rows:
                return [r[0] for r in rows if r[0]]
        except Exception:
            pass

    # Fallback: current pbpaste only
    result = subprocess.run(["pbpaste"], capture_output=True, text=True)
    return [result.stdout] if result.stdout else []


def _clipboard_history_linux(n: int) -> list[str]:
    """Linux: try Clipman (xfce4-clipman) JSON log, then gpaste via dbus,
    then fall back to xclip/xsel current entry.
    """
    import os
    # xfce4-clipman stores history in a JSON file
    clipman_path = os.path.expanduser("~/.local/share/xfce4/clipman/textsrc")
    if os.path.exists(clipman_path):
        try:
            entries = json.loads(open(clipman_path).read())
            texts = [e.get("content", "") for e in reversed(entries) if e.get("content")]
            return texts[:n]
        except Exception:
            pass

    # gpaste via dbus-send
    try:
        result = subprocess.run(
            ["gpaste-client", "history", "--zero-ui"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
            return lines[:n]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: current clipboard entry
    for cmd in [["xclip", "-selection", "clipboard", "-o"],
                ["xsel", "--clipboard", "--output"],
                ["wl-paste"]]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and result.stdout:
                return [result.stdout]
        except FileNotFoundError:
            continue
    return []


@tool
def clipboard_history(n: int = 10) -> str:
    """Return the most recent clipboard entries from the system clipboard manager.
    Supports Ditto (Windows), Maccy (macOS), xfce4-clipman and gpaste (Linux).
    Falls back gracefully to the current clipboard entry on systems without a
    clipboard manager installed.
    Args:
        n: Maximum number of recent entries to return (default 10).
    """
    try:
        n = max(1, min(n, 100))
        if sys.platform == "win32":
            entries = _clipboard_history_win(n)
        elif sys.platform == "darwin":
            entries = _clipboard_history_mac(n)
        else:
            entries = _clipboard_history_linux(n)

        if not entries:
            return "[Info] No clipboard history found. Is a clipboard manager installed?"

        lines = [f"Clipboard history ({len(entries)} entries):"]
        for i, entry in enumerate(entries, 1):
            preview = entry.replace("\n", " ").replace("\r", "")
            if len(preview) > 120:
                preview = preview[:120] + "..."
            lines.append(f"  [{i}] {preview}")
        return "\n".join(lines)
    except Exception as exc:
        return f"[Error] clipboard_history failed: {exc}"
