import json
import os
import uuid
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Optional, Union, Any
from langchain_core.tools import tool
from .common import _truncate_output


def _http_request(
    url: str,
    method: str = "GET",
    headers: Optional[dict] = None,
    body: Optional[str] = None,
    timeout: int = 30,
) -> dict:
    """Internal helper: perform an HTTP request and return status + body."""
    req = urllib.request.Request(url, method=method.upper())

    # Default headers
    req.add_header("User-Agent", "Mozilla/5.0 AI-Agent/1.0")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)

    data = body.encode("utf-8") if body else None

    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return {
                "status_code": resp.status,
                "headers": dict(resp.headers),
                "body": raw,
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return {
            "status_code": exc.code,
            "headers": dict(exc.headers) if exc.headers else {},
            "body": raw,
            "error": str(exc),
        }
    except Exception as exc:
        return {"status_code": None, "headers": {}, "body": "", "error": str(exc)}


def _build_multipart(fields: dict, file_path: str, file_field: str) -> tuple[bytes, str]:
    """Build a multipart/form-data body from text fields and one file.

    Returns (body_bytes, content_type_header_value).
    Implemented without any third-party library — only stdlib.
    """
    boundary = uuid.uuid4().hex
    ctype = f"multipart/form-data; boundary={boundary}"

    parts = []
    sep = f"--{boundary}\r\n".encode()

    # Text fields
    for name, value in fields.items():
        parts.append(sep)
        parts.append(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        )
        parts.append(f"{value}\r\n".encode())

    # File part
    filename = os.path.basename(file_path)
    # Guess MIME type from extension (basic set; good enough for agents)
    ext = os.path.splitext(filename)[1].lower()
    mime_map = {
        ".json": "application/json",
        ".txt":  "text/plain",
        ".csv":  "text/csv",
        ".html": "text/html",
        ".xml":  "application/xml",
        ".pdf":  "application/pdf",
        ".zip":  "application/zip",
        ".gz":   "application/gzip",
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif":  "image/gif",
        ".webp": "image/webp",
        ".mp4":  "video/mp4",
        ".py":   "text/x-python",
        ".js":   "application/javascript",
    }
    mime = mime_map.get(ext, "application/octet-stream")

    with open(file_path, "rb") as fh:
        file_bytes = fh.read()

    parts.append(sep)
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode()
    )
    parts.append(file_bytes)
    parts.append(b"\r\n")

    # Closing boundary
    parts.append(f"--{boundary}--\r\n".encode())

    return b"".join(parts), ctype


def _format_response(result: dict) -> str:
    status = result["status_code"]
    error = result["error"]
    body = result["body"]

    lines = []
    if status:
        lines.append(f"Status: {status}")
    if error and not status:
        lines.append(f"[Error] {error}")

    # Pretty-print JSON bodies automatically
    if body:
        try:
            parsed = json.loads(body)
            lines.append("Body (JSON):")
            lines.append(json.dumps(parsed, indent=2, ensure_ascii=False))
        except Exception:
            lines.append("Body:")
            lines.append(body)

    return _truncate_output("\n".join(lines))


@tool
def http_get(url: str, headers: Union[str, dict] = "{}") -> str:
    """Perform an HTTP GET request to a URL.
    Use this for reading REST API endpoints, downloading JSON data, or accessing authenticated APIs.
    Args:
        url: The full URL to request (e.g. 'https://api.example.com/users').
        headers: JSON string or dict of additional HTTP headers (e.g. '{"Authorization": "Bearer TOKEN"}').
    """
    if isinstance(headers, str):
        try:
            h = json.loads(headers) if headers.strip() else {}
        except Exception:
            return "[Error] headers must be a valid JSON object string."
    else:
        h = headers or {}
    
    if not isinstance(h, dict):
        return "[Error] headers must be a dictionary or a JSON object string."

    result = _http_request(url, method="GET", headers=h)
    return _format_response(result)


@tool
def http_post(url: str, body: Any = "{}", headers: Union[str, dict] = "{}") -> str:
    """Perform an HTTP POST request with a JSON body.
    Use this to create resources, submit forms, or call REST APIs that require a request body.
    Args:
        url: The full URL to POST to.
        body: JSON string or dict of the request body (e.g. '{"name": "Alice"}').
        headers: JSON string or dict of additional HTTP headers. Content-Type is set to application/json automatically.
    """
    if isinstance(headers, str):
        try:
            h = json.loads(headers) if headers.strip() else {}
        except Exception as exc:
            return f"[Error] Invalid JSON in headers: {exc}"
    else:
        h = headers or {}

    if not isinstance(h, dict):
        return "[Error] headers must be a dictionary or a JSON object string."

    # Process body
    if isinstance(body, (dict, list)):
        b_str = json.dumps(body)
    elif isinstance(body, str):
        # Validate it's JSON if it's a string, or just use it
        try:
            json.loads(body)
            b_str = body
        except Exception:
            # Not valid JSON, but maybe it's just raw text? 
            # For http_post we usually expect JSON, but let's be flexible.
            b_str = body
    else:
        b_str = str(body)

    h.setdefault("Content-Type", "application/json")
    result = _http_request(url, method="POST", headers=h, body=b_str)
    return _format_response(result)


@tool
def http_put(url: str, body: Any = "{}", headers: Union[str, dict] = "{}") -> str:
    """Perform an HTTP PUT request to update a resource.
    Use this to replace an existing resource via a REST API.
    Args:
        url: The full URL of the resource to update.
        body: JSON string or dict of the updated resource data.
        headers: JSON string or dict of additional HTTP headers.
    """
    if isinstance(headers, str):
        try:
            h = json.loads(headers) if headers.strip() else {}
        except Exception as exc:
            return f"[Error] Invalid JSON in headers: {exc}"
    else:
        h = headers or {}

    if not isinstance(h, dict):
        return "[Error] headers must be a dictionary or a JSON object string."

    if isinstance(body, (dict, list)):
        b_str = json.dumps(body)
    elif isinstance(body, str):
        b_str = body
    else:
        b_str = str(body)

    h.setdefault("Content-Type", "application/json")
    result = _http_request(url, method="PUT", headers=h, body=b_str)
    return _format_response(result)


@tool
def http_patch(url: str, body: Any = "{}", headers: Union[str, dict] = "{}") -> str:
    """Perform an HTTP PATCH request to partially update a resource.
    Use this when you only need to update specific fields of an existing resource.
    Args:
        url: The full URL of the resource to patch.
        body: JSON string or dict with only the fields to update.
        headers: JSON string or dict of additional HTTP headers.
    """
    if isinstance(headers, str):
        try:
            h = json.loads(headers) if headers.strip() else {}
        except Exception as exc:
            return f"[Error] Invalid JSON in headers: {exc}"
    else:
        h = headers or {}

    if not isinstance(h, dict):
        return "[Error] headers must be a dictionary or a JSON object string."

    if isinstance(body, (dict, list)):
        b_str = json.dumps(body)
    elif isinstance(body, str):
        b_str = body
    else:
        b_str = str(body)

    h.setdefault("Content-Type", "application/json")
    result = _http_request(url, method="PATCH", headers=h, body=b_str)
    return _format_response(result)


@tool
def http_delete(url: str, headers: Union[str, dict] = "{}") -> str:
    """Perform an HTTP DELETE request to remove a resource.
    Use this to delete resources via REST APIs.
    Args:
        url: The full URL of the resource to delete.
        headers: JSON string or dict of additional HTTP headers (e.g. auth token).
    """
    if isinstance(headers, str):
        try:
            h = json.loads(headers) if headers.strip() else {}
        except Exception:
            return "[Error] headers must be a valid JSON object string."
    else:
        h = headers or {}

    if not isinstance(h, dict):
        return "[Error] headers must be a dictionary or a JSON object string."

    result = _http_request(url, method="DELETE", headers=h)
    return _format_response(result)


@tool
def http_request(url: str, method: str = "GET", body: Any = "", headers: Union[str, dict] = "{}") -> str:
    """Perform a fully custom HTTP request with any method, body, and headers.
    Use this as a catch-all when the specific http_get/post/put/patch/delete tools don't fit.
    Args:
        url: The full URL to request.
        method: HTTP method — GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS, etc.
        body: Raw request body string, dict, or list (can be JSON, form data, or empty).
        headers: JSON string or dict of HTTP headers to include.
    """
    if isinstance(headers, str):
        try:
            h = json.loads(headers) if headers.strip() else {}
        except Exception:
            return "[Error] headers must be a valid JSON object string."
    else:
        h = headers or {}

    if not isinstance(h, dict):
        return "[Error] headers must be a dictionary or a JSON object string."

    if isinstance(body, (dict, list)):
        b_str = json.dumps(body)
    elif isinstance(body, str):
        b_str = body
    else:
        b_str = str(body) if body is not None else None

    result = _http_request(url, method=method.upper(), headers=h, body=b_str)
    return _format_response(result)


@tool
def http_upload(
    url: str,
    file_path: str,
    file_field: str = "file",
    fields: str = "{}",
    headers: str = "{}",
    timeout: int = 120,
) -> str:
    """Upload a local file to a remote URL as multipart/form-data (like a browser file upload).
    Use this to send files to REST APIs, upload attachments, submit forms with file inputs,
    or push build artifacts to a remote service.

    The Content-Type header (including the multipart boundary) is set automatically —
    do NOT include it in the headers argument.

    Args:
        url: The full URL to upload to.
        file_path: Local path of the file to upload (absolute or relative to AGENT_WORKDIR).
        file_field: The form field name the server expects for the file (default: 'file').
                    Check the API docs — common values are 'file', 'upload', 'attachment'.
        fields: JSON string of extra text form fields to include alongside the file
                (e.g. '{"description": "report", "tag": "v1.0"}').
        headers: JSON string of extra HTTP headers (e.g. '{"Authorization": "Bearer TOKEN"}').
                 Do NOT include Content-Type here — it is set automatically.
        timeout: Seconds to wait for the upload to complete (default 120).
                 Increase for large files on slow connections.

    Example — upload to a generic file API with an auth token:
        http_upload(
            url="https://api.example.com/files",
            file_path="report.pdf",
            file_field="file",
            fields='{"project": "mars", "version": "2"}',
            headers='{"Authorization": "Bearer abc123"}',
        )
    """
    # Resolve path relative to AGENT_WORKDIR if not absolute
    if not os.path.isabs(file_path):
        work_dir = os.environ.get("AGENT_WORKDIR", ".")
        file_path = os.path.join(work_dir, file_path)

    if not os.path.exists(file_path):
        return f"[Error] File not found: {file_path}"
    if not os.path.isfile(file_path):
        return f"[Error] Path is not a file: {file_path}"

    try:
        extra_headers = json.loads(headers) if headers.strip() else {}
    except Exception:
        return "[Error] headers must be a valid JSON object string."

    try:
        extra_fields = json.loads(fields) if fields.strip() else {}
        if not isinstance(extra_fields, dict):
            return "[Error] fields must be a JSON object (key-value pairs)."
    except Exception:
        return "[Error] fields must be a valid JSON object string."

    try:
        body_bytes, content_type = _build_multipart(extra_fields, file_path, file_field)
    except Exception as exc:
        return f"[Error] Failed to build multipart body: {exc}"

    # Build and send the request manually (urllib doesn't support multipart natively)
    req = urllib.request.Request(url, method="POST")
    req.add_header("User-Agent", "Mozilla/5.0 AI-Agent/1.0")
    req.add_header("Content-Type", content_type)
    req.add_header("Content-Length", str(len(body_bytes)))
    for k, v in extra_headers.items():
        req.add_header(k, v)

    file_size_kb = os.path.getsize(file_path) / 1024
    try:
        with urllib.request.urlopen(req, data=body_bytes, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            result = {
                "status_code": resp.status,
                "headers": dict(resp.headers),
                "body": raw,
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        result = {
            "status_code": exc.code,
            "headers": dict(exc.headers) if exc.headers else {},
            "body": raw,
            "error": str(exc),
        }
    except Exception as exc:
        return f"[Error] Upload failed: {exc}"

    status = result["status_code"]
    lines = [
        f"[Upload] {os.path.basename(file_path)} ({file_size_kb:.1f} KB) → {url}",
        f"Status: {status}",
    ]
    if result["body"]:
        try:
            parsed = json.loads(result["body"])
            lines.append("Response (JSON):")
            lines.append(json.dumps(parsed, indent=2, ensure_ascii=False))
        except Exception:
            lines.append("Response:")
            lines.append(result["body"])

    if status and status >= 400:
        lines.insert(1, f"[Error] Server returned {status}")

    return _truncate_output("\n".join(lines))


@tool
def http_download(url: str, dest_path: str, headers: str = "{}",
                  timeout: int = 300, overwrite: bool = False) -> str:
    """Download a file from a URL and save it to disk using streaming.
    Unlike fetch_url, this never loads the file into memory — it streams directly
    to disk, so it works for files of any size (models, datasets, ZIPs, binaries).
    Args:
        url: The full URL to download from.
        dest_path: Local path where the file will be saved. Parent directories are
                   created automatically. If a filename is not included (path ends
                   with a directory separator), the filename is inferred from the URL.
        headers: JSON string of extra HTTP headers, e.g. '{"Authorization": "Bearer TOKEN"}'.
        timeout: Seconds to wait for the connection and each chunk (default 300).
        overwrite: If False (default), refuses to overwrite an existing file.
                   Set to True to replace it.
    """
    try:
        h = json.loads(headers) if headers.strip() else {}
    except Exception:
        return "[Error] headers must be a valid JSON object string."

    try:
        dest = Path(dest_path)
        # If dest looks like a directory (ends with sep or exists as dir), infer filename
        if dest_path.endswith(("/", "\\")) or dest.is_dir():
            filename = url.rstrip("/").split("/")[-1].split("?")[0] or "download"
            dest = dest / filename

        if dest.exists() and not overwrite:
            return (
                f"[Error] File already exists: {dest}\n"
                f"Pass overwrite=True to replace it."
            )

        dest.parent.mkdir(parents=True, exist_ok=True)

        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0 AI-Agent/1.0")
        for k, v in h.items():
            req.add_header(k, v)

        chunk_size = 1024 * 1024  # 1 MB chunks
        bytes_written = 0

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = resp.headers.get("Content-Length")
            total_mb = f"{int(total)/1024/1024:.1f} MB" if total else "unknown size"
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    bytes_written += len(chunk)

        downloaded_mb = bytes_written / 1024 / 1024
        return (
            f"OK — downloaded to {dest}\n"
            f"Size: {downloaded_mb:.2f} MB (expected: {total_mb})"
        )

    except urllib.error.HTTPError as exc:
        return f"[Error] HTTP {exc.code}: {exc.reason} — {url}"
    except urllib.error.URLError as exc:
        return f"[Error] URL error: {exc.reason}"
    except Exception as exc:
        return f"[Error] http_download failed: {exc}"
