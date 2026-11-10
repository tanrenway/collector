"""Synthetic Windows Collector contracts; real SQLite, fake DPAPI/MT5/network only."""

import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from tanren_collector.diagnostics import export
from tanren_collector.discovery import candidates
from tanren_collector.engine import CAPTURE_INTERVAL, Engine, backoff, safe_error
from tanren_collector.pairing import advance, begin
from tanren_collector.protocol import PREFIX, V2Api, batches
from tanren_collector.rotation import refresh
from tanren_collector.terminal_v2 import RawTerminal, numeric, observation
from tanren_collector.v2_store import Store
from tanren_collector.windows import FileLock
from test_collector import IDENTITY, TestProtector

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)
ACCOUNT = str(uuid.uuid4())
DEVICE = str(uuid.uuid4())
SYNC = str(uuid.uuid4())


def receipt(body):
    return {
        "batch_id": body["batch_id"],
        "receipt_id": str(uuid.uuid4()),
        "job_id": str(uuid.uuid4()),
        "delivery_status": "received",
    }


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "queue-v2.sqlite", TestProtector())
    result.save(
        "config",
        {
            "token": "synthetic-credential",
            "identity": IDENTITY,
            "account_id": ACCOUNT,
            "device_id": DEVICE,
        },
    )
    yield result
    result.close()


def test_fragment_coverage_and_receipt_checkpoint_are_transactional(store):
    start = (NOW - timedelta(days=2)).isoformat()
    end = NOW.isoformat()
    parts = batches(IDENTITY, [{"kind": "fixture", "x": "0.123456789012"}] * 1001, start, end, SYNC)
    assert [len(p["records"]) for p in parts] == [500, 500, 1]
    assert [p["scanned_until"] for p in parts] == [start, start, end]
    store.capture("window", parts, "capture_cursor", end)
    assert store.get("capture_cursor") == end and store.get("received_cursor") is None
    for index in range(3):
        key, body = store.due()
        assert body == parts[index]
        store.received(key, receipt(body))
        assert store.get("received_cursor") == (end if index == 2 else None)
    assert store.sync_ready(SYNC)
    assert store.counts() == {"received": 3}
    assert (
        store.db.execute("SELECT count(*) FROM deliveries WHERE payload IS NOT NULL").fetchone()[0]
        == 0
    )


def test_restart_retries_identical_id_bytes_and_checksum(tmp_path):
    path = tmp_path / "queue-v2.sqlite"
    parts = batches(IDENTITY, [], NOW.isoformat(), NOW.isoformat())
    with_store = Store(path, TestProtector())
    with_store.capture("w", parts, "capture_cursor", NOW.isoformat())
    with_store.close()
    reopened = Store(path, TestProtector())
    try:
        assert reopened.due()[1] == parts[0]
        assert b'"identity"' not in path.read_bytes()
        with reopened.db:
            reopened.db.execute("UPDATE deliveries SET checksum='tampered'")
        with pytest.raises(RuntimeError, match="CHECKSUM"):
            reopened.due()
    finally:
        reopened.close()


def test_invalid_receipt_capacity_and_exclusive_writer_do_not_advance(store, tmp_path):
    parts = batches(IDENTITY, [], NOW.isoformat(), NOW.isoformat())
    store.capacity = 1
    with pytest.raises(RuntimeError, match="CAPACITY"):
        store.capture("w", parts, "capture_cursor", NOW.isoformat())
    assert store.get("capture_cursor") is None
    store.capacity = 1000000
    store.capture("w", parts, "capture_cursor", NOW.isoformat())
    with pytest.raises(RuntimeError, match="RECEIPT"):
        store.received(parts[0]["batch_id"], {"status": "applied"})
    assert store.due()
    lock = FileLock(tmp_path / "lock")
    try:
        with pytest.raises(OSError):
            FileLock(tmp_path / "lock")
    finally:
        lock.close()


class FakeTerminal:
    def __init__(self):
        self.calls = []
        self.fail = False

    def connect(self):
        if self.fail:
            raise RuntimeError("TERMINAL_DISCONNECTED")

    def verify(self):
        pass

    def available_start(self, now):
        return now - timedelta(days=2), True

    def rows(self, *args):
        return 0

    def read(self, start, end):
        self.calls.append((start, end))
        return []


class FakeServer:
    def __init__(self):
        self.offline = False
        self.calls = []
        self.sync = []
        self.state = "received"
        self.processing = "processed"

    def factory(self, token):
        return self

    def call(self, path, body=None):
        self.calls.append((path, body))
        if self.offline:
            raise ConnectionError("DO_NOT_EXPORT_SECRET")
        if path.endswith("/control"):
            return {
                "account_id": ACCOUNT,
                "device_id": DEVICE,
                "expires_at": (NOW + timedelta(days=30)).isoformat(),
            }
        if path.endswith("/batches"):
            return receipt(body)
        if path.endswith("/sync-jobs"):
            return {"items": self.sync}
        if "/sync-jobs/" in path:
            return {"state": self.state}
        if "/jobs/" in path:
            return {"state": self.processing}
        return {"accepted": True}


def test_network_failure_keeps_capture_and_restart_delivery_idempotent(store):
    terminal = FakeTerminal()
    server = FakeServer()
    server.offline = True
    now = [NOW]
    engine = Engine(store, terminal, server.factory, lambda: now[0])
    first = engine.step()
    assert first["state"] == "waiting_for_network" and len(terminal.calls) == 1
    key, body = store.due(now=NOW.timestamp() + 1000)
    now[0] += timedelta(seconds=CAPTURE_INTERVAL + 1)
    engine.step()
    assert len(terminal.calls) == 2 and store.counts()["pending"] == 2
    server.offline = False
    now[0] += timedelta(minutes=10)
    engine.step()
    assert any(p.endswith("/batches") and b["batch_id"] == key for p, b in server.calls)
    assert body["batch_id"] == key


def test_force_sync_never_completes_after_old_pending_delivery(store):
    terminal = FakeTerminal()
    server = FakeServer()
    old = batches(IDENTITY, [], (NOW - timedelta(days=1)).isoformat(), NOW.isoformat())
    store.capture("old", old, "capture_cursor", NOW.isoformat())
    start = (NOW - timedelta(days=20)).isoformat()
    server.sync = [
        {"id": SYNC, "state": "requested", "history_start": start, "history_end": NOW.isoformat()}
    ]
    now = [NOW]
    engine = Engine(store, terminal, server.factory, lambda: now[0])
    engine.step()
    assert store.get("sync_jobs")[SYNC]["state"] == "scanning"
    assert not any("/sync-jobs/" in p for p, _ in server.calls)
    for _ in range(12):
        now[0] += timedelta(seconds=10)
        engine.step()
    assert store.get("force:" + SYNC) == NOW.isoformat()
    assert store.get("sync_jobs")[SYNC]["state"] != "complete"
    server.state = "partial"
    now[0] += timedelta(seconds=10)
    engine.step()
    assert store.get("sync_jobs")[SYNC]["state"] == "needs_attention"
    server.state = "processed"
    now[0] += timedelta(seconds=10)
    engine.step()
    assert store.get("sync_jobs")[SYNC]["state"] == "complete"
    assert len([1 for p, _ in server.calls if "/sync-jobs/" in p]) >= 2


def test_unavailable_terminal_still_delivers_valid_old_queue(store):
    terminal = FakeTerminal()
    terminal.fail = True
    server = FakeServer()
    parts = batches(IDENTITY, [], NOW.isoformat(), NOW.isoformat())
    store.capture("old", parts, "capture_cursor", NOW.isoformat())
    result = Engine(store, terminal, server.factory, lambda: NOW).step()
    assert result["state"] == "waiting_for_terminal"
    assert not store.counts().get("pending")


def test_pairing_persists_before_claim_and_recovers_lost_response(store):
    begin(store, "synthetic-enrollment", "C:/MT5/terminal64.exe", IDENTITY)
    pending = store.get("pairing")
    calls = []

    class Api:
        def call(self, path, body=None):
            calls.append((path, body))
            assert store.get("pairing")["device"] == pending["device"]
            if len(calls) == 1:
                raise ConnectionError("lost ACK")
            if path.endswith("claim"):
                return {"state": "awaiting_browser_confirmation"}
            return {"state": "confirmed", "account_id": ACCOUNT, "device_id": DEVICE}

    with pytest.raises(ConnectionError):
        advance(store, lambda _: Api())
    assert advance(store, lambda _: Api()) == "awaiting_browser_confirmation"
    assert calls[0][1] == calls[1][1]
    assert advance(store, lambda _: Api()) == "confirmed"
    assert store.get("config")["token"] == pending["device"]
    assert store.get("pairing") is None


def test_rotation_probe_recovers_lost_ack_without_reissuing_or_extending(store):
    store.save("rotation", {"id": str(uuid.uuid4()), "token": "synthetic-next"})
    expected_next = store.get("rotation")["token"]
    used = []

    class Api:
        def call(self, path, body=None):
            assert path.endswith("control")
            return {
                "account_id": ACCOUNT,
                "device_id": DEVICE,
                "expires_at": (NOW + timedelta(days=30)).isoformat(),
            }

    def factory(token):
        used.append(token)
        return Api()

    refresh(store, factory, NOW)
    assert used == ["synthetic-next"] and store.get("rotation") is None
    assert store.get("config")["token"] == expected_next


def test_raw_fields_and_no_local_financial_inference():
    row = SimpleNamespace(
        type=0,
        ticket=88,
        identifier=77,
        symbol="EURUSD",
        time_msc=1792843200123,
        volume=0.5,
        price_open=1.1,
        price_current=1.2,
        profit=12.5,
        swap=-1.25,
        sl=1.09,
        tp=1.2,
        magic=123,
        comment="local note",
        time_update_msc=1792843200123,
    )
    value = observation("position", row)
    assert value["ticket"] == "88" and value["identifier"] == value["position_id"] == "77"
    assert value["profit"] == "12.5" and value["price_open"] == "1.1"
    assert "risk" not in value and "net_pl" not in value
    with pytest.raises(RuntimeError):
        numeric(float("nan"))
    with pytest.raises(RuntimeError, match="PRECISION"):
        numeric("0.1234567890123")


def test_read_v2_snapshots_current_orders_specs_and_identity_switch():
    class MT5:
        switched = False

        def initialize(self, path, /, **kwargs):
            assert path and set(kwargs) == {"timeout"}
            return True

        def account_info(self):
            return SimpleNamespace(
                login=999 if self.switched else 123,
                server=IDENTITY["server"],
                company=IDENTITY["broker"],
                currency="USD",
                margin_mode=2,
                balance=10000,
                equity=10001,
                profit=1,
                margin=0,
                margin_free=10001,
            )

        def terminal_info(self):
            return SimpleNamespace(connected=True)

        def last_error(self):
            return (1, "ok")

        def history_deals_get(self, *_):
            return []

        def history_orders_get(self, *_):
            return []

        def orders_get(self):
            return []

        def positions_get(self):
            return []

    bridge = MT5()
    terminal = RawTerminal("C:/MT5/terminal64.exe", IDENTITY, bridge)
    terminal.connect()
    result = terminal.read(NOW - timedelta(days=1), NOW)
    assert result == [
        {
            "kind": "account",
            "time": result[0]["time"],
            "time_source": "collector_utc",
            "currency": "USD",
            "balance": "10000",
            "equity": "10001",
            "profit": "1",
            "margin": "0",
            "free_margin": "10001",
        }
    ]
    bridge.switched = True
    with pytest.raises(RuntimeError, match="MISMATCH"):
        terminal.read(NOW, NOW)


def test_discovery_dedup_and_diagnostic_secret_exclusion(tmp_path):
    terminal = tmp_path / "Broker" / "terminal64.exe"
    terminal.parent.mkdir()
    terminal.touch()
    assert candidates(running=[terminal], installed=[terminal], roots=[tmp_path]) == [
        {"path": str(terminal), "running": True}
    ]
    destination = tmp_path / "safe.zip"
    export(
        destination,
        [
            {
                "state": "queued",
                "token": "secret",
                "identity": IDENTITY,
                "path": "C:/secret",
                "error": "secret",
                "queue": {"pending": 1, "secret": 7},
            }
        ],
    )
    with zipfile.ZipFile(destination) as archive:
        raw = archive.read("diagnostics.json")
        value = json.loads(raw)
    assert b'"token"' not in raw and b"C:/secret" not in raw and b'"login"' not in raw
    assert value["bindings"][0]["queue"] == {"pending": 1}
    assert safe_error(RuntimeError("PASSWORD=secret")) == "COLLECTOR_OPERATION_FAILED"


def test_v2_route_allowlist_no_arbitrary_urls_and_bounded_backoff():
    api = V2Api("synthetic")
    assert api.allowed_path(PREFIX + "/sync-jobs/" + SYNC)
    assert not api.allowed_path(PREFIX + "/jobs/../credentials")
    assert not api.allowed_path("https://elsewhere.test")
    assert backoff(100, 300) >= 300 and backoff(100) < 304


def test_palette_tokens_match_web_design_registry():
    import re

    from conftest import monorepo_file
    from tanren_collector.palette_tokens import PALETTES

    source = monorepo_file("frontend/lib/palettes.ts").read_text()
    for block in re.findall(r"\{\s*id:.*?\n  \}", source, re.S):
        data = dict(re.findall(r'(\w+): "([^"\n]+)"', block))
        assert PALETTES[data["id"]] == tuple(
            data[k] for k in ("canvas", "surface", "text", "muted", "accent", "accentInk")
        )


def test_capture_rolls_back_all_fragments_if_checkpoint_write_fails(store):
    import sqlite3

    store.db.execute(
        "CREATE TRIGGER fail_cursor BEFORE INSERT ON metadata "
        "WHEN NEW.key='capture_cursor' BEGIN SELECT RAISE(ABORT,'synthetic'); END"
    )
    parts = batches(IDENTITY, [{}] * 501, NOW.isoformat(), NOW.isoformat())
    with pytest.raises(sqlite3.DatabaseError):
        store.capture("w", parts, "capture_cursor", NOW.isoformat())
    assert store.db.execute("SELECT count(*) FROM deliveries").fetchone()[0] == 0
    assert store.db.execute("SELECT count(*) FROM windows").fetchone()[0] == 0
    assert store.get("capture_cursor") is None


def test_bindings_are_independent_and_rebinding_identity_is_forbidden(store, tmp_path):
    other = Store(tmp_path / "other.sqlite", TestProtector())
    try:
        parts = batches(IDENTITY, [], NOW.isoformat(), NOW.isoformat())
        store.capture("one", parts, "capture_cursor", NOW.isoformat())
        assert not other.due() and other.get("capture_cursor") is None
        with pytest.raises(RuntimeError, match="IDENTITY_IMMUTABLE"):
            begin(store, "synthetic", "C:/other/terminal64.exe", {**IDENTITY, "login": "999"})
    finally:
        other.close()


def test_backoff_retries_fifo_and_failed_tls_remains_attention(store):
    parts = batches(IDENTITY, [{}] * 501, NOW.isoformat(), NOW.isoformat())
    store.capture("w", parts, "capture_cursor", NOW.isoformat())
    key = parts[0]["batch_id"]
    store.retry(key, "NETWORK_UNAVAILABLE", 300, now=1000)
    assert store.due(now=1299) is None
    assert store.due(now=1300)[0] == key
    terminal = FakeTerminal()
    server = FakeServer()

    def fail(*args):
        raise RuntimeError("TLS_VALIDATION_FAILED")

    server.call = fail
    assert Engine(store, terminal, server.factory, lambda: NOW).step()["state"] == "needs_attention"
    assert (
        Engine(store, terminal, server.factory, lambda: NOW + timedelta(seconds=10)).step()["state"]
        == "needs_attention"
    )


def test_ack_cleanup_does_not_remove_pending_or_unresolved_metadata(store):
    parts = batches(IDENTITY, [], NOW.isoformat(), NOW.isoformat())
    store.capture("w", parts, "capture_cursor", NOW.isoformat())
    store.compact()
    assert store.due()
    key, body = store.due()
    store.received(key, receipt(body))
    store.processed(key, "partial")
    store.compact()
    assert store.counts() == {"partial": 1} and store.window("w")["received"] is True


def test_force_window_in_future_is_not_certified_before_wall_clock_reaches_end(store):
    terminal = FakeTerminal()
    server = FakeServer()
    server.state = "processed"
    end = (NOW + timedelta(minutes=5)).isoformat()
    server.sync = [
        {
            "id": SYNC,
            "state": "requested",
            "history_start": (NOW - timedelta(days=1)).isoformat(),
            "history_end": end,
        }
    ]
    engine = Engine(store, terminal, server.factory, lambda: NOW)
    engine.step()
    engine.step()
    assert store.get("force:" + SYNC) == NOW.isoformat()
    assert store.get("sync_jobs")[SYNC]["state"] != "complete"
    assert terminal.calls[-1][1] <= NOW


def test_processing_poll_fairness_and_recovery_after_server_retry(store):
    parts = batches(IDENTITY, [{}] * 501, NOW.isoformat(), NOW.isoformat())
    store.capture("w", parts, "capture_cursor", NOW.isoformat())
    for body in parts:
        store.received(body["batch_id"], receipt(body))
    first = parts[0]["batch_id"]
    second = parts[1]["batch_id"]
    store.processed(first, "needs_review")
    assert store.unsettled()[0] == first
    assert store.unsettled()[0] == second
    store.processed(second, "processed")
    assert store.unsettled()[0] == first
    store.processed(first, "queued")
    assert store.counts() == {"processed": 1, "received": 1}
    store.processed(first, "processed")
    assert store.unsettled() is None


def test_explicit_unconfirmed_boolean_is_not_overridden_by_legacy_state(store):
    begin(store, "synthetic-enrollment", "C:/MT5/terminal64.exe", IDENTITY)

    class Api:
        def call(self, path, body=None):
            if path.endswith("claim"):
                return {"state": "awaiting_browser_confirmation"}
            return {
                "confirmed": False,
                "state": "confirmed",
                "account_id": ACCOUNT,
                "device_id": DEVICE,
            }

    assert advance(store, lambda _: Api()) == "awaiting_browser_confirmation"
    assert advance(store, lambda _: Api()) == "awaiting_browser_confirmation"
    assert store.get("pairing") is not None
