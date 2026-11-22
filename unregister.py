"""Local device unregister — Credential Manager only. Never deletes the device on the server."""

from __future__ import annotations

from fingerprint import collect_identity
from secretstore import clear_device_secret, load_slot_if_any


def unregister_local() -> dict:
    """Wipe activation on this PC only. Server device record is left untouched."""
    load_slot_if_any()
    clear_device_secret()
    return {
        "ok": True,
        "local_cleared": True,
        "identity": collect_identity(),
    }
