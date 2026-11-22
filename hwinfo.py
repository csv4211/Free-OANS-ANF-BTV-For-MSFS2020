"""Hardware info via Windows registry / simple WinAPI (no PowerShell, no SMBIOS).

Avoid GetSystemFirmwareTable — Hybrid Analysis scores it as malicious fingerprinting.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


def _reg_values(root, path: str, names: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    if os.name != "nt":
        return out
    try:
        import winreg
    except ImportError:
        return out
    try:
        with winreg.OpenKey(root, path) as key:
            for name in names:
                try:
                    val, _ = winreg.QueryValueEx(key, name)
                    s = str(val).strip()
                    if s:
                        out[name] = s
                except OSError:
                    pass
    except OSError:
        pass
    return out


def read_smbios_parts() -> dict[str, str]:
    """Return raw strings: cpu / board / ram. Name kept for call sites; registry-based."""
    import winreg

    cpu_reg = _reg_values(
        winreg.HKEY_LOCAL_MACHINE,
        r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        ["ProcessorNameString", "Identifier", "VendorIdentifier", "FeatureSet"],
    )
    cpu = "|".join(
        cpu_reg[k]
        for k in ("Identifier", "ProcessorNameString", "VendorIdentifier", "FeatureSet")
        if cpu_reg.get(k)
    )

    bios = _reg_values(
        winreg.HKEY_LOCAL_MACHINE,
        r"HARDWARE\DESCRIPTION\System\BIOS",
        [
            "BaseBoardManufacturer",
            "BaseBoardProduct",
            "BaseBoardVersion",
            "BaseBoardSerialNumber",
            "SystemManufacturer",
            "SystemProductName",
            "SystemSerialNumber",
            "SystemFamily",
            "BIOSVendor",
            "BIOSVersion",
        ],
    )
    sysinfo = _reg_values(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\SystemInformation",
        [
            "SystemManufacturer",
            "SystemProductName",
            "SystemSerialNumber",
            "BIOSVersion",
            "ComputerHardwareId",
        ],
    )
    # Prefer baseboard fields; fall back to system identity.
    board = "|".join(
        x
        for x in (
            bios.get("BaseBoardSerialNumber") or sysinfo.get("SystemSerialNumber") or bios.get("SystemSerialNumber"),
            bios.get("BaseBoardProduct") or sysinfo.get("SystemProductName") or bios.get("SystemProductName"),
            bios.get("BaseBoardManufacturer") or sysinfo.get("SystemManufacturer") or bios.get("SystemManufacturer"),
            sysinfo.get("ComputerHardwareId"),
        )
        if x
    )

    ram = f"total:{_total_phys_bytes()}"
    return {"cpu": cpu, "board": board, "ram": ram}


def _total_phys_bytes() -> int:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        return 0
    return int(stat.ullTotalPhys)


def read_disk_raw() -> str:
    """Boot volume serial|label|filesystem via GetVolumeInformationW (no drive IOCTL)."""
    if os.name != "nt":
        return ""
    root = os.environ.get("SystemDrive", "C:") + "\\"
    vol_name = ctypes.create_unicode_buffer(261)
    fs_name = ctypes.create_unicode_buffer(261)
    serial = wintypes.DWORD(0)
    max_comp = wintypes.DWORD(0)
    flags = wintypes.DWORD(0)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        root,
        vol_name,
        len(vol_name),
        ctypes.byref(serial),
        ctypes.byref(max_comp),
        ctypes.byref(flags),
        fs_name,
        len(fs_name),
    )
    if not ok:
        return ""
    return f"{serial.value:08X}|{vol_name.value}|{fs_name.value}"
