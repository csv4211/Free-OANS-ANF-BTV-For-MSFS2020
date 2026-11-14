"""Run child processes without flashing console windows."""

from __future__ import annotations

import os
import subprocess
from typing import Sequence

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def run_hidden(args: Sequence[str], *, timeout: float | None = 30, **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("timeout", timeout)
    if os.name == "nt":
        kwargs["creationflags"] = int(kwargs.get("creationflags") or 0) | CREATE_NO_WINDOW
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        kwargs["startupinfo"] = si
    return subprocess.run(list(args), **kwargs)
