from ai_agent.mas.communication import MessageBus
import json
import os
import re
from typing import Any, Dict, List, Optional
from pathlib import Path

DEFAULT_MODEL = "qwen3-coder:480b-cloud"
DEFAULT_API_URL = "https://ollama.com"

class AgentConfig:
    def __init__(self, data: Dict[str, Any], parent_id: Optional[str] = None, level: int = 0):
        self.id = data.get("id", f"agent{os.urandom(2).hex()}")
        if not re.match(r"^[a-zA-Z0-9]+$", self.id):
            raise ValueError(f"Agent ID '{self.id}' contains invalid characters. Only alphanumeric characters (a-zA-Z0-9) are allowed.")
        self.model = data.get("model", DEFAULT_MODEL)
        self.api_url = data.get("api_url", DEFAULT_API_URL)
        raw_key = data.get("api_key", "")
        self.api_keys = [k.strip() for k in raw_key.split(",")] if "," in raw_key else [raw_key]
        self.api_key = self.api_keys[0] if self.api_keys else None
        
        config = data.get("config", {})
        self.can_coding = config.get("can_coding", False)
        
        self.parent_id = parent_id
        self.level = level
        
        self.slaves: List['AgentConfig'] = []
        for slave_data in data.get("slaves", []):
            self.slaves.append(AgentConfig(slave_data, parent_id=self.id, level=level + 1))
            
        # [Rule] If no slaves, this agent MUST be able to code.
        if not self.slaves:
            self.can_coding = True

    def register_in_db(self, bus: MessageBus):
        bus.update_agent(self.id, status="live", parent_id=self.parent_id)
        for slave in self.slaves:
            slave.register_in_db(bus)

    def get_all_identities(self, index: int = 0) -> List[tuple]:
        ids = [(self.level, index)]
        for i, slave in enumerate(self.slaves):
            ids.extend(slave.get_all_identities(i))
        return ids

    def get_hierarchy_map(self) -> Dict[str, List[Any]]:
        return {self.id: [slave.get_hierarchy_map() for slave in self.slaves]}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "model": self.model,
            "api_url": self.api_url,
            "api_key": self.api_key,
            "config": {
                "can_coding": self.can_coding
            },
            "slaves": [s.to_dict() for s in self.slaves]
        }

def load_config(path: str) -> AgentConfig:
    try:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Config file not found at {os.path.abspath(path)}")
        with open(path, 'r') as f:
            data = json.load(f)
        return AgentConfig(data)
    except Exception as e:
        print(f"[Error] Failed to load config from {path}: {e}")
        raise e

def generate_template() -> str:
    template = {
        "id": "rootMaster",
        "model": DEFAULT_MODEL,
        "api_url": DEFAULT_API_URL,
        "api_key": "YOUR_MASTER_KEY",
        "config": {
            "can_coding": True
        },
        "slaves": [
            {
                "id": "master1",
                "api_key": "KEY_1",
                "slaves": [
                    {"id": "slave11", "api_key": "KEY_1_1", "config": {"can_coding": True}},
                    {"id": "slave12", "api_key": "KEY_1_2", "config": {"can_coding": True}}
                ]
            },
            {
                "id": "master2",
                "api_key": "KEY_2",
                "slaves": [
                    {"id": "slave21", "api_key": "KEY_2_1", "config": {"can_coding": True}},
                    {"id": "slave22", "api_key": "KEY_2_2", "config": {"can_coding": True}}
                ]
            }
        ]
    }
    return json.dumps(template, indent=2)

if __name__ == "__main__":
    # Test generation
    print(generate_template())
