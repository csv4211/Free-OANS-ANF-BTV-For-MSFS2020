"""Device slot in EXE / embedded.py.

Strategy for frozen EXE:
1) Try patch slot in-place (same file).
2) Else write patched copy (*.tmp.exe), on exit replace original and delete the old one.
"""

from __future__ import annotations

import atexit
import hashlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import embedded

_WIPED_APP_KEY = "0" * 64
_runtime_secret: str | None = None
_active_binary: Path | None = None
_pending: tuple[Path, Path] | None = None  # (original_exe, patched_tmp)


def placeholder() -> str:
    return getattr(embedded, "DEVICE_SECRET_PLACEHOLDER", None) or ("0" * 64)


def slot_prefix() -> str:
    return getattr(embedded, "DEVICE_SECRET_SLOT_PREFIX", None) or "AMDB_DEVSEC_SLOT_v1="


def slot_blob(secret: str | None = None) -> bytes:
    return (slot_prefix() + (secret or placeholder()).lower()).encode("ascii")


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


def binary_path() -> Path:
    if _active_binary is not None:
        return _active_binary
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


# build.ps1 appends the patchable slot at EOF. Never search the whole file —
# an internal copy of the marker lives inside the PyInstaller archive; patching
# that corrupts python312.dll extraction ("Failed to load Python DLL").
_SLOT_TAIL_WINDOW = 512


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


def patch_secret_into_bytes(data: bytes, secret: str) -> bytes:
    """Patch or append EOF device-secret trailer. Safe for onefile EXE."""
    if not data.startswith(b"MZ"):
        raise OSError("not a PE executable")
    return _patch_bytes(data, secret)


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


def _finish_pending_tmp(exe: Path) -> bool:
    """If a patched .tmp.exe exists from last run, replace original now."""
    tmp = _tmp_path(exe)
    if not tmp.exists():
        return False
    sec = read_slot_secret(tmp)
    if not sec or sec == placeholder():
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    # Prefer replacing stock/original with activated tmp
    try:
        # If we're not running from tmp, try delete+replace
        if Path(sys.executable).resolve() != tmp.resolve():
            try:
                if exe.exists():
                    exe.unlink()
            except OSError:
                # still locked — leave tmp for replace helper later
                return False
            tmp.replace(exe)
            set_runtime_secret(sec)
            return True
    except OSError:
        return False
    return False


def load_slot_if_any() -> bool:
    if not getattr(sys, "frozen", False):
        return is_activated()

    exe = Path(sys.executable)
    cleanup_leftovers(exe)

    # Complete interrupted replace from previous session
    _finish_pending_tmp(exe if exe.suffix.lower() == ".exe" else exe)

    # Running the main EXE
    sec = read_slot_secret(Path(sys.executable))
    if sec and sec != placeholder():
        set_runtime_secret(sec)
        # Drop tmp if main already activated
        tmp = _tmp_path(Path(sys.executable))
        try:
            if tmp.exists() and read_slot_secret(tmp) == sec:
                tmp.unlink()
        except OSError:
            pass
        return True

    # Main still stock but tmp ready — try replace again
    main = Path(sys.executable)
    if _finish_pending_tmp(main):
        return is_activated()

    tmp = _tmp_path(main)
    if tmp.exists():
        sec = read_slot_secret(tmp)
        if sec and sec != placeholder():
            # Keep using tmp content in RAM; schedule replace on exit
            set_runtime_secret(sec)
            global _pending, _active_binary
            _pending = (main, tmp)
            _active_binary = tmp
            return True
    return False


def _write_at(path: Path, offset: int, data: bytes) -> None:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        GENERIC_WRITE = 0x40000000
        FILE_SHARE_ALL = 0x00000007
        OPEN_EXISTING = 3
        FILE_BEGIN = 0
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateFileW(str(path), GENERIC_WRITE, FILE_SHARE_ALL, None, OPEN_EXISTING, 0, None)
        if handle in (0, -1, ctypes.c_void_p(-1).value):
            raise OSError("CreateFileW failed")
        try:
            high = wintypes.DWORD(0)
            kernel32.SetFilePointer(handle, offset, ctypes.byref(high), FILE_BEGIN)
            written = wintypes.DWORD(0)
            if not kernel32.WriteFile(handle, data, len(data), ctypes.byref(written), None):
                raise OSError("WriteFile failed")
            if written.value != len(data):
                raise OSError("short write")
            kernel32.FlushFileBuffers(handle)
        finally:
            kernel32.CloseHandle(handle)
        return
    with path.open("r+b") as f:
        f.seek(offset)
        f.write(data)
        f.flush()


def _patch_bytes(data: bytes, secret: str) -> bytes:
    """Patch EOF trailer only. Never rewrite bytes inside the PyInstaller archive."""
    sec = secret.lower()
    pref = slot_prefix().encode("ascii")
    i = _find_slot(data)
    if i >= 0:
        start = i + len(pref)
        if len(data) >= start + 64:
            return data[:start] + sec.encode("ascii") + data[start + 64 :]
        return data[:i] + pref + sec.encode("ascii")
    return data + slot_blob(sec)


def _try_inplace(exe: Path, secret: str) -> bool:
    raw = exe.read_bytes()
    i = _find_slot(raw)
    if i < 0:
        return False
    start = i + len(slot_prefix())
    if len(raw) < start + 64:
        return False
    try:
        _write_at(exe, start, secret.lower().encode("ascii"))
        return read_slot_secret(exe) == secret.lower()
    except OSError:
        return False


def _patch_embedded_py(path: Path, secret: str) -> None:
    text = path.read_text(encoding="utf-8")
    ph = placeholder()
    sec = secret.lower()
    if f'DEVICE_SECRET = "{ph}"' in text or f"DEVICE_SECRET = '{ph}'" in text:
        text = text.replace(f'DEVICE_SECRET = "{ph}"', f'DEVICE_SECRET = "{sec}"', 1)
        text = text.replace(f"DEVICE_SECRET = '{ph}'", f"DEVICE_SECRET = '{sec}'", 1)
    else:
        text, n = re.subn(
            r'^(DEVICE_SECRET\s*=\s*)(["\'])([0-9a-fA-F]{64})\2',
            rf'\1\2{sec}\2',
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if not n:
            raise FileNotFoundError("DEVICE_SECRET line not found")
    text = text.replace(slot_prefix() + ph, slot_prefix() + sec, 1)
    if embedded.APP_KEY and embedded.APP_KEY != _WIPED_APP_KEY:
        text, _ = re.subn(
            rf'^(APP_KEY\s*=\s*)(["\']){re.escape(embedded.APP_KEY)}\2',
            rf'\1\2{_WIPED_APP_KEY}\2',
            text,
            count=1,
            flags=re.MULTILINE,
        )
    path.write_text(text, encoding="utf-8")


def _ps_quote(path: str) -> str:
    return "'" + path.replace("'", "''") + "'"


def _spawn_replace(original: Path, tmp: Path) -> None:
    """After this PID exits: delete original, rename tmp → original. No console window."""
    if sys.platform != "win32":
        return
    pid = os.getpid()
    o = _ps_quote(str(original))
    t = _ps_quote(str(tmp))
    # Entirely in PowerShell — no cmd/find/timeout console flash
    ps = (
        f"while (Get-Process -Id {pid} -ErrorAction SilentlyContinue) "
        f"{{ Start-Sleep -Milliseconds 400 }}; "
        f"Start-Sleep -Milliseconds 800; "
        f"$o = {o}; $t = {t}; "
        f"for ($i = 0; $i -lt 40; $i++) {{ "
        f"  try {{ if (Test-Path -LiteralPath $o) {{ Remove-Item -LiteralPath $o -Force -ErrorAction Stop }} ; break }} "
        f"  catch {{ Start-Sleep -Milliseconds 500 }} "
        f"}}; "
        f"if (Test-Path -LiteralPath $t) {{ Move-Item -LiteralPath $t -Destination $o -Force }}"
    )
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            ps,
        ],
        cwd=str(original.parent),
        startupinfo=si,
        creationflags=flags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def finish_pending_replace() -> None:
    global _pending
    if not _pending:
        cleanup_leftovers()
        return
    original, tmp = _pending
    _pending = None
    if not tmp.exists():
        return
    # Try immediate replace first (sometimes works right as we quit)
    try:
        time.sleep(0.05)
        if original.exists():
            original.unlink()
        tmp.replace(original)
        cleanup_leftovers(original)
        return
    except OSError:
        pass
    _spawn_replace(original, tmp)


atexit.register(finish_pending_replace)


def patch_device_secret(secret: str) -> Path:
    """Patch same EXE in-place, or copy→patch→replace-on-exit (delete old)."""
    global _active_binary, _pending

    secret = secret.lower().strip()
    set_runtime_secret(secret)

    if not getattr(sys, "frozen", False):
        target = Path(embedded.__file__).resolve()
        _patch_embedded_py(target, secret)
        embedded.APP_KEY = _WIPED_APP_KEY
        _active_binary = target
        return target

    exe = Path(sys.executable)
    cleanup_leftovers(exe)
    embedded.APP_KEY = _WIPED_APP_KEY

    if _try_inplace(exe, secret):
        _active_binary = exe
        _pending = None
        return exe

    # Copy → patch the copy → on exit delete old and rename copy
    raw = exe.read_bytes()
    patched = _patch_bytes(raw, secret)
    tmp = _tmp_path(exe)
    tmp.write_bytes(patched)
    if read_slot_secret(tmp) != secret:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise OSError("failed to write patched copy")

    _pending = (exe, tmp)
    _active_binary = tmp
    return tmp


# Startup
load_slot_if_any()
