import os
import re
from pathlib import Path
from langchain_core.tools import tool
from .common import _truncate_output

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


@tool
def file_search(path: str, pattern: str, regex: bool = False,
                context_lines: int = 0, max_matches: int = 200) -> str:
    """Search a file or every file in a directory for lines matching a pattern.
    Returns only the matching lines with their line numbers — never the whole file.
    Use this instead of read_file when you need to find a function, config key,
    error message, or any string inside a potentially large file.
    Args:
        path: File or directory to search. Directories are searched recursively;
              hidden folders (.git, __pycache__, node_modules) are skipped.
        pattern: The string or regular expression to search for.
        regex: If False (default), treat pattern as a plain substring (case-insensitive).
               If True, treat pattern as a Python regular expression.
        context_lines: Number of lines to show before and after each match (default 0).
                       Like grep -C. Useful for seeing surrounding code.
        max_matches: Stop after this many matches to protect token budget (default 200).
    """
    try:
        target = Path(path)
        if not target.exists():
            return f"[Error] Path does not exist: {path}"

        # Compile pattern
        try:
            if regex:
                compiled = re.compile(pattern, re.MULTILINE)
            else:
                compiled = re.compile(re.escape(pattern), re.IGNORECASE)
        except re.error as exc:
            return f"[Error] Invalid regex pattern: {exc}"

        SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache"}

        def search_file(fp: Path) -> list[str]:
            try:
                lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                return []
            results = []
            for i, line in enumerate(lines):
                if compiled.search(line):
                    # Gather context window
                    lo = max(0, i - context_lines)
                    hi = min(len(lines), i + context_lines + 1)
                    for j in range(lo, hi):
                        marker = ">>>" if j == i else "   "
                        results.append(f"{marker} {fp}:{j+1}: {lines[j]}")
                    if context_lines:
                        results.append("    ---")
            return results

        matches: list[str] = []
        truncated = False

        if target.is_file():
            matches = search_file(target)
            if len(matches) > max_matches:
                matches = matches[:max_matches]
                truncated = True
        else:
            for root, dirs, files in os.walk(target):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for fname in files:
                    fp = Path(root) / fname
                    # Skip binary files by extension
                    if fp.suffix.lower() in {".pyc", ".exe", ".dll", ".so",
                                              ".png", ".jpg", ".zip", ".gz"}:
                        continue
                    file_hits = search_file(fp)
                    remaining = max_matches - len(matches)
                    if len(file_hits) >= remaining:
                        matches.extend(file_hits[:remaining])
                        truncated = True
                        break
                    matches.extend(file_hits)
                if truncated:
                    break

        if not matches:
            return f"No matches found for '{pattern}' in {path}"

        header = f"Found {len(matches)} match line(s) for '{pattern}' in {path}:"
        if truncated:
            header += f" (truncated at {max_matches} — narrow your pattern or use regex)"
        return _truncate_output(header + "\n" + "\n".join(matches))

    except Exception as exc:
        return f"[Error] file_search failed: {exc}"


@tool
def file_edit_lines(path: str, start_line: int, end_line: int, new_content: str) -> str:
    """Replace a specific line range in a file with new content.
    Use this for surgical edits — changing a function body, updating a config block,
    or fixing a bug — without rewriting the entire file.
    Always call diff_file_content or file_search first to confirm the correct line numbers.
    Args:
        path: Path to the file to edit.
        start_line: First line to replace (1-indexed, inclusive).
        end_line: Last line to replace (1-indexed, inclusive). Use the same value
                  as start_line to replace a single line. To insert without removing,
                  set end_line = start_line - 1.
        new_content: The replacement text. Trailing newline is added automatically
                     if missing. Pass an empty string to delete the line range.
    """
    try:
        fp = Path(path)
        if not fp.exists():
            return f"[Error] File not found: {path}"
        if not fp.is_file():
            return f"[Error] Path is not a file: {path}"

        original = fp.read_text(encoding="utf-8", errors="replace")
        lines = original.splitlines(keepends=True)
        total = len(lines)

        # Validate range
        if start_line < 1:
            return f"[Error] start_line must be >= 1 (got {start_line})"
        if end_line < start_line - 1:  # allow end = start-1 for pure insert
            return f"[Error] end_line ({end_line}) must be >= start_line-1 ({start_line-1})"
        if start_line > total + 1:
            return f"[Error] start_line {start_line} exceeds file length ({total} lines)"

        # Normalise new_content — ensure it ends with newline unless empty
        replacement_lines: list[str] = []
        if new_content:
            for ln in new_content.splitlines(keepends=True):
                replacement_lines.append(ln if ln.endswith("\n") else ln + "\n")

        # Splice
        s = start_line - 1                   # 0-indexed start (inclusive)
        e = min(end_line, total)             # 0-indexed end (exclusive after)
        new_lines = lines[:s] + replacement_lines + lines[e:]
        new_text = "".join(new_lines)

        fp.write_text(new_text, encoding="utf-8")

        removed = e - s
        added = len(replacement_lines)
        return (
            f"OK — edited {path}\n"
            f"Lines {start_line}–{end_line}: removed {removed} line(s), "
            f"inserted {added} line(s). File now has {len(new_lines)} lines."
        )

    except Exception as exc:
        return f"[Error] file_edit_lines failed: {exc}"
