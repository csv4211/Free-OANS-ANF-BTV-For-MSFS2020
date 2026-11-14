"""Client-side HMAC + AES-GCM unwrap (mirrors server/devauth)."""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def hmac_hex(key: str, message: str) -> str:
    return hmac.new(key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def proof_message(*parts: str) -> str:
    return "|".join(parts)


def derive_wrap_key(app_key: str) -> bytes:
    return hashlib.sha256(app_key.encode("utf-8")).digest()


def unwrap_secret(app_key: str, wrapped_b64: str, aad: str) -> str:
    raw = base64.b64decode(wrapped_b64)
    if len(raw) < 13:
        raise ValueError("wrapped_secret too short")
    iv, ct = raw[:12], raw[12:]
    pt = AESGCM(derive_wrap_key(app_key)).decrypt(iv, ct, aad.encode("utf-8"))
    return pt.decode("utf-8")
