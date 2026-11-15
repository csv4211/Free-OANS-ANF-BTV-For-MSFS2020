"""Store device_secret in Windows Credential Manager (per-user).

Like a password vault entry: Windows encrypts it for this Windows user.
The EXE itself stays unchanged (no binary patch).
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

TARGET = "AMDB-OANS/device_secret"
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2  # survives reboot for this user logon profile


class CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _advapi() -> ctypes.WinDLL:
    return ctypes.WinDLL("advapi32", use_last_error=True)


def cred_write(secret: str) -> None:
    if sys.platform != "win32":
        raise OSError("Credential Manager is Windows-only")
    data = secret.lower().strip().encode("utf-8")
    blob = ctypes.create_string_buffer(data)
    cred = CREDENTIAL()
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = TARGET
    cred.CredentialBlobSize = len(data)
    cred.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_char))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = "AMDB-OANS"
    adv = _advapi()
    if not adv.CredWriteW(ctypes.byref(cred), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def cred_read() -> str | None:
    if sys.platform != "win32":
        return None
    adv = _advapi()
    ptr = ctypes.POINTER(CREDENTIAL)()
    if not adv.CredReadW(TARGET, CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)):
        return None
    try:
        cred = ptr.contents
        n = int(cred.CredentialBlobSize)
        if n <= 0 or not cred.CredentialBlob:
            return None
        raw = ctypes.string_at(cred.CredentialBlob, n)
        text = raw.decode("utf-8", errors="ignore").strip().lower()
        if len(text) == 64 and all(c in "0123456789abcdef" for c in text):
            return text
        return None
    finally:
        adv.CredFree(ptr)


def cred_delete() -> None:
    if sys.platform != "win32":
        return
    _advapi().CredDeleteW(TARGET, CRED_TYPE_GENERIC, 0)
