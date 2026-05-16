import os
import time
import sqlite3
import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from langchain_core.tools import tool

class SASKnowledgeBase:
    def __init__(self, db_name: str = "sas_knowledge.db"):
        # Store in .sas folder in the agent's working directory
        work_dir = Path(os.environ.get("AGENT_WORKDIR", "."))
        self.base_dir = work_dir / ".sas"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_dir / db_name
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS shared_knowledge (
                    topic TEXT PRIMARY KEY,
                    insight TEXT NOT NULL,
                    updated_on REAL DEFAULT (strftime('%s','now')),
                    relative_file_path TEXT DEFAULT NULL,
                    file_mtime REAL DEFAULT NULL
                );
            """)

    def update_knowledge(self, topic: str, insight: str, relative_file_path: Optional[str] = None):
        file_mtime = None
        if relative_file_path and os.path.exists(relative_file_path):
            file_mtime = os.path.getmtime(relative_file_path)
            
        with self._get_conn() as conn:
            now = time.time()
            conn.execute("""
                INSERT INTO shared_knowledge (topic, insight, relative_file_path, file_mtime, updated_on)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(topic) DO UPDATE SET 
                    insight = excluded.insight,
                    updated_on = excluded.updated_on,
                    relative_file_path = coalesce(excluded.relative_file_path, shared_knowledge.relative_file_path),
                    file_mtime = excluded.file_mtime
            """, (topic, insight, relative_file_path, file_mtime, now))

    def get_knowledge(self, topic: Optional[str] = None, relative_file_path: Optional[str] = None) -> Dict[str, Any]:
        with self._get_conn() as conn:
            if topic or relative_file_path:
                if topic:
                    cursor = conn.execute("SELECT * FROM shared_knowledge WHERE topic = ?", (topic,))
                else:
                    cursor = conn.execute("SELECT * FROM shared_knowledge WHERE relative_file_path = ?", (relative_file_path,))
            else:
                cursor = conn.execute("SELECT * FROM shared_knowledge")
                
            knowledge = {}
            for row in cursor.fetchall():
                data = dict(row)
                topic_name = data.pop("topic")
                check_path = data.get("relative_file_path")
                if check_path and data.get("file_mtime") is not None and os.path.exists(check_path):
                    if os.path.getmtime(check_path) > data["file_mtime"]:
                        data["is_stale"] = True
                knowledge[topic_name] = data
            return knowledge

# Global instance
KB = SASKnowledgeBase()

@tool
def sas_add_knowledge(topic: str, insight: str, relative_file_path: Optional[str] = None) -> str:
    """Record a discovery, analysis, or architectural finding into your long-term memory.
    Use this to 'save' information you've gathered so you can retrieve it in future turns.
    Args:
        topic: A concise title for the insight.
        insight: The detailed explanation or finding.
        relative_file_path: Optional. If the insight relates to a specific file, include its relative path.
    """
    KB.update_knowledge(topic, insight, relative_file_path)
    return f"[SUCCESS] SAS knowledge vault updated with topic: {topic}"

@tool
def sas_list_knowledge() -> str:
    """List all available topics you have previously saved in your memory vault.
    Use this to see what analysis or research is already available."""
    knowledge = KB.get_knowledge()
    if not knowledge: return "The SAS knowledge vault is currently empty."
    
    topic_lines = []
    for topic, data in knowledge.items():
        path = data.get("relative_file_path")
        topic_lines.append(f"{topic} (File: {path})" if path else topic)
            
    return "SAS KNOWLEDGE VAULT INDEX:\n - " + "\n - ".join(topic_lines)

@tool
def sas_query_knowledge(topic: Optional[str] = None, relative_file_path: Optional[str] = None) -> str:
    """Retrieve saved insights from your memory vault using a topic or file path.
    Args:
        topic: Optional. Specific topic name to look up.
        relative_file_path: Optional. Path of a file to see if you have analyzed it before.
    """
    knowledge = KB.get_knowledge(topic=topic, relative_file_path=relative_file_path)
    if not knowledge: return "No SAS knowledge found for this query."
    
    output = "--- SAS Knowledge Vault ---\n"
    for t, data in knowledge.items():
        output += f"\nTopic: {t}\nInsight: {data['insight']}\n"
        if data.get("is_stale"):
            output += "⚠️ WARNING: This insight is STALE. The file has been modified since this was written.\n"
    return output

@tool
def sas_execute_sql(query: str) -> str:
    """Executes a raw SQL query against the SAS database. 
    You have full freedom to use this tool for any operation (CREATE, INSERT, UPDATE, SELECT) to manage your own custom data structures.
    
    CRITICAL RULES:
    1. Do NOT DROP or DELETE the 'shared_knowledge' table. It is your foundational long-term memory.
    2. PERSISTENCE MAPPING: Whenever you create a new table OR store critical information in a custom location, you MUST use 'sas_add_knowledge' to record a 'Pointer' or 'Insight' about it. 
       - Topic example: "Data Registry: [Table Name or Purpose]"
       - Insight: Describe what the data is, where it is stored (which table), and its schema/purpose.
    
    This 'Registry' ensures that you (and future agents) have a 'Map' of all custom data structures you've built.
    
    Example Workflow:
    Step 1 (Action): sas_execute_sql(query="CREATE TABLE recon_results (id INTEGER PRIMARY KEY, url TEXT, vuln TEXT)")
    Step 2 (Mapping): sas_add_knowledge(topic="Data Registry: Recon Results", insight="Custom table 'recon_results' created to track vulnerabilities. Columns: id, url, vuln.")

    Args:
        query: The SQL statement to execute.
    """
    try:
        # Check for destructive operations on the core table
        q_lower = query.strip().lower()
        forbidden = ["drop table shared_knowledge", "delete from shared_knowledge", "truncate table shared_knowledge"]
        if any(f in q_lower for f in forbidden):
            return "[REJECTED] You are not allowed to delete or remove the core 'shared_knowledge' table."
            
        with KB._get_conn() as conn:
            cursor = conn.execute(query)
            
            # 1. Logic for SELECT
            if q_lower.startswith("select"):
                rows = cursor.fetchall()
                if not rows: return "[INFO] Query returned no results."
                results = [dict(row) for row in rows]
                return json.dumps(results, indent=2)
            
            # 2. Commit and return success
            conn.commit()
            return f"[SUCCESS] SQL executed. Rows affected: {cursor.rowcount}"
    except Exception as e:
        return f"[ERROR] SQL execution failed: {str(e)}"
