import json
import os
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

class MessageBus:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.msg_dir = base_dir / "messages"
        self.state_dir = base_dir / "state"
        self.archive_dir = base_dir / "archive"
        self.msg_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def send_message(self, from_id: str, to_id: str, content: Any, msg_type: str = "text"):
        # Ensure message directory exists
        self.msg_dir.mkdir(parents=True, exist_ok=True)
        msg = {
            "timestamp": time.time(),
            "from": from_id,
            "to": to_id,
            "type": msg_type,
            "content": content
        }
        filename = f"msg_{int(time.time()*1000)}_{from_id}_{to_id}.json"
        with open(self.msg_dir / filename, "w") as f:
            json.dump(msg, f)

    def get_messages(self, agent_id: str) -> List[Dict[str, Any]]:
        messages = []
        for file in self.msg_dir.glob(f"*_{agent_id}.json"):
            try:
                with open(file, "r") as f:
                    messages.append(json.load(f))
                # Archive instead of delete
                file.rename(self.archive_dir / file.name)
            except Exception as e:
                print(f"[Comm Error] Failed to read/archive {file.name}: {e}")
        return sorted(messages, key=lambda x: x["timestamp"])

    def update_status(self, agent_id: str, status: str, current_task: Optional[str] = None):
        state = {
            "status": status,
            "current_task": current_task,
            "last_update": time.time()
        }
        with open(self.state_dir / f"{agent_id}_status.json", "w") as f:
            json.dump(state, f)

    def get_agent_status(self, agent_id: str) -> Dict[str, Any]:
        path = self.state_dir / f"{agent_id}_status.json"
        if path.exists():
            with open(path, "r") as f:
                return json.load(f)
        return {"status": "unknown"}

    def get_agent_history(self, agent_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve archived messages for a specific agent (Auditing)."""
        history = []
        # Check messages to/from this agent in the archive
        for file in self.archive_dir.glob(f"*_{agent_id}.json"):
            with open(file, "r") as f:
                history.append(json.load(f))
        for file in self.archive_dir.glob(f"*{agent_id}_*.json"):
            with open(file, "r") as f:
                msg = json.load(f)
                if msg not in history: history.append(msg)
        
        return sorted(history, key=lambda x: x["timestamp"], reverse=True)[:limit]
