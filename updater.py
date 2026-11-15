"""Update check (main app) + download/replace helpers (updater EXE)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
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


def updater_exe_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().with_name("AmdbOansUpdater.exe")
    return Path(__file__).resolve().parent / "AmdbOansUpdater.exe"


def launch_updater(*, wait_pid: int, target_exe: Path) -> None:
    upd = updater_exe_path()
    if not upd.is_file():
        raise UpdateError("updater not found: " + str(upd))
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) # show updater UI — don't hide
    # Updater has its own window; start without CREATE_NO_WINDOW
    subprocess.Popen(
        [
            str(upd),
            "--wait-pid",
            str(wait_pid),
            "--target",
            str(target_exe),
        ],
        cwd=str(upd.parent),
        close_fds=True,
    )


def replace_exe_and_relaunch(target: Path, data: bytes, *, wait_pid: int | None = None) -> None:
    """Write target.update.exe, wait for pid, replace, start target."""
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
            tmp.unlink()
        part.replace(tmp)
    except Exception:
        try:
            if part.exists():
                part.unlink()
        except OSError:
            pass
        raise

    pid = int(wait_pid or 0)

    def q(p: str) -> str:
        return "'" + p.replace("'", "''") + "'"

    o = q(str(target))
    n = q(str(tmp))
    wait = (
        f"if ({pid} -gt 0) {{ while (Get-Process -Id {pid} -ErrorAction SilentlyContinue) "
        f"{{ Start-Sleep -Milliseconds 400 }} }}; "
        if pid > 0
        else ""
    )
    ps = (
        wait
        + f"Start-Sleep -Milliseconds 800; "
        f"$o = {o}; $n = {n}; "
        f"for ($i = 0; $i -lt 50; $i++) {{ "
        f"  try {{ if (Test-Path -LiteralPath $o) {{ Remove-Item -LiteralPath $o -Force -ErrorAction Stop }} ; break }} "
        f"  catch {{ Start-Sleep -Milliseconds 400 }} "
        f"}}; "
        f"if (Test-Path -LiteralPath $n) {{ Move-Item -LiteralPath $n -Destination $o -Force }}; "
        f"Start-Sleep -Milliseconds 400; "
        f"if (Test-Path -LiteralPath $o) {{ Start-Process -FilePath $o }}"
    )
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
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
        cwd=str(target.parent),
        startupinfo=si,
        creationflags=flags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
