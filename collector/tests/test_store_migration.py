"""Bridge release safety for the local outbox schema (v1/v2 -> v3) and downgrade.

fixtures/released_0_8_0_v2_store.py is the store module exactly as shipped in Bridge 0.8.0
(`git show 7022aef:collector/tanren_collector/v2_store.py`, SHA-256 44e7a0ab…c945). Real SQLite,
synthetic records only; no Windows, DPAPI or MT5 claim.
"""

import importlib.util
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
import tanren_collector.v2_store as v2_store
from tanren_collector.engine import safe_error
from tanren_collector.protocol import batches
from tanren_collector.v2_store import Store
from test_collector import TestProtector
from test_v2 import IDENTITY, NOW, receipt

FIXTURE = Path(__file__).parent / "fixtures" / "released_0_8_0_v2_store.py"
P = TestProtector()


def released():
    """Bridge 0.8.0's Store class, loaded inside the current package for its relative imports."""
    spec = importlib.util.spec_from_file_location("tanren_collector._released_v2_store", FIXTURE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Store


def populate(path, binding):
    """A realistic 0.8.0 outbox: received, pending (with a retry) and a 3-fragment window."""
    old = released()(path, P)
    keys = []
    for index, count in enumerate((1, 1, 1001)):
        start = (NOW + timedelta(hours=index)).isoformat()
        end = (NOW + timedelta(hours=index + 1)).isoformat()
        rows = [
            {"kind": "deal", "ticket": str(n), "profit": "1.000000000001"} for n in range(count)
        ]
        parts = batches(IDENTITY, rows if count > 1 else [], start, end)
        window = str(uuid.uuid4())
        old.capture(
            window,
            parts,
            "capture_cursor",
            end,
            provenance={
                "binding_id": binding,
                "epoch": 1,
                "window_id": window,
                "fragment_count": len(parts),
            },
        )
        keys += [p["batch_id"] for p in parts]
    old.save("config", {"binding_id": binding, "identity": IDENTITY})
    old.received(keys[0], receipt({"batch_id": keys[0]}))
    old.retry(keys[1], "NETWORK_UNAVAILABLE", 30)
    snapshot = snapshot_of(old)
    old.close()
    return keys, snapshot


def snapshot_of(store):
    rows = store.db.execute(
        "SELECT sequence,id,window_id,payload,checksum,status,receipt,attempts,next_attempt,error "
        "FROM deliveries ORDER BY sequence"
    ).fetchall()
    metadata = store.db.execute("SELECT key,payload FROM metadata ORDER BY key").fetchall()
    windows = store.db.execute("SELECT id,payload FROM windows ORDER BY id").fetchall()
    return rows, metadata, windows


def version(path):
    db = sqlite3.connect(path)
    try:
        return db.execute("PRAGMA user_version").fetchone()[0]
    finally:
        db.close()


def test_v1_legacy_cli_queue_is_never_upgraded_and_stays_untouched(tmp_path):
    path = tmp_path / "queue.sqlite"
    db = sqlite3.connect(path)
    db.executescript("""
 CREATE TABLE state(key TEXT PRIMARY KEY,value BLOB);
 CREATE TABLE outbox(id TEXT PRIMARY KEY,payload BLOB NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending',receipt BLOB);
 INSERT INTO outbox(id,payload) VALUES('legacy','synthetic');
 """)
    db.close()
    with pytest.raises(RuntimeError, match="QUEUE_SCHEMA_MISMATCH"):
        Store(path, P)
    db = sqlite3.connect(path)
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert db.execute("SELECT id FROM outbox").fetchall() == [("legacy",)]
    db.close()
    assert version(path) == 0 and "deliveries" not in tables


def test_released_v2_outbox_migrates_to_v3_without_changing_any_fact(tmp_path):
    path = tmp_path / "queue.sqlite"
    keys, before = populate(path, str(uuid.uuid4()))
    assert version(path) == 2
    store = Store(path, P)
    assert version(path) == 3
    assert snapshot_of(store) == before  # ids, payloads, checksums, retries, cursor, windows.
    columns = {r[1] for r in store.db.execute("PRAGMA table_info(deliveries)")}
    assert {"quarantined_at", "quarantine_version", "first_failure", "server_failures"} <= columns
    assert store.attempts(keys[1]) == 1 and store.get("capture_cursor")
    # Delivery continues exactly where 0.8.0 stopped: FIFO, same bytes, retry stamp honoured.
    assert store.next_delivery(time.time()) is None
    assert store.next_delivery(time.time() + 3600)[0] == keys[1]
    assert store.counts() == {"received": 1, "pending": len(keys) - 1}
    store.close()


class Bomb(str):
    """A column definition that fails while the migration transaction is open."""

    def split(self, *args):
        raise sqlite3.OperationalError("synthetic failure inside the migration")


def test_failure_inside_the_migration_rolls_back_and_a_reopen_completes_it(tmp_path, monkeypatch):
    path = tmp_path / "queue.sqlite"
    _, before = populate(path, str(uuid.uuid4()))
    columns = v2_store.DEAD_LETTER_COLUMNS
    monkeypatch.setattr(v2_store, "DEAD_LETTER_COLUMNS", (columns[0], Bomb(columns[1])))
    with pytest.raises(sqlite3.OperationalError, match="synthetic"):
        Store(path, P)
    # Rolled back as a whole: still a valid 0.8.0 store, readable by the released Bridge.
    assert version(path) == 2
    old = released()(path, P)
    assert snapshot_of(old) == before
    old.close()
    monkeypatch.setattr(v2_store, "DEAD_LETTER_COLUMNS", columns)
    store = Store(path, P)
    assert version(path) == 3 and snapshot_of(store) == before
    store.close()


KILL = """
import os, sys
sys.path[:0] = sys.argv[2:]
import tanren_collector.v2_store as v2
from test_collector import TestProtector

class Kill(str):
    def split(self, *args):
        os._exit(9)  # The process dies with the migration transaction open.

v2.DEAD_LETTER_COLUMNS = (v2.DEAD_LETTER_COLUMNS[0], Kill(v2.DEAD_LETTER_COLUMNS[1]))
v2.Store(sys.argv[1], TestProtector())
"""


def test_process_killed_mid_migration_leaves_a_consistent_v2_store(tmp_path):
    path = tmp_path / "queue.sqlite"
    _, before = populate(path, str(uuid.uuid4()))
    here = Path(__file__).parent
    result = subprocess.run(  # noqa: S603 - fixed interpreter and a synthetic test script
        [sys.executable, "-c", KILL, str(path), str(here.parent), str(here)],
        env={**os.environ, "PYTHONPATH": ""},
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 9, result.stderr.decode()
    assert version(path) == 2  # The hot journal is rolled back on the next open.
    store = Store(path, P)
    assert version(path) == 3 and snapshot_of(store) == before
    store.close()


def test_older_bridge_refuses_a_v3_store_and_leaves_it_intact(tmp_path):
    path = tmp_path / "queue.sqlite"
    keys, _ = populate(path, str(uuid.uuid4()))
    store = Store(path, P)
    store.quarantine(keys[2], "HTTP_422:INVALID_INPUT")
    after = snapshot_of(store)
    store.close()
    with pytest.raises(RuntimeError, match="QUEUE_SCHEMA_MISMATCH"):
        released()(path, P)  # Bridge 0.8.0 fails closed: no read, no write, no relabel.
    assert version(path) == 3
    store = Store(path, P)
    assert snapshot_of(store) == after
    store.close()
    # 0.8.0 reports this as COLLECTOR_OPERATION_FAILED; this build names the cause.
    assert safe_error(RuntimeError("QUEUE_SCHEMA_MISMATCH")) == "QUEUE_SCHEMA_MISMATCH"


def test_newer_schema_is_refused_by_this_build_with_a_clear_message(tmp_path):
    path = tmp_path / "queue.sqlite"
    Store(path, P).close()
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version=4")
    db.close()
    with pytest.raises(RuntimeError, match="QUEUE_SCHEMA_MISMATCH"):
        Store(path, P)
    assert version(path) == 4
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from tanren_collector.qt.bridge import Bridge
    from tanren_collector.qt.strings import PAIRS

    QApplication.instance() or QApplication([])
    assert Bridge(True).explain("QUEUE_SCHEMA_MISMATCH") in PAIRS["schemaHelp"]
