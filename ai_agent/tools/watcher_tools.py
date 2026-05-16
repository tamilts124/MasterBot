"""
watcher_tools.py — File and directory change watcher.

Blocks for up to `timeout_seconds`, polling for modifications.
Returns a structured report of what changed: which paths were created,
modified, or deleted, along with timestamps.

No external dependencies — uses only the stdlib (os.stat / os.scandir).
If the `watchdog` package is installed it is used instead for more
reliable event detection (particularly on network drives).
"""

import os
import time
import json
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool
from .common import _truncate_output

try:
    from watchdog.observers import Observer as _WatchdogObserver
    from watchdog.events import FileSystemEventHandler as _WatchdogHandler
    _WATCHDOG_AVAILABLE = True
except Exception:
    _WATCHDOG_AVAILABLE = False


# ---------------------------------------------------------------------------
# Core polling logic
# ---------------------------------------------------------------------------

def _snapshot(target: Path) -> dict:
    """Return {str_path: mtime_ns} for target (file) or all files under target (dir)."""
    snap = {}
    if target.is_file():
        try:
            snap[str(target)] = target.stat().st_mtime_ns
        except OSError:
            pass
    elif target.is_dir():
        for root, dirs, files in os.walk(target):
            # Skip hidden dirs to avoid noise from .git etc.
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                p = Path(root) / f
                try:
                    snap[str(p)] = p.stat().st_mtime_ns
                except OSError:
                    pass
    return snap


def _diff_snapshots(before: dict, after: dict) -> dict:
    """Return {created: [...], modified: [...], deleted: [...]}."""
    b_keys = set(before)
    a_keys = set(after)
    created  = sorted(a_keys - b_keys)
    deleted  = sorted(b_keys - a_keys)
    modified = sorted(
        k for k in b_keys & a_keys if before[k] != after[k]
    )
    return {"created": created, "modified": modified, "deleted": deleted}


def _poll_watch(target: Path, timeout: int, poll_interval: float = 0.5) -> dict:
    """Poll-based watcher. Returns event dict the moment something changes."""
    baseline = _snapshot(target)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        current = _snapshot(target)
        diff = _diff_snapshots(baseline, current)
        if any(diff.values()):
            return diff
    return {}  # timed out — nothing changed


def _watchdog_watch(target: Path, timeout: int) -> dict:
    """watchdog-based watcher — more efficient, works with network mounts."""
    events_seen: list = []

    class _Collector(_WatchdogHandler):
        def on_any_event(self, event):
            if event.is_directory:
                return
            events_seen.append(event)

    observer = _WatchdogObserver()
    handler  = _Collector()
    watch_path = str(target.parent if target.is_file() else target)
    observer.schedule(handler, watch_path, recursive=target.is_dir())
    observer.start()
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if events_seen:
                break
            time.sleep(0.2)
    finally:
        observer.stop()
        observer.join()

    # Classify events
    created, modified, deleted = [], [], []
    for ev in events_seen:
        # filter to the exact file if target is a file
        if target.is_file() and ev.src_path != str(target):
            continue
        t = ev.event_type
        if t == "created":
            created.append(ev.src_path)
        elif t in ("modified", "closed"):
            modified.append(ev.src_path)
        elif t == "deleted":
            deleted.append(ev.src_path)
        elif t == "moved":
            deleted.append(ev.src_path)
            created.append(getattr(ev, "dest_path", "?"))

    return {
        "created":  sorted(set(created)),
        "modified": sorted(set(modified)),
        "deleted":  sorted(set(deleted)),
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool
def watch_file(path: str, timeout_seconds: int = 30) -> str:
    """Watch a file or directory for any filesystem change and report what changed.
    Blocks until the first change is detected or the timeout expires.
    Useful for hot-reload workflows, waiting for a build artifact, or detecting
    config changes made by another process.

    Uses the `watchdog` library when available (install: pip install watchdog);
    falls back to efficient polling otherwise.

    Args:
        path: Absolute or relative path to a file or directory to watch.
        timeout_seconds: How long to wait for a change, in seconds (default 30,
                         max 3600). Returns immediately once any change is seen.
    Returns:
        JSON-style summary with keys 'created', 'modified', 'deleted' listing
        the affected paths, plus 'elapsed_seconds'. If nothing changed within
        the timeout, all lists are empty.
    """
    try:
        target = Path(path).resolve()
        if not target.exists():
            return f"[Error] Path does not exist: {path}"

        timeout_seconds = max(1, min(timeout_seconds, 3600))
        t0 = time.monotonic()

        # Try watchdog first; fall back to polling
        if _WATCHDOG_AVAILABLE:
            diff = _watchdog_watch(target, timeout_seconds)
            engine = "watchdog"
        else:
            diff = _poll_watch(target, timeout_seconds)
            engine = "polling"

        elapsed = round(time.monotonic() - t0, 2)
        total_events = sum(len(v) for v in diff.values())

        result = {
            "path": str(target),
            "engine": engine,
            "elapsed_seconds": elapsed,
            "timed_out": total_events == 0,
            **diff,
        }
        return _truncate_output(json.dumps(result, indent=2))

    except Exception as exc:
        return f"[Error] watch_file failed: {exc}"


@tool
def watch_until_stable(path: str, stable_seconds: int = 2, timeout_seconds: int = 60) -> str:
    """Watch a file or directory until it stops changing for `stable_seconds`.
    Useful after triggering a build or download — wait until writes settle before
    reading the output.
    Args:
        path: Path to the file or directory to monitor.
        stable_seconds: How many consecutive quiet seconds counts as 'stable' (default 2).
        timeout_seconds: Hard upper limit before giving up (default 60).
    Returns:
        JSON summary with 'stable' (bool), 'elapsed_seconds', and total event counts.
    """
    try:
        target = Path(path).resolve()
        if not target.exists():
            return f"[Error] Path does not exist: {path}"

        stable_seconds  = max(1, stable_seconds)
        timeout_seconds = max(stable_seconds + 1, min(timeout_seconds, 3600))
        poll_interval   = 0.3

        baseline    = _snapshot(target)
        last_change = time.monotonic()
        t0          = last_change
        total_events = {"created": 0, "modified": 0, "deleted": 0}

        while True:
            now = time.monotonic()
            elapsed = now - t0
            if elapsed >= timeout_seconds:
                stable = False
                break
            if (now - last_change) >= stable_seconds:
                stable = True
                break
            time.sleep(poll_interval)
            current = _snapshot(target)
            diff = _diff_snapshots(baseline, current)
            if any(diff.values()):
                last_change = time.monotonic()
                for k in total_events:
                    total_events[k] += len(diff[k])
                baseline = current

        result = {
            "path": str(target),
            "stable": stable,
            "elapsed_seconds": round(time.monotonic() - t0, 2),
            **{f"total_{k}": v for k, v in total_events.items()},
        }
        return json.dumps(result, indent=2)

    except Exception as exc:
        return f"[Error] watch_until_stable failed: {exc}"
