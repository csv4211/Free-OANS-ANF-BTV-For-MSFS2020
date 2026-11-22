"""Runtime helper copy of the frozen client EXE.

Updater/swap must run from a different file path than the install EXE
(Windows locks a running image). Distribution ships only AmdbOansClient.exe;
a copy is created under LocalAppData when needed.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path


def helper_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    path = Path(base) / "AMDB-OANS"
    path.mkdir(parents=True, exist_ok=True)
    return path


def helper_exe_path() -> Path:
    return helper_dir() / "AmdbOansHelper.exe"


def ensure_runtime_helper() -> Path:
    """Return path to a runnable helper EXE (copy of this frozen binary)."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("runtime helper only available when frozen")

    src = Path(sys.executable).resolve()
    dst = helper_exe_path()
    stamp = dst.with_suffix(".stamp")

    src_stat = src.stat()
    stamp_payload = f"{src}|{src_stat.st_size}|{int(src_stat.st_mtime)}\n"
    if dst.is_file() and stamp.is_file():
        try:
            if stamp.read_text(encoding="utf-8") == stamp_payload and dst.stat().st_size == src_stat.st_size:
                return dst
        except OSError:
            pass

    fd, part_name = tempfile.mkstemp(prefix="AmdbOansHelper_", suffix=".part", dir=str(dst.parent))
    os.close(fd)
    part = Path(part_name)
    try:
        shutil.copy2(src, part)
        if dst.exists():
            try:
                dst.unlink()
            except OSError:
                pass
        part.replace(dst)
        stamp.write_text(stamp_payload, encoding="utf-8")
    except Exception:
        try:
            if part.exists():
                part.unlink()
        except OSError:
            pass
        raise
    return dst


def client_argv_prefix() -> list[str]:
    """Argv prefix to re-enter this app (frozen EXE or python run_client.py)."""
    if getattr(sys, "frozen", False):
        return [str(ensure_runtime_helper())]
    script = Path(__file__).resolve().parent / "run_client.py"
    return [sys.executable, str(script)]
