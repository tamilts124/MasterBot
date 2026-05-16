import os
import difflib
import subprocess
import tempfile
from pathlib import Path
from langchain_core.tools import tool
from .common import _truncate_output


def _read_file(path: Path) -> list[str]:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.readlines()


@tool
def diff_files(path_a: str, path_b: str) -> str:
    """Generate a unified diff between two files (or between a file and a string).
    Use this to review what changed before overwriting, to compare versions, or to audit agent edits.
    Args:
        path_a: Path to the original / baseline file.
        path_b: Path to the modified / new file.
    """
    try:
        a = Path(path_a).expanduser().resolve()
        b = Path(path_b).expanduser().resolve()
        for p, label in [(a, path_a), (b, path_b)]:
            if not p.exists():
                return f"[Error] File not found: {label}"

        lines_a = _read_file(a)
        lines_b = _read_file(b)
        diff = list(difflib.unified_diff(
            lines_a, lines_b,
            fromfile=f"a/{a.name}",
            tofile=f"b/{b.name}",
            lineterm=""
        ))
        if not diff:
            return f"[Info] Files are identical: {path_a} == {path_b}"
        return _truncate_output("\n".join(diff))
    except Exception as exc:
        return f"[Error] diff_files failed: {exc}"


@tool
def diff_file_content(file_path: str, new_content: str) -> str:
    """Preview a unified diff between the current content of a file and proposed new content.
    ALWAYS call this before write_file to see exactly what will change.
    This prevents accidental overwrites and produces cleaner git history.
    Args:
        file_path: Path to the existing file to compare against.
        new_content: The proposed new content as a string.
    """
    try:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            # New file — show everything as additions
            new_lines = new_content.splitlines(keepends=True)
            diff = list(difflib.unified_diff(
                [], new_lines,
                fromfile="(new file)",
                tofile=file_path,
                lineterm=""
            ))
            return _truncate_output("\n".join(diff)) if diff else "[Info] Empty new file."

        old_lines = _read_file(path)
        new_lines = new_content.splitlines(keepends=True)
        # Ensure trailing newlines match
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"

        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{path.name}",
            tofile=f"b/{path.name}",
            lineterm=""
        ))
        if not diff:
            return "[Info] No changes — proposed content is identical to the current file."

        additions = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
        deletions = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
        header = f"[Diff Summary: +{additions} lines, -{deletions} lines]\n"
        return _truncate_output(header + "\n".join(diff))
    except Exception as exc:
        return f"[Error] diff_file_content failed: {exc}"


@tool
def patch_file(file_path: str, old_text: str, new_text: str) -> str:
    """Surgically replace an exact block of text in a file without rewriting the whole file.
    This is the preferred way to make targeted edits — safer than write_file for large files.
    The old_text must match the file content exactly (whitespace and all).
    Args:
        file_path: Path to the file to patch.
        old_text: The exact block of text to find and replace.
        new_text: The replacement text.
    """
    try:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return f"[Error] File not found: {file_path}"

        content = path.read_text(encoding="utf-8", errors="replace")

        count = content.count(old_text)
        if count == 0:
            # Try to give a helpful hint about why it failed
            stripped = old_text.strip()
            if stripped in content:
                return (
                    "[Error] Exact match not found — but the text exists with different surrounding whitespace. "
                    "Copy the text precisely including all leading/trailing spaces and newlines."
                )
            return "[Error] old_text not found in file. Verify the text matches exactly, character-for-character."
        if count > 1:
            return (
                f"[Error] old_text appears {count} times in the file — ambiguous patch. "
                "Make old_text longer/more specific so it matches exactly once."
            )

        new_content = content.replace(old_text, new_text, 1)

        # Show a mini diff before writing
        old_lines = content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{path.name}",
            tofile=f"b/{path.name}",
            lineterm=""
        ))
        additions = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
        deletions = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

        path.write_text(new_content, encoding="utf-8")
        diff_preview = "\n".join(diff[:60])
        suffix = "\n...[diff truncated]" if len(diff) > 60 else ""
        return f"[Success] Patched {path.name} (+{additions}/-{deletions} lines)\n{diff_preview}{suffix}"
    except Exception as exc:
        return f"[Error] patch_file failed: {exc}"


@tool
def apply_unified_diff(file_path: str, diff_text: str) -> str:
    """Apply a unified diff (patch) string directly to a file using the system `patch` command.
    Use this when you have a diff in standard unified format (e.g. from diff_files or diff_file_content).
    Args:
        file_path: Path to the file to apply the patch to.
        diff_text: The unified diff text to apply.
    """
    try:
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return f"[Error] File not found: {file_path}"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".patch",
                                         delete=False, encoding="utf-8") as tf:
            tf.write(diff_text)
            patch_path = tf.name

        try:
            result = subprocess.run(
                ["patch", "--no-backup-if-mismatch", str(path), patch_path],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                return f"[Success] Patch applied to {path.name}:\n{result.stdout}"
            return f"[Error] patch command failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}"
        finally:
            os.unlink(patch_path)
    except FileNotFoundError:
        return "[Error] 'patch' command not found. Install it (apt install patch / brew install gpatch) or use patch_file instead."
    except Exception as exc:
        return f"[Error] apply_unified_diff failed: {exc}"


@tool
def git_diff(staged: bool = False) -> str:
    """Show the current git diff of the working directory — what has changed but not yet committed.
    Args:
        staged: If True, show diff of staged (git add'd) changes. If False (default), show unstaged changes.
    """
    try:
        is_repo = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True
        )
        if is_repo.returncode != 0:
            return "[Error] Not a git repository."

        cmd = ["git", "diff"]
        if staged:
            cmd.append("--staged")

        result = subprocess.run(cmd, capture_output=True, text=True)
        output = result.stdout.strip()
        if not output:
            label = "staged" if staged else "unstaged"
            return f"[Info] No {label} changes in the working directory."
        return _truncate_output(output)
    except Exception as exc:
        return f"[Error] git_diff failed: {exc}"


@tool
def text_diff(text_a: str, text_b: str, label_a: str = "original", label_b: str = "modified") -> str:
    """Generate a unified diff between two in-memory strings without touching the filesystem.
    Use this when you already have two versions of content as strings — avoids writing
    temp files just to compare them. Ideal for comparing API responses, generated code,
    config snippets, or any two text values the agent holds in context.
    Args:
        text_a: The original / baseline text.
        text_b: The modified / new text.
        label_a: Label shown in the diff header for text_a (default 'original').
        label_b: Label shown in the diff header for text_b (default 'modified').
    """
    try:
        lines_a = text_a.splitlines(keepends=True)
        lines_b = text_b.splitlines(keepends=True)

        # Ensure trailing newlines so the diff reads cleanly
        if lines_a and not lines_a[-1].endswith("\n"):
            lines_a[-1] += "\n"
        if lines_b and not lines_b[-1].endswith("\n"):
            lines_b[-1] += "\n"

        diff = list(difflib.unified_diff(
            lines_a, lines_b,
            fromfile=label_a,
            tofile=label_b,
            lineterm=""
        ))

        if not diff:
            return "[Info] Strings are identical — no differences found."

        additions = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++ "))
        deletions = sum(1 for l in diff if l.startswith("-") and not l.startswith("--- "))
        header = f"[Diff: +{additions} line(s) added, -{deletions} line(s) removed]\n"
        return _truncate_output(header + "\n".join(diff))
    except Exception as exc:
        return f"[Error] text_diff failed: {exc}"
