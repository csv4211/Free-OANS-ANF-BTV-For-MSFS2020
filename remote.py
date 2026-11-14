"""Fetch AMDB from origin server into RAM only (no disk cache)."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Callable
from urllib.parse import urlparse

from devauth import hmac_hex, proof_message
from i18n import t
from secretstore import current_secret, is_activated

IdentityProvider = Callable[[], dict[str, str]]


def _looks_like_markup(text: str) -> bool:
    s = (text or "").lstrip().lower()
    return s.startswith("<!doctype") or s.startswith("<html") or "<html" in s[:200]


def friendly_http_error(code: int | None = None, body: str | bytes | None = None) -> str:
    """Short UI-safe message — never return HTML or long dumps."""
    text = ""
    if isinstance(body, bytes):
        text = body.decode("utf-8", errors="replace")
    elif isinstance(body, str):
        text = body

    if code == 502 or code == 503 or code == 504:
        return t("server_temp")
    if code == 403:
        return t("err_forbidden")
    if code == 401:
        return t("err_unauthorized")
    if code == 404:
        return t("err_not_found")
    if _looks_like_markup(text) or "bad gateway" in text.lower():
        return t("server_temp")
    return t("err_no_server")


class RemoteAmdb:
    def __init__(
        self,
        base_url: str,
        identity_fn: IdentityProvider,
        insecure_tls: bool = False,
        ca_cert: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.identity_fn = identity_fn
        self.insecure_tls = insecure_tls
        self.ca_cert = ca_cert

    def _ctx(self) -> ssl.SSLContext | None:
        if not self.base_url.startswith("https://"):
            return None
        if self.insecure_tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        if self.ca_cert:
            return ssl.create_default_context(cafile=self.ca_cert)
        return ssl.create_default_context()

    def _identity_headers(self) -> dict[str, str]:
        ident = self.identity_fn()
        return {
            "Accept": "application/json",
            "User-Agent": f"amdb-oans-client/{ident.get('client_version', '1.0')}",
            "X-Device-Id": ident["device_id"],
            "X-Hw-Fingerprint": ident["hw_fingerprint"],
            "X-Exe-Hash": ident.get("exe_hash") or "",
            "X-Hostname": ident.get("hostname") or "",
            "X-Client-Version": ident.get("client_version") or "",
        }

    def _urlopen(self, req: urllib.request.Request, timeout: float = 90):
        return urllib.request.urlopen(req, timeout=timeout, context=self._ctx())

    def fetch_challenge(self) -> dict:
        headers = self._identity_headers()
        req = urllib.request.Request(self.base_url + "/v1/auth/challenge", headers=headers, method="GET")
        try:
            with self._urlopen(req, timeout=30) as resp:
                raw = resp.read().decode()
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            body = e.read()
            raise RuntimeError(friendly_http_error(e.code, body)) from None
        except Exception:
            raise RuntimeError(friendly_http_error()) from None

    def _auth_headers(self, method: str, path: str) -> dict[str, str]:
        headers = self._identity_headers()
        if not is_activated():
            return headers
        secret = current_secret()
        ch = self.fetch_challenge()
        challenge_id = ch["challenge_id"]
        nonce = ch["nonce"]
        ident = self.identity_fn()
        proof = hmac_hex(
            secret,
            proof_message(
                nonce,
                ident["hw_fingerprint"],
                ident.get("exe_hash") or "",
                method.upper(),
                path,
            ),
        )
        headers["X-Challenge-Id"] = challenge_id
        headers["X-Auth-Proof"] = proof
        return headers

    def post_json(self, path: str, payload: dict, *, signed: bool = False) -> dict:
        if not path.startswith("/"):
            path = "/" + path
        headers = self._auth_headers("POST", path) if signed else self._identity_headers()
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method="POST")
        try:
            with self._urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            try:
                obj = json.loads(detail)
                if isinstance(obj, dict):
                    # Keep machine codes for activate mapping; strip markup bodies
                    err = str(obj.get("error") or obj.get("reason") or "")
                    if _looks_like_markup(err) or len(err) > 120:
                        obj["error"] = friendly_http_error(e.code, detail)
                    return obj
            except json.JSONDecodeError:
                pass
            return {"ok": False, "error": friendly_http_error(e.code, detail)}
        except Exception:
            return {"ok": False, "error": friendly_http_error()}

    def get(self, path_qs: str) -> bytes:
        if not path_qs.startswith("/"):
            path_qs = "/" + path_qs
        route = urlparse(path_qs).path
        headers = self._auth_headers("GET", route)
        url = self.base_url + path_qs
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with self._urlopen(req, timeout=90) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                obj = json.loads(body.decode(errors="replace"))
                reason = str(obj.get("reason") or obj.get("error") or "").lower()
                if reason in ("banned", "banned_hw"):
                    raise RuntimeError(t("err_banned")) from None
            except RuntimeError:
                raise
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                pass
            raise RuntimeError(friendly_http_error(e.code, body)) from None
        except RuntimeError:
            raise
        except Exception:
            raise RuntimeError(friendly_http_error()) from None

    def heartbeat(self) -> dict:
        if not is_activated():
            return {"ok": False, "error": "not_activated"}
        return self.post_json("/v1/device/heartbeat", self.identity_fn(), signed=True)

    def enroll(self, *, challenge_id: str, proof: str, exe_hash: str) -> dict:
        ident = self.identity_fn()
        return self.post_json(
            "/v1/device/enroll",
            {
                "challenge_id": challenge_id,
                "proof": proof,
                "device_id": ident["device_id"],
                "hw_fingerprint": ident["hw_fingerprint"],
                "exe_hash": exe_hash,
                "hostname": ident.get("hostname") or "",
                "client_version": ident.get("client_version") or "",
            },
            signed=False,
        )

    def bind_exe(self, *, challenge_id: str, proof: str, exe_hash: str) -> dict:
        ident = self.identity_fn()
        return self.post_json(
            "/v1/device/bind-exe",
            {
                "challenge_id": challenge_id,
                "proof": proof,
                "device_id": ident["device_id"],
                "hw_fingerprint": ident["hw_fingerprint"],
                "exe_hash": exe_hash,
                "hostname": ident.get("hostname") or "",
                "client_version": ident.get("client_version") or "",
            },
            signed=False,
        )
