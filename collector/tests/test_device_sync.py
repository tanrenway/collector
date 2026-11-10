"""V3 core with real protected SQLite store, mock MT5/server, no Windows claim."""

import uuid
from datetime import timedelta

import pytest
from tanren_collector.device_sync import AccountSync, SyncApi
from tanren_collector.protocol import batches
from tanren_collector.v2_store import Store
from test_collector import TestProtector
from test_v2 import IDENTITY, NOW, FakeTerminal, receipt


class Device:
    def get(self):
        return {"state": "paired", "token": "synthetic-" + str(uuid.uuid4())}


class Server:
    def __init__(self):
        self.calls = []
        self.role = "active"
        self.epoch = 1
        self.fail_ack = False
        self.receipts = {}
        self.leases = {}
        self.sync = []
        self.sync_state = "receiving"
        self.processing = "queued"
        self.stale = False

    def factory(self, _):
        return self

    def call(self, path, body=None):
        self.calls.append((path, body))
        if path.endswith("/lease"):
            key = body["request_id"]
            result = self.leases.setdefault(
                key,
                {
                    "role": "standby" if body["action"] == "release" else self.role,
                    "epoch": self.epoch,
                    "server_time": NOW.isoformat(),
                    "expires_at": (NOW + timedelta(seconds=120)).isoformat(),
                },
            )
            if self.fail_ack:
                self.fail_ack = False
                raise ConnectionError("synthetic lost ACK")
            return result
        if path.endswith("/batches"):
            if self.stale and not body.get("recovery_id"):
                raise RuntimeError("SYNC_PAUSED_HTTP_409")
            return self.receipts.setdefault(body["batch"]["batch_id"], receipt(body["batch"]))
        if path.endswith("/replays"):
            return {"recovery_id": str(uuid.uuid4()), "authoritative_coverage": False}
        if path.endswith("/sync-jobs"):
            return {"items": self.sync}
        if "/sync-jobs/" in path:
            return {"state": self.sync_state, "epoch": self.epoch}
        if "/jobs/" in path:
            return {"state": self.processing}
        return {"accepted": True}


def context(tmp_path, server=None, binding=None):
    binding = binding or str(uuid.uuid4())
    store = Store(tmp_path / "queue.sqlite", TestProtector())
    store.save(
        "config", {"binding_id": binding, "identity": IDENTITY, "account_id": str(uuid.uuid4())}
    )
    terminal = FakeTerminal()
    server = server or Server()
    mono = [0.0]
    sync = AccountSync(store, Device(), binding, terminal, server.factory, lambda: mono[0])
    sync.engine.now = lambda: NOW
    return sync, store, terminal, server, mono


def test_capture_persists_provenance_atomically_and_restart_never_assumes_active(tmp_path):
    sync, store, terminal, server, mono = context(tmp_path)
    with pytest.raises(RuntimeError, match="UNCERTAIN"):
        sync.capture()
    sync.refresh()
    sync.capture()
    key, raw = store.due()
    provenance = store.get("v3_batch:" + key)
    assert provenance["epoch"] == 1 and provenance["binding_id"] == sync.binding
    assert raw["protocol"] == "mt5-v2" and "epoch" not in raw
    old = raw.copy()
    store.close()
    reopened = Store(tmp_path / "queue.sqlite", TestProtector())
    recovered = AccountSync(
        reopened, Device(), sync.binding, terminal, server.factory, lambda: mono[0]
    )
    assert recovered.role == "unknown" and reopened.due()[1] == old
    terminal.fail = True
    server.stale = True
    result = recovered.deliver()  # No terminal access or lease acquisition needed.
    assert result["delivery_status"] == "received"
    assert any(path.endswith("/replays") for path, _ in server.calls)
    assert reopened.get("capture_cursor") == old["scanned_until"]
    assert reopened.counts() == {"received": 1}
    reopened.close()


def test_lost_renewal_ack_requires_fresh_confirmation_and_stale_requests_clear(tmp_path):
    sync, store, _, server, mono = context(tmp_path)
    sync.refresh()
    server.fail_ack = True
    with pytest.raises(ConnectionError):
        sync.lease("renew")
    pending = store.get("v3_lease_request")
    assert sync.role == "unknown" and sync.deadline == 0
    mono[0] = 300
    # Simulate the persisted ACK replay on reconnect; it must not give Active by itself.
    sync.lease()
    assert sync.role == "unknown" and sync.deadline == 300
    assert server.calls[-1][1] == pending
    sync.refresh()
    assert sync.role == "active"

    class Denied:
        def call(self, *_):
            raise RuntimeError("SYNC_PAUSED_HTTP_409")

    sync.factory = lambda _: Denied()
    with pytest.raises(RuntimeError):
        sync.lease("renew")
    assert store.get("v3_lease_request") is None and sync.role == "unknown"
    store.close()


def test_standby_never_reads_terminal_and_multiple_contexts_independent(tmp_path):
    left = tmp_path / "one"
    left.mkdir()
    right = tmp_path / "two"
    right.mkdir()
    standby, one, terminal, server, _ = context(left)
    active, two, terminal2, _, _ = context(right)
    server.role = "standby"
    assert standby.step()["role"] == "standby" and not terminal.calls
    assert active.step()["role"] == "active" and terminal2.calls
    assert not one.get("capture_cursor") and two.get("capture_cursor")
    one.close()
    two.close()


def test_force_requires_real_scan_local_delivery_and_server_processed_current_epoch(tmp_path):
    sync, store, terminal, server, _ = context(tmp_path)
    job = {
        "id": str(uuid.uuid4()),
        "epoch": 1,
        "state": "receiving",
        "history_start": (NOW - timedelta(days=1)).isoformat(),
        "history_end": NOW.isoformat(),
    }
    sync.refresh()
    server.sync = [job]
    sync.force_jobs()
    server.sync_state = "processed"
    sync.poll_force()
    assert store.get("sync_jobs")[job["id"]]["state"] != "complete"  # Old packets cannot finish it.
    sync.capture()
    sync.poll_force()
    assert (
        store.get("sync_jobs")[job["id"]]["state"] != "complete"
    )  # Local capture is not delivery.
    sync.deliver()
    server.epoch = 2
    sync.poll_force()
    assert store.get("sync_jobs")[job["id"]]["state"] != "complete"
    server.epoch = 1
    sync.poll_force()
    assert store.get("sync_jobs")[job["id"]]["state"] == "complete"
    # A takeover must reset the previous epoch's full-range scan cursor.
    sync.epoch = 2
    server.sync = [{**job, "epoch": 2}]
    sync.force_jobs()
    assert store.get("force:" + job["id"]) == job["history_start"]
    store.close()


def test_legacy_pending_never_relabelled_and_transaction_failure_rolls_back(tmp_path, monkeypatch):
    sync, store, _, _, _ = context(tmp_path)
    parts = batches(IDENTITY, [], NOW.isoformat(), NOW.isoformat())
    store.capture("legacy", parts, "capture_cursor", NOW.isoformat())
    with pytest.raises(RuntimeError, match="HANDOVER_REQUIRED"):
        sync.deliver()
    assert store.due()[1] == parts[0]
    original = store.put

    def failed(key, value):
        if key == "capture_cursor":
            raise OSError("synthetic disk failure")
        return original(key, value)

    monkeypatch.setattr(store, "put", failed)
    new = batches(IDENTITY, [], NOW.isoformat(), NOW.isoformat())
    with pytest.raises(OSError):
        store.capture(
            "new",
            new,
            "capture_cursor",
            NOW.isoformat(),
            provenance={"binding_id": sync.binding, "epoch": 1},
        )
    assert not store.get("v3_batch:" + new[0]["batch_id"])
    assert not store.window("new")
    assert store.counts() == {"pending": 1}
    store.close()


def test_v3_transport_allowlist_is_exact():
    api = SyncApi()
    binding = str(uuid.uuid4())
    base = "/api/v1/mt5/collector/v3/accounts/" + binding
    for suffix in [
        "lease",
        "batches",
        "replays",
        "heartbeat",
        "sync-jobs",
        "jobs/" + str(uuid.uuid4()),
        "sync-jobs/" + str(uuid.uuid4()),
    ]:
        assert api.allowed_path(base + "/" + suffix)
    for path in [
        base + "/batches/extra",
        base + "/../control",
        base + "/grants",
        "/api/v1/me",
        base.replace(binding, "not-a-uuid") + "/lease",
    ]:
        assert not api.allowed_path(path)


def test_mid_scan_expiry_and_account_switch_never_commit_capture_cursor(tmp_path):
    sync, store, terminal, server, mono = context(tmp_path)
    sync.refresh()

    def too_slow(*_):
        mono[0] = 111
        return []

    terminal.read = too_slow
    with pytest.raises(RuntimeError, match="UNCERTAIN"):
        sync.capture()
    assert not store.get("capture_cursor") and not store.due()
    mono[0] = 0

    def switched(*_):
        raise RuntimeError("TERMINAL_IDENTITY_MISMATCH")

    terminal.read = switched
    sync.refresh()
    sync.step()
    assert not store.get("capture_cursor") and sync.role == "standby"
    assert any(
        path.endswith("/lease") and body["action"] == "release" for path, body in server.calls
    )
    store.close()


def test_lost_upload_ack_retries_exact_packet_without_duplicate_local_receipt(tmp_path):
    sync, store, _, server, _ = context(tmp_path)
    sync.refresh()
    sync.capture()
    key, original = store.due()
    original_call = server.call
    fail = [True]

    def lost(path, body=None):
        result = original_call(path, body)
        if path.endswith("/batches") and fail[0]:
            fail[0] = False
            raise ConnectionError("network")
        return result

    server.call = lost
    with pytest.raises(ConnectionError):
        sync.deliver()
    assert store.due() == (key, original) and store.counts() == {"pending": 1}
    result = sync.deliver()
    assert result["delivery_status"] == "received" and len(server.receipts) == 1
    sent = [body for path, body in server.calls if path.endswith("/batches")]
    assert sent[0] == sent[1]
    store.close()


@pytest.mark.parametrize(
    "code", ["TERMINAL_UNAVAILABLE", "CHILD_PROCESS_TIMEOUT", "MT5_NATIVE_LOAD_FAILED"]
)
def test_failed_capture_worker_releases_authority_but_retains_pending(tmp_path, code):
    sync, store, terminal, server, _ = context(tmp_path)
    sync.refresh()
    sync.capture()
    pending = store.due()

    def fail(*_):
        raise RuntimeError(code)

    terminal.read = fail
    store.save("last_capture", 0)
    result = sync.step()
    assert result["role"] == "standby" and code in result["errors"]
    assert pending[0] in server.receipts  # Old pending delivery succeeds without capture.
    assert store.counts() == {"received": 1}
    store.close()


@pytest.mark.parametrize("stamp", [None, "invalid", "2026-10-26T09:00:00", "2026-10-26T09:00:00Z"])
def test_presentation_timestamps_require_actual_observation_and_server_processing(tmp_path, stamp):
    sync, store, terminal, server, _ = context(tmp_path)
    assert store.get("last_observed_at") is None
    sync.refresh()
    sync.capture()
    assert store.get("last_observed_at")
    sync.deliver()
    assert store.get("last_processed_at") is None  # Receipt is not processing.
    original = server.call

    def result(path, body=None):
        if "/jobs/" in path:
            return {"state": "processed", "updated_at": stamp}
        return original(path, body)

    server.call = result
    sync.poll_processing()
    assert store.get("last_processed_at") == (
        "2026-10-26T09:00:00+00:00" if stamp and stamp.endswith("Z") else None
    )
    assert store.counts() == {"processed": 1}
    store.close()
