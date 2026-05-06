import time
from typing import Optional, List, Dict, Any
from Infinitydatabase import Infinitydatabase

class DatabaseManager:
    def __init__(self, admin_url: str):
        self.db = Infinitydatabase(admin_url)
        self._init_db()

    def _init_db(self):
        # Create Tables using the scraper
        tables = [
            "CREATE TABLE IF NOT EXISTS agent_uptime (agent_id VARCHAR(100) PRIMARY KEY, parent_id VARCHAR(100), level INT, start_time DOUBLE, last_heartbeat DOUBLE, status VARCHAR(50), uptime_seconds DOUBLE)",
            "CREATE TABLE IF NOT EXISTS tasks (task_id VARCHAR(100) PRIMARY KEY, assigned_to VARCHAR(100), status VARCHAR(50), description TEXT, achievements TEXT, progress_summary TEXT, last_updated DOUBLE, history_json_path TEXT)"
        ]
        
        for table_sql in tables:
            self.db.query(table_sql)

    def update_agent_status(self, agent_id: str, parent_id: str, level: int, status: str):
        now = time.time()
        # Note: Infinitydatabase uses MySQL syntax. Using REPLACE INTO for simplicity if ON DUPLICATE KEY is complex for scraping
        sql = f"""
        REPLACE INTO agent_uptime (agent_id, parent_id, level, start_time, last_heartbeat, status, uptime_seconds)
        VALUES ('{agent_id}', '{parent_id}', {level}, {now}, {now}, '{status}', 0)
        """
        self.db.query(sql)

    def update_task(self, task_id: str, assigned_to: str, status: str, 
                    description: str = "", achievements: str = "", 
                    progress_summary: str = "", history_path: str = ""):
        now = time.time()
        sql = f"""
        REPLACE INTO tasks (task_id, assigned_to, status, description, achievements, progress_summary, last_updated, history_json_path)
        VALUES ('{task_id}', '{assigned_to}', '{status}', '{description}', '{achievements}', '{progress_summary}', {now}, '{history_path}')
        """
        self.db.query(sql)

    def get_stale_agents(self, timeout_seconds: int = 60) -> List[str]:
        now = time.time()
        sql = f"SELECT agent_id FROM agent_uptime WHERE {now} - last_heartbeat > {timeout_seconds} AND status != 'offline'"
        result = self.db.query(sql)
        if result and isinstance(result, dict):
            return [row[0] for row in result.get('row', [])]
        return []
