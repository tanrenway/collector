"""Per-binding DPAPI SQLite outbox. Capture, delivery and financial status are distinct."""

import hashlib
import json
import time
from pathlib import Path

from .protocol import encoded
from .storage import Queue


class Store(Queue):
    """Separate v2 database: never upgrades/relabels a legacy CLI queue."""

    def __init__(self, path, protector, capacity=100_000_000):
        super().__init__(path, protector)
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 2) or (
            version == 0 and self.db.execute("SELECT count(*) FROM outbox").fetchone()[0]
        ):
            self.close()
            raise RuntimeError("QUEUE_SCHEMA_MISMATCH")
        self.capacity = capacity
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.executescript("""
 CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,payload BLOB NOT NULL);
 CREATE TABLE IF NOT EXISTS deliveries(
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,window_id TEXT NOT NULL,
 payload BLOB,checksum TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',receipt BLOB,
 attempts INTEGER NOT NULL DEFAULT 0,next_attempt REAL NOT NULL DEFAULT 0,error TEXT);
 CREATE INDEX IF NOT EXISTS ix_delivery_pending ON deliveries(status,sequence);
 CREATE TABLE IF NOT EXISTS windows(id TEXT PRIMARY KEY,payload BLOB NOT NULL);
 PRAGMA user_version=2;
 """)

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
            pending = self.db.execute(
                "SELECT count(*) FROM deliveries WHERE window_id=? AND status='pending'", row
            ).fetchone()[0]
            if not pending:
                window = self.window(row[0])
                window["received"] = True
                self.db.execute(
                    "UPDATE windows SET payload=? WHERE id=?",
                    (self.protector.seal(encoded(window)), row[0]),
                )
                # FIFO delivery makes normal-window receipt checkpoint contiguous.
                if window["cursor_key"] == "capture_cursor":
                    self.put("received_cursor", window["end"])

    def window(self, key):
        row = self.db.execute("SELECT payload FROM windows WHERE id=?", (key,)).fetchone()
        return json.loads(self.protector.open(row[0])) if row else None

    def retry(self, key, code, delay, now=None):
        with self.db:
            self.db.execute(
                "UPDATE deliveries SET attempts=attempts+1,error=?,next_attempt=? WHERE id=?",
                (code, (time.time() if now is None else now) + delay, key),
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
