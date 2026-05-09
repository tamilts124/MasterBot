import json
import os
import time
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

class MessageBus:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.db_path = base_dir / "mas_communication.db"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self):
        # timeout=10 means if database is locked, wait up to 10 seconds before throwing error
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        # Enable Write-Ahead Logging (WAL) for better concurrent read/write
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS messages (
                    sno INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_id TEXT NOT NULL,
                    to_id TEXT NOT NULL,
                    timestamp REAL DEFAULT (strftime('%s','now')),
                    content TEXT,
                    need_reply INTEGER DEFAULT 0,
                    reply_sno INTEGER,
                    is_read INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS agent_task_status (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    original_agent_id TEXT NOT NULL,
                    task TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    assigned_on REAL DEFAULT (strftime('%s','now')),
                    updated_on REAL DEFAULT (strftime('%s','now')),
                    assigner_id TEXT NOT NULL,
                    is_verified INTEGER DEFAULT 0,
                    verified_by TEXT,
                    UNIQUE(agent_id, task)
                );

                CREATE TABLE IF NOT EXISTS agents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT UNIQUE NOT NULL,
                    parent_id TEXT DEFAULT NULL,
                    last_active_time REAL DEFAULT (strftime('%s','now')),
                    status TEXT DEFAULT 'live'
                );

                CREATE TABLE IF NOT EXISTS shared_knowledge (
                    topic TEXT PRIMARY KEY,
                    insight TEXT NOT NULL,
                    contributor_id TEXT NOT NULL,
                    updated_on REAL DEFAULT (strftime('%s','now')),
                    updated_agent_id TEXT NOT NULL,
                    relative_file_path TEXT DEFAULT NULL,
                    file_mtime REAL DEFAULT NULL
                );
            """)

    def send_message(self, from_id: str, to_id: str, content: Any, need_reply: bool = False) -> int:
        content_str = json.dumps(content) if isinstance(content, (dict, list)) else str(content)
        
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO messages (from_id, to_id, timestamp, content, need_reply)
                VALUES (?, ?, ?, ?, ?)
            """, (from_id, to_id, time.time(), content_str, int(need_reply)))
            return cursor.lastrowid

    def reply_message(self, from_id: str, to_id: str, content: Any, chat_sno: int, need_reply: bool = False):
        """Replies to a specific message from 'to_id' using its serial number (chat_sno)."""
        # Call send_message to insert the new message (DRY principle)
        new_sno = self.send_message(from_id, to_id, content, need_reply=need_reply)
        
        with self._get_conn() as conn:
            # Update the original message's reply_sno to point to this new reply
            conn.execute("""
                UPDATE messages 
                SET reply_sno = ? 
                WHERE sno = ?
            """, (new_sno, chat_sno))

    def get_message_by_sno(self, sno: int) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM messages WHERE sno = ?", (sno,))
            row = cursor.fetchone()
            if row:
                msg = dict(row)
                msg["from"] = msg.pop("from_id")
                msg["to"] = msg.pop("to_id")
                try:
                    msg["content"] = json.loads(msg["content"])
                except: pass
                return msg
        return None

    def get_unread_messages_count(self, agent_id: str) -> Dict[str, int]:
        """Get counts of unread and unreplied messages without marking them as read."""
        with self._get_conn() as conn:
            # Count unread
            cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE to_id = ? AND is_read = 0", (agent_id,))
            unread_count = cursor.fetchone()[0]
            
            # Count unreplied
            cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE to_id = ? AND need_reply = 1 AND reply_sno IS NULL", (agent_id,))
            unreplied_count = cursor.fetchone()[0]
            
            return {"unread": unread_count, "unreplied": unreplied_count}

    def read_unread_messages(self, agent_id: str, sender_id: Optional[str] = None) -> Union[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        new_messages = []
        with self._get_conn() as conn:
            # Fetch unread messages
            if sender_id:
                cursor = conn.execute("""
                    SELECT * FROM messages 
                    WHERE to_id = ? AND from_id = ? AND is_read = 0
                    ORDER BY sno ASC
                """, (agent_id, sender_id))
            else:
                cursor = conn.execute("""
                    SELECT * FROM messages
                    WHERE to_id = ? AND is_read = 0
                    ORDER BY sno ASC
                """, (agent_id,))
                
            rows = cursor.fetchall()
            
            for row in rows:
                msg = dict(row)
                msg["need_reply"] = bool(msg["need_reply"])
                msg["is_read"] = bool(msg["is_read"])
                msg["from"] = msg.pop("from_id")
                msg["to"] = msg.pop("to_id")
                
                # Attempt to parse JSON content back to dict/list
                try:
                    msg["content"] = json.loads(msg["content"])
                except: pass
                
                new_messages.append(msg)
                
            if new_messages:
                # Mark them as read in a single query
                sno_list = [m["sno"] for m in new_messages]
                placeholders = ",".join("?" for _ in sno_list)
                conn.execute(f"UPDATE messages SET is_read = 1 WHERE sno IN ({placeholders})", sno_list)
        if sender_id is None:
            grouped = {}
            for msg in new_messages:
                sender = msg["from"]
                if sender not in grouped:
                    grouped[sender] = []
                grouped[sender].append(msg)
            return grouped
            
        return new_messages

    def read_unreplied_messages(self, agent_id: str, sender_id: Optional[str] = None) -> List[Dict[str, Any]]:
        unreplied_messages = []
        with self._get_conn() as conn:
            # Fetch unreplied messages
            if sender_id:
                cursor = conn.execute("""
                    SELECT * FROM messages 
                    WHERE to_id = ? AND from_id = ? AND need_reply = 1 AND reply_sno IS NULL
                    ORDER BY sno ASC
                """, (agent_id, sender_id))
            else:
                cursor = conn.execute("""
                    SELECT * FROM messages
                    WHERE to_id = ? AND need_reply = 1 AND reply_sno IS NULL
                    ORDER BY sno ASC
                """, (agent_id,))
                
            rows = cursor.fetchall()
            
            for row in rows:
                msg = dict(row)
                msg["need_reply"] = bool(msg["need_reply"])
                msg["is_read"] = bool(msg["is_read"])
                msg["from"] = msg.pop("from_id")
                msg["to"] = msg.pop("to_id")
                try:
                    msg["content"] = json.loads(msg["content"])
                except: pass
                unreplied_messages.append(msg)
                
        return unreplied_messages


    def get_all_agents_task_status(self) -> List[Dict[str, Any]]:
        """Retrieve the current state and latest task status for all agents."""
        with self._get_conn() as conn:
            cursor = conn.execute("""
                SELECT 
                    a.agent_id, 
                    a.parent_id, 
                    a.status as agent_status, 
                    a.last_active_time,
                    ats.task, 
                    ats.status as task_status,
                    ats.updated_on as task_updated_on,
                    ats.assigner_id
                FROM agents a
                LEFT JOIN (
                    SELECT agent_id, task, status, updated_on, assigner_id
                    FROM agent_task_status 
                    WHERE id IN (
                        SELECT MAX(id) 
                        FROM agent_task_status 
                        GROUP BY agent_id
                    )
                ) ats ON a.agent_id = ats.agent_id
                ORDER BY a.last_active_time DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def update_agent(self, agent_id: str, status: str = "live", parent_id: Optional[str] = None):
        with self._get_conn() as conn:
            now = time.time()
            conn.execute("""
                INSERT INTO agents (agent_id, status, parent_id, last_active_time)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    status = excluded.status,
                    parent_id = coalesce(excluded.parent_id, agents.parent_id),
                    last_active_time = excluded.last_active_time
            """, (agent_id, status, parent_id, now))

    def get_agents(self, agent_id: Optional[str] = None) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        with self._get_conn() as conn:
            if agent_id:
                cursor = conn.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,))
                row = cursor.fetchone()
                return dict(row) if row else {}
            else:
                cursor = conn.execute("SELECT * FROM agents ORDER BY last_active_time DESC")
                return [dict(row) for row in cursor.fetchall()]

    def get_my_slaves(self, agent_id: str) -> List[Dict[str, Any]]:
        """Retrieve all live slaves for a given agent from the database."""
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM agents WHERE parent_id = ? AND status = 'live'", (agent_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_my_coworkers(self, agent_id: str) -> List[Dict[str, Any]]:
        """Retrieve all live coworkers (siblings) for a given agent."""
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT parent_id FROM agents WHERE agent_id = ?", (agent_id,))
            row = cursor.fetchone()
            if not row or not row["parent_id"]:
                return []
            parent_id = row["parent_id"]
            cursor = conn.execute("SELECT * FROM agents WHERE parent_id = ? AND status = 'live' AND agent_id != ?", (parent_id, agent_id))
            return [dict(row) for row in cursor.fetchall()]

    def get_live_hierarchy(self) -> Dict[str, Any]:
        """Build a hierarchical map of all currently 'live' agents."""
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT agent_id, parent_id FROM agents WHERE status = 'live'")
            rows = [dict(row) for row in cursor.fetchall()]
            
        children_map = {}
        for row in rows:
            agent_id = row["agent_id"]
            if agent_id not in children_map:
                children_map[agent_id] = []
                
        root_agents = []
        for row in rows:
            agent_id = row["agent_id"]
            parent_id = row["parent_id"]
            
            if parent_id in children_map:
                children_map[parent_id].append(agent_id)
            else:
                root_agents.append(agent_id)
                
        def build_tree(aid: str) -> Dict[str, list]:
            return {aid: [build_tree(child) for child in children_map.get(aid, [])]}
            
        hierarchy = {}
        for root in root_agents:
            hierarchy.update(build_tree(root))
            
        return hierarchy

    def update_agent_task_status(self, agent_id: str, status: str, task: Optional[str] = None, 
                                 assigner_id: Optional[str] = None, row_id: Optional[int] = None,
                                 is_verified: Optional[int] = None, verified_by: Optional[str] = None) -> Optional[int]:
        allowed = ["pending", "inprogress", "completed"]
        if status not in allowed:
            raise ValueError(f"Invalid task status: {status}. Must be one of {allowed}")
            
        with self._get_conn() as conn:
            now = time.time()
            if row_id:
                # Update by primary key
                conn.execute("""
                    UPDATE agent_task_status 
                    SET status = ?, updated_on = ?, 
                        assigner_id = coalesce(?, assigner_id),
                        task = coalesce(?, task),
                        is_verified = coalesce(?, is_verified),
                        verified_by = coalesce(?, verified_by)
                    WHERE id = ?
                """, (status, now, assigner_id, task, is_verified, verified_by, row_id))
                return row_id
            elif task:
                # Upsert based on the (agent_id, task) unique constraint
                cursor = conn.execute("""
                    INSERT INTO agent_task_status (agent_id, original_agent_id, status, task, assigner_id, is_verified, verified_by, assigned_on, updated_on)
                    VALUES (?, ?, ?, ?, coalesce(?, ?), ?, ?, ?, ?)
                    ON CONFLICT(agent_id, task) DO UPDATE SET 
                        status = excluded.status,
                        updated_on = excluded.updated_on,
                        is_verified = coalesce(excluded.is_verified, agent_task_status.is_verified),
                        verified_by = coalesce(excluded.verified_by, agent_task_status.verified_by),
                        assigner_id = coalesce(excluded.assigner_id, agent_task_status.assigner_id)
                    RETURNING id
                """, (agent_id, agent_id, status, task, assigner_id, agent_id, is_verified, verified_by, now, now))
                row = cursor.fetchone()
                return row["id"] if row else None
            else:
                # Cleanup Path: Update all active tasks for this agent
                conn.execute("""
                    UPDATE agent_task_status 
                    SET status = ?, updated_on = ? 
                    WHERE agent_id = ? AND status IN ('pending', 'inprogress')
                """, (status, now, agent_id))
                return None
                
    def get_agent_task_status(self, agent_id: Optional[str] = None, assigner_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve task status records, filtered by agent or assigner."""
        with self._get_conn() as conn:
            if agent_id:
                cursor = conn.execute("SELECT * FROM agent_task_status WHERE agent_id = ?", (agent_id,))
                rows = cursor.fetchall()
                if not rows: return []
                return [dict(r) for r in rows]
            elif assigner_id:
                cursor = conn.execute("SELECT * FROM agent_task_status WHERE assigner_id = ?", (assigner_id,))
                return [dict(r) for r in cursor.fetchall()]
            return []

    def reassign_all_tasks(self, from_id: str, to_id: str):
        """Atomically move all pending/inprogress tasks from one agent to another."""
        with self._get_conn() as conn:
            now = time.time()
            conn.execute("""
                UPDATE agent_task_status 
                SET agent_id = ?, updated_on = ? 
                WHERE agent_id = ? AND status IN ('pending', 'inprogress')
            """, (to_id, now, from_id))

    def reassign_all_slaves(self, old_parent_id: str, new_parent_id: str):
        """Atomically move all direct slaves from one Master to another (Adoption)."""
        with self._get_conn() as conn:
            conn.execute("UPDATE agents SET parent_id = ? WHERE parent_id = ?", (new_parent_id, old_parent_id))

    def get_chat_history(self, agent_a: str, agent_b: Optional[str] = None) -> Union[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """Retrieve full bi-directional chat history."""
        with self._get_conn() as conn:
            if agent_b:
                cursor = conn.execute("""
                    SELECT * FROM messages 
                    WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)
                    ORDER BY sno ASC
                """, (agent_a, agent_b, agent_b, agent_a))
                
                history = []
                for row in cursor.fetchall():
                    msg = dict(row)
                    msg["need_reply"] = bool(msg["need_reply"])
                    msg["is_read"] = bool(msg["is_read"])
                    msg["from"] = msg.pop("from_id")
                    msg["to"] = msg.pop("to_id")
                    try:
                        msg["content"] = json.loads(msg["content"])
                    except: pass
                    history.append(msg)
                return history
            else:
                cursor = conn.execute("""
                    SELECT * FROM messages 
                    WHERE from_id = ? OR to_id = ?
                    ORDER BY sno ASC
                """, (agent_a, agent_a))
                
                grouped = {}
                for row in cursor.fetchall():
                    msg = dict(row)
                    msg["need_reply"] = bool(msg["need_reply"])
                    msg["is_read"] = bool(msg["is_read"])
                    msg["from"] = msg.pop("from_id")
                    msg["to"] = msg.pop("to_id")
                    try:
                        msg["content"] = json.loads(msg["content"])
                    except: pass
                    
                    other_agent = msg["to"] if msg["from"] == agent_a else msg["from"]
                    if other_agent not in grouped:
                        grouped[other_agent] = []
                    grouped[other_agent].append(msg)
                return grouped

    def update_knowledge(self, topic: str, insight: str, agent_id: str, relative_file_path: Optional[str] = None):
        file_mtime = None
        if relative_file_path and os.path.exists(relative_file_path):
            file_mtime = os.path.getmtime(relative_file_path)
            
        with self._get_conn() as conn:
            now = time.time()
            conn.execute("""
                INSERT INTO shared_knowledge (topic, insight, contributor_id, updated_agent_id, relative_file_path, file_mtime, updated_on)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(topic) DO UPDATE SET 
                    insight = excluded.insight,
                    updated_on = excluded.updated_on,
                    updated_agent_id = excluded.updated_agent_id,
                    relative_file_path = coalesce(excluded.relative_file_path, shared_knowledge.relative_file_path),
                    file_mtime = excluded.file_mtime
            """, (topic, insight, agent_id, agent_id, relative_file_path, file_mtime, now))

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
