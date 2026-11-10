"""Real SQLite failure/restart tests. No filesystem filling, native DPAPI or real MT5 claim."""

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from tanren_collector.protocol import batches
from tanren_collector.v2_store import Store
from test_collector import IDENTITY, TestProtector
from test_v2 import receipt


def test_sqlite_full_rolls_back_whole_window_and_checkpoint_then_recovers(tmp_path):
    path = tmp_path / "queue.sqlite"
    store = Store(path, TestProtector())
    end = datetime.now(UTC).isoformat()
    existing = batches(IDENTITY, [], end, end)
    store.capture("retained", existing, "capture_cursor", end)
    # Force SQLITE_FULL inside THIS database, without filling any disk or affecting other files.
    pages = store.db.execute("PRAGMA page_count").fetchone()[0]
    store.db.execute(f"PRAGMA max_page_count={pages}")
    later = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    large = batches(IDENTITY, [{"kind": "fixture", "text": "x" * 200000}], end, later)
    try:
        with pytest.raises(sqlite3.OperationalError, match="full"):
            store.capture("must-rollback", large, "capture_cursor", later)
        assert store.get("capture_cursor") == end
        assert store.window("must-rollback") is None
        assert store.due()[1] == existing[0]
        assert store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        store.close()
    reopened = Store(path, TestProtector())
    try:
        assert reopened.get("capture_cursor") == end
        reopened.db.execute("PRAGMA max_page_count=100000")
        reopened.capture("recovered", large, "capture_cursor", later)
        assert reopened.get("capture_cursor") == later
        assert reopened.counts() == {"pending": 2}
    finally:
        reopened.close()


def test_lost_commit_response_reopens_and_retries_same_batch_before_receipt(tmp_path):
    path = tmp_path / "queue.sqlite"
    end = datetime.now(UTC).isoformat()
    body = batches(IDENTITY, [{"kind": "fixture", "price": "0.000000000001"}], end, end)
    store = Store(path, TestProtector())
    store.capture("window", body, "capture_cursor", end)
    key, original = store.due()
    committed = receipt(original)  # Server committed; response never reaches local received().
    store.retry(key, "NETWORK_UNAVAILABLE", 10, now=100)
    store.close()
    store = Store(path, TestProtector())
    try:
        assert store.due(109) is None
        assert store.due(110) == (key, original)
        store.received(key, committed)  # Same server idempotency receipt on retry.
        assert store.get("received_cursor") == end
        assert store.counts() == {"received": 1}
        assert store.get("last_success") is None  # Raw acknowledgment is not financial success.
        store.processed(key, "processed")
        assert store.counts() == {"processed": 1}
    finally:
        store.close()


def test_force_20_year_range_never_completes_with_only_old_pending_receipt(tmp_path):
    from tanren_collector.engine import Engine
    from test_v2 import NOW

    store = Store(tmp_path / "queue.sqlite", TestProtector())
    sync = str(uuid.uuid4())
    start = NOW - timedelta(days=365 * 20)
    store.save("config", {"token": "synthetic", "identity": IDENTITY})
    store.save("available_start", start.isoformat())
    store.save(
        "sync_jobs",
        {
            sync: {
                "id": sync,
                "state": "scanning",
                "history_start": start.isoformat(),
                "history_end": NOW.isoformat(),
            }
        },
    )

    class Terminal:
        def connect(self):
            pass

        def verify(self):
            pass

        def rows(self, *_):
            return 0

        def read(self, *_):
            return []

    try:
        engine = Engine(store, Terminal(), clock=lambda: NOW)
        count = 0
        while store.get("force:" + sync, start.isoformat()) != NOW.isoformat():
            engine.capture(store.get("config"))
            count += 1
            assert count <= 1100
        assert count == 1043  # ceil(7300 / 7), independently calculated.
        assert not store.sync_ready(sync)
        while pending := store.due():
            key, body = pending
            store.received(key, receipt(body))
        assert store.sync_ready(sync)
        assert store.get("sync_jobs")[sync]["state"] == "scanning"
        assert store.get("last_success") is None
    finally:
        store.close()


def interrupted_capture(path, end, committed):
    """Spawned child exits abruptly inside/beyond real capture transaction; no cleanup handlers."""
    import os

    store = Store(path, TestProtector())
    original = store.put
    if not committed:

        def crash(key, value):
            original(key, value)
            os._exit(37)

        store.put = crash
    body = batches(IDENTITY, [{"kind": "fixture", "amount": "0.000000000001"}], end, end)
    store.capture("crashing-window", body, "capture_cursor", end)
    os._exit(37)


@pytest.mark.parametrize("committed", [False, True])
def test_actual_process_crash_before_or_after_sqlite_commit(tmp_path, committed):
    import multiprocessing

    path = tmp_path / "queue.sqlite"
    store = Store(path, TestProtector())
    end = datetime.now(UTC).isoformat()
    store.save("capture_cursor", "retained-before-crash")
    store.close()
    child = multiprocessing.get_context("spawn").Process(
        target=interrupted_capture, args=(path, end, committed)
    )
    child.start()
    child.join(15)
    if child.is_alive():
        child.terminate()
        child.join(5)
        pytest.fail("Synthetic crash child did not finish")
    assert child.exitcode == 37
    store = Store(path, TestProtector())
    try:
        assert store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert store.get("capture_cursor") == (end if committed else "retained-before-crash")
        assert store.counts() == ({"pending": 1} if committed else {})
        assert store.get("received_cursor") is None
        if committed:
            assert store.due()[1]["records"][0]["amount"] == "0.000000000001"
    finally:
        store.close()
