#!/usr/bin/env python3
"""Entry for PyInstaller / python run_client.py

Modes:
  (default)              main UI
  --update               download + replace (default channel only)
  --unregister           unregister UI
  --unregister-silent    clear local registration (uninstall)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import channel


def main() -> None:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--update", action="store_true", help="Run update UI and replace --target")
    ap.add_argument("--unregister", action="store_true", help="Unregister UI")
    ap.add_argument("--unregister-silent", action="store_true", help="Clear local registration, no UI")
    ap.add_argument("--wait-pid", type=int, default=0)
    ap.add_argument("--target", type=str, default="")
    args = ap.parse_args()

    if args.update:
        if not channel.AUTO_UPDATE:
            raise SystemExit("auto-update disabled in this build")
        from run_updater import _run_ui

        if not args.target:
            raise SystemExit("missing --target")
        _run_ui(args.wait_pid or 0, Path(args.target))
        return

    if args.unregister_silent:
        from run_unregister import _run_silent

        raise SystemExit(_run_silent())

    if args.unregister:
        from run_unregister import _run_ui

        _run_ui()
        return

    from ui import main as ui_main

    ui_main()


if __name__ == "__main__":
    main()
