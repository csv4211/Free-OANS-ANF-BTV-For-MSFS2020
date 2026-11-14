"""Safe logging when running as windowed EXE (stdout may be None)."""

from __future__ import annotations

import sys


def log(msg: str) -> None:
    try:
        out = sys.stdout
        if out is not None:
            out.write(msg + "\n")
            out.flush()
    except Exception:
        pass
