"""R-10: one permanently rejected v3 batch never blocks later facts or the heartbeat.

Real protected SQLite store, synthetic server and terminal only; no Windows or network claim.
"""

import sqlite3
import time
import uuid
from datetime import timedelta

import pytest
from tanren_collector.client import RetryableError
from tanren_collector.device_sync import AccountSync
from tanren_collector.protocol import batches
from tanren_collector.v2_store import Store
from test_collector import TestProtector
from test_device_sync import Device, Server, context
from test_v2 import IDENTITY, NOW


class Rejected(RuntimeError):
    """Shape of client.py's 4xx error: unchanged message plus optional server error code."""

    def __init__(self, status, code=None):
        super().__init__("SYNC_PAUSED_HTTP_" + str(status))
        self.status, self.server_code = status, code


class Poison(Server):
    """Rejects listed batch ids on /batches; everything else behaves like the healthy server."""

    def __init__(self):
        super().__init__()
        self.reject = {}
        self.down = None
        self.heartbeats = 0
        self.replay_error = None

    def call(self, path, body=None):
        if self.down is not None and not path.endswith("/lease"):
            self.calls.append((path, body))
            raise self.down
        if path.endswith("/replays") and self.replay_error is not None:
            self.calls.append((path, body))
            raise self.replay_error
        if path.endswith("/heartbeat"):
            self.heartbeats += 1
        if path.endswith("/batches") and body["batch"]["batch_id"] in self.reject:
            self.calls.append((path, body))
            error = self.reject[body["batch"]["batch_id"]]
            raise error() if callable(error) else error
        return super().call(path, body)


def enqueue(sync, store, count):
    keys = []
    for index in range(count):
        start = (NOW + timedelta(minutes=index)).isoformat()
        end = (NOW + timedelta(minutes=index + 1)).isoformat()
        parts = batches(IDENTITY, [], start, end)
        window = str(uuid.uuid4())
        store.capture(
            window,
            parts,
            "capture_cursor",
            end,
            provenance={
                "binding_id": sync.binding,
                "epoch": 1,
                "window_id": window,
                "fragment_count": len(parts),
            },
        )
        keys += [p["batch_id"] for p in parts]
    return keys


def later():
    """Wall clock that jumps an hour per read, past any capped per-batch backoff."""
    tick = [time.time()]

    def clock():
        tick[0] += 3600
        return tick[0]

    return clock


def poisoned(tmp_path, count=3):
    sync, store, terminal, server, mono = context(tmp_path, Poison())
    server.role = "standby"  # Delivery only: no terminal read, no new captures.
    keys = enqueue(sync, store, count)
    sync.clock = later()  # Per-batch backoff has elapsed at every turn.
    return sync, store, server, keys


def delivered(server):
    return [b["batch"]["batch_id"] for p, b in server.calls if p.endswith("/batches")]


def row(store, key):
    return store.db.execute(
        "SELECT status,attempts,error,payload IS NOT NULL FROM deliveries WHERE id=?", (key,)
    ).fetchone()


@pytest.mark.parametrize(
    ("status", "code", "reason"),
    [
        (422, "INVALID_INPUT", "HTTP_422:INVALID_INPUT"),
        (413, "BODY_TOO_LARGE", "HTTP_413:BODY_TOO_LARGE"),
        (413, None, "HTTP_413"),  # A proxy's bare 413 is just as permanent for these bytes.
        (404, "SYNC_JOB_NOT_FOUND", "HTTP_404:SYNC_JOB_NOT_FOUND"),
        (409, "MT5_BATCH_KEY_CONFLICT", "HTTP_409:MT5_BATCH_KEY_CONFLICT"),
    ],
)
def test_first_poisoned_batch_is_quarantined_and_later_batches_and_heartbeat_continue(
    tmp_path, status, code, reason
):
    sync, store, server, keys = poisoned(tmp_path)
    server.reject[keys[0]] = Rejected(status, code)
    for _ in range(4):
        sync.step()
    assert row(store, keys[0]) == ("quarantined", 1, reason, 1)  # Kept, never deleted.
    assert all(row(store, k)[0] == "received" for k in keys[1:])
    assert store.counts() == {"quarantined": 1, "received": 2}
    assert server.heartbeats == 4
    assert store.quarantined()[0]["reason"] == reason
    # A quarantined window is not "received": force sync and the receipt checkpoint stay honest.
    assert store.get("received_cursor") is None
    store.close()


def test_unfixable_409_after_replay_permit_is_quarantined_but_fixable_409_is_delivered(tmp_path):
    sync, store, server, keys = poisoned(tmp_path)
    attempts = []

    def conflict():
        attempts.append(1)
        return Rejected(409, "CAPTURE_FRAGMENT_CONFLICT")

    server.reject[keys[0]] = conflict
    server.stale = True  # keys[1:] are fixed by the server-issued replay permit.
    for _ in range(3):
        sync.step()
    assert len(attempts) == 2  # Original upload + one upload with the replay permit.
    assert row(store, keys[0])[:3] == ("quarantined", 1, "HTTP_409:CAPTURE_FRAGMENT_CONFLICT")
    assert all(row(store, k)[0] == "received" for k in keys[1:])
    store.close()


@pytest.mark.parametrize(
    "error",
    [
        Rejected(401),
        Rejected(403, "DEVICE_SCOPE_REQUIRED"),
        Rejected(404, "GRANT_NOT_FOUND"),
        Rejected(404),
        Rejected(409, "ACCOUNT_FROZEN"),
        Rejected(409, "CAPTURE_HANDOVER_REQUIRED"),
        Rejected(409),  # No readable server code: never enough to dead-letter facts.
        Rejected(400),  # Bare 400/422 come from intermediaries, not the API.
        Rejected(422),
    ],
)
def test_auth_and_account_state_rejections_pause_in_order_without_quarantine(tmp_path, error):
    sync, store, server, keys = poisoned(tmp_path)
    server.reject = dict.fromkeys(keys, error)
    for _ in range(3):
        result = sync.step()
    assert str(error) in result["errors"]
    assert row(store, keys[0])[:2] == ("pending", 3)
    assert set(delivered(server)) == {keys[0]}  # Strict order kept; nothing skipped.
    assert store.counts() == {"pending": 3} and server.heartbeats == 3
    store.close()


@pytest.mark.parametrize(
    "error",
    [
        RetryableError("RETRY_HTTP_429", 120),
        RetryableError("RETRY_HTTP_500"),
        RetryableError("RETRY_HTTP_502"),
        RetryableError("RETRY_HTTP_503"),
        ConnectionError("NETWORK_OR_TLS_UNAVAILABLE"),  # Timeout.
        RetryableError("NETWORK_UNAVAILABLE"),  # Network drop.
    ],
)
def test_transient_batch_failures_back_off_persist_attempts_and_never_quarantine(tmp_path, error):
    sync, store, server, keys = poisoned(tmp_path)
    sync.clock = time.time
    server.reject[keys[0]] = error
    result = sync.step()
    assert "NETWORK_UNAVAILABLE" in result["errors"]
    status, attempts, code, kept = row(store, keys[0])
    assert (status, attempts, kept) == ("pending", 1, 1) and code
    wait = store.db.execute("SELECT next_attempt FROM deliveries WHERE id=?", keys[:1]).fetchone()
    assert wait[0] > time.time() + (100 if "429" in str(error) else 1)
    assert server.heartbeats == 1  # Liveness independent of the failed upload.
    sync.step()  # Backoff respected: the head is not re-sent and later rows do not jump it.
    assert delivered(server) == [keys[0]]
    # Retry-After of an upload throttles that batch only, never the heartbeat.
    assert server.heartbeats == 2 and sync.network_after == 0
    store.close()


def test_attempts_survive_restart_and_old_v2_database_migrates_forward(tmp_path):
    path = tmp_path / "queue.sqlite"
    old = sqlite3.connect(path)
    old.executescript("""
 CREATE TABLE state(key TEXT PRIMARY KEY,value BLOB);
 CREATE TABLE outbox(id TEXT PRIMARY KEY,payload BLOB NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending',receipt BLOB);
 CREATE TABLE metadata(key TEXT PRIMARY KEY,payload BLOB NOT NULL);
 CREATE TABLE deliveries(
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,window_id TEXT NOT NULL,
 payload BLOB,checksum TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',receipt BLOB,
 attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,error TEXT);
 CREATE INDEX ix_delivery_pending ON deliveries(status,sequence);
 CREATE TABLE windows(id TEXT PRIMARY KEY,payload BLOB NOT NULL);
 PRAGMA user_version=2;
 """)
    old.close()
    sync, store, server, keys = poisoned(tmp_path)
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == 3
    sync.clock = time.time
    server.reject[keys[0]] = RetryableError("RETRY_HTTP_503")
    sync.step()
    store.close()
    reopened = Store(path, TestProtector())  # Restart: a new process, a new AccountSync.
    assert row(reopened, keys[0])[:2] == ("pending", 1)
    again = AccountSync(reopened, Device(), sync.binding, None, server.factory, lambda: 0.0)
    again.clock = later()
    again.step()
    assert row(reopened, keys[0])[:2] == ("pending", 2)  # Counter continues, not reset.
    server.reject.clear()
    for _ in range(3):
        again.step()
    assert reopened.counts() == {"received": 3}
    assert delivered(server)[-3:] == keys  # FIFO preserved through transient failures.
    reopened.close()
    newer = sqlite3.connect(path)
    newer.execute("PRAGMA user_version=4")
    newer.close()
    with pytest.raises(RuntimeError, match="QUEUE_SCHEMA_MISMATCH"):
        Store(path, TestProtector())  # Never silently downgrade a newer local schema.


def test_corrupted_local_batch_is_quarantined_kept_and_does_not_block(tmp_path):
    sync, store, server, keys = poisoned(tmp_path)
    with store.db:
        store.db.execute("UPDATE deliveries SET checksum=? WHERE id=?", ("0" * 64, keys[0]))
    for _ in range(3):
        sync.step()
    assert row(store, keys[0]) == ("quarantined", 0, "QUEUE_CHECKSUM_MISMATCH", 1)
    assert keys[0] not in delivered(server)  # Corrupt bytes are never sent.
    assert all(row(store, k)[0] == "received" for k in keys[1:])
    store.compact()  # Housekeeping never prunes dead-lettered facts or their provenance.
    assert row(store, keys[0])[0] == "quarantined" and store.get("v3_batch:" + keys[0])
    store.close()


def test_requeue_after_cause_fixed_and_automatic_requeue_on_upgrade(tmp_path, monkeypatch):
    sync, store, server, keys = poisoned(tmp_path)
    server.reject[keys[0]] = Rejected(422, "INVALID_INPUT")
    for _ in range(3):
        sync.step()
    assert store.counts() == {"quarantined": 1, "received": 2}
    assert store.requeue_quarantined() == 1  # Explicit hook after the server/app is fixed.
    assert row(store, keys[0])[:3] == ("pending", 0, None)
    sync.step()  # Still rejected: quarantined again, nothing lost.
    assert row(store, keys[0])[0] == "quarantined"
    # Same version on reopen: no automatic loop.
    store.close()
    store = Store(tmp_path / "queue.sqlite", TestProtector())
    assert row(store, keys[0])[0] == "quarantined"
    store.close()
    # An upgraded Bridge (new collector version) re-tries quarantined batches once.
    import tanren_collector.v2_store as module

    monkeypatch.setattr(module, "VERSION", "99.0.0")
    store = Store(tmp_path / "queue.sqlite", TestProtector())
    assert row(store, keys[0])[:2] == ("pending", 0)
    server.reject.clear()
    fixed = AccountSync(store, Device(), sync.binding, None, server.factory, lambda: 0.0)
    fixed.clock = later()
    fixed.step()
    assert store.counts() == {"received": 3}
    assert store.get("received_cursor") == (NOW + timedelta(minutes=3)).isoformat()
    store.close()


def test_long_backend_outage_keeps_everything_queued_in_order(tmp_path):
    sync, store, server, keys = poisoned(tmp_path)
    server.down = RetryableError("RETRY_HTTP_503")
    for _ in range(40):
        sync.network_after = 0  # Simulate the scheduler's later turns.
        result = sync.step()
        assert "NETWORK_UNAVAILABLE" in result["errors"]
    assert store.counts() == {"pending": 3}
    assert row(store, keys[0])[:2] == ("pending", 40)
    assert store.get("v3_network_failures") == 40
    assert sync.network_after - sync.monotonic() <= 303  # Bounded backoff.
    server.down = None
    sync.network_after = 0
    for _ in range(3):
        sync.step()
    assert store.counts() == {"received": 3}
    assert delivered(server)[-3:] == keys
    assert store.get("v3_network_failures") == 0
    store.close()


def test_heartbeat_and_processing_polls_run_while_deliver_fails(tmp_path):
    sync, store, server, keys = poisoned(tmp_path)
    server.reject[keys[1]] = Rejected(401)
    sync.step()  # keys[0] received.
    sync.step()  # keys[1] fails with auth; processing poll + heartbeat still run.
    paths = [p for p, _ in server.calls]
    tail = paths[paths.index(next(p for p in reversed(paths) if p.endswith("/batches"))) :]
    assert any("/jobs/" in p for p in tail) and tail[-1].endswith("/heartbeat")
    assert server.heartbeats == 2
    store.close()


def test_heartbeat_reports_attention_when_only_quarantined_rows_remain(tmp_path):
    sync, store, server, keys = poisoned(tmp_path, count=1)
    server.reject[keys[0]] = Rejected(422, "INVALID_INPUT")
    sync.step()
    sync.step()
    beat = [b for p, b in server.calls if p.endswith("/heartbeat")][-1]
    assert beat["state"] == "needs_attention" and beat["queue_depth"] == 0
    store.close()


def test_client_keeps_only_a_safe_server_error_code():
    import io
    import urllib.error

    from tanren_collector.client import server_code

    def http(body):
        return urllib.error.HTTPError("https://x.invalid", 422, "x", {}, io.BytesIO(body))

    assert server_code(http(b'{"detail":"INVALID_INPUT","fields":[]}')) == "INVALID_INPUT"
    assert server_code(http(b'{"detail":"secret value with spaces"}')) is None
    assert server_code(http(b'{"detail":[{"loc":"x"}]}')) is None
    assert server_code(http(b"not json")) is None
    assert server_code(http(b'{"detail":"' + b"A" * 100 + b'"}')) is None


def fragmented(sync, store, records=1001):
    """One capture window split into several fragments; only the last carries coverage."""
    start, end = NOW.isoformat(), (NOW + timedelta(hours=1)).isoformat()
    rows = [{"kind": "deal", "ticket": str(n)} for n in range(records)]
    parts = batches(IDENTITY, rows, start, end)
    window = str(uuid.uuid4())
    store.capture(
        window,
        parts,
        "capture_cursor",
        end,
        provenance={
            "binding_id": sync.binding,
            "epoch": 1,
            "window_id": window,
            "fragment_count": len(parts),
        },
    )
    return [p["batch_id"] for p in parts], parts


def test_quarantined_fragment_holds_the_rest_of_its_window_until_requeued(tmp_path):
    sync, store, server, _ = poisoned(tmp_path, count=0)
    fragments, parts = fragmented(sync, store)
    after = enqueue(sync, store, 1)  # A later, independent window still flows.
    assert len(fragments) == 3 and parts[0]["scanned_until"] == parts[0]["history_start"]
    server.reject[fragments[0]] = Rejected(422, "INVALID_INPUT")
    for _ in range(5):
        sync.step()
    sent = delivered(server)
    assert row(store, fragments[0])[0] == "quarantined"
    # The coverage-carrying last fragment must never reach the server without fragment 0.
    assert fragments[1] not in sent and fragments[2] not in sent
    assert row(store, fragments[2])[0] == "pending" and row(store, after[0])[0] == "received"
    assert store.get("received_cursor") is None
    server.reject.clear()
    store.requeue_quarantined()
    for _ in range(4):
        sync.step()
    order = [k for k in delivered(server) if k in fragments]
    assert order[-3:] == fragments  # Fragment order within the window is preserved.
    assert all(row(store, k)[0] in {"received", "processed"} for k in fragments)
    assert store.get("received_cursor") == (NOW + timedelta(minutes=1)).isoformat()
    store.close()


def test_deterministic_5xx_is_exhausted_after_24h_only_while_the_server_is_reachable(tmp_path):
    sync, store, server, keys = poisoned(tmp_path)
    server.reject[keys[0]] = RetryableError("RETRY_HTTP_503")
    for _ in range(30):  # later(): one hour of wall clock per turn, heartbeat succeeds.
        sync.step()
    status, attempts, reason, kept = row(store, keys[0])
    assert (status, reason, kept) == ("quarantined", "RETRY_EXHAUSTED:HTTP_503", 1)
    assert attempts >= 24
    assert all(row(store, k)[0] in {"received", "processed"} for k in keys[1:])
    assert store.requeue_quarantined() == 1  # Re-queueable like any quarantine.
    assert row(store, keys[0])[:2] == ("pending", 0)
    store.close()


def test_clock_moved_backwards_and_sync_now_never_stall_the_queue(tmp_path):
    sync, store, server, keys = poisoned(tmp_path)
    sync.clock = time.time
    with store.db:  # Backoff stamped by a clock that was 10 days fast.
        store.db.execute(
            "UPDATE deliveries SET next_attempt=? WHERE id=?", (time.time() + 864000, keys[0])
        )
    sync.step()
    assert row(store, keys[0])[0] in {"received", "processed"}
    with store.db:  # A legitimate Retry-After within a day is still honoured ...
        store.db.execute(
            "UPDATE deliveries SET next_attempt=? WHERE id=?", (time.time() + 3600, keys[1])
        )
    sync.step()
    assert row(store, keys[1])[0] == "pending"
    assert store.retry_now() == 1  # ... until the user presses Sync now.
    sync.step()
    assert row(store, keys[1])[0] in {"received", "processed"}
    store.close()


@pytest.mark.parametrize(
    "replay_error",
    [Rejected(404, "GRANT_NOT_FOUND"), Rejected(403, "DEVICE_SCOPE_REQUIRED"), Rejected(401)],
)
def test_409_followed_by_an_auth_or_grant_answer_is_never_quarantined(tmp_path, replay_error):
    sync, store, server, keys = poisoned(tmp_path)
    server.reject[keys[0]] = Rejected(409, "MT5_BATCH_KEY_CONFLICT")
    server.replay_error = replay_error
    for _ in range(2):
        sync.step()
    assert row(store, keys[0])[:2] == ("pending", 2) and store.counts() == {"pending": 3}
    store.close()


def test_invalid_receipt_after_replay_is_retried_not_quarantined(tmp_path):
    sync, store, server, keys = poisoned(tmp_path)
    calls = []

    def first_conflict_then_bad_receipt(path, body=None):
        if path.endswith("/batches") and body["batch"]["batch_id"] == keys[0]:
            calls.append(body)
            if len(calls) % 2:
                raise Rejected(409, "MT5_BATCH_KEY_CONFLICT")
            return {"batch_id": keys[0], "delivery_status": "bogus"}
        return Poison.call(server, path, body)

    server.call = first_conflict_then_bad_receipt
    sync.step()
    assert row(store, keys[0])[:3] == ("pending", 1, "INVALID_SERVER_RECEIPT")
    store.close()


def test_replay_denied_after_a_batch_specific_conflict_is_quarantined(tmp_path):
    sync, store, server, keys = poisoned(tmp_path)
    server.reject[keys[0]] = Rejected(409, "MT5_BATCH_KEY_CONFLICT")
    server.replay_error = Rejected(409, "CAPTURE_RECOVERY_DENIED")
    for _ in range(3):
        sync.step()
    assert row(store, keys[0])[:3] == ("quarantined", 1, "HTTP_409:MT5_BATCH_KEY_CONFLICT")
    store.close()


def test_batch_key_held_under_other_provenance_is_quarantined_with_facts_kept(tmp_path):
    # The server compares provenance only, never content: its copy is NOT proof of these facts.
    sync, store, server, keys = poisoned(tmp_path)
    server.reject[keys[0]] = Rejected(409, "CAPTURE_REQUEST_CONFLICT")
    for _ in range(4):
        sync.step()
    assert row(store, keys[0]) == ("quarantined", 1, "HTTP_409:CAPTURE_REQUEST_CONFLICT", 1)
    checksum = store.db.execute("SELECT checksum FROM deliveries WHERE id=?", keys[:1]).fetchone()
    assert checksum[0] and store.get("v3_batch:" + keys[0])
    assert all(row(store, k)[0] in {"received", "processed"} for k in keys[1:])
    assert store.get("received_cursor") is None  # The window is not counted as received.
    for _ in range(3):
        store.compact()
    assert row(store, keys[0]) == ("quarantined", 1, "HTTP_409:CAPTURE_REQUEST_CONFLICT", 1)
    store.close()


def test_5xx_streak_is_broken_by_other_failures_and_counted_separately(tmp_path):
    sync, store, server, keys = poisoned(tmp_path)
    errors = iter(
        [RetryableError("RETRY_HTTP_503")]
        + [RetryableError("NETWORK_UNAVAILABLE")] * 30
        + [RetryableError("RETRY_HTTP_503")] * 3
    )
    server.reject[keys[0]] = lambda: next(errors)
    for _ in range(34):  # later(): an hour per turn; heartbeat keeps succeeding.
        sync.step()
    status, attempts, reason, kept = row(store, keys[0])
    assert status == "pending" and attempts == 34  # One 5xx + a day of network + 5xx: no.
    since, streak = store.db.execute(
        "SELECT first_failure,server_failures FROM deliveries WHERE id=?", keys[:1]
    ).fetchone()
    assert streak == 3 and since is not None
    store.close()


def test_store_at_unreleased_v3_without_newer_columns_is_completed_idempotently(tmp_path):
    path = tmp_path / "queue.sqlite"
    store = Store(path, TestProtector())
    store.close()
    old = sqlite3.connect(path)  # Shape written by 645ab10 (v3 without the streak columns).
    old.executescript("""
 ALTER TABLE deliveries DROP COLUMN first_failure;
 ALTER TABLE deliveries DROP COLUMN server_failures;
 """)
    old.close()
    for _ in range(2):
        store = Store(path, TestProtector())
        columns = {r[1] for r in store.db.execute("PRAGMA table_info(deliveries)")}
        assert {"first_failure", "server_failures", "quarantined_at"} <= columns
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 3
        store.close()


def test_diagnostics_export_quarantine_reason_counts_only(tmp_path):
    import json
    import zipfile

    from tanren_collector.diagnostics import export

    destination = tmp_path / "diag.zip"
    export(
        destination,
        [
            {
                "state": "needs_attention",
                "queue": {"quarantined": 2},
                "quarantine_reasons": {
                    "HTTP_422:INVALID_INPUT": 1,
                    "RETRY_EXHAUSTED:HTTP_503": 1,
                    "secret /path/payload": 5,
                },
            }
        ],
    )
    with zipfile.ZipFile(destination) as archive:
        report = json.loads(archive.read("diagnostics.json"))
    binding = report["bindings"][0]
    assert binding["queue"]["quarantined"] == 2
    assert binding["quarantine_reasons"] == {
        "HTTP_422:INVALID_INPUT": 1,
        "RETRY_EXHAUSTED:HTTP_503": 1,
    }


def test_client_sends_the_same_compact_utf8_bytes_the_size_cap_measures(monkeypatch):
    import io

    from tanren_collector import client
    from tanren_collector.protocol import encoded

    sent = []

    class Opener:
        def open(self, request, timeout):
            sent.append(request.data)
            return io.BytesIO(b"{}")

    api = client.Api("https://example.invalid", "synthetic")
    api.opener = Opener()
    monkeypatch.setattr(client, "require_network", lambda: None)
    body = {"comment": "Купівля", "b": [1, 2]}
    api.call("/api/v1/mt5/collector/batches", body)
    assert sent == [encoded(body)]


@pytest.mark.parametrize(
    "answer",
    [
        lambda key: {"batch_id": key, "delivery_status": "received", "job_id": "not-a-uuid"},
        lambda key: {"batch_id": key, "delivery_status": "received"},  # Missing ids.
        lambda key: {"batch_id": str(uuid.uuid4()), "delivery_status": "received"},
        lambda key: ["unexpected", "shape"],
        lambda key: (_ for _ in ()).throw(ValueError("non-JSON 200 body")),
    ],
)
def test_incompatible_server_answers_retry_with_facts_kept_then_redeliver(tmp_path, answer):
    sync, store, server, keys = poisoned(tmp_path)
    original = Poison.call
    broken = [True]

    def incompatible(path, body=None):
        if path.endswith("/batches") and broken[0]:
            server.calls.append((path, body))
            return answer(body["batch"]["batch_id"])
        return original(server, path, body)

    server.call = incompatible
    sync.step()
    status, attempts, _, kept = row(store, keys[0])
    assert (status, attempts, kept) == ("pending", 1, 1)  # Never quarantined, never lost.
    assert server.heartbeats == 1
    broken[0] = False  # Server fixed / reconnect: the SAME bytes are redelivered.
    for _ in range(3):
        sync.step()
    sent = [
        b for p, b in server.calls if p.endswith("/batches") and b["batch"]["batch_id"] == keys[0]
    ]
    assert sent[0] == sent[-1] and len(sent) == 2
    assert all(row(store, k)[0] in {"received", "processed"} for k in keys)
    store.close()


class Suspended(Poison):
    """K37 server for a suspended owner: every device call answers 403 ACCOUNT_SUSPENDED."""

    def __init__(self):
        super().__init__()
        self.suspended = True

    def call(self, path, body=None):
        if self.suspended:
            self.calls.append((path, body))
            raise Rejected(403, "ACCOUNT_SUSPENDED")
        return super().call(path, body)


def test_suspended_account_pauses_keeps_the_queue_and_resumes_after_reactivation(tmp_path):
    from tanren_collector.engine import safe_error

    assert safe_error(Rejected(403, "ACCOUNT_SUSPENDED")) == "ACCOUNT_SUSPENDED"
    assert safe_error(Rejected(403, "DEVICE_SCOPE_REQUIRED")) == "SYNC_PAUSED_HTTP_403"
    sync, store, terminal, server, mono = context(tmp_path, Suspended())
    server.role = "standby"
    keys = enqueue(sync, store, 2)
    sync.clock = later()
    result = sync.step()
    assert result["errors"][0] == "ACCOUNT_SUSPENDED"  # Lease answer; not "pair again".
    assert store.counts() == {"pending": 2}  # Nothing quarantined, nothing dropped.
    assert any(p.endswith("/heartbeat") for p, _ in server.calls)  # Liveness still probed.
    assert sync.network_after > mono[0]  # Calm backoff while suspended.
    mono[0] = sync.network_after + 1
    server.suspended = False  # Owner reactivated: the same device and queue continue.
    for _ in range(3):
        sync.step()
    assert all(row(store, k)[0] == "received" for k in keys)
    store.close()


def test_heartbeat_runs_when_the_terminal_read_fails(tmp_path):
    sync, store, terminal, server, mono = context(tmp_path, Poison())
    keys = enqueue(sync, store, 1)
    sync.clock = later()

    def broken(*_args, **_kwargs):
        raise RuntimeError("TERMINAL_DISCONNECTED")

    sync.capture = broken
    result = sync.step()
    assert "TERMINAL_DISCONNECTED" in result["errors"]
    assert row(store, keys[0])[0] == "received"  # Delivery independent of the terminal.
    beat = [b for p, b in server.calls if p.endswith("/heartbeat")][-1]
    assert beat["terminal_connected"] is False
    store.close()
