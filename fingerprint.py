"""Hardware fingerprint — separate parts (CPU / board / RAM / disk / machine).

device_id is derived only from stable core (cpu + board + ram), so disk
swap does not mint a new device. Each part is sent to the server so a ban still
sticks if even one part matches a banned device.

Collection uses SMBIOS + storage IOCTL (no PowerShell).
"""

from __future__ import annotations

import hashlib
import os
import socket

from embedded import CLIENT_VERSION
from secretstore import current_secret, file_sha256, is_activated

# Core parts define device_id and must match for the same user.
CORE_PARTS = ("cpu", "board", "ram")
ALL_PARTS = ("cpu", "board", "ram", "disk", "machine")


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()


def _part_hash(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw or raw.lower() in ("none", "to be filled by o.e.m.", "default string", "0"):
        return ""
    return _sha256_text(raw)


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


def _wmi_raw() -> dict[str, str]:
    """Hardware raw strings. Name kept for call sites; no WMI/PowerShell."""
    if os.name != "nt":
        return {}
    out: dict[str, str] = {}
    try:
        from hwinfo import read_disk_raw, read_smbios_parts

        out.update({k: v for k, v in read_smbios_parts().items() if v})
        disk = read_disk_raw()
        if disk:
            out["disk"] = disk
    except Exception:
        pass
    return out


def collect_hw_parts() -> dict[str, str]:
    """Return {part_name: sha256_hex} for available components."""
    raw = _wmi_raw()
    parts: dict[str, str] = {}
    for key in ("cpu", "board", "ram", "disk"):
        h = _part_hash(raw.get(key, ""))
        if h:
            parts[key] = h
    mg = _part_hash(machine_guid())
    if mg:
        parts["machine"] = mg
    return parts


def encode_hw_parts(parts: dict[str, str]) -> str:
    """Compact header form: cpu=..,board=..,..."""
    return ",".join(f"{k}={parts[k]}" for k in ALL_PARTS if parts.get(k))


def device_id_from_parts(parts: dict[str, str]) -> str:
    core = [f"{k}={parts[k]}" for k in CORE_PARTS if parts.get(k)]
    if not core:
        # Fallback: any parts we have
        core = [f"{k}={parts[k]}" for k in ALL_PARTS if parts.get(k)]
    return _sha256_text("|".join(core) or "unknown-hw")


def hardware_fingerprint(parts: dict[str, str] | None = None) -> str:
    """Legacy single string (HMAC / display): hash of all present parts."""
    p = parts if parts is not None else collect_hw_parts()
    blob = "|".join(f"{k}={p[k]}" for k in ALL_PARTS if p.get(k))
    return _sha256_text(blob or "unknown-hw")


def exe_hash() -> str:
    return file_sha256()


def collect_identity() -> dict[str, str]:
    parts = collect_hw_parts()
    did = device_id_from_parts(parts)
    return {
        "device_id": did,
        "hw_fingerprint": hardware_fingerprint(parts),
        "hw_parts": encode_hw_parts(parts),
        "exe_hash": exe_hash(),
        "hostname": socket.gethostname(),
        "client_version": CLIENT_VERSION,
        "activated": "1" if is_activated() else "0",
        "has_secret": "1" if current_secret() else "0",
    }
