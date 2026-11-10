"""User-scoped DPAPI secrets and SQLite durable encrypted outbox."""

import base64
import ctypes
import json
import os
import sqlite3
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from .build_profile import ENGINEERING, check_storage_path, current

ENGINEERING_SEAL = b"TanrenCollectorEngineering\x00"


class DPAPI:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Windows DPAPI required; plaintext fallback is forbidden")
        self.crypt = ctypes.WinDLL("crypt32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    def transform(self, data, encrypt):
        class Blob(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        source, target = Blob(len(data), buffer), Blob()
        function = self.crypt.CryptProtectData if encrypt else self.crypt.CryptUnprotectData
        function.argtypes = [
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(Blob),
        ]
        function.restype = wintypes.BOOL
        if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
            raise RuntimeError("DPAPI operation failed")
        try:
            return ctypes.string_at(target.data, target.size)
        finally:
            self.kernel.LocalFree.argtypes = [ctypes.c_void_p]
            self.kernel.LocalFree.restype = ctypes.c_void_p
            self.kernel.LocalFree(target.data)

    def seal(self, value):
        if current() == ENGINEERING:
            return ENGINEERING_SEAL + self.transform(ENGINEERING_SEAL + value, True)
        return self.transform(value, True)

    def open(self, value):
        if current() == ENGINEERING:
            if not value.startswith(ENGINEERING_SEAL):
                raise RuntimeError("ENGINEERING_CREDENTIAL_NAMESPACE_REQUIRED")
            plain = self.transform(value[len(ENGINEERING_SEAL) :], False)
            if not plain.startswith(ENGINEERING_SEAL):
                raise RuntimeError("ENGINEERING_CREDENTIAL_NAMESPACE_REQUIRED")
            return plain[len(ENGINEERING_SEAL) :]
        return self.transform(value, False)


def save_config(path: Path, value: dict, protector):
    check_storage_path(path)
    temporary = path.with_suffix(".tmp")
    check_storage_path(temporary)
    with temporary.open("wb") as stream:
        stream.write(base64.b64encode(protector.seal(json.dumps(value).encode())))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def load_config(path: Path, protector):
    check_storage_path(path)
    return json.loads(protector.open(base64.b64decode(path.read_bytes())))


class Queue:
    def __init__(self, path, protector):
        check_storage_path(path)
        check_storage_path(str(path) + ".lock")
        for suffix in ("-wal", "-shm", "-journal"):
            check_storage_path(str(path) + suffix)
        self.lock_file = open(str(path) + ".lock", "a+b")
        self.lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            if not self.lock_file.read(1):
                self.lock_file.write(b"0")
                self.lock_file.flush()
            self.lock_file.seek(0)
            msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.protector = protector
        self.db_path = str(path)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value BLOB);
 CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,payload BLOB NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending',receipt BLOB);""")
        if self.db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("QUEUE_CORRUPT")

    def checkpoint(self, key):
        value = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return self.protector.open(value[0]).decode() if value else None

    def enqueue(self, payload):
        used = sum(p.stat().st_size for p in Path(self.db_path).parent.glob("outbox.sqlite*"))
        if used > 100_000_000:
            raise RuntimeError("QUEUE_CAPACITY_REACHED")
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        # Payload/key and scanned cursor committed together. Never advance applied before ACK.
        with self.db:
            self.db.execute(
                "INSERT INTO outbox(id,payload) VALUES(?,?)",
                (payload["batch_id"], self.protector.seal(raw)),
            )
            self.db.execute(
                "INSERT OR REPLACE INTO state VALUES(?,?)",
                ("scanned", self.protector.seal(payload["scanned_until"].encode())),
            )

    def pending(self):
        row = self.db.execute(
            "SELECT id,payload FROM outbox WHERE status='pending' ORDER BY rowid LIMIT 1"
        ).fetchone()
        return (row[0], json.loads(self.protector.open(row[1]))) if row else None

    def acknowledge(self, key, result, applied_until):
        if result["status"] not in {"applied", "partial"}:
            raise RuntimeError("SOURCE_CONFLICT_REVIEW_REQUIRED")
        old_received = self.checkpoint("received")
        barrier = bool(self.checkpoint("projection_barrier")) or result["status"] == "partial"
        highwater = (
            max(old_received, applied_until, key=datetime.fromisoformat)
            if old_received
            else applied_until
        )
        with self.db:
            self.db.execute(
                "UPDATE outbox SET status=?,receipt=? WHERE id=?",
                (
                    "received" if barrier else "applied",
                    self.protector.seal(json.dumps(result).encode()),
                    key,
                ),
            )
            self.db.execute(
                "INSERT OR REPLACE INTO state VALUES(?,?)",
                ("received", self.protector.seal(highwater.encode())),
            )

            if not barrier:
                self.db.execute(
                    "INSERT OR REPLACE INTO state VALUES(?,?)",
                    ("applied", self.protector.seal(highwater.encode())),
                )
            else:
                self.db.execute(
                    "INSERT OR REPLACE INTO state VALUES(?,?)",
                    ("projection_barrier", self.protector.seal(b"review_required")),
                )
            self.db.execute(
                "INSERT OR REPLACE INTO state VALUES(?,?)",
                ("scan_cursor", self.protector.seal(applied_until.encode())),
            )

    def close(self):
        self.db.close()
        self.lock_file.close()
