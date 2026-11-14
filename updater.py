"""Check origin for a newer stock EXE, replace self, relaunch."""

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


def fetch_manifest(remote: RemoteAmdb) -> dict:
    import json
    import urllib.request

    url = remote.base_url.rstrip("/") + "/v1/client/update"
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


def download_update(remote: RemoteAmdb, manifest: dict) -> bytes:
    import urllib.request

    path = str(manifest.get("url") or "/v1/client/download")
    if not path.startswith("/"):
        path = "/" + path
    url = remote.base_url.rstrip("/") + path
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"amdb-oans-client/{embedded.CLIENT_VERSION}"},
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
    if len(data) < 1024 * 100:
        raise UpdateError("update too small")
    return data


def _spawn_replace_relaunch(original: Path, new_exe: Path) -> None:
    if sys.platform != "win32":
        raise UpdateError("auto-update only on Windows")
    pid = os.getpid()

    def q(p: str) -> str:
        return "'" + p.replace("'", "''") + "'"

    o = q(str(original))
    n = q(str(new_exe))
    ps = (
        f"while (Get-Process -Id {pid} -ErrorAction SilentlyContinue) "
        f"{{ Start-Sleep -Milliseconds 400 }}; "
        f"Start-Sleep -Milliseconds 900; "
        f"$o = {o}; $n = {n}; "
        f"for ($i = 0; $i -lt 50; $i++) {{ "
        f"  try {{ if (Test-Path -LiteralPath $o) {{ Remove-Item -LiteralPath $o -Force -ErrorAction Stop }} ; break }} "
        f"  catch {{ Start-Sleep -Milliseconds 400 }} "
        f"}}; "
        f"if (Test-Path -LiteralPath $n) {{ Move-Item -LiteralPath $n -Destination $o -Force }}; "
        f"Start-Sleep -Milliseconds 500; "
        f"if (Test-Path -LiteralPath $o) {{ "
        f"  $len = (Get-Item -LiteralPath $o).Length; "
        f"  if ($len -gt 100000) {{ Start-Process -FilePath $o }} "
        f"}}"
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
        cwd=str(original.parent),
        startupinfo=si,
        creationflags=flags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def apply_update_bytes(data: bytes) -> Path:
    """Write clean stock EXE beside the running one and schedule replace+relaunch.

    Device secret is NOT copied: after restart the stock EXE re-enrolls on the
    same device_id/hw and binds itself (same as a fresh install on a known PC).
    """
    if not getattr(sys, "frozen", False):
        raise UpdateError("auto-update only for frozen EXE")
    if not data.startswith(b"MZ"):
        raise UpdateError("update is not a valid EXE")

    exe = Path(sys.executable).resolve()
    tmp = exe.with_name(exe.stem + ".update" + exe.suffix)
    fd, tmp_name = tempfile.mkstemp(prefix=exe.stem + "_", suffix=".part", dir=str(exe.parent))
    os.close(fd)
    part = Path(tmp_name)
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

    _spawn_replace_relaunch(exe, tmp)
    return tmp


def resume_pending_update() -> bool:
    """If a previous update left *.update.exe, finish replace + relaunch."""
    if not getattr(sys, "frozen", False):
        return False
    exe = Path(sys.executable).resolve()
    upd = exe.with_name(exe.stem + ".update" + exe.suffix)
    if not upd.is_file():
        return False
    if upd.resolve() == exe:
        return False
    try:
        if upd.stat().st_size < 1024 * 100:
            upd.unlink()
            return False
    except OSError:
        return False
    _spawn_replace_relaunch(exe, upd)
    return True


def check_and_update(remote: RemoteAmdb) -> dict:
    """
    If a newer client is published, download clean stock EXE + replace + relaunch.
    Returns {"updated": False} or {"updated": True, ...} (caller must exit).
    """
    if not getattr(sys, "frozen", False):
        return {"updated": False, "skipped": "not_frozen"}

    if resume_pending_update():
        return {"updated": True, "resumed": True}

    try:
        man = fetch_manifest(remote)
    except UpdateError as e:
        return {"updated": False, "skipped": "check_failed", "error": str(e)}

    remote_ver = str(man.get("version") or "").strip()
    if remote_ver and not needs_update(remote_ver):
        return {"updated": False, "skipped": "up_to_date", "version": remote_ver}

    if not man.get("update"):
        # Server wants a newer version but published no EXE in updates/
        if remote_ver and needs_update(remote_ver):
            return {"updated": False, "skipped": "package_missing", "version": remote_ver}
        return {"updated": False, "skipped": "none", "version": remote_ver or None}

    data = download_update(remote, man)
    new_path = apply_update_bytes(data)
    return {"updated": True, "version": remote_ver, "path": str(new_path)}
