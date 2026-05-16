"""
config_tools.py — Safe in-place patching of JSON and YAML config files.

Key concepts
------------
* key_path  — dot-separated string addressing nested keys, e.g. "server.port"
              or "database.hosts.0" (integer segments address list indices).
* Patch-only — we read, mutate the in-memory object, then write back, so
  unrelated keys and file structure are preserved as much as possible.
* YAML round-trip — uses ruamel.yaml when available (preserves comments and
  key order); falls back to PyYAML silently.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from .common import _truncate_output


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_key_path(key_path: str) -> list:
    """Split "a.b.0.c" into ["a", "b", 0, "c"] (integers for list indices)."""
    parts = []
    for seg in key_path.split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            parts.append(seg)
    return parts


def _get_nested(obj: Any, parts: list) -> Any:
    for p in parts:
        try:
            obj = obj[p]
        except (KeyError, IndexError, TypeError) as exc:
            raise KeyError(f"Key segment {p!r} not found: {exc}") from exc
    return obj


def _set_nested(obj: Any, parts: list, value: Any) -> None:
    """Mutate obj in-place, creating intermediate dicts as needed."""
    for p in parts[:-1]:
        if isinstance(p, int):
            obj = obj[p]
        else:
            if p not in obj:
                obj[p] = {}
            obj = obj[p]
    obj[parts[-1]] = value


def _atomic_write(path: Path, text: str) -> None:
    """Write to a temp file then replace, so the original is never half-written."""
    dir_ = path.parent
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _coerce_value(raw: str) -> Any:
    """Try to parse raw as JSON so agents can pass true/false/numbers/objects.
    Falls back to the raw string if parsing fails."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


# ---------------------------------------------------------------------------
# JSON tools
# ---------------------------------------------------------------------------

@tool
def json_get(file: str, key_path: str) -> str:
    """Read a value from a JSON file at a dot-separated key path.
    Use this to inspect a single key without loading the entire file.
    Args:
        file: Path to the JSON file.
        key_path: Dot-separated key path, e.g. 'server.port' or 'items.0.name'.
    """
    try:
        path = Path(file)
        data = json.loads(path.read_text(encoding="utf-8"))
        parts = _parse_key_path(key_path)
        value = _get_nested(data, parts)
        return json.dumps(value, indent=2, ensure_ascii=False)
    except FileNotFoundError:
        return f"[Error] File not found: {file}"
    except KeyError as exc:
        return f"[Error] Key path '{key_path}' not found: {exc}"
    except Exception as exc:
        return f"[Error] {exc}"


@tool
def json_set(file: str, key_path: str, value: str) -> str:
    """Patch a single key in a JSON file without rewriting the whole file.
    Reads the file, updates the value at the given key path, and writes back atomically.
    Args:
        file: Path to the JSON file.
        key_path: Dot-separated key path, e.g. 'server.port' or 'database.name'.
                  Integer segments address list indices, e.g. 'hosts.0'.
        value: New value as a JSON-encoded string. Scalars like numbers, booleans,
               and null are decoded automatically (e.g. '8080', 'true', 'null').
               Strings must be quoted: '"hello"'. Objects/arrays are accepted too.
    """
    try:
        path = Path(file)
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        parts = _parse_key_path(key_path)
        coerced = _coerce_value(value)
        _set_nested(data, parts, coerced)
        new_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        _atomic_write(path, new_text)
        return f"OK — set '{key_path}' = {json.dumps(coerced)} in {file}"
    except FileNotFoundError:
        return f"[Error] File not found: {file}"
    except KeyError as exc:
        return f"[Error] Key path '{key_path}' not found: {exc}"
    except Exception as exc:
        return f"[Error] {exc}"


@tool
def json_delete(file: str, key_path: str) -> str:
    """Delete a key from a JSON file at the given dot-separated key path.
    Args:
        file: Path to the JSON file.
        key_path: Dot-separated key path to remove, e.g. 'cache.ttl'.
    """
    try:
        path = Path(file)
        data = json.loads(path.read_text(encoding="utf-8"))
        parts = _parse_key_path(key_path)
        parent = _get_nested(data, parts[:-1]) if len(parts) > 1 else data
        last = parts[-1]
        if isinstance(parent, list):
            if not isinstance(last, int):
                return f"[Error] Expected integer index for list, got '{last}'"
            del parent[last]
        else:
            if last not in parent:
                return f"[Error] Key '{last}' not found at path '{key_path}'"
            del parent[last]
        new_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        _atomic_write(path, new_text)
        return f"OK — deleted '{key_path}' from {file}"
    except FileNotFoundError:
        return f"[Error] File not found: {file}"
    except Exception as exc:
        return f"[Error] {exc}"


# ---------------------------------------------------------------------------
# YAML tools
# ---------------------------------------------------------------------------

def _load_yaml_engine():
    """Return (load_fn, dump_fn, engine_name). Prefers ruamel.yaml for comment
    preservation; falls back to PyYAML."""
    try:
        from ruamel.yaml import YAML
        y = YAML()
        y.preserve_quotes = True
        y.width = 120

        def load_fn(text: str):
            import io
            return y.load(io.StringIO(text))

        def dump_fn(data) -> str:
            import io
            buf = io.StringIO()
            y.dump(data, buf)
            return buf.getvalue()

        return load_fn, dump_fn, "ruamel.yaml"
    except ImportError:
        pass

    try:
        import yaml

        def load_fn(text: str):
            return yaml.safe_load(text)

        def dump_fn(data) -> str:
            return yaml.dump(data, default_flow_style=False, allow_unicode=True)

        return load_fn, dump_fn, "PyYAML"
    except ImportError:
        raise ImportError(
            "No YAML library found. Install ruamel.yaml (recommended) or PyYAML:\n"
            "  pip install ruamel.yaml"
        )


@tool
def yaml_get(file: str, key_path: str) -> str:
    """Read a value from a YAML file at a dot-separated key path.
    Args:
        file: Path to the YAML file.
        key_path: Dot-separated key path, e.g. 'server.port' or 'list.0.name'.
    """
    try:
        load_fn, _, _ = _load_yaml_engine()
        path = Path(file)
        data = load_fn(path.read_text(encoding="utf-8"))
        parts = _parse_key_path(key_path)
        value = _get_nested(data, parts)
        # Render value as JSON for a clean, unambiguous display
        return json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except FileNotFoundError:
        return f"[Error] File not found: {file}"
    except KeyError as exc:
        return f"[Error] Key path '{key_path}' not found: {exc}"
    except ImportError as exc:
        return f"[Error] {exc}"
    except Exception as exc:
        return f"[Error] {exc}"


@tool
def json_query(file: str, expression: str) -> str:
    """Query a JSON file using a jq-style expression and return the matching data.
    More powerful than json_get — supports filtering, mapping, and slicing across
    arrays and nested objects without loading the whole file into the conversation.
    Uses the `jq` Python library (pure-Python, no binary needed).
    Args:
        file: Path to the JSON file.
        expression: A jq expression. Examples:
            '.'                              — entire document
            '.users[]'                       — all items in a 'users' array
            '.users[] | select(.active)'     — only active users
            '[.items[] | .name]'             — list of name fields
            '.config | keys'                 — keys of a nested object
            '.servers[] | select(.port > 8000) | .host'  — filtered field
    """
    try:
        import jq as jq_lib
    except ImportError:
        return (
            "[Error] The 'jq' Python library is not installed.\n"
            "Install it with: pip install jq\n"
            "Note: on Windows this requires a C compiler or use the pre-built wheel."
        )
    try:
        fp = Path(file)
        if not fp.exists():
            return f"[Error] File not found: {file}"
        data = json.loads(fp.read_text(encoding="utf-8"))
        result = jq_lib.first(expression, data) if expression.strip() else data
        # jq.first returns the first match; use jq.all for multiple
        try:
            all_results = list(jq_lib.compile(expression).input(data))
        except Exception:
            all_results = [result]
        if len(all_results) == 1:
            output = json.dumps(all_results[0], indent=2, ensure_ascii=False)
        else:
            output = json.dumps(all_results, indent=2, ensure_ascii=False)
        return _truncate_output(output)
    except json.JSONDecodeError as exc:
        return f"[Error] Invalid JSON in file: {exc}"
    except Exception as exc:
        return f"[Error] jq query failed: {exc}"


@tool
def yaml_set(file: str, key_path: str, value: str) -> str:
    """Patch a single key in a YAML file without rewriting the whole file.
    Uses ruamel.yaml when available to preserve comments and key ordering.
    Falls back to PyYAML if ruamel is not installed.
    Args:
        file: Path to the YAML file.
        key_path: Dot-separated key path, e.g. 'server.port' or 'app.debug'.
                  Integer segments address list indices.
        value: New value as a JSON-encoded string (same rules as json_set).
               Examples: '8080', 'true', '"hello"', '["a","b"]'.
    """
    try:
        load_fn, dump_fn, engine = _load_yaml_engine()
        path = Path(file)
        text = path.read_text(encoding="utf-8")
        data = load_fn(text)
        parts = _parse_key_path(key_path)
        coerced = _coerce_value(value)
        _set_nested(data, parts, coerced)
        new_text = dump_fn(data)
        _atomic_write(path, new_text)
        return f"OK — set '{key_path}' = {json.dumps(coerced)} in {file} (via {engine})"
    except FileNotFoundError:
        return f"[Error] File not found: {file}"
    except KeyError as exc:
        return f"[Error] Key path '{key_path}' not found: {exc}"
    except ImportError as exc:
        return f"[Error] {exc}"
    except Exception as exc:
        return f"[Error] {exc}"


@tool
def yaml_delete(file: str, key_path: str) -> str:
    """Delete a key from a YAML file at the given dot-separated key path.
    Args:
        file: Path to the YAML file.
        key_path: Dot-separated key path to remove, e.g. 'logging.level'.
    """
    try:
        load_fn, dump_fn, engine = _load_yaml_engine()
        path = Path(file)
        data = load_fn(path.read_text(encoding="utf-8"))
        parts = _parse_key_path(key_path)
        parent = _get_nested(data, parts[:-1]) if len(parts) > 1 else data
        last = parts[-1]
        if isinstance(parent, list):
            if not isinstance(last, int):
                return f"[Error] Expected integer index for list, got '{last}'"
            del parent[last]
        else:
            if last not in parent:
                return f"[Error] Key '{last}' not found at path '{key_path}'"
            del parent[last]
        new_text = dump_fn(data)
        _atomic_write(path, new_text)
        return f"OK — deleted '{key_path}' from {file} (via {engine})"
    except FileNotFoundError:
        return f"[Error] File not found: {file}"
    except ImportError as exc:
        return f"[Error] {exc}"
    except Exception as exc:
        return f"[Error] {exc}"
