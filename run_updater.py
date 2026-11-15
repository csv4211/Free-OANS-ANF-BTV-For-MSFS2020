"""Standalone updater UI. Built as AmdbOansUpdater.exe — not the main client."""

from __future__ import annotations

import argparse
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from updater import UpdateError, download_update, fetch_manifest, replace_exe_and_relaunch


def _run_ui(wait_pid: int, target: Path) -> None:
    root = tk.Tk()
    root.title("AMDB OANS Update")
    root.geometry("380x140")
    root.resizable(False, False)
    root.configure(bg="#0b1218")

    status = tk.StringVar(value="Checking for update…")
    tk.Label(
        root,
        textvariable=status,
        bg="#0b1218",
        fg="#e8eef4",
        font=("Segoe UI", 10),
        wraplength=340,
        justify="left",
    ).pack(padx=20, pady=28, anchor="w")

    def work() -> None:
        try:
            status.set("Downloading update…")
            man = fetch_manifest()
            if not man.get("update"):
                raise UpdateError("no update package on server")
            data = download_update(man)
            status.set("Installing…")
            replace_exe_and_relaunch(target, data, wait_pid=wait_pid)
            status.set("Done. Restarting…")
            root.after(800, root.destroy)
        except Exception as e:
            msg = str(e) or "update failed"

            def _err() -> None:
                messagebox.showerror("AMDB OANS Update", msg)
                root.destroy()

            root.after(0, _err)

    threading.Thread(target=work, daemon=True).start()
    root.mainloop()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait-pid", type=int, default=0)
    ap.add_argument("--target", type=str, default="")
    args = ap.parse_args()

    if args.target:
        target = Path(args.target)
    elif getattr(sys, "frozen", False):
        target = Path(sys.executable).resolve().with_name("AmdbOansClient.exe")
    else:
        target = Path(__file__).resolve().parent / "dist" / "AmdbOansClient.exe"

    _run_ui(args.wait_pid or 0, target)


if __name__ == "__main__":
    main()
