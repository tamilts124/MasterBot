import socket
import time
import subprocess
import os
from pathlib import Path
from typing import Dict, Optional

class TorManager:
    def __init__(self, base_socks_port: int = 9050, base_control_port: int = 9051):
        self.base_socks_port = base_socks_port
        self.base_control_port = base_control_port
        self.agent_ports: Dict[str, int] = {} # agent_id -> socks_port

    def is_port_open(self, port: int) -> bool:
        """Check if a port is listening on localhost."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(("127.0.0.1", port)) == 0

    def get_proxy_for_agent(self, agent_id: str, level: int, index: int) -> str:
        """Assign a unique Tor port. Reuse if active, launch and WAIT if silent."""
        port = self.base_socks_port + (level * 20) + (index * 5)
        control = port + 1
        
        if self.is_port_open(port):
            print(f"[Tor] Port {port} is ALREADY ACTIVE. Reusing instance for {agent_id}.")
        else:
            self.start_tor_instance(port, control)
            # Physical Wait: Do not return until the port is actually open
            print(f"[Tor] Waiting for instance on {port} to wake up...")
            for _ in range(30): # Up to 30 seconds
                if self.is_port_open(port):
                    print(f"[Tor] Instance on {port} is now READY.")
                    break
                time.sleep(1)
            
        self.agent_ports[agent_id] = port
        return f"socks5://127.0.0.1:{port}"

    def start_tor_instance(self, socks_port: int, control_port: int):
        """Spawn a new background Tor process."""
        data_dir = os.path.abspath(f"tor_data_{socks_port}")
        os.makedirs(data_dir, exist_ok=True)
        
        torrc_path = os.path.join(data_dir, "torrc")
        with open(torrc_path, "w") as f:
            f.write(f"SocksPort {socks_port}\n")
            f.write(f"ControlPort {control_port}\n")
            f.write(f"DataDirectory {data_dir}\n")
            f.write("AvoidDiskWrites 1\n")
            f.write("FetchUselessDescriptors 0\n")
            f.write("__DisableCookieAuthentication 1\n")
        
        cmd = ["tor", "-f", torrc_path]
        try:
            # Launch in background
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[Tor] Launched background instance on {socks_port}")
        except Exception as e:
            print(f"[Error] Could not launch Tor on {socks_port}: {e}")

    def rotate_ip(self, agent_id: str):
        """Signal NEWNYM for the squad."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect(("127.0.0.1", self.base_control_port))
                s.sendall(b'AUTHENTICATE ""\r\n')
                s.sendall(b'SIGNAL NEWNYM\r\n')
                s.sendall(b'QUIT\r\n')
            print(f"[Tor] IP Rotated.")
        except: pass

def setup_agent_env(proxy_url: str) -> Dict[str, str]:
    """Prepare environment variables for an agent process."""
    env = os.environ.copy()
    env["HTTP_PROXY"] = proxy_url
    env["HTTPS_PROXY"] = proxy_url
    return env
