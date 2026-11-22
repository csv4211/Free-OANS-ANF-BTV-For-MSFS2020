"""First-run enroll → unwrap → store secret in Credential Manager → bind-exe."""

from __future__ import annotations

import embedded
from devauth import hmac_hex, proof_message, unwrap_secret
from i18n import t
from remote import RemoteAmdb
from secretstore import (
    clear_device_secret,
    is_activated,
    load_slot_if_any,
    set_runtime_secret,
    stock_exe_hash,
    store_device_secret,
)

# Keep stock key for re-enroll even after RAM wipe of embedded.APP_KEY.
_STOCK_APP_KEY = (getattr(embedded, "APP_KEY", None) or "").strip()

_ORPHAN_REASONS = frozenset(
    {
        "unknown_device",
        "not_enrolled",
        "not_registered",
        "bad_proof",
        "missing_proof",
        "device_mismatch",
    }
)


class ActivationError(RuntimeError):
    def __init__(self, key: str, **kwargs) -> None:
        self.key = key
        self.kwargs = kwargs
        super().__init__(t(key, **kwargs))


def _user_err(internal: str) -> ActivationError:
    """Map internal failures to short UI keys (no HTML / dumps)."""
    raw = internal or ""
    low = raw.lower()
    if "<html" in low or "<!doctype" in low or "bad gateway" in low:
        return ActivationError("server_temp")
    if "client_version" in low:
        return ActivationError("err_need_new_version")
    if "stock_exe_hash" in low or ("stock" in low and "hash" in low):
        return ActivationError("err_build_rejected")
    if "bad_proof" in low or "unwrap" in low:
        return ActivationError("err_device_check")
    if "bad_challenge" in low:
        return ActivationError("err_session_expired")
    if "deny" in low or "banned" in low:
        return ActivationError("err_access_denied")
    if "app_key" in low or "missing" in low:
        return ActivationError("err_need_stock")
    if "bind" in low:
        return ActivationError("err_bind_failed")
    if "enroll" in low:
        return ActivationError("err_enroll_failed")
    if (
        "недоступен" in low
        or "нет связи" in low
        or "unavailable" in low
        or "no connection" in low
        or "server_temp" in low
        or "err_no_server" in low
    ):
        return ActivationError("err_no_server")
    return ActivationError("err_prepare_failed")


def rebind_exe_hash(remote: RemoteAmdb, identity_refresh, exe_hash: str | None = None) -> dict:
    """Re-bind device_secret → current EXE hash (after update)."""
    from secretstore import current_secret

    secret = current_secret()
    if not secret or secret == "0" * 64:
        raise ActivationError("err_need_stock")
    identity_refresh()
    ident = remote.identity_fn()
    hw = ident["hw_fingerprint"]
    new_hash = (exe_hash or ident.get("exe_hash") or stock_exe_hash()).lower()
    ch = remote.fetch_challenge()
    proof = hmac_hex(secret, proof_message(ch["nonce"], hw, new_hash))
    bind = remote.bind_exe(challenge_id=ch["challenge_id"], proof=proof, exe_hash=new_hash)
    if not bind.get("ok"):
        raise _user_err(str(bind.get("error") or bind.get("reason") or "bind failed"))
    identity_refresh()
    return {"ok": True, "exe_hash": new_hash}


def _server_reason(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("reason") or payload.get("error") or "").lower().strip()


def _local_secret_orphaned(remote: RemoteAmdb) -> bool:
    """True when this PC has a secret but the server has no matching device."""
    try:
        remote.clear_session()
        hb = remote.heartbeat()
    except Exception:
        return False
    reason = _server_reason(hb if isinstance(hb, dict) else None)
    if reason in _ORPHAN_REASONS:
        return True
    # Session mint can also reveal a missing device before heartbeat.
    if reason in ("bad_session",) or (isinstance(hb, dict) and hb.get("ok") is False and reason in _ORPHAN_REASONS):
        return True
    return False


def ensure_activated(remote: RemoteAmdb, identity_refresh) -> dict:
    load_slot_if_any()
    if is_activated():
        identity_refresh()
        if not _local_secret_orphaned(remote):
            return {"ok": True, "already": True}
        # Local activation left over, server record gone / new device_id — re-enroll.
        try:
            remote.clear_session()
        except Exception:
            pass
        clear_device_secret()

    app_key = _STOCK_APP_KEY or (embedded.APP_KEY or "").strip()
    if not app_key or app_key == "0" * 64:
        raise _user_err("APP_KEY missing")

    stock_hash = stock_exe_hash().lower()
    identity_refresh()

    try:
        ch = remote.fetch_challenge()
    except Exception:
        raise ActivationError("err_no_server") from None

    challenge_id = ch["challenge_id"]
    nonce = ch["nonce"]
    ident = remote.identity_fn()
    hw = ident["hw_fingerprint"]

    proof = hmac_hex(app_key, proof_message(nonce, hw, stock_hash))
    resp = remote.enroll(challenge_id=challenge_id, proof=proof, exe_hash=stock_hash)
    if not resp.get("ok") or not resp.get("wrapped_secret"):
        raise _user_err(str(resp.get("error") or resp.get("reason") or "enroll failed"))

    aad = proof_message(challenge_id, hw)
    try:
        secret = unwrap_secret(app_key, resp["wrapped_secret"], aad)
    except Exception:
        raise _user_err("unwrap failed") from None

    set_runtime_secret(secret)
    try:
        store_device_secret(secret)
    except Exception:
        raise ActivationError("err_write_activation") from None

    # EXE is not patched — bind the stock hash; secret lives in Credential Manager.
    new_hash = stock_hash
    identity_refresh()

    ch2 = remote.fetch_challenge()
    proof2 = hmac_hex(secret, proof_message(ch2["nonce"], hw, new_hash))
    bind = remote.bind_exe(challenge_id=ch2["challenge_id"], proof=proof2, exe_hash=new_hash)
    if not bind.get("ok"):
        raise _user_err(str(bind.get("error") or bind.get("reason") or "bind failed"))

    identity_refresh()
    return {
        "ok": True,
        "already": False,
        "exe_hash": new_hash,
    }
