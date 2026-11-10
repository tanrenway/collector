"""Opt-in device store tests with reversible protector, no native DPAPI claim."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from tanren_collector.device_pairing import DeviceApi, DeviceStore, PairingSession, digest, phrase
from test_collector import TestProtector


class Service:
    def __init__(self):
        self.confirmed = False
        self.lose_claim = False
        self.lose_rotate = False
        self.claims = []
        self.rotation_count = 0
        self.identifier = str(uuid.uuid4())
        self.device = str(uuid.uuid4())
        self.accepted = set()
        self.expires = datetime.now(UTC) + timedelta(days=90)

    def factory(self, token=""):
        service = self

        class Api:
            def call(self, path, body=None):
                if path.endswith("/pairing/claim"):
                    service.claims.append(body)
                    service.body = body
                    result = {
                        "id": service.identifier,
                        "verification_phrase": phrase(
                            service.identifier,
                            body["request_id"],
                            body["claim_digest"],
                            body["device_digest"],
                        ),
                    }
                    if service.lose_claim:
                        service.lose_claim = False
                        raise ConnectionError("NETWORK_UNAVAILABLE")
                    return result
                if path.endswith("/pairing"):
                    return {
                        "id": service.identifier,
                        "verification_phrase": phrase(
                            service.identifier,
                            service.body["request_id"],
                            service.body["claim_digest"],
                            service.body["device_digest"],
                        ),
                        "state": "confirmed"
                        if service.confirmed
                        else "awaiting_browser_confirmation",
                    }
                if path.endswith("/control"):
                    if digest(token) not in service.accepted:
                        raise RuntimeError("SYNC_PAUSED_HTTP_401")
                    return {
                        "id": service.device,
                        "expires_at": service.expires.isoformat(),
                        "grants": [],
                    }
                if path.endswith("/credentials/rotate"):
                    service.rotation_count += 1
                    service.accepted.add(body["next_digest"])
                    service.expires = datetime.now(UTC) + timedelta(days=90)
                    if service.lose_rotate:
                        service.lose_rotate = False
                        raise ConnectionError("NETWORK_UNAVAILABLE")
                    return {"rotation_id": body["rotation_id"]}
                raise AssertionError("Unexpected route")

        return Api()

    def confirm(self):
        self.confirmed = True
        self.accepted.add(self.body["device_digest"])


def test_claim_persist_before_network_and_reopen_exact_retry(tmp_path):
    queue = tmp_path / "v2" / "bindings" / "fixture"
    queue.mkdir(parents=True)
    marker = queue / "queue-v2.sqlite"
    marker.write_bytes(b"untouched protected account queue")
    service = Service()
    service.lose_claim = True
    store = DeviceStore(tmp_path / "device-v3", TestProtector())
    session = PairingSession(store, service.factory)
    session.begin("ABCD-EFGH-JKMP", "Synthetic device")
    saved = store.get()
    assert saved["token"] != saved["claim"]
    with pytest.raises(ConnectionError):
        session.advance()
    assert store.get() == saved
    store.close()
    store = DeviceStore(tmp_path / "device-v3", TestProtector())
    session = PairingSession(store, service.factory)
    assert session.advance()["state"] == "awaiting_browser_confirmation"
    assert service.claims[0] == service.claims[1]
    assert "code" not in store.get()
    service.confirm()
    assert session.advance()["state"] == "paired"
    assert "claim" not in store.get()
    assert session.control()["id"] == service.device
    assert marker.read_bytes() == b"untouched protected account queue"
    store.close()


def test_confirmation_expiry_recovery_probes_permanent_credential_first(tmp_path):
    service = Service()
    store = DeviceStore(tmp_path, TestProtector())
    session = PairingSession(store, service.factory)
    session.begin("ABCD-EFGH-JKMP", "Synthetic")
    session.advance()
    service.confirm()
    # If claim polling were attempted after code expiry this fixture would fail.
    original = service.factory

    def factory(token=""):
        assert digest(token) != store.get().get("claim_digest")
        if token == store.get().get("claim"):
            raise AssertionError("Must recover through permanent secret")
        return original(token)

    session.factory = factory
    assert session.advance()["state"] == "paired"
    store.close()


def test_rotation_lost_ack_restart_and_revocation_state(tmp_path):
    service = Service()
    store = DeviceStore(tmp_path, TestProtector())
    session = PairingSession(store, service.factory)
    session.begin("ABCD-EFGH-JKMP", "Synthetic")
    session.advance()
    service.confirm()
    session.advance()
    old = store.get()["token"]
    service.expires = datetime.now(UTC) + timedelta(days=1)
    session.control()
    next_token = store.get()["rotation"]["token"]
    assert next_token != old
    service.lose_rotate = True
    with pytest.raises(ConnectionError):
        session.control()
    store.close()
    store = DeviceStore(tmp_path, TestProtector())
    session = PairingSession(store, service.factory)
    assert session.control()["id"] == service.device
    assert store.get()["token"] == next_token and "rotation" not in store.get()
    assert service.rotation_count == 1
    service.accepted.clear()
    with pytest.raises(RuntimeError, match="HTTP_401"):
        session.control()
    assert store.get()["state"] == "authorization_required"
    session.revoke_local()
    assert session.advance()["state"] == "locally_revoked"
    store.close()


def test_no_implicit_reset_no_arbitrary_routes_and_atomic_write_failure(tmp_path, monkeypatch):
    store = DeviceStore(tmp_path, TestProtector())
    session = PairingSession(store, Service().factory)
    session.begin("ABCD-EFGH-JKMP", "Synthetic")
    with pytest.raises(RuntimeError, match="DEVICE_STATE_EXISTS"):
        session.begin("x", "other")
    previous = store.path.read_bytes()
    from pathlib import Path

    original = Path.replace

    def failed_replace(self, target):
        raise OSError("synthetic failed durable replacement")

    monkeypatch.setattr(Path, "replace", failed_replace)
    with pytest.raises(OSError):
        store.save({"state": "must not commit"})
    assert store.path.read_bytes() == previous
    monkeypatch.setattr(Path, "replace", original)
    api = DeviceApi("fixture")
    assert not api.allowed_path("/api/v1/me")
    assert not api.allowed_path("/api/v1/mt5/collector/v2/batches")
    assert not api.allowed_path("/api/v1/mt5/collector/v3/accounts/register")
    assert api.allowed_path("/api/v1/mt5/collector/v3/control")
    with pytest.raises(RuntimeError):
        DeviceStore.current_user() if __import__("os").name != "nt" else session.begin("x", "x")
    store.close()


@pytest.mark.skipif(os.name != "nt", reason="Native current-user Windows DPAPI required")
def test_native_device_store_dpapi_roundtrip(tmp_path):
    import secrets

    from tanren_collector.storage import DPAPI

    value = secrets.token_urlsafe(48)
    store = DeviceStore(tmp_path, DPAPI())
    store.save({"token": value})
    assert value.encode() not in store.path.read_bytes()
    store.close()
    store = DeviceStore(tmp_path, DPAPI())
    assert store.get()["token"] == value
    store.close()


def _store(tmp_path):
    return DeviceStore(tmp_path / "device-v3", TestProtector())


@pytest.mark.parametrize("state", ["authorization_required", "locally_revoked"])
def test_new_code_replaces_a_pairing_that_never_produced_a_device(tmp_path, state):
    store = _store(tmp_path)
    store.save({"state": state, "pairing_id": "old", "request_id": "old", "name": "Old"})
    PairingSession(store).begin("NEW-CODE", "New")
    saved = store.get()
    assert saved["state"] == "claiming" and saved["code"] == "NEW-CODE"
    assert saved["name"] == "New" and "pairing_id" not in saved
    store.close()


@pytest.mark.parametrize(
    "state", ["paired", "authorization_required", "awaiting_browser_confirmation"]
)
def test_new_code_never_replaces_a_real_or_active_device(tmp_path, state):
    store = _store(tmp_path)
    existing = {"state": state, "device_id": "device"}
    if state == "awaiting_browser_confirmation":
        existing = {"state": state, "pairing_id": "pending"}
    store.save(existing)
    with pytest.raises(RuntimeError, match="DEVICE_STATE_EXISTS"):
        PairingSession(store).begin("NEW-CODE", "New")
    assert store.get() == existing
    store.close()


def test_rejected_code_can_be_replaced_with_a_new_one(tmp_path):
    class Rejecting:
        def __init__(self, token=""):
            pass

        def call(self, path, body=None):
            raise RuntimeError("SYNC_PAUSED_HTTP_401")

    store = _store(tmp_path)
    session = PairingSession(store, Rejecting)
    session.begin("WRONG-CODE", "Legion")
    with pytest.raises(RuntimeError, match="SYNC_PAUSED_HTTP_401"):
        session.advance()
    assert store.get()["state"] == "authorization_required"
    session.begin("RIGHT-CODE", "Legion")
    assert store.get()["state"] == "claiming" and store.get()["code"] == "RIGHT-CODE"
    store.close()
