"""Standalone unregister tool. Built as AmdbOansUnregister.exe — not the main client.

Clears local Credential Manager registration only. Does not remove the device on the server.
"""

from __future__ import annotations

import argparse
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from i18n import t
from unregister import unregister_local


def _run_silent() -> int:
    try:
        unregister_local()
        return 0
    except Exception:
        try:
            from secretstore import clear_device_secret

            clear_device_secret()
        except Exception:
            pass
        return 1


def _run_ui() -> None:
    root = tk.Tk()
    root.title(t("unreg_title"))
    root.geometry("420x190")
    root.resizable(False, False)
    root.configure(bg="#0b1218")

    status = tk.StringVar(value=t("unreg_confirm_hint"))
    tk.Label(
        root,
        textvariable=status,
        bg="#0b1218",
        fg="#e8eef4",
        font=("Segoe UI", 10),
        wraplength=380,
        justify="left",
    ).pack(padx=20, pady=(24, 12), anchor="w")

    btns = tk.Frame(root, bg="#0b1218")
    btns.pack(padx=20, pady=8, anchor="e")

    def do_unreg() -> None:
        yes.config(state="disabled")
        no.config(state="disabled")
        status.set(t("unreg_working"))

        def work() -> None:
            try:
                unregister_local()

                def _ok() -> None:
                    messagebox.showinfo(t("unreg_title"), t("unreg_done"))
                    root.destroy()

                root.after(0, _ok)
            except Exception:

                def _err() -> None:
                    messagebox.showerror(t("unreg_title"), t("unreg_failed"))
                    root.destroy()

                root.after(0, _err)

        threading.Thread(target=work, daemon=True).start()

    yes = tk.Button(
        btns,
        text=t("unreg_yes"),
        command=do_unreg,
        width=14,
        bg="#c44",
        fg="#fff",
        activebackground="#a33",
        activeforeground="#fff",
        relief="flat",
        cursor="hand2",
    )
    yes.pack(side="left", padx=(0, 8))
    no = tk.Button(
        btns,
        text=t("unreg_no"),
        command=root.destroy,
        width=10,
        bg="#1c2834",
        fg="#e8eef4",
        activebackground="#243040",
        activeforeground="#fff",
        relief="flat",
        cursor="hand2",
    )
    no.pack(side="left")

    root.mainloop()


def main() -> None:
    ap = argparse.ArgumentParser(description="Clear AMDB OANS registration on this PC")
    ap.add_argument(
        "--silent",
        action="store_true",
        help="No UI; clear local registration. For uninstall.",
    )
    args = ap.parse_args()

    if args.silent:
        raise SystemExit(_run_silent())

    _run_ui()


if __name__ == "__main__":
    main()
