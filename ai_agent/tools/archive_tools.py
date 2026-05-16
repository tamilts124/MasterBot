import os
import subprocess
import zipfile
import tarfile
import shutil
from pathlib import Path
from langchain_core.tools import tool
from .common import _truncate_output


@tool
def archive_create(output_path: str, source_paths: str, format: str = "zip") -> str:
    """Create a zip or tar.gz archive from one or more files or directories.
    Args:
        output_path: Path for the output archive file (e.g. 'dist/output.zip').
        source_paths: Comma-separated list of files or directories to include.
        format: Archive format — 'zip' (default) or 'tar.gz'.
    """
    try:
        sources = [Path(p.strip()).expanduser().resolve() for p in source_paths.split(",")]
        out = Path(output_path).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

        missing = [str(s) for s in sources if not s.exists()]
        if missing:
            return f"[Error] Sources not found: {', '.join(missing)}"

        if format == "zip":
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
                for src in sources:
                    if src.is_dir():
                        for file in src.rglob("*"):
                            if file.is_file():
                                zf.write(file, file.relative_to(src.parent))
                    else:
                        zf.write(src, src.name)
            size = out.stat().st_size
            return f"[Success] Created zip archive: {out} ({size:,} bytes)"

        elif format in ("tar.gz", "tgz"):
            with tarfile.open(str(out), "w:gz") as tf:
                for src in sources:
                    tf.add(str(src), arcname=src.name)
            size = out.stat().st_size
            return f"[Success] Created tar.gz archive: {out} ({size:,} bytes)"

        else:
            return f"[Error] Unsupported format '{format}'. Use 'zip' or 'tar.gz'."

    except Exception as exc:
        return f"[Error] Failed to create archive: {exc}"


@tool
def archive_extract(archive_path: str, output_dir: str = "") -> str:
    """Extract a zip or tar.gz archive to a directory.
    Args:
        archive_path: Path to the archive file to extract.
        output_dir: Directory to extract into. Defaults to same directory as the archive.
    """
    try:
        src = Path(archive_path).expanduser().resolve()
        if not src.exists():
            return f"[Error] Archive not found: {archive_path}"

        dest = Path(output_dir).expanduser().resolve() if output_dir else src.parent
        dest.mkdir(parents=True, exist_ok=True)

        name = src.name.lower()
        if name.endswith(".zip"):
            with zipfile.ZipFile(src, "r") as zf:
                zf.extractall(dest)
                members = zf.namelist()
        elif name.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar")):
            with tarfile.open(str(src)) as tf:
                tf.extractall(dest)
                members = tf.getnames()
        else:
            # Try 7z as fallback if installed
            result = subprocess.run(
                ["7z", "x", str(src), f"-o{dest}", "-y"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                return _truncate_output(f"[Success] Extracted via 7z to: {dest}\n{result.stdout}")
            return f"[Error] Unsupported archive format: {src.suffix}. Install 7z or use zip/tar.gz."

        preview = "\n".join(members[:30])
        suffix = f"\n...and {len(members) - 30} more" if len(members) > 30 else ""
        return f"[Success] Extracted {len(members)} items to: {dest}\n{preview}{suffix}"

    except Exception as exc:
        return f"[Error] Failed to extract archive: {exc}"


@tool
def archive_list(archive_path: str) -> str:
    """List the contents of a zip or tar.gz archive without extracting it.
    Args:
        archive_path: Path to the archive file to inspect.
    """
    try:
        src = Path(archive_path).expanduser().resolve()
        if not src.exists():
            return f"[Error] Archive not found: {archive_path}"

        name = src.name.lower()
        if name.endswith(".zip"):
            with zipfile.ZipFile(src, "r") as zf:
                infos = zf.infolist()
                lines = [f"[Zip Archive: {src.name} | {len(infos)} entries]"]
                for info in infos:
                    size = f"{info.file_size:,}B"
                    lines.append(f"  {info.filename:<60} {size:>12}")
        elif name.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar")):
            with tarfile.open(str(src)) as tf:
                members = tf.getmembers()
                lines = [f"[Tar Archive: {src.name} | {len(members)} entries]"]
                for m in members:
                    size = f"{m.size:,}B"
                    lines.append(f"  {m.name:<60} {size:>12}")
        else:
            # Try 7z
            result = subprocess.run(
                ["7z", "l", str(src)], capture_output=True, text=True
            )
            if result.returncode == 0:
                return _truncate_output(result.stdout)
            return f"[Error] Unsupported archive format: {src.suffix}"

        return _truncate_output("\n".join(lines))

    except Exception as exc:
        return f"[Error] Failed to list archive: {exc}"
