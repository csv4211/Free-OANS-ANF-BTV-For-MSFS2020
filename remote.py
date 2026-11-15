"""Fetch AMDB from origin server into RAM only (no disk cache)."""

from __future__ import annotations

import base64
import json
import ssl
import time
import urllib.error
import urllib.request
from typing import Callable
from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from devauth import hmac_hex, proof_message
from i18n import t
from secretstore import current_secret, is_activated

IdentityProvider = Callable[[], dict[str, str]]

_MAP_AAD = b"amdb-map-v1"


def _decrypt_map_body(content_key_hex: str, blob: bytes) -> bytes:
    obj = json.loads(blob.decode("utf-8"))
    if not isinstance(obj, dict) or int(obj.get("v") or 0) != 1:
        raise ValueError("bad envelope")
    key = bytes.fromhex(content_key_hex)
    iv = base64.b64decode(obj["iv"])
    ct = base64.b64decode(obj["ct"])
    return AESGCM(key).decrypt(iv, ct, _MAP_AAD)


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
        self._session_token: str | None = None
        self._session_exp: float = 0.0
        self._content_key: str | None = None

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

    def _device_secret_headers(self, method: str, path: str) -> dict[str, str]:
        """HMAC with long-lived device_secret (session mint / fallback)."""
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

    def clear_session(self) -> None:
        self._session_token = None
        self._session_exp = 0.0
        self._content_key = None

    def ensure_session(self, *, force: bool = False) -> str:
        """Get/refresh short-lived Bearer token (1–2h). Uses device_secret only here."""
        now = time.time()
        if (
            not force
            and self._session_token
            and self._content_key
            and now < self._session_exp - 120
        ):
            return self._session_token
        if not is_activated():
            raise RuntimeError(t("need_activation"))

        path = "/v1/auth/session"
        headers = self._device_secret_headers("POST", path)
        headers["Content-Type"] = "application/json"
        data = json.dumps(self.identity_fn()).encode()
        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method="POST")
        try:
            with self._urlopen(req, timeout=60) as resp:
                obj = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                obj = json.loads(body.decode(errors="replace"))
                reason = str(obj.get("reason") or obj.get("error") or "").lower()
                if reason in ("banned", "banned_hw"):
                    raise RuntimeError(t("err_banned")) from None
            except RuntimeError:
                raise
            except Exception:
                pass
            raise RuntimeError(friendly_http_error(e.code, body)) from None
        except RuntimeError:
            raise
        except Exception:
            raise RuntimeError(friendly_http_error()) from None

        token = str(obj.get("access_token") or "")
        map_ck = str(obj.get("content_key") or "")
        if not obj.get("ok") or not token:
            raise RuntimeError(str(obj.get("error") or obj.get("reason") or t("auth_error")))
        expires_in = int(obj.get("expires_in") or 7200)
        self._session_token = token
        self._content_key = map_ck or None
        self._session_exp = now + max(60, expires_in)
        return token

    def _auth_headers(self, method: str, path: str, *, require_session: bool = False) -> dict[str, str]:
        headers = self._identity_headers()
        if not is_activated():
            return headers
        try:
            token = self.ensure_session()
            if require_session and not self._content_key:
                raise RuntimeError(t("auth_error"))
            headers["Authorization"] = f"Bearer {token}"
            return headers
        except Exception:
            if require_session:
                raise
            # Heartbeat only: HMAC fallback if session mint failed
            return self._device_secret_headers(method, path)

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
            # Session expired → clear and retry once with fresh token / secret proof
            if e.code == 403 and signed and is_activated():
                try:
                    obj = json.loads(detail)
                    reason = str(obj.get("reason") or obj.get("error") or "").lower()
                except Exception:
                    reason = ""
                if reason in ("bad_session", "missing_proof", "bad_challenge"):
                    self.clear_session()
                    try:
                        headers = self._auth_headers("POST", path)
                        headers["Content-Type"] = "application/json"
                        req2 = urllib.request.Request(
                            self.base_url + path, data=data, headers=headers, method="POST"
                        )
                        with self._urlopen(req2, timeout=60) as resp:
                            return json.loads(resp.read().decode())
                    except Exception:
                        pass
            try:
                obj = json.loads(detail)
                if isinstance(obj, dict):
                    err = str(obj.get("error") or obj.get("reason") or "")
                    if _looks_like_markup(err) or len(err) > 120:
                        obj["error"] = friendly_http_error(e.code, detail)
                    return obj
            except json.JSONDecodeError:
                pass
            return {"ok": False, "error": friendly_http_error(e.code, detail)}
        except Exception:
            return {"ok": False, "error": friendly_http_error()}

    def _maybe_decrypt(self, raw: bytes, enc_hdr: str | None) -> bytes:
        if (enc_hdr or "").strip() != "1":
            return raw
        if not self._content_key:
            raise RuntimeError(t("auth_error"))
        try:
            return _decrypt_map_body(self._content_key, raw)
        except Exception:
            raise RuntimeError(t("auth_error")) from None

    def get(self, path_qs: str) -> bytes:
        if not path_qs.startswith("/"):
            path_qs = "/" + path_qs
        route = urlparse(path_qs).path
        headers = self._auth_headers("GET", route, require_session=True)
        url = self.base_url + path_qs
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with self._urlopen(req, timeout=90) as resp:
                enc = resp.headers.get("X-AMDB-Enc")
                raw = resp.read()
                if enc != "1":
                    raise RuntimeError(t("auth_error"))
                return self._maybe_decrypt(raw, enc)
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                obj = json.loads(body.decode(errors="replace"))
                reason = str(obj.get("reason") or obj.get("error") or "").lower()
                if reason in ("banned", "banned_hw"):
                    raise RuntimeError(t("err_banned")) from None
                if reason in ("bad_session", "session_required") and is_activated():
                    self.clear_session()
                    headers = self._auth_headers("GET", route, require_session=True)
                    req2 = urllib.request.Request(url, headers=headers, method="GET")
                    with self._urlopen(req2, timeout=90) as resp:
                        enc = resp.headers.get("X-AMDB-Enc")
                        raw = resp.read()
                        if enc != "1":
                            raise RuntimeError(t("auth_error"))
                        return self._maybe_decrypt(raw, enc)
            except RuntimeError:
                raise
            except Exception:
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
