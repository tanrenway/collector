"""Synthetic adapter/transport, real SQLite crash recovery; no broker dependency."""

import json
import urllib.error
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from tanren_collector.__main__ import cycle
from tanren_collector.client import Api, NoRedirect
from tanren_collector.storage import Queue
from tanren_collector.terminal import Terminal, money


class TestProtector:
    # Test double only. Production constructor always requires Windows user DPAPI.
    __test__ = False

    def seal(self, data):
        return b"test-only:" + data[::-1]

    def open(self, data):
        assert data.startswith(b"test-only:")
        return data[10:][::-1]


IDENTITY = {
    "broker": "Synthetic",
    "server": "Test-Demo",
    "login": "123",
    "currency": "USD",
    "mode": "hedging",
}


class FakeTerminal:
    def __init__(self):
        self.calls = []
        self.failure = False

    def read(self, start, end):
        if self.failure:
            raise RuntimeError("TERMINAL_UNAVAILABLE")
        self.calls.append((start, end))
        return []


class FakeApi:
    def __init__(self):
        self.bodies = []
        self.fail = False
        self.conflict = False

    def call(self, path, body):
        self.bodies.append(json.loads(json.dumps(body)))
        if self.fail:
            raise ConnectionError("timeout after server commit")
        return {"status": "conflict" if self.conflict else "applied"}


def config():
    return {
        "history_start": (datetime.now(UTC) - timedelta(days=3)).isoformat(),
        "identity": IDENTITY,
    }


def test_initial_backfill_increments_and_queue_restart_timeout(tmp_path):
    path = tmp_path / "outbox.sqlite"
    queue = Queue(path, TestProtector())
    terminal = FakeTerminal()
    api = FakeApi()
    settings = config()
    api.fail = True
    with pytest.raises(ConnectionError):
        cycle(queue, terminal, api, settings)
    key, body = queue.pending()
    assert queue.checkpoint("applied") is None
    assert queue.checkpoint("scanned") == body["scanned_until"]
    queue.close()
    queue = Queue(path, TestProtector())
    api.fail = False
    cycle(queue, terminal, api, settings)
    assert api.bodies[0] == api.bodies[1]
    assert queue.pending() is None and queue.checkpoint("applied") == body["scanned_until"]
    cycle(queue, terminal, api, settings)
    assert datetime.fromisoformat(api.bodies[-1]["scanned_until"]) > datetime.fromisoformat(
        body["scanned_until"]
    )
    assert len(terminal.calls) == 2
    assert b'"identity"' not in path.read_bytes()
    queue.close()


def test_terminal_network_conflict_do_not_advance_applied(tmp_path):
    queue = Queue(tmp_path / "q", TestProtector())
    terminal = FakeTerminal()
    api = FakeApi()
    terminal.failure = True
    with pytest.raises(RuntimeError, match="TERMINAL_UNAVAILABLE"):
        cycle(queue, terminal, api, config())
    assert queue.checkpoint("scanned") is None
    terminal.failure = False
    api.conflict = True
    with pytest.raises(RuntimeError, match="SOURCE_CONFLICT"):
        cycle(queue, terminal, api, config())
    assert queue.checkpoint("applied") is None and queue.pending()
    queue.close()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:secret@example.com",
        "file:///tmp/x",
        "https://example.com/path",
        "https://example.com?token=x",
    ],
)
def test_transport_fails_closed(url):
    with pytest.raises(ValueError):
        Api(url, "synthetic-test-credential")


def test_transport_no_redirect_and_revocation_stop():
    assert NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere") is None
    api = Api("https://example.com", "synthetic-test-credential")

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == "https://example.com/api/v1/mt5/collector/control"
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    api.opener = Opener()
    with pytest.raises(RuntimeError, match="SYNC_PAUSED_HTTP_401"):
        api.call("/api/v1/mt5/collector/control")
    with pytest.raises(ValueError):
        api.call("/api/v1/me")


def test_read_allowlist_identity_switch_and_unknown_fields():
    class Bridge:
        switched = False
        connected = False

        def initialize(self, path, /, **kwargs):
            assert path == "C:/explicit/terminal64.exe" and not kwargs
            self.connected = True
            return True

        def account_info(self):
            return SimpleNamespace(
                login=999 if self.switched else 123,
                server="Test-Demo",
                company="Synthetic",
                currency="USD",
                margin_mode=2,
            )

        def terminal_info(self):
            return SimpleNamespace(connected=self.connected)

        def last_error(self):
            return (1, "ok")

        def history_deals_get(self, start, end):
            return [
                SimpleNamespace(
                    ticket=2**63 + 1,
                    position_id=77,
                    order=88,
                    type=0,
                    entry=0,
                    symbol="EURUSD",
                    time_msc=1792483200123,
                    volume=0.1,
                    price=1.12345,
                    profit=0.0,
                    commission=-1.25,
                    swap=0.0,
                    fee=0.0,
                )
            ]

        def history_orders_get(self, start, end):
            return []

        def positions_get(self):
            return []

        def shutdown(self):
            self.connected = False

    bridge = Bridge()
    terminal = Terminal("C:/explicit/terminal64.exe", IDENTITY, bridge)
    terminal.connect()
    rows = terminal.read(datetime.now(UTC) - timedelta(days=1), datetime.now(UTC))
    assert rows[0]["ticket"] == str(2**63 + 1) and rows[0]["sl"] is None
    assert rows[0]["commission"] == "-1.25" and rows[0]["time"].endswith("+00:00")
    bridge.switched = True
    with pytest.raises(RuntimeError, match="IDENTITY_MISMATCH"):
        terminal.read(datetime.now(UTC), datetime.now(UTC))
    terminal.close()
    with pytest.raises(RuntimeError):
        money(float("nan"))


def test_full_replay_highwater_and_initial_backfill_not_reset(tmp_path):
    queue = Queue(tmp_path / "outbox.sqlite", TestProtector())
    terminal = FakeTerminal()
    api = FakeApi()
    settings = config()
    body = {
        "batch_id": "initial",
        "history_start": settings["history_start"],
        "scanned_until": datetime.now(UTC).isoformat(),
    }
    queue.enqueue(body)
    queue.acknowledge("initial", {"status": "applied"}, body["scanned_until"])
    cycle(queue, terminal, api, settings, full=True)
    low = queue.checkpoint("scan_cursor")
    assert datetime.fromisoformat(low) < datetime.fromisoformat(queue.checkpoint("applied"))
    cycle(queue, terminal, api, settings, full=True)
    assert datetime.fromisoformat(queue.checkpoint("scan_cursor")) > datetime.fromisoformat(low)
    queue.close()


def test_queue_single_process_and_adaptive_dense_window(tmp_path):
    queue = Queue(tmp_path / "outbox.sqlite", TestProtector())
    with pytest.raises(OSError):
        Queue(tmp_path / "outbox.sqlite", TestProtector())

    class Dense(FakeTerminal):
        def read(self, start, end):
            self.calls.append((start, end))
            return [{}] * 501 if (end - start).total_seconds() > 100 else []

    terminal = Dense()
    api = FakeApi()
    settings = config()
    cycle(queue, terminal, api, settings)
    first = queue.checkpoint("scan_cursor")
    assert len(terminal.calls) > 1
    cycle(queue, terminal, api, settings)
    assert datetime.fromisoformat(queue.checkpoint("scan_cursor")) > datetime.fromisoformat(first)
    queue.close()


def test_retry_after_and_tls_fail_closed():
    import ssl

    api = Api("https://example.com", "synthetic-test-credential")

    class RateLimited:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 429, "rate limit", {"Retry-After": "300"}, None
            )

    api.opener = RateLimited()
    with pytest.raises(ConnectionError) as failure:
        api.call("/api/v1/mt5/collector/control")
    assert failure.value.retry_after == 300

    class BadTLS:
        def open(self, request, timeout):
            raise urllib.error.URLError(ssl.SSLCertVerificationError())

    api.opener = BadTLS()
    with pytest.raises(RuntimeError, match="TLS_VALIDATION_FAILED"):
        api.call("/api/v1/mt5/collector/control")


def test_partial_receipt_advances_scan_not_financial_checkpoint(tmp_path):
    queue = Queue(tmp_path / "outbox.sqlite", TestProtector())
    first = {
        "batch_id": "partial",
        "history_start": "2026-10-20T00:00:00+00:00",
        "scanned_until": "2026-10-21T00:00:00+00:00",
    }
    queue.enqueue(first)
    queue.acknowledge("partial", {"status": "partial"}, first["scanned_until"])
    assert queue.checkpoint("received") == first["scanned_until"]
    assert queue.checkpoint("scan_cursor") == first["scanned_until"]
    assert queue.checkpoint("applied") is None
    assert queue.pending() is None
    second = {**first, "batch_id": "later", "scanned_until": "2026-10-22T00:00:00+00:00"}
    queue.enqueue(second)
    queue.acknowledge("later", {"status": "applied"}, second["scanned_until"])
    assert queue.checkpoint("received") == second["scanned_until"]
    assert queue.checkpoint("applied") is None
    queue.close()
