"""Opt-in installation pairing. Separate DPAPI file; never opens or promotes account queues."""

import hashlib
import hmac
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import __version__
from .build_profile import check_storage_path, profile_root
from .build_target import ORIGIN
from .client import Api
from .storage import DPAPI, load_config, save_config
from .windows import FileLock

PREFIX = "/api/v1/mt5/collector/v3"
PATHS = {
    PREFIX + suffix for suffix in ("/pairing/claim", "/pairing", "/control", "/credentials/rotate")
}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def phrase(identifier, request_id, claim_digest, device_digest):
    value = digest(":".join((identifier, request_id, claim_digest, device_digest)))[:12].upper()
    return " ".join(value[index : index + 4] for index in range(0, 12, 4))


class DeviceApi(Api):
    def __init__(self, token=""):
        super().__init__(ORIGIN, token)

    def allowed_path(self, path):
        return path in PATHS


class DeviceStore:
    """Single writer, atomic DPAPI replacement, no plaintext fallback or queue schema changes."""

    def __init__(self, directory, protector):
        directory = Path(directory)
        check_storage_path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(directory / "device.lock")
        self.path = directory / "device.dpapi"
        self.protector = protector

    @classmethod
    def current_user(cls):
        if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
            raise RuntimeError("WINDOWS_USER_PROFILE_REQUIRED")
        root = profile_root() / "device-v3"
        if str(root).startswith("\\\\"):
            raise RuntimeError("LOCAL_PROFILE_REQUIRED")
        return cls(root, DPAPI())

    def get(self):
        return load_config(self.path, self.protector) if self.path.exists() else {}

    def save(self, state):
        save_config(self.path, state, self.protector)

    def close(self):
        self.lock.close()


# The server rejected or expired this pairing and it never produced a device: a new code may replace
# it. "claiming" stays protected because an interrupted claim must be able to retry exactly.
RETRYABLE_STATES = {"authorization_required", "locally_revoked"}


class PairingSession:
    def __init__(self, store, api_factory=DeviceApi):
        self.store, self.factory = store, api_factory

    def begin(self, code, name, *, replace_pending=False):
        existing = self.store.get()
        abandoned = existing.get("state") in RETRYABLE_STATES and "device_id" not in existing
        if (
            existing
            and not abandoned
            and (not replace_pending or existing.get("state") == "paired")
        ):
            raise RuntimeError("DEVICE_STATE_EXISTS")
        if not isinstance(code, str) or not 1 <= len(code) <= 32:
            raise ValueError("INVALID_PAIRING_CODE")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("INVALID_DEVICE_NAME")
        self.store.save(
            {
                "state": "claiming",
                "code": code,
                "name": name,
                "claim": secrets.token_urlsafe(48),
                "token": secrets.token_urlsafe(48),
                "request_id": str(uuid.uuid4()),
            }
        )

    def advance(self):
        state = self.store.get()
        if not state:
            raise RuntimeError("DEVICE_NOT_PAIRED")
        if state["state"] in {"authorization_required", "locally_revoked"}:
            return {"state": state["state"]}
        try:
            if state["state"] == "claiming":
                body = {
                    "code": state["code"],
                    "request_id": state["request_id"],
                    "claim_digest": digest(state["claim"]),
                    "device_digest": digest(state["token"]),
                    "name": state["name"],
                    "client_version": __version__,
                }
                view = self.factory().call(PREFIX + "/pairing/claim", body)
                expected = phrase(
                    view["id"], state["request_id"], body["claim_digest"], body["device_digest"]
                )
                if not hmac.compare_digest(view.get("verification_phrase", ""), expected):
                    raise RuntimeError("DEVICE_PAIRING_RESPONSE_MISMATCH")
                state.update(
                    state="awaiting_browser_confirmation",
                    pairing_id=view["id"],
                    verification_phrase=expected,
                )
                state.pop("code")
                self.store.save(state)
                return {"state": state["state"], "verification_phrase": expected}
            if state["state"] == "awaiting_browser_confirmation":
                # Probe permanent secret first: confirmation may have committed before a lost ACK,
                # even after pairing expiry. It cannot authenticate before browser confirmation.
                try:
                    control = self.factory(state["token"]).call(PREFIX + "/control")
                except RuntimeError as exc:
                    if str(exc) != "SYNC_PAUSED_HTTP_401":
                        raise
                    control = None
                if control is None:
                    view = self.factory(state["claim"]).call(PREFIX + "/pairing")
                    if (
                        view["id"] != state["pairing_id"]
                        or view["verification_phrase"] != state["verification_phrase"]
                    ):
                        raise RuntimeError("DEVICE_PAIRING_RESPONSE_MISMATCH")
                    if view["state"] != "confirmed":
                        return {
                            "state": view["state"],
                            "verification_phrase": state["verification_phrase"],
                        }
                    control = self.factory(state["token"]).call(PREFIX + "/control")
                state.update(state="paired", device_id=control["id"])
                state.pop("claim", None)
                self.store.save(state)
                return {"state": "paired", "device_id": state["device_id"]}
            return self.control()
        except RuntimeError as exc:
            if str(exc) == "SYNC_PAUSED_HTTP_401":
                state["state"] = "authorization_required"
                self.store.save(state)
            raise

    def control(self, now=None):
        state = self.store.get()
        if state.get("state") != "paired":
            raise RuntimeError("DEVICE_NOT_PAIRED")
        try:
            pending = state.get("rotation")
            if pending:
                try:
                    control = self.factory(pending["token"]).call(PREFIX + "/control")
                except RuntimeError as exc:
                    if str(exc) != "SYNC_PAUSED_HTTP_401":
                        raise
                    self.factory(state["token"]).call(
                        PREFIX + "/credentials/rotate",
                        {"rotation_id": pending["id"], "next_digest": digest(pending["token"])},
                    )
                    control = self.factory(pending["token"]).call(PREFIX + "/control")
                if control["id"] != state["device_id"]:
                    raise RuntimeError("DEVICE_SCOPE_MISMATCH")
                state["token"] = pending["token"]
                state.pop("rotation")
            else:
                control = self.factory(state["token"]).call(PREFIX + "/control")
                if control["id"] != state["device_id"]:
                    raise RuntimeError("DEVICE_SCOPE_MISMATCH")
                if datetime.fromisoformat(control["expires_at"]) - (
                    now or datetime.now(UTC)
                ) < timedelta(days=7):
                    state["rotation"] = {
                        "id": str(uuid.uuid4()),
                        "token": secrets.token_urlsafe(48),
                    }
            self.store.save(state)  # Persist next secret before any future rotation request.
            return control
        except RuntimeError as exc:
            if str(exc) == "SYNC_PAUSED_HTTP_401":
                state["state"] = (
                    "authorization_required"  # Do not misreport expiry as proven revoke.
                )
                self.store.save(state)
            raise

    def revoke_local(self):
        # Explicit local disconnect only; does not pretend to revoke server/browser authorization.
        state = self.store.get()
        state["state"] = "locally_revoked"
        self.store.save(state)
