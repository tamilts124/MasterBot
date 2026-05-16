import os
import io
import time
import socket
from typing import Optional
from langchain_core.tools import tool
from .common import _truncate_output


def _check_paramiko() -> bool:
    try:
        import paramiko  # noqa
        return True
    except ImportError:
        return False


def _get_client(
    host: str,
    port: int,
    username: str,
    password: Optional[str],
    key_path: Optional[str],
    key_passphrase: Optional[str],
    timeout: int,
):
    """Create and return a connected paramiko SSHClient."""
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs = dict(
        hostname=host,
        port=port,
        username=username,
        timeout=timeout,
        allow_agent=True,
        look_for_keys=True,
    )

    if key_path:
        key_path_expanded = os.path.expanduser(key_path)
        pkey = paramiko.RSAKey.from_private_key_file(
            key_path_expanded,
            password=key_passphrase or None
        )
        connect_kwargs["pkey"] = pkey
    elif password:
        connect_kwargs["password"] = password

    client.connect(**connect_kwargs)
    return client


def _resolve_creds(
    host: str,
    username: str,
    password: Optional[str],
    key_path: Optional[str],
) -> tuple[str, str, Optional[str], Optional[str]]:
    """Merge explicit args with SSH_* env vars, explicit args win."""
    host = host or os.environ.get("SSH_HOST", "")
    username = username or os.environ.get("SSH_USER", os.environ.get("USER", ""))
    password = password or os.environ.get("SSH_PASSWORD") or None
    key_path = key_path or os.environ.get("SSH_KEY_PATH") or None
    return host, username, password, key_path


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@tool
def ssh_run(
    command: str,
    host: str = "",
    username: str = "",
    password: str = "",
    key_path: str = "",
    port: int = 22,
    timeout: int = 60,
    key_passphrase: str = "",
) -> str:
    """Run a shell command on a remote server via SSH and return its output.
    Credentials can be passed as arguments or set via env vars:
    SSH_HOST, SSH_USER, SSH_PASSWORD, SSH_KEY_PATH.
    Args:
        command: The shell command to run on the remote host.
        host: Remote hostname or IP. Reads SSH_HOST if empty.
        username: SSH username. Reads SSH_USER if empty.
        password: SSH password (leave empty if using a key). Reads SSH_PASSWORD if empty.
        key_path: Path to private key file (e.g. '~/.ssh/id_rsa'). Reads SSH_KEY_PATH if empty.
        port: SSH port (default 22).
        timeout: Connection + command timeout in seconds (default 60).
        key_passphrase: Passphrase for encrypted private keys (if needed).
    """
    if not _check_paramiko():
        return "[Error] paramiko is not installed. Run: pip install paramiko"

    host, username, password, key_path = _resolve_creds(host, username, password, key_path)
    if not host:
        return "[Error] host is required. Pass it or set SSH_HOST env var."
    if not username:
        return "[Error] username is required. Pass it or set SSH_USER env var."

    try:
        client = _get_client(host, port, username,
                             password or None, key_path or None,
                             key_passphrase or None, timeout)
        try:
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            combined = (out + err).strip()
            status = "✅" if exit_code == 0 else f"❌ (exit {exit_code})"
            header = f"[SSH {username}@{host}:{port}] {status}\n$ {command}\n"
            return _truncate_output(header + (combined or "[No output]"))
        finally:
            client.close()
    except Exception as exc:
        return f"[Error] SSH connection to {host}:{port} failed: {exc}"


@tool
def ssh_upload(
    local_path: str,
    remote_path: str,
    host: str = "",
    username: str = "",
    password: str = "",
    key_path: str = "",
    port: int = 22,
    key_passphrase: str = "",
) -> str:
    """Upload a local file to a remote server via SFTP (SSH file transfer).
    Use this to deploy build artifacts, config files, or scripts to a server.
    Args:
        local_path: Path to the local file to upload.
        remote_path: Destination path on the remote server (e.g. '/var/www/app/deploy.sh').
        host: Remote hostname or IP. Reads SSH_HOST if empty.
        username: SSH username. Reads SSH_USER if empty.
        password: SSH password. Reads SSH_PASSWORD if empty.
        key_path: Path to private key. Reads SSH_KEY_PATH if empty.
        port: SSH port (default 22).
        key_passphrase: Passphrase for encrypted key (if needed).
    """
    if not _check_paramiko():
        return "[Error] paramiko is not installed. Run: pip install paramiko"

    import os as _os
    host, username, password, key_path = _resolve_creds(host, username, password, key_path)
    if not host:
        return "[Error] host is required."

    local = _os.path.expanduser(local_path)
    if not _os.path.exists(local):
        return f"[Error] Local file not found: {local_path}"

    try:
        client = _get_client(host, port, username,
                             password or None, key_path or None,
                             key_passphrase or None, timeout=30)
        try:
            sftp = client.open_sftp()
            sftp.put(local, remote_path)
            sftp.close()
            size = _os.path.getsize(local)
            return f"[Success] Uploaded {local_path} → {username}@{host}:{remote_path} ({size:,} bytes)"
        finally:
            client.close()
    except Exception as exc:
        return f"[Error] SFTP upload failed: {exc}"


@tool
def ssh_download(
    remote_path: str,
    local_path: str,
    host: str = "",
    username: str = "",
    password: str = "",
    key_path: str = "",
    port: int = 22,
    key_passphrase: str = "",
) -> str:
    """Download a file from a remote server to the local machine via SFTP.
    Use this to retrieve logs, outputs, or data from a deployed server.
    Args:
        remote_path: Path of the file on the remote server.
        local_path: Where to save it locally.
        host: Remote hostname or IP. Reads SSH_HOST if empty.
        username: SSH username. Reads SSH_USER if empty.
        password: SSH password. Reads SSH_PASSWORD if empty.
        key_path: Path to private key. Reads SSH_KEY_PATH if empty.
        port: SSH port (default 22).
        key_passphrase: Passphrase for encrypted key (if needed).
    """
    if not _check_paramiko():
        return "[Error] paramiko is not installed. Run: pip install paramiko"

    import os as _os
    host, username, password, key_path = _resolve_creds(host, username, password, key_path)
    if not host:
        return "[Error] host is required."

    try:
        client = _get_client(host, port, username,
                             password or None, key_path or None,
                             key_passphrase or None, timeout=30)
        try:
            sftp = client.open_sftp()
            local_expanded = _os.path.expanduser(local_path)
            sftp.get(remote_path, local_expanded)
            sftp.close()
            size = _os.path.getsize(local_expanded)
            return f"[Success] Downloaded {username}@{host}:{remote_path} → {local_path} ({size:,} bytes)"
        finally:
            client.close()
    except Exception as exc:
        return f"[Error] SFTP download failed: {exc}"


@tool
def ssh_run_script(
    script: str,
    host: str = "",
    username: str = "",
    password: str = "",
    key_path: str = "",
    port: int = 22,
    timeout: int = 300,
    key_passphrase: str = "",
) -> str:
    """Upload and execute a multi-line shell script on a remote server via SSH.
    Use this for deployment sequences, server setup, or any multi-step remote operation.
    The script runs as a bash script on the remote machine.
    Args:
        script: The full multi-line bash script to run remotely.
        host: Remote hostname or IP. Reads SSH_HOST if empty.
        username: SSH username. Reads SSH_USER if empty.
        password: SSH password. Reads SSH_PASSWORD if empty.
        key_path: Path to private key. Reads SSH_KEY_PATH if empty.
        port: SSH port (default 22).
        timeout: Max seconds to wait for the script to complete (default 300).
        key_passphrase: Passphrase for encrypted key (if needed).
    """
    if not _check_paramiko():
        return "[Error] paramiko is not installed. Run: pip install paramiko"

    host, username, password, key_path = _resolve_creds(host, username, password, key_path)
    if not host:
        return "[Error] host is required."

    # Upload script via stdin and run it
    wrapped = f"bash -s << 'AGENT_EOF'\n{script}\nAGENT_EOF"
    return ssh_run.invoke({
        "command": wrapped,
        "host": host,
        "username": username,
        "password": password or "",
        "key_path": key_path or "",
        "port": port,
        "timeout": timeout,
        "key_passphrase": key_passphrase or "",
    })


@tool
def ssh_check_port(host: str, port: int = 22, timeout: int = 5) -> str:
    """Check if a TCP port is open on a remote host (no credentials needed).
    Use this before attempting SSH connections to verify the server is reachable.
    Args:
        host: Hostname or IP to probe.
        port: Port number to check (default 22 for SSH).
        timeout: Seconds to wait (default 5).
    """
    try:
        start = time.time()
        with socket.create_connection((host, port), timeout=timeout):
            elapsed = (time.time() - start) * 1000
            return f"[Open] {host}:{port} is reachable ({elapsed:.0f}ms)"
    except socket.timeout:
        return f"[Closed/Filtered] {host}:{port} — connection timed out after {timeout}s"
    except ConnectionRefusedError:
        return f"[Closed] {host}:{port} — connection refused"
    except Exception as exc:
        return f"[Error] Could not probe {host}:{port}: {exc}"
