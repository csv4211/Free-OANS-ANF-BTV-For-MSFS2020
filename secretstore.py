"""Device secret storage.

Primary: Windows Credential Manager (per-user).
Legacy: EOF trailer slot on older EXE builds — read once and migrate into Cred Manager.
"""

from __future__ import annotations

import atexit
import hashlib
import sys
from pathlib import Path

import embedded
from wincred import cred_delete, cred_read, cred_write

_WIPED_APP_KEY = "0" * 64
_runtime_secret: str | None = None

# build.ps1 may append a trailer slot. Only search the EOF window —
# an internal copy of the marker lives inside the PyInstaller archive.
_SLOT_TAIL_WINDOW = 512


def placeholder() -> str:
    return getattr(embedded, "DEVICE_SECRET_PLACEHOLDER", None) or ("0" * 64)


def slot_prefix() -> str:
    return getattr(embedded, "DEVICE_SECRET_SLOT_PREFIX", None) or "AMDB_DEVSEC_SLOT_v1="


def current_secret() -> str:
    if _runtime_secret:
        return _runtime_secret
    return (embedded.DEVICE_SECRET or "").strip()


def is_activated() -> bool:
    s = current_secret()
    return bool(s) and s != placeholder() and len(s) == 64 and all(c in "0123456789abcdef" for c in s.lower())


def set_runtime_secret(secret: str) -> None:
    global _runtime_secret
    _runtime_secret = secret
    embedded.DEVICE_SECRET = secret


def store_device_secret(secret: str) -> None:
    """Persist secret in Windows Credential Manager; keep in RAM for this process."""
    secret = secret.lower().strip()
    set_runtime_secret(secret)
    if sys.platform == "win32":
        cred_write(secret)
    if embedded.APP_KEY and embedded.APP_KEY != _WIPED_APP_KEY:
        embedded.APP_KEY = _WIPED_APP_KEY


def clear_device_secret() -> None:
    """Remove secret from Credential Manager and RAM. Does not touch the server."""
    global _runtime_secret
    _runtime_secret = None
    try:
        embedded.DEVICE_SECRET = placeholder()
    except Exception:
        pass
    try:
        cred_delete()
    except Exception:
        pass


def binary_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(embedded.__file__).resolve()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path | None = None) -> str:
    return _sha256_bytes((path or binary_path()).read_bytes())


def stock_exe_hash() -> str:
    if getattr(sys, "frozen", False):
        return _sha256_bytes(Path(sys.executable).read_bytes())
    return _sha256_bytes(Path(embedded.__file__).resolve().read_bytes())


def _find_slot(data: bytes) -> int:
    """Index of EOF trailer slot only (not mid-archive)."""
    pref = slot_prefix().encode("ascii")
    if not data or len(data) < len(pref):
        return -1
    window = min(len(data), _SLOT_TAIL_WINDOW)
    rel = data[-window:].rfind(pref)
    if rel < 0:
        return -1
    return len(data) - window + rel


def read_slot_secret(path: Path | None = None) -> str | None:
    target = path or binary_path()
    try:
        data = target.read_bytes()
    except OSError:
        return None
    i = _find_slot(data)
    if i < 0:
        return None
    start = i + len(slot_prefix())
    sec = data[start : start + 64]
    if len(sec) != 64:
        return None
    try:
        text = sec.decode("ascii").lower()
    except UnicodeDecodeError:
        return None
    return text if all(c in "0123456789abcdef" for c in text) else None


def _tmp_path(exe: Path) -> Path:
    return exe.with_name(exe.stem + ".tmp" + exe.suffix)


def _junk_paths(exe: Path) -> list[Path]:
    return [
        exe.with_suffix(exe.suffix + ".new"),
        exe.with_name(exe.stem + "_swap.cmd"),
        exe.with_name(exe.stem + "_activated" + exe.suffix),
        exe.with_name(exe.stem + ".amdbsec"),
        exe.with_name(exe.stem + "_replace.cmd"),
    ]


def cleanup_leftovers(exe: Path | None = None) -> None:
    if not getattr(sys, "frozen", False) and exe is None:
        return
    base = exe or Path(sys.executable)
    for p in _junk_paths(base):
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass


def _migrate_secret(sec: str) -> bool:
    if not sec or sec == placeholder():
        return False
    set_runtime_secret(sec)
    try:
        cred_write(sec)
    except Exception:
        pass
    return True


def _finish_pending_tmp(exe: Path) -> bool:
    """If a patched .tmp.exe exists from an old install, take its secret and remove it."""
    tmp = _tmp_path(exe)
    if not tmp.exists():
        return False
    sec = read_slot_secret(tmp)
    try:
        tmp.unlink()
    except OSError:
        pass
    return _migrate_secret(sec or "")


def load_slot_if_any() -> bool:
    """Load secret from Credential Manager (or migrate legacy EXE slot)."""
    try:
        sec = cred_read()
        if sec and sec != placeholder():
            set_runtime_secret(sec)
            return True
    except Exception:
        pass

    if not getattr(sys, "frozen", False):
        return is_activated()

    exe = Path(sys.executable)
    cleanup_leftovers(exe)
    if _finish_pending_tmp(exe if exe.suffix.lower() == ".exe" else exe):
        return True

    sec = read_slot_secret(exe)
    if _migrate_secret(sec or ""):
        return True
    return False


atexit.register(cleanup_leftovers)

# Startup
load_slot_if_any()
