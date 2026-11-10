"""Bounded fair spawn-process scheduling, one MT5 IPC connection per process/turn."""

import time
import uuid
from pathlib import Path

from .build_profile import check_storage_path
from .discovery import discover
from .engine import Engine, safe_error
from .observability import DiagnosticFailure, capture
from .pairing import advance, begin
from .processes import SpawnPool
from .storage import DPAPI
from .terminal_v2 import RawTerminal
from .v2_store import Store
from .windows import terminal_lock


def probe(directory, path):
    lock = terminal_lock(directory, path)
    terminal = None
    try:
        terminal = RawTerminal(path, None)
        terminal.connect()
        identity = terminal.identity()
        if terminal.identity() != identity:
            raise RuntimeError("TERMINAL_IDENTITY_MISMATCH")
        return identity
    except ImportError as exc:
        raise DiagnosticFailure(
            "MT5_BRIDGE_UNAVAILABLE", getattr(exc, "collector_diagnostic", None)
        ) from None
    finally:
        if terminal:
            terminal.close()
        lock.close()


def step(directory, binding):
    terminal = None
    lock = None
    try:
        with_store = Store(Path(directory) / "bindings" / binding / "queue-v2.sqlite", DPAPI())
        try:
            if with_store.get("pairing"):
                state = advance(with_store)
                result = {"state": "connected", "pairing": state, "queue": with_store.counts()}
            else:
                config = with_store.get("config")
                if not config or config.get("paused"):
                    return {
                        "state": "paused" if config and config.get("paused") else "disconnected",
                        "queue": with_store.counts(),
                        "identity": (config or {}).get("identity"),
                        "account_id": (config or {}).get("account_id"),
                        "account_name": with_store.get("account_name"),
                    }
                lock = terminal_lock(directory, config["terminal"])
                terminal = RawTerminal(config["terminal"], config["identity"])
                result = Engine(with_store, terminal).step()
            config = with_store.get("config") or with_store.get("pairing") or {}
            # This explicit UI DTO never includes credentials, source payload or protected config.
            return {
                **result,
                "identity": config.get("identity"),
                "account_id": config.get("account_id"),
                "account_name": with_store.get("account_name"),
            }
        finally:
            with_store.close()
    except Exception as exc:
        diagnostic = getattr(exc, "collector_diagnostic", None) or capture("child_call", exc)
        code = diagnostic["code"]
        return {
            "state": "authentication_expired"
            if code == "SYNC_PAUSED_HTTP_401"
            else "needs_attention",
            "error": code,
            "diagnostic": diagnostic,
        }
    finally:
        if terminal:
            terminal.close()
        if lock:
            lock.close()


class Supervisor:
    def __init__(self, directory, max_workers=4):
        check_storage_path(directory)
        self.directory = Path(directory)
        check_storage_path(self.directory / "bindings")
        (self.directory / "bindings").mkdir(exist_ok=True)
        self.pool = SpawnPool(max_workers=max_workers)
        self.pending = {}
        self.status = {}
        self.next = {}
        self.closed = False

    def bindings(self):
        result = []
        for path in (self.directory / "bindings").iterdir():
            try:
                uuid.UUID(path.name)
            except ValueError:
                continue
            if path.is_dir():
                result.append(path.name)
        return sorted(result)

    def tick(self):
        if self.closed:
            return
        self.pool.tick()
        for key in self.bindings():
            future = self.pending.get(key)
            if future and future.done():
                try:
                    self.status[key] = future.result()
                except Exception as exc:
                    self.status[key] = {
                        "state": "error",
                        "error": safe_error(exc),
                        "diagnostic": getattr(exc, "collector_diagnostic", None),
                    }
                self.pending.pop(key, None)
                state = self.status[key].get("state")
                delay = (
                    15
                    if state == "up_to_date"
                    else 30
                    if state == "waiting_for_terminal"
                    else 300
                    if state in ("needs_attention", "authentication_expired", "error")
                    else 5
                )
                self.next[key] = time.monotonic() + delay
            if key not in self.pending and time.monotonic() >= self.next.get(key, 0):
                self.pending[key] = self.pool.submit(step, str(self.directory), key)
        return self.status

    def probe(self, path):
        return self.pool.submit(probe, str(self.directory), path)

    def discover(self):
        return self.pool.submit(discover)

    def edit(self, key, action):
        if key in self.pending:
            raise RuntimeError("BINDING_BUSY")
        with_store = Store(self.directory / "bindings" / key / "queue-v2.sqlite", DPAPI())
        try:
            return action(with_store)
        finally:
            with_store.close()

    def add(self, token, path, identity, key=None):
        key = key or str(uuid.uuid4())
        uuid.UUID(key)
        directory = self.directory / "bindings" / key
        check_storage_path(directory)
        directory.mkdir(exist_ok=True)
        self.edit(key, lambda store: begin(store, token, path, identity))
        self.next[key] = 0
        return key

    def request_sync(self, key):
        def check(store):
            with store.db:
                store.put("last_capture", 0)
                store.put("last_control", 0)
                store.put("last_sync_poll", 0)

        self.edit(key, check)
        self.next[key] = 0

    def pause(self, key, paused):
        def change(store):
            config = store.get("config")
            if config:
                config["paused"] = paused
                store.save("config", config)

        self.edit(key, change)
        self.next[key] = 0

    def close(self):
        self.closed = True
        self.pool.shutdown()
