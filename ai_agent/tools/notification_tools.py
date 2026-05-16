import os
import sys
import subprocess
import platform
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from langchain_core.tools import tool


def _desktop_notify(title: str, message: str) -> str:
    """Send a native desktop notification cross-platform."""
    plat = sys.platform

    if plat == "win32":
        # Use PowerShell toast notification (works on Windows 10+)
        ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.BalloonTipTitle = '{title.replace("'", "''")}'
$notify.BalloonTipText = '{message.replace("'", "''")}'
$notify.Visible = $True
$notify.ShowBalloonTip(5000)
Start-Sleep -Seconds 6
$notify.Dispose()
""".strip()
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return "ok"
        # Fallback: msg command
        subprocess.run(["msg", "*", f"{title}: {message}"], capture_output=True, timeout=5)
        return "ok"

    elif plat == "darwin":
        script = f'display notification "{message}" with title "{title}"'
        result = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
        return "ok" if result.returncode == 0 else result.stderr.decode()

    else:
        # Linux: try notify-send, then zenity
        for cmd in [
            ["notify-send", title, message],
            ["zenity", "--notification", f"--text={title}: {message}"],
        ]:
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=10)
                if result.returncode == 0:
                    return "ok"
            except FileNotFoundError:
                continue
        return "[Error] No desktop notification utility found. Install libnotify-bin (notify-send) on Linux."


@tool
def notify_desktop(title: str, message: str) -> str:
    """Send a native desktop notification to the user's screen.
    Use this to alert the user when a long-running task completes, fails, or needs attention.
    Works on Windows (toast), macOS (notification center), and Linux (notify-send/zenity).
    Args:
        title: The notification title (short, e.g. 'Task Complete').
        message: The notification body text.
    """
    try:
        result = _desktop_notify(title, message)
        if result == "ok":
            return f"[Success] Desktop notification sent: '{title}'"
        return f"[Warning] Notification attempted but may not have displayed: {result}"
    except subprocess.TimeoutExpired:
        return "[Warning] Notification timed out — may still have displayed."
    except Exception as exc:
        return f"[Error] Failed to send desktop notification: {exc}"


@tool
def notify_email(
    to: str,
    subject: str,
    body: str,
    smtp_host: str = "",
    smtp_port: int = 587,
    smtp_user: str = "",
    smtp_password: str = "",
) -> str:
    """Send an email notification via SMTP.
    Credentials can be passed as arguments or read from environment variables:
    NOTIFY_SMTP_HOST, NOTIFY_SMTP_PORT, NOTIFY_SMTP_USER, NOTIFY_SMTP_PASSWORD.
    Args:
        to: Recipient email address (or comma-separated list).
        subject: Email subject line.
        body: Plain-text email body.
        smtp_host: SMTP server hostname (e.g. 'smtp.gmail.com'). Reads NOTIFY_SMTP_HOST if empty.
        smtp_port: SMTP port (default 587 for TLS). Reads NOTIFY_SMTP_PORT if 587.
        smtp_user: SMTP username / sender email. Reads NOTIFY_SMTP_USER if empty.
        smtp_password: SMTP password or app password. Reads NOTIFY_SMTP_PASSWORD if empty.
    """
    # Resolve from env if not provided
    host = smtp_host or os.environ.get("NOTIFY_SMTP_HOST", "")
    port = smtp_port if smtp_port != 587 else int(os.environ.get("NOTIFY_SMTP_PORT", 587))
    user = smtp_user or os.environ.get("NOTIFY_SMTP_USER", "")
    password = smtp_password or os.environ.get("NOTIFY_SMTP_PASSWORD", "")

    if not host:
        return "[Error] SMTP host is required. Pass smtp_host or set NOTIFY_SMTP_HOST env var."
    if not user:
        return "[Error] SMTP user is required. Pass smtp_user or set NOTIFY_SMTP_USER env var."
    if not password:
        return "[Error] SMTP password is required. Pass smtp_password or set NOTIFY_SMTP_PASSWORD env var."

    try:
        recipients = [r.strip() for r in to.split(",") if r.strip()]

        msg = MIMEMultipart()
        msg["From"] = user
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(host, port, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            server.sendmail(user, recipients, msg.as_string())

        return f"[Success] Email sent to {to} via {host}:{port}"
    except smtplib.SMTPAuthenticationError:
        return "[Error] SMTP authentication failed. Check your username and password (use an App Password for Gmail)."
    except smtplib.SMTPConnectError as exc:
        return f"[Error] Could not connect to SMTP server {host}:{port}: {exc}"
    except Exception as exc:
        return f"[Error] Failed to send email: {exc}"


@tool
def notify_sound(sound: str = "default") -> str:
    """Play a system alert sound to audibly notify the user.
    Useful in combination with desktop notifications for important events.
    Args:
        sound: Sound type — 'default', 'error', or 'success' (behavior varies by OS).
    """
    try:
        plat = sys.platform
        if plat == "win32":
            import winsound
            sound_map = {
                "default": winsound.MB_ICONASTERISK,
                "error": winsound.MB_ICONHAND,
                "success": winsound.MB_ICONASTERISK,
            }
            winsound.MessageBeep(sound_map.get(sound, winsound.MB_ICONASTERISK))
            return f"[Success] Played '{sound}' sound on Windows."

        elif plat == "darwin":
            sound_map = {
                "default": "Glass",
                "error": "Basso",
                "success": "Hero",
            }
            afplay_sound = f"/System/Library/Sounds/{sound_map.get(sound, 'Glass')}.aiff"
            subprocess.run(["afplay", afplay_sound], capture_output=True, timeout=5)
            return f"[Success] Played '{sound}' sound on macOS."

        else:
            # Linux: paplay or aplay
            for cmd in [["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
                        ["aplay", "/usr/share/sounds/alsa/Front_Center.wav"]]:
                try:
                    result = subprocess.run(cmd, capture_output=True, timeout=5)
                    if result.returncode == 0:
                        return f"[Success] Played alert sound on Linux."
                except FileNotFoundError:
                    continue
            # Fallback: terminal bell
            print("\a", end="", flush=True)
            return "[Info] Sent terminal bell (no audio player found; install pulseaudio or alsa)."

    except Exception as exc:
        return f"[Error] Failed to play sound: {exc}"
