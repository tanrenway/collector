"""Crash-recoverable one-use enrollment. Persist three distinct secrets before the claim."""

import secrets
import uuid

from .protocol import PREFIX, V2Api, digest


def begin(store, token, terminal, identity):
    config = store.get("config", {})
    if config.get("identity") not in (None, identity):
        raise RuntimeError("BINDING_IDENTITY_IMMUTABLE")
    pending = {
        "enrollment": token,
        "claim": secrets.token_urlsafe(48),
        "device": secrets.token_urlsafe(48),
        "request_id": str(uuid.uuid4()),
        "identity": identity,
        "terminal": terminal,
        "claimed": False,
    }
    if len({token, pending["claim"], pending["device"]}) != 3:
        raise RuntimeError("DISTINCT_CREDENTIALS_REQUIRED")
    store.save("pairing", pending)


def advance(store, api_factory=V2Api):
    pending = store.get("pairing")
    if not pending:
        return None
    if not pending["claimed"]:
        api_factory(pending["enrollment"]).call(
            PREFIX + "/enrollment/claim",
            {
                "request_id": pending["request_id"],
                "claim_digest": digest(pending["claim"]),
                "device_digest": digest(pending["device"]),
                "identity": pending["identity"],
                "label": "Tanren Collector",
            },
        )
        pending["claimed"] = True
        pending.pop("enrollment")
        store.save("pairing", pending)
        return "awaiting_browser_confirmation"
    view = api_factory(pending["claim"]).call(PREFIX + "/enrollment")
    if not (
        view.get("confirmed") is True
        or ("confirmed" not in view and view.get("state") == "confirmed")
    ):
        return "awaiting_browser_confirmation"
    old = store.get("config", {})
    if old.get("account_id") not in (None, view["account_id"]):
        raise RuntimeError("BINDING_ACCOUNT_IMMUTABLE")
    config = {
        **old,
        "token": pending["device"],
        "identity": pending["identity"],
        "terminal": pending["terminal"],
        "account_id": view["account_id"],
        "device_id": view["device_id"],
        "paused": False,
    }
    with store.db:
        store.put("config", config)
        store.put("pairing", None)
        store.put("rotation", None)
        store.put("network_after", 0)
        store.put("transport_state", "connected")
    return "confirmed"
