"""Per-binding DPAPI SQLite outbox. Capture, delivery and financial status are distinct."""

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

from .protocol import VERSION, encoded
from .storage import Queue

SCHEMA = 3  # v3 adds the dead-letter (quarantine) columns; pending+quarantined = not received.
DEAD_LETTER_COLUMNS = (
    "quarantined_at REAL",
    "quarantine_version TEXT",
    "first_failure REAL",  # Start of the current consecutive 5xx streak.
    "server_failures INTEGER NOT NULL DEFAULT 0",  # Length of that streak.
)
SCHEMA_V3 = (
    "CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,payload BLOB NOT NULL)",
    "CREATE TABLE IF NOT EXISTS deliveries("
    "sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,window_id TEXT NOT NULL,"
    "payload BLOB,checksum TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',receipt BLOB,"
    "attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,error TEXT,"
    + ",".join(DEAD_LETTER_COLUMNS)
    + ")",
    "CREATE INDEX IF NOT EXISTS ix_delivery_pending ON deliveries(status,sequence)",
    "CREATE TABLE IF NOT EXISTS windows(id TEXT PRIMARY KEY,payload BLOB NOT NULL)",
)
# Longest legitimate wait (Retry-After cap) plus jitter; a later stamp means the clock jumped.
MAX_WAIT = 86400 + 60


class Store(Queue):
    """Separate v2 database: never upgrades/relabels a legacy CLI queue."""

    def __init__(self, path, protector, capacity=100_000_000):
        super().__init__(path, protector)
        self.capacity = capacity
        self.db.execute("PRAGMA secure_delete=ON")
        # Version check and roll-forward (0/2 -> 3) in ONE write transaction; user_version is
        # re-read under the write lock so a concurrent opener cannot migrate twice.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 2, SCHEMA) or (
                version == 0 and self.db.execute("SELECT count(*) FROM outbox").fetchone()[0]
            ):
                raise RuntimeError("QUEUE_SCHEMA_MISMATCH")
            for statement in SCHEMA_V3:
                self.db.execute(statement)
            # Additive columns, idempotent: v2 stores and unreleased early-v3 stores alike.
            present = {r[1] for r in self.db.execute("PRAGMA table_info(deliveries)")}
            for column in DEAD_LETTER_COLUMNS:
                if column.split()[0] not in present:
                    self.db.execute("ALTER TABLE deliveries ADD COLUMN " + column)
            if version != SCHEMA:
                self.db.execute("PRAGMA user_version=3")
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            self.close()
            raise
        # An upgraded Bridge retries batches an older build quarantined, once per version.
        self.requeue_quarantined(only_other_versions=True)

    def get(self, key, default=None):
        row = self.db.execute("SELECT payload FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(self.protector.open(row[0])) if row else default

    def put(self, key, value):
        self.db.execute(
            "INSERT OR REPLACE INTO metadata VALUES(?,?)",
            (key, self.protector.seal(encoded(value))),
        )

    def save(self, key, value):
        with self.db:
            self.put(key, value)

    def size(self):
        return sum(
            p.stat().st_size
            for p in Path(self.db_path).parent.glob(Path(self.db_path).name + "*")
            if p.is_file()
        )

    def capture(self, window_id, bodies, cursor_key, end, provenance=None):
        protected = [(b, self.protector.seal(encoded(b))) for b in bodies]
        used_pages = (
            self.db.execute("PRAGMA page_count").fetchone()[0]
            - self.db.execute("PRAGMA freelist_count").fetchone()[0]
        )
        used = used_pages * self.db.execute("PRAGMA page_size").fetchone()[0]
        if used + sum(len(blob) for _, blob in protected) + 65536 > self.capacity:
            raise RuntimeError("QUEUE_CAPACITY_REACHED")
        window = {
            "start": bodies[0]["history_start"],
            "end": end,
            "cursor_key": cursor_key,
            "sync_id": bodies[0].get("sync_job_id"),
            "received": False,
        }
        with self.db:
            self.db.execute(
                "INSERT INTO windows VALUES(?,?)", (window_id, self.protector.seal(encoded(window)))
            )
            for index, (body, blob) in enumerate(protected):
                if provenance is not None:
                    self.put(
                        "v3_batch:" + body["batch_id"], {**provenance, "fragment_index": index}
                    )
                self.db.execute(
                    "INSERT INTO deliveries(id,window_id,payload,checksum) VALUES(?,?,?,?)",
                    (body["batch_id"], window_id, blob, hashlib.sha256(encoded(body)).hexdigest()),
                )
            self.put(cursor_key, end)  # Durable CAPTURE cursor, not delivered/applied checkpoint.

    def due(self, now=None):
        row = self.db.execute(
            "SELECT id,payload,checksum,next_attempt FROM deliveries "
            "WHERE status='pending' ORDER BY sequence LIMIT 1"
        ).fetchone()
        if not row or row[3] > (time.time() if now is None else now):
            return None
        raw = self.protector.open(row[1])
        if hashlib.sha256(raw).hexdigest() != row[2]:
            raise RuntimeError("QUEUE_CHECKSUM_MISMATCH")
        return row[0], json.loads(raw)

    def received(self, key, receipt):
        if receipt.get("batch_id") != key or receipt.get("delivery_status") != "received":
            raise RuntimeError("INVALID_SERVER_RECEIPT")
        # Validate technical IDs before storing/using as routes. No financial ACK substitution.
        import uuid

        uuid.UUID(receipt["job_id"])
        uuid.UUID(receipt["receipt_id"])
        row = self.db.execute(
            "SELECT window_id FROM deliveries WHERE id=? AND status='pending'", (key,)
        ).fetchone()
        if not row:
            raise RuntimeError("UNKNOWN_PENDING_BATCH")
        with self.db:
            self.db.execute(
                "UPDATE deliveries SET status='received',receipt=?,payload=NULL,error=NULL "
                "WHERE id=?",
                (self.protector.seal(encoded(receipt)), key),
            )
            self.settle_window(row[0])

    def settle_window(self, window_id):
        pending = self.db.execute(
            "SELECT count(*) FROM deliveries WHERE window_id=? "
            "AND status IN ('pending','quarantined')",
            (window_id,),
        ).fetchone()[0]
        if not pending:
            window = self.window(window_id)
            window["received"] = True
            self.db.execute(
                "UPDATE windows SET payload=? WHERE id=?",
                (self.protector.seal(encoded(window)), window_id),
            )
            if window["cursor_key"] == "capture_cursor":
                self.advance_received_cursor()

    def advance_received_cursor(self):
        """Receipt checkpoint stays contiguous: it never passes a pending/quarantined window."""
        rows = self.db.execute(
            "SELECT window_id,sum(status IN ('pending','quarantined')) FROM deliveries "
            "GROUP BY window_id ORDER BY min(sequence)"
        ).fetchall()
        cursor = None
        for window_id, unreceived in rows:
            window = self.window(window_id)
            if not window or window["cursor_key"] != "capture_cursor":
                continue
            if unreceived:
                break
            cursor = window["end"]
        prior = self.get("received_cursor")
        if cursor and (
            prior is None or datetime.fromisoformat(cursor) > datetime.fromisoformat(prior)
        ):
            self.put("received_cursor", cursor)

    def window(self, key):
        row = self.db.execute("SELECT payload FROM windows WHERE id=?", (key,)).fetchone()
        return json.loads(self.protector.open(row[0])) if row else None

    def next_delivery(self, now=None):
        """Oldest due pending row. A locally corrupted row is quarantined (kept), not sent.

        Rows after a quarantined fragment of the SAME window are held: earlier fragments carry
        zero-length coverage and only the last certifies the window, so sending the rest would
        let the server count the window complete without the quarantined facts.
        """
        now = time.time() if now is None else now
        while True:
            row = self.db.execute(
                "SELECT id,payload,checksum,next_attempt FROM deliveries d "
                "WHERE status='pending' AND NOT EXISTS(SELECT 1 FROM deliveries q "
                "WHERE q.window_id=d.window_id AND q.sequence<d.sequence "
                "AND q.status='quarantined') ORDER BY sequence LIMIT 1"
            ).fetchone()
            # A stamp further ahead than any legitimate wait means the clock moved back.
            if not row or now < row[3] <= now + MAX_WAIT:
                return None
            raw = self.protector.open(row[1])
            if hashlib.sha256(raw).hexdigest() != row[2]:
                self.quarantine(row[0], "QUEUE_CHECKSUM_MISMATCH", now, attempted=False)
                continue
            try:
                return row[0], json.loads(raw)
            except ValueError:
                self.quarantine(row[0], "QUEUE_PAYLOAD_INVALID", now, attempted=False)

    def attempts(self, key):
        row = self.db.execute("SELECT attempts FROM deliveries WHERE id=?", (key,)).fetchone()
        return row[0] if row else 0

    def quarantine(self, key, reason, now=None, attempted=True):
        """Dead-letter: payload, checksum and provenance stay; only delivery is suspended."""
        with self.db:
            self.db.execute(
                "UPDATE deliveries SET status='quarantined',attempts=attempts+?,error=?,"
                "quarantined_at=?,quarantine_version=? WHERE id=? AND status='pending'",
                (int(attempted), reason, time.time() if now is None else now, VERSION, key),
            )

    def quarantine_reasons(self):
        """Counts per diagnostic reason code; never payloads or ids."""
        return dict(
            self.db.execute(
                "SELECT error,count(*) FROM deliveries WHERE status='quarantined' GROUP BY error"
            ).fetchall()
        )

    def server_streak(self, key):
        """(start, length) of the batch's current consecutive 5xx streak."""
        row = self.db.execute(
            "SELECT first_failure,server_failures FROM deliveries WHERE id=?", (key,)
        ).fetchone()
        return (row[0], row[1]) if row else (None, 0)

    def retry_now(self):
        """User "Sync now": due all pending rows now and requeue quarantined ones."""
        with self.db:
            cursor = self.db.execute(
                "UPDATE deliveries SET next_attempt=0 WHERE status='pending' AND next_attempt>0"
            )
        return cursor.rowcount + self.requeue_quarantined()

    def quarantined(self):
        return [
            {"batch_id": r[0], "reason": r[1], "attempts": r[2], "quarantined_at": r[3]}
            for r in self.db.execute(
                "SELECT id,error,attempts,quarantined_at FROM deliveries "
                "WHERE status='quarantined' ORDER BY sequence"
            ).fetchall()
        ]

    def requeue_quarantined(self, only_other_versions=False):
        """Put quarantined rows back in their original FIFO position after the cause is fixed."""
        query = (
            "UPDATE deliveries SET status='pending',attempts=0,next_attempt=0,error=NULL,"
            "quarantined_at=NULL,quarantine_version=NULL,first_failure=NULL,server_failures=0 "
            "WHERE status='quarantined'"
        )
        with self.db:
            if only_other_versions:
                cursor = self.db.execute(query + " AND quarantine_version IS NOT ?", (VERSION,))
            else:
                cursor = self.db.execute(query)
        return cursor.rowcount

    def retry(self, key, code, delay, now=None, server_error=False):
        now = time.time() if now is None else now
        with self.db:
            if server_error:
                # Extend the consecutive 5xx streak; restart it if the clock moved back.
                self.db.execute(
                    "UPDATE deliveries SET attempts=attempts+1,error=?,next_attempt=?,"
                    "first_failure=CASE WHEN first_failure IS NULL OR first_failure>? "
                    "THEN ? ELSE first_failure END,server_failures=CASE WHEN "
                    "first_failure IS NULL OR first_failure>? THEN 1 "
                    "ELSE server_failures+1 END WHERE id=?",
                    (code, now + delay, now, now, now, key),
                )
            else:
                # Any other failure (network, 429, auth...) breaks the 5xx streak.
                self.db.execute(
                    "UPDATE deliveries SET attempts=attempts+1,error=?,next_attempt=?,"
                    "first_failure=NULL,server_failures=0 WHERE id=?",
                    (code, now + delay, key),
                )

    def unsettled(self):
        after = self.get("processing_poll_sequence", 0)
        query = (
            "SELECT sequence,id,receipt FROM deliveries WHERE "
            "status IN ('received','partial','needs_review','paused') "
        )
        row = self.db.execute(
            query + "AND sequence>? ORDER BY sequence LIMIT 1", (after,)
        ).fetchone()
        if row is None:
            row = self.db.execute(query + "ORDER BY sequence LIMIT 1").fetchone()
        if row:
            self.save("processing_poll_sequence", row[0])
        return (row[1], json.loads(self.protector.open(row[2]))) if row else None

    def processed(self, key, state):
        if state not in {
            "processed",
            "partial",
            "needs_review",
            "paused",
            "cancelled",
            "queued",
            "retry",
            "processing",
        }:
            raise RuntimeError("INVALID_PROCESSING_STATE")
        local = (
            state
            if state in {"processed", "partial", "needs_review", "paused", "cancelled"}
            else "received"
        )
        with self.db:
            self.db.execute(
                "UPDATE deliveries SET status=? WHERE id=? "
                "AND status IN ('received','partial','needs_review','paused')",
                (local, key),
            )

    def sync_ready(self, sync_id):
        windows = self.db.execute("SELECT id,payload FROM windows").fetchall()
        relevant = [
            self.window(key) for key, _ in windows if self.window(key)["sync_id"] == sync_id
        ]
        return bool(relevant) and all(w["received"] for w in relevant)

    def counts(self):
        return dict(
            self.db.execute("SELECT status,count(*) FROM deliveries GROUP BY status").fetchall()
        )

    def compact(self):
        jobs = self.get("sync_jobs", {})
        completed = sorted(
            (j for j in jobs.values() if j["state"] == "complete"),
            key=lambda j: j.get("finished_at", ""),
        )
        retired = {j["id"] for j in completed[:-100]}
        if retired:
            with self.db:
                for key in retired:
                    self.db.execute("DELETE FROM metadata WHERE key=?", ("force:" + key,))
                self.put("sync_jobs", {key: job for key, job in jobs.items() if key not in retired})
        # Keep pending and unresolved metadata; prune only processed delivery metadata.
        with self.db:
            self.db.execute(
                "DELETE FROM deliveries WHERE status='processed' AND sequence NOT IN "
                "(SELECT sequence FROM deliveries ORDER BY sequence DESC LIMIT 100)"
            )
            self.db.execute(
                "DELETE FROM windows WHERE id NOT IN (SELECT window_id FROM deliveries)"
            )
            self.db.execute(
                "DELETE FROM metadata WHERE key LIKE 'v3_batch:%' AND substr(key,10) "
                "NOT IN (SELECT id FROM deliveries)"
            )
        # Reclaim secure-deleted pages without replacing the protected pending database.
        self.db.execute("PRAGMA incremental_vacuum(100)")
