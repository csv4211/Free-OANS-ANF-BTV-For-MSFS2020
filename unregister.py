"""Local device unregister — Credential Manager only. Never deletes the device on the server."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fingerprint import collect_identity
from secretstore import clear_device_secret, load_slot_if_any


class UnregisterError(RuntimeError):
    pass


def unregister_exe_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().with_name("AmdbOansUnregister.exe")
    return Path(__file__).resolve().parent / "AmdbOansUnregister.exe"


def launch_unregister() -> None:
    """Start standalone unregister EXE (main client must exit afterwards)."""
    exe = unregister_exe_path()
    if not exe.is_file():
        raise UnregisterError("unregister tool not found: " + str(exe))
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
    subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        close_fds=True,
        creationflags=flags,
    )


def unregister_local() -> dict:
    """Wipe activation on this PC only. Server device record is left untouched."""
    load_slot_if_any()
    clear_device_secret()
    return {
        "ok": True,
        "local_cleared": True,
        "identity": collect_identity(),
    }
