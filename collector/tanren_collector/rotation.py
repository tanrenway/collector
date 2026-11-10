"""Persist next credential before rotation; recover lost ACK by probing next credential first."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from .protocol import PREFIX, V2Api, digest


def refresh(store, api_factory=V2Api, now=None):
    now = now or datetime.now(UTC)
    config = store.get("config")
    pending = store.get("rotation")
    if pending:
        try:
            control = api_factory(pending["token"]).call(PREFIX + "/control")
        except RuntimeError as exc:
            if str(exc) != "SYNC_PAUSED_HTTP_401":
                raise
            control = None
        if control is None:
            api_factory(config["token"]).call(
                PREFIX + "/credentials/rotate",
                {"rotation_id": pending["id"], "next_digest": digest(pending["token"])},
            )
            control = api_factory(pending["token"]).call(PREFIX + "/control")
        if (
            control["account_id"] != config["account_id"]
            or control["device_id"] != config["device_id"]
        ):
            raise RuntimeError("CREDENTIAL_SCOPE_MISMATCH")
        config["token"] = pending["token"]
        with store.db:
            store.put("config", config)
            store.put("rotation", None)
        return control
    control = api_factory(config["token"]).call(PREFIX + "/control")
    if control["account_id"] != config["account_id"] or control["device_id"] != config["device_id"]:
        raise RuntimeError("CREDENTIAL_SCOPE_MISMATCH")
    expiry = datetime.fromisoformat(control["expires_at"])
    if expiry - now < timedelta(days=7):
        store.save("rotation", {"id": str(uuid.uuid4()), "token": secrets.token_urlsafe(48)})
    return control
