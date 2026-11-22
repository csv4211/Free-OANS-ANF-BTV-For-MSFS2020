"""Update check (main app) + download/replace helpers (updater EXE)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import embedded
from remote import RemoteAmdb


class UpdateError(RuntimeError):
    pass


def _parse_ver(v: str) -> tuple[int, ...]:
    parts: list[int] = []
    for p in (v or "").strip().split("."):
        if not p:
            continue
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) if parts else (0,)


def needs_update(remote_version: str, local_version: str | None = None) -> bool:
    local = (local_version if local_version is not None else embedded.CLIENT_VERSION) or "0"
    return _parse_ver(remote_version) > _parse_ver(local)


def _ssl_ctx():
    import ssl

    if not embedded.SERVER_BASE_URL.startswith("https://"):
        return None
    if embedded.INSECURE_TLS:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return ssl.create_default_context()


def fetch_manifest(remote: RemoteAmdb | None = None) -> dict:
    import json
    import urllib.request

    base = (remote.base_url if remote else embedded.SERVER_BASE_URL).rstrip("/")
    url = base + "/v1/client/update"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": f"amdb-oans-client/{embedded.CLIENT_VERSION}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl_ctx()) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        raise UpdateError(str(e) or "update check failed") from None


def check_for_update(remote: RemoteAmdb) -> dict:
    """
    Main app: only check, never download/replace.
    Returns keys: available, version, package_missing, skipped, ...
    """
    try:
        man = fetch_manifest(remote)
    except UpdateError as e:
        return {"available": False, "skipped": "check_failed", "error": str(e)}

    remote_ver = str(man.get("version") or "").strip()
    if remote_ver and not needs_update(remote_ver):
        return {"available": False, "skipped": "up_to_date", "version": remote_ver}

    if remote_ver and needs_update(remote_ver) and not man.get("update"):
        return {"available": False, "skipped": "package_missing", "version": remote_ver}

    if man.get("update") and remote_ver and needs_update(remote_ver):
        return {"available": True, "version": remote_ver, "manifest": man}

    return {"available": False, "skipped": "none", "version": remote_ver or None}


def download_update(manifest: dict, *, base_url: str | None = None) -> bytes:
    import urllib.request

    path = str(manifest.get("url") or "/v1/client/download")
    if not path.startswith("/"):
        path = "/" + path
    url = (base_url or embedded.SERVER_BASE_URL).rstrip("/") + path
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"amdb-oans-updater/{embedded.CLIENT_VERSION}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=300, context=_ssl_ctx()) as resp:
            data = resp.read()
    except Exception as e:
        raise UpdateError(str(e) or "download failed") from None

    expect = str(manifest.get("sha256") or "").strip().lower()
    got = hashlib.sha256(data).hexdigest().lower()
    if expect and got != expect:
        raise UpdateError("update hash mismatch")
    size = manifest.get("size")
    if isinstance(size, int) and size > 0 and len(data) != size:
        raise UpdateError("update size mismatch")
    if len(data) < 1024 * 100 or not data.startswith(b"MZ"):
        raise UpdateError("update is not a valid EXE")
    return data


def launch_updater(*, wait_pid: int, target_exe: Path) -> None:
    """Start update UI from a helper copy of this app (same binary, different path)."""
    from helperutil import client_argv_prefix

    try:
        argv = client_argv_prefix()
    except Exception as e:
        raise UpdateError(str(e) or "could not prepare updater") from e
    cwd = str(target_exe.resolve().parent)
    subprocess.Popen(
        [
            *argv,
            "--update",
            "--wait-pid",
            str(wait_pid),
            "--target",
            str(target_exe),
        ],
        cwd=cwd,
        close_fds=True,
    )


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) == 0:
            return False
        return int(code.value) == STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def wait_for_pid(pid: int, *, timeout_sec: float = 120.0) -> None:
    if pid <= 0:
        return
    deadline = time.time() + max(1.0, timeout_sec)
    while time.time() < deadline and _pid_running(pid):
        time.sleep(0.4)


def swap_files(src: Path, dst: Path, *, retries: int = 50) -> None:
    """Replace dst with src (delete dst, move src → dst). Pure Python, no PowerShell."""
    src = src.resolve()
    dst = dst.resolve()
    for _ in range(max(1, retries)):
        try:
            if dst.exists():
                dst.unlink()
            break
        except OSError:
            time.sleep(0.4)
    if not src.exists():
        raise UpdateError("update file missing")
    src.replace(dst)


def replace_exe_and_relaunch(target: Path, data: bytes, *, wait_pid: int | None = None) -> None:
    """Write update beside target, wait for old process, replace, relaunch — no PowerShell."""
    if sys.platform != "win32":
        raise UpdateError("Windows only")
    if not data.startswith(b"MZ"):
        raise UpdateError("not a PE executable")

    target = target.resolve()
    tmp = target.with_name(target.stem + ".update" + target.suffix)
    fd, part_name = tempfile.mkstemp(prefix=target.stem + "_", suffix=".part", dir=str(target.parent))
    os.close(fd)
    part = Path(part_name)
    try:
        part.write_bytes(data)
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        part.replace(tmp)
    except Exception:
        try:
            if part.exists():
                part.unlink()
        except OSError:
            pass
        raise

    wait_for_pid(int(wait_pid or 0))
    time.sleep(0.8)
    swap_files(tmp, target)
    time.sleep(0.4)
    subprocess.Popen(
        [str(target)],
        cwd=str(target.parent),
        close_fds=True,
    )
