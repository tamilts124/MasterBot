import json
import os
from typing import Any, Dict, List, Optional
from pathlib import Path

DEFAULT_MODEL = "gemma4:31b-cloud"
DEFAULT_API_URL = "https://ollama.com"

class AgentConfig:
    def __init__(self, data: Dict[str, Any], parent_id: Optional[str] = None, level: int = 0):
        self.id = data.get("id", f"agent_{os.urandom(2).hex()}")
        self.model = data.get("model", DEFAULT_MODEL)
        self.api_url = data.get("api_url", DEFAULT_API_URL)
        raw_key = data.get("api_key", "")
        self.api_keys = [k.strip() for k in raw_key.split(",")] if "," in raw_key else [raw_key]
        self.api_key = self.api_keys[0] if self.api_keys else None
        
        config = data.get("config", {})
        self.communicate_same_level = config.get("communicate_same_level_agents", True)
        self.communicate_anyone = config.get("communicate_anyone", False)
        self.can_coding = config.get("can_coding", False)
        
        self.parent_id = parent_id
        self.level = level
        
        self.slaves: List['AgentConfig'] = []
        for slave_data in data.get("slaves", []):
            self.slaves.append(AgentConfig(slave_data, parent_id=self.id, level=level + 1))
            
        # [Rule] If no slaves, this agent MUST be able to code.
        if not self.slaves:
            self.can_coding = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "model": self.model,
            "api_url": self.api_url,
            "api_key": self.api_key,
            "config": {
                "communicate_same_level_agents": self.communicate_same_level,
                "communicate_anyone": self.communicate_anyone,
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
        "id": "root_master",
        "model": DEFAULT_MODEL,
        "api_url": DEFAULT_API_URL,
        "api_key": "YOUR_MASTER_KEY",
        "config": {
            "communicate_same_level_agents": True,
            "can_coding": True
        },
        "slaves": [
            {
                "id": "master_1",
                "api_key": "KEY_1",
                "slaves": [
                    {"id": "slave_1_1", "api_key": "KEY_1_1", "config": {"can_coding": True}},
                    {"id": "slave_1_2", "api_key": "KEY_1_2", "config": {"can_coding": True}}
                ]
            },
            {
                "id": "master_2",
                "api_key": "KEY_2",
                "slaves": [
                    {"id": "slave_2_1", "api_key": "KEY_2_1", "config": {"can_coding": True}},
                    {"id": "slave_2_2", "api_key": "KEY_2_2", "config": {"can_coding": True}}
                ]
            }
        ]
    }
    return json.dumps(template, indent=2)

if __name__ == "__main__":
    # Test generation
    print(generate_template())
