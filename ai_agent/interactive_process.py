import subprocess
import threading
import queue
import uuid
import time
from typing import Dict, Optional

class InteractiveProcess:
    def __init__(self, command: str):
        self.command = command
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=True,
            bufsize=1,
            universal_newlines=True
        )
        self.full_log = []
        self.id = str(uuid.uuid4())[:8]
        self.lock = threading.Lock()
        
        # Thread to read output without blocking (ALWAYS UPDATING IN BACKGROUND)
        self.reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self.reader_thread.start()

    def _read_output(self):
        """Continuously captures process output even if the agent is busy or idle."""
        try:
            # Read until stdout is closed (process finished)
            for line in self.process.stdout:
                clean_line = line.strip()
                if clean_line:
                    with self.lock:
                        self.full_log.append(f"[OUTPUT] {line}")
        except Exception as e:
            with self.lock:
                self.full_log.append(f"[ERROR] Reader thread encountered an issue: {str(e)}\n")
        finally:
            # Check exit code when process finishes
            exit_code = self.process.wait()
            with self.lock:
                if exit_code != 0:
                    self.full_log.append(f"[CRASH] Process terminated unexpectedly with exit code {exit_code}.\n")
                else:
                    self.full_log.append(f"[TERMINATED] Process finished successfully (Exit Code 0).\n")

    def get_full_log(self):
        with self.lock:
            return "".join(self.full_log)

    def send_input(self, text: str):
        if self.process.poll() is None:
            with self.lock:
                self.full_log.append(f"[INPUT] {text}\n")
            self.process.stdin.write(text + "\n")
            self.process.stdin.flush()
            return True
        return False

    def terminate(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except:
            self.process.kill()

# Registry to keep track of active processes across tool calls
ACTIVE_PROCESSES: Dict[str, InteractiveProcess] = {}
