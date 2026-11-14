"""OANS client UI. Run: python ui.py"""

from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox

import embedded
from activate import ActivationError, ensure_activated, rebind_exe_hash
from fingerprint import collect_identity
from i18n import get_lang, set_lang, t
from mitm import MitmService, is_admin
from remote import RemoteAmdb
from secretstore import finish_pending_replace, is_activated
from updater import UpdateError, check_and_update
from web_bridge import WebOansService

# Night-deck palette (EFIS / OANS feel)
BG = "#0b1218"
BG_RAISED = "#121c26"
BG_CARD = "#162231"
BG_CARD_ON = "#1a3340"
LINE = "#243447"
TEXT = "#e8eef4"
MUTED = "#8aa0b5"
AMBER = "#f0b429"
CYAN = "#3dd6c6"
DANGER = "#e85d5d"
OK = "#5dce8a"


def _relaunch_as_admin() -> bool:
    if os.name != "nt" or is_admin():
        return False
    try:
        import ctypes

        params = " ".join(f'"{a}"' for a in sys.argv[1:])
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        return int(rc) > 32
    except Exception:
        return False


class ToggleRow(tk.Frame):
    """Clickable card toggle with title + hint."""

    def __init__(self, master, title: str, hint: str, variable: tk.BooleanVar, command) -> None:
        super().__init__(master, bg=BG_CARD, highlightthickness=1, highlightbackground=LINE)
        self.variable = variable
        self.command = command

        inner = tk.Frame(self, bg=BG_CARD)
        inner.pack(fill=tk.X, padx=14, pady=12)

        left = tk.Frame(inner, bg=BG_CARD)
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.lbl_title = tk.Label(
            left, text=title, bg=BG_CARD, fg=TEXT, font=("Segoe UI Semibold", 11), anchor="w"
        )
        self.lbl_title.pack(anchor="w")
        self.lbl_hint = tk.Label(
            left, text=hint, bg=BG_CARD, fg=MUTED, font=("Segoe UI", 9), anchor="w"
        )
        self.lbl_hint.pack(anchor="w", pady=(2, 0))

        self.pill = tk.Label(
            inner,
            text="OFF",
            width=5,
            bg=LINE,
            fg=MUTED,
            font=("Consolas", 10, "bold"),
            padx=8,
            pady=4,
        )
        self.pill.pack(side=tk.RIGHT)

        for w in (self, inner, left, self.lbl_title, self.lbl_hint, self.pill):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)

        variable.trace_add("write", lambda *_: self._sync())
        self._sync()

    def set_texts(self, title: str, hint: str) -> None:
        self.lbl_title.configure(text=title)
        self.lbl_hint.configure(text=hint)

    def _click(self, _e=None) -> None:
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()

    def _enter(self, _e=None) -> None:
        if not self.variable.get():
            self.configure(highlightbackground=MUTED)

    def _leave(self, _e=None) -> None:
        self._sync()

    def _sync(self) -> None:
        on = bool(self.variable.get())
        bg = BG_CARD_ON if on else BG_CARD
        edge = CYAN if on else LINE
        self.configure(bg=bg, highlightbackground=edge)
        for w in self.winfo_children():
            self._recolor(w, bg)
        self.pill.configure(
            text="ON" if on else "OFF",
            bg=CYAN if on else LINE,
            fg=BG if on else MUTED,
        )

    def _recolor(self, w, bg: str) -> None:
        try:
            if w is self.pill:
                return
            w.configure(bg=bg)
            for c in w.winfo_children():
                self._recolor(c, bg)
        except tk.TclError:
            pass


class App:
    def __init__(self) -> None:
        self.identity = collect_identity()
        self.remote = RemoteAmdb(
            embedded.SERVER_BASE_URL,
            identity_fn=lambda: self.identity,
            insecure_tls=bool(embedded.INSECURE_TLS),
            ca_cert=None,
        )
        self.mitm = MitmService(self.remote)
        self.web = WebOansService(self.remote, port=int(embedded.WEB_PORT))
        self.web_url = f"http://127.0.0.1:{self.web.port}"

        self.root = tk.Tk()
        self.root.title(t("app_title"))
        self.root.minsize(420, 420)
        self.root.geometry("440x450")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        try:
            self.root.tk.call("tk", "scaling", 1.15)
        except tk.TclError:
            pass

        shell = tk.Frame(self.root, bg=BG)
        shell.pack(fill=tk.BOTH, expand=True, padx=22, pady=20)

        brand = tk.Frame(shell, bg=BG)
        brand.pack(fill=tk.X)
        tk.Label(
            brand, text="AMDB", bg=BG, fg=AMBER, font=("Segoe UI", 22, "bold"), anchor="w"
        ).pack(side=tk.LEFT)
        tk.Label(
            brand, text=" OANS", bg=BG, fg=TEXT, font=("Segoe UI Light", 22), anchor="w"
        ).pack(side=tk.LEFT)

        lang_row = tk.Frame(brand, bg=BG)
        lang_row.pack(side=tk.RIGHT)
        self.btn_en = tk.Button(
            lang_row,
            text="EN",
            command=lambda: self._switch_lang("en"),
            bg=BG_CARD,
            fg=MUTED,
            activebackground=BG_CARD_ON,
            activeforeground=TEXT,
            relief=tk.FLAT,
            font=("Consolas", 9, "bold"),
            padx=6,
            pady=2,
            cursor="hand2",
        )
        self.btn_en.pack(side=tk.LEFT, padx=(0, 4))
        self.btn_ru = tk.Button(
            lang_row,
            text="RU",
            command=lambda: self._switch_lang("ru"),
            bg=BG_CARD,
            fg=MUTED,
            activebackground=BG_CARD_ON,
            activeforeground=TEXT,
            relief=tk.FLAT,
            font=("Consolas", 9, "bold"),
            padx=6,
            pady=2,
            cursor="hand2",
        )
        self.btn_ru.pack(side=tk.LEFT)

        status_box = tk.Frame(shell, bg=BG_RAISED, highlightthickness=1, highlightbackground=LINE)
        status_box.pack(fill=tk.X, pady=(14, 14))
        pad = tk.Frame(status_box, bg=BG_RAISED)
        pad.pack(fill=tk.X, padx=12, pady=10)

        self.dot = tk.Label(pad, text="●", bg=BG_RAISED, fg=MUTED, font=("Segoe UI", 10))
        self.dot.pack(side=tk.LEFT)
        self.status = tk.StringVar(value=t("checking_server"))
        self.status_lbl = tk.Label(
            pad,
            textvariable=self.status,
            bg=BG_RAISED,
            fg=TEXT,
            font=("Segoe UI", 9),
            anchor="w",
            wraplength=360,
            justify="left",
        )
        self.status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        self.oans_var = tk.BooleanVar(value=False)
        self.web_var = tk.BooleanVar(value=False)

        self.oans_row = ToggleRow(
            shell,
            t("oans_title"),
            t("oans_hint"),
            self.oans_var,
            self._toggle_oans,
        )
        self.oans_row.pack(fill=tk.X, pady=(0, 8))

        self.web_row = ToggleRow(
            shell,
            t("web_title"),
            t("web_hint"),
            self.web_var,
            self._toggle_web,
        )
        self.web_row.pack(fill=tk.X, pady=(0, 12))

        actions = tk.Frame(shell, bg=BG)
        actions.pack(fill=tk.X)

        self.link = tk.Button(
            actions,
            text=t("open_web"),
            command=self._open_web,
            state=tk.DISABLED,
            bg=BG_CARD,
            fg=MUTED,
            activebackground=BG_CARD_ON,
            activeforeground=TEXT,
            disabledforeground="#5a6b7c",
            relief=tk.FLAT,
            font=("Segoe UI Semibold", 10),
            padx=14,
            pady=9,
            cursor="hand2",
        )
        self.link.pack(side=tk.LEFT)

        self.quit_btn = tk.Button(
            actions,
            text=t("quit"),
            command=self._quit,
            bg=BG,
            fg=MUTED,
            activebackground=BG_RAISED,
            activeforeground=DANGER,
            relief=tk.FLAT,
            font=("Segoe UI", 10),
            padx=12,
            pady=9,
            cursor="hand2",
        )
        self.quit_btn.pack(side=tk.RIGHT)

        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self._activated = is_activated()
        self._status_key = "checking_server"
        self._status_kwargs: dict = {}
        self._status_tone = "neutral"
        self._apply_lang_buttons()
        self.root.after(200, self._boot_activate)

    def _web_url_with_lang(self) -> str:
        return f"{self.web_url}/?lang={get_lang()}"

    def _apply_lang_buttons(self) -> None:
        lang = get_lang()
        for btn, code in ((self.btn_en, "en"), (self.btn_ru, "ru")):
            on = lang == code
            btn.configure(
                bg=AMBER if on else BG_CARD,
                fg=BG if on else MUTED,
                activebackground="#ffc94a" if on else BG_CARD_ON,
                activeforeground=BG if on else TEXT,
            )

    def _switch_lang(self, code: str) -> None:
        if code == get_lang():
            return
        set_lang(code)
        self.root.title(t("app_title"))
        self.oans_row.set_texts(t("oans_title"), t("oans_hint"))
        self.web_row.set_texts(t("web_title"), t("web_hint"))
        self.link.configure(text=t("open_web"))
        self.quit_btn.configure(text=t("quit"))
        self._apply_lang_buttons()
        # Same status, new language — do not re-query the server.
        if self.web.running or self.mitm.running:
            self._refresh_status()
        else:
            self._render_status()

    def _refresh_identity(self) -> None:
        self.identity = collect_identity()

    def _sanitize_status(self, msg: str) -> str:
        text = (msg or "").strip()
        low = text.lower()
        if "<html" in low or "<!doctype" in low or "bad gateway" in low or "<center>" in low:
            return t("server_temp")
        if len(text) > 90 or "\n" in text:
            return t("server_down")
        return text

    def _set_status_key(self, key: str, *, tone: str = "neutral", **kwargs) -> None:
        self._status_key = key
        self._status_kwargs = dict(kwargs)
        self._status_tone = tone
        self._render_status()

    def _render_status(self) -> None:
        self.status.set(t(self._status_key, **self._status_kwargs))
        colors = {"ok": OK, "err": DANGER, "warn": AMBER, "neutral": MUTED}
        self.dot.configure(fg=colors.get(self._status_tone, MUTED))

    def _exit_for_update(self) -> None:
        try:
            self.web.stop()
        except Exception:
            pass
        try:
            self.mitm.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        raise SystemExit(0)

    def _boot_activate(self) -> None:
        self._set_status_key("checking_update", tone="warn")

        def work() -> None:
            # 1) Auto-update before activation (works even if version is outdated)
            try:
                upd = check_and_update(self.remote)
                if upd.get("updated"):
                    def _restart() -> None:
                        self._set_status_key("update_restart", tone="warn")
                        self.root.after(600, self._exit_for_update)

                    self.root.after(0, _restart)
                    return
                if upd.get("skipped") == "package_missing":
                    self.root.after(0, lambda: self._set_status_key("update_missing", tone="err"))
                    return
            except UpdateError:
                self.root.after(0, lambda: self._set_status_key("update_failed", tone="err"))
                # Fall through — may still activate if versions match
            except Exception:
                pass

            self.root.after(0, lambda: self._set_status_key("activating", tone="warn"))
            try:
                result = ensure_activated(self.remote, self._refresh_identity)
                self._activated = True

                def _ok() -> None:
                    if result.get("needs_relaunch"):
                        self._set_status_key("ready_relaunch", tone="warn")
                    else:
                        self._set_status_key("ready", tone="ok")
                    self._ping_server()

                self.root.after(0, _ok)
            except ActivationError as e:
                self._activated = False
                key = getattr(e, "key", None) or "err_prepare_failed"
                if key in ("err_need_new_version", "need_update"):
                    key = "update_missing"
                kw = dict(getattr(e, "kwargs", {}) or {})
                self.root.after(
                    0,
                    lambda k=key, kws=kw: self._set_status_key(k, tone="err", **kws),
                )
            except Exception:
                self._activated = False
                self.root.after(0, lambda: self._set_status_key("server_down", tone="err"))

        threading.Thread(target=work, daemon=True).start()

    def _status_key_from_server(self, payload: dict) -> tuple[str, str]:
        """Return (i18n key, tone) from heartbeat / API body."""
        if payload.get("ok"):
            return "server_ok", "ok"
        reason = str(payload.get("reason") or payload.get("error") or "").lower()
        if reason in ("banned", "banned_hw"):
            return "banned", "err"
        if reason in ("client_version_mismatch",):
            return "need_update", "err"
        if reason in ("exe_hash_mismatch", "exe_not_bound", "hw_mismatch"):
            return "device_mismatch", "warn"
        if reason in ("not_enrolled", "unknown_device"):
            return "not_registered", "warn"
        if reason in ("deny_all",):
            return "deny_all", "err"
        if reason in ("bad_proof", "bad_challenge", "missing_proof"):
            return "auth_error", "warn"
        if reason in ("not_activated",):
            return "need_activation", "warn"
        return "server_refuse", "warn"

    def _ping_server(self) -> None:
        def work() -> None:
            try:
                hb = self.remote.heartbeat()
                if isinstance(hb, dict):
                    reason = str(hb.get("reason") or hb.get("error") or "").lower()
                    if reason in ("exe_hash_mismatch", "exe_not_bound"):
                        try:
                            rebind_exe_hash(self.remote, self._refresh_identity)
                            hb = self.remote.heartbeat()
                        except Exception:
                            pass
                key, tone = self._status_key_from_server(hb if isinstance(hb, dict) else {})
                self.root.after(0, lambda: self._set_status_key(key, tone=tone))
            except Exception:
                self.root.after(0, lambda: self._set_status_key("server_down", tone="err"))

        threading.Thread(target=work, daemon=True).start()

    def _require_activated(self) -> bool:
        if self._activated and is_activated():
            return True
        messagebox.showwarning(t("app_title"), t("wait_activation"))
        return False

    def _refresh_status(self) -> None:
        parts = []
        if self.web.running:
            parts.append(t("part_web"))
        if self.mitm.running:
            parts.append(t("part_oans"))
        if parts:
            self._set_status_key("enabled", tone="ok", parts=", ".join(parts))
        else:
            self._set_status_key("ready", tone="neutral")

    def _open_web(self) -> None:
        if self.web.running:
            webbrowser.open(self._web_url_with_lang())

    def _set_web_open_enabled(self, on: bool) -> None:
        if on:
            self.link.configure(state=tk.NORMAL, bg=AMBER, fg=BG, activebackground="#ffc94a", activeforeground=BG)
        else:
            self.link.configure(state=tk.DISABLED, bg=BG_CARD, fg=MUTED)

    def _toggle_oans(self) -> None:
        if self.oans_var.get() and not self._require_activated():
            self.oans_var.set(False)
            return
        if self.oans_var.get() and not is_admin():
            self.oans_var.set(False)
            if messagebox.askyesno(t("admin_needed_title"), t("admin_needed_body")):
                if _relaunch_as_admin():
                    self._quit()
                else:
                    messagebox.showerror(t("part_oans"), t("admin_fail"))
            return

        def work() -> None:
            try:
                if self.oans_var.get():
                    self.mitm.start()
                    try:
                        self.remote.heartbeat()
                    except Exception:
                        pass
                else:
                    self.mitm.stop()
                self.root.after(0, self._refresh_status)
            except Exception as e:
                self.root.after(0, lambda: self.oans_var.set(False))
                err = self._sanitize_status(str(e))
                self.root.after(0, lambda: messagebox.showerror(t("part_oans"), err))
                self.root.after(0, self._refresh_status)

        threading.Thread(target=work, daemon=True).start()

    def _toggle_web(self) -> None:
        if self.web_var.get() and not self._require_activated():
            self.web_var.set(False)
            return

        def work() -> None:
            try:
                if self.web_var.get():
                    self.web.start()
                    try:
                        self.remote.heartbeat()
                    except Exception:
                        self.root.after(
                            0,
                            lambda: messagebox.showwarning(t("server"), t("web_server_warn")),
                        )

                    def _on() -> None:
                        self._set_web_open_enabled(True)
                        self._refresh_status()
                        webbrowser.open(self._web_url_with_lang())

                    self.root.after(0, _on)
                else:
                    self.web.stop()

                    def _off() -> None:
                        self._set_web_open_enabled(False)
                        self._refresh_status()

                    self.root.after(0, _off)
            except Exception as e:
                self.root.after(0, lambda: self.web_var.set(False))
                self.root.after(0, lambda: self._set_web_open_enabled(False))
                err = self._sanitize_status(str(e))
                self.root.after(0, lambda: messagebox.showerror(t("web_title"), err))
                self.root.after(0, self._refresh_status)

        threading.Thread(target=work, daemon=True).start()

    def _quit(self) -> None:
        try:
            self.web.stop()
        except Exception:
            pass
        try:
            self.mitm.stop()
        except Exception:
            pass
        try:
            finish_pending_replace()
        except Exception:
            pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
