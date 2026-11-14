"""Hardware fingerprint — no files written."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import uuid

from embedded import CLIENT_VERSION
from secretstore import file_sha256, is_activated, current_secret
from winproc import run_hidden


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()


def machine_guid() -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            val, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(val).strip()
    except Exception:
        return ""


def _wmi_bundle() -> dict[str, str]:
    if os.name != "nt":
        return {}
    ps = r"""
$ErrorActionPreference='SilentlyContinue'
$o=[ordered]@{}
$o.uuid=(Get-CimInstance Win32_ComputerSystemProduct | Select-Object -First 1 -ExpandProperty UUID)
$o.board=(Get-CimInstance Win32_BaseBoard | Select-Object -First 1 -ExpandProperty SerialNumber)
$o.disk=(Get-CimInstance Win32_DiskDrive | Select-Object -First 1 -ExpandProperty SerialNumber)
$o | ConvertTo-Json -Compress
"""
    try:
        r = run_hidden(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-Command", ps],
            timeout=20,
        )
        data = json.loads((r.stdout or "").strip() or "{}")
        return {k: str(v).strip() for k, v in data.items() if v}
    except Exception:
        return {}


def hardware_fingerprint() -> str:
    parts = [
        machine_guid(),
        hex(uuid.getnode()),
        socket.gethostname(),
    ]
    parts.extend(_wmi_bundle().values())
    raw = "|".join(p for p in parts if p)
    return _sha256_text(raw or "unknown-hw")


def exe_hash() -> str:
    return file_sha256()


def collect_identity() -> dict[str, str]:
    hw = hardware_fingerprint()
    return {
        "device_id": hw,
        "hw_fingerprint": hw,
        "exe_hash": exe_hash(),
        "hostname": socket.gethostname(),
        "client_version": CLIENT_VERSION,
        "activated": "1" if is_activated() else "0",
        "has_secret": "1" if current_secret() else "0",
    }
