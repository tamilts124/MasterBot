"""
sqlite_tools.py — General-purpose SQLite query tool.

Supports any SQLite database file by path, not just the SAS knowledge DB.
Read queries return pretty-printed results. Write queries (INSERT/UPDATE/DELETE/
CREATE/DROP) commit and report rows affected.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from .common import _truncate_output


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rows_to_text(cursor: sqlite3.Cursor, rows: list) -> str:
    """Format query results as a readable table."""
    cols = [d[0] for d in cursor.description] if cursor.description else []
    if not cols:
        return "(no columns returned)"
    if not rows:
        return "(" + ", ".join(cols) + ")\n(0 rows)"

    # Serialize each cell to a short string
    def cell(v: Any) -> str:
        if v is None:
            return "NULL"
        if isinstance(v, (bytes, bytearray)):
            return f"<blob {len(v)}B>"
        return str(v)

    str_rows = [[cell(v) for v in row] for row in rows]
    widths = [max(len(c), *(len(r[i]) for r in str_rows)) for i, c in enumerate(cols)]
    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    header = "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cols)) + " |"

    lines = [sep, header, sep]
    for r in str_rows:
        lines.append("| " + " | ".join(r[i].ljust(widths[i]) for i in range(len(cols))) + " |")
    lines.append(sep)
    lines.append(f"({len(rows)} row{'s' if len(rows) != 1 else ''})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool
def sqlite_query(db_path: str, sql: str, params: str = "[]") -> str:
    """Run a SQL statement against any SQLite database file and return the results.
    Works for SELECT (returns formatted table), and for INSERT / UPDATE / DELETE /
    CREATE / DROP (commits and reports rows affected).
    Args:
        db_path: Path to the SQLite database file. The file must already exist for
                 read queries. It will be created for write/DDL statements.
        sql: The SQL statement to execute. Use ? placeholders for parameterised
             queries (see params).
        params: Optional JSON array of positional parameters matching ? placeholders,
                e.g. '[42, "hello"]'. Defaults to no parameters.
    """
    try:
        path = Path(db_path)
        is_read = sql.strip().upper().startswith("SELECT")

        if is_read and not path.exists():
            return f"[Error] Database file not found: {db_path}"

        try:
            param_list = json.loads(params)
            if not isinstance(param_list, list):
                return "[Error] 'params' must be a JSON array, e.g. '[1, \"hello\"]'"
        except json.JSONDecodeError as exc:
            return f"[Error] Could not parse 'params' as JSON: {exc}"

        conn = sqlite3.connect(str(path))
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(sql, param_list)

            if is_read:
                rows = [tuple(r) for r in cur.fetchall()]
                return _truncate_output(_rows_to_text(cur, rows))
            else:
                conn.commit()
                return (
                    f"OK — statement executed successfully.\n"
                    f"Rows affected: {cur.rowcount}\n"
                    f"Last insert rowid: {cur.lastrowid}"
                )
        finally:
            conn.close()

    except sqlite3.OperationalError as exc:
        return f"[SQLite Error] {exc}"
    except Exception as exc:
        return f"[Error] {exc}"


@tool
def sqlite_schema(db_path: str, table: str = "") -> str:
    """Inspect the schema of a SQLite database: list tables, or show columns for one table.
    Args:
        db_path: Path to the SQLite database file.
        table: Optional table name. If omitted, lists all tables and their CREATE statements.
    """
    try:
        path = Path(db_path)
        if not path.exists():
            return f"[Error] Database file not found: {db_path}"

        conn = sqlite3.connect(str(path))
        try:
            cur = conn.cursor()
            if table:
                # Column info for a specific table
                cur.execute(f"PRAGMA table_info({sqlite3.escape_string(table)})")
                rows = cur.fetchall()
                if not rows:
                    return f"[Error] Table '{table}' not found or has no columns."
                lines = [f"Columns for '{table}':", ""]
                lines.append(f"{'cid':<5} {'name':<25} {'type':<20} {'notnull':<8} {'dflt_value':<15} {'pk'}")
                lines.append("-" * 80)
                for r in rows:
                    cid, name, typ, notnull, dflt, pk = r
                    lines.append(f"{cid:<5} {name:<25} {(typ or ''):<20} {notnull:<8} {str(dflt or ''):<15} {pk}")
                return "\n".join(lines)
            else:
                # List all tables with their CREATE SQL
                cur.execute(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type='table' ORDER BY name"
                )
                rows = cur.fetchall()
                if not rows:
                    return f"(Database is empty or has no tables: {db_path})"
                parts = []
                for name, ddl in rows:
                    parts.append(f"-- {name}\n{ddl or '(no DDL)'}")
                return _truncate_output("\n\n".join(parts))
        finally:
            conn.close()

    except sqlite3.OperationalError as exc:
        return f"[SQLite Error] {exc}"
    except Exception as exc:
        return f"[Error] {exc}"
