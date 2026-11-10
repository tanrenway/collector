"""Unified runtime contracts: real protected SQLite/files, synthetic MT5/network only."""

import json
import os
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import pytest
from tanren_collector.application_runtime import ApplicationRuntime
from tanren_collector.application_state import ApplicationState, DeviceView
from tanren_collector.application_workers import (
    LazyTerminal,
    account_turn,
    device_turn,
    discovery_turn,
    registration_turn,
)
from tanren_collector.device_pairing import DeviceStore
from tanren_collector.legacy_transition import transition_turn
from tanren_collector.protocol import batches
from tanren_collector.runtime_store import Catalog, account_path, terminal_key
from tanren_collector.v2_store import Store
from test_collector import IDENTITY, TestProtector
from test_device_pairing import Service
from test_device_sync import Server
from test_v2 import receipt

P = TestProtector()
META = {
    "name": "Synthetic",
    "firm": "User entered",
    "category": "personal",
    "journal_mode": "automatic",
    "timezone": "UTC",
}


class Terminal:
    identities = {}
    unavailable = set()
    reads = []

    def __init__(self, path, expected):
        self.path, self.expected = path, expected

    def connect(self):
        if self.path in self.unavailable:
            raise RuntimeError("TERMINAL_UNAVAILABLE")
        self.verify()

    def identity(self):
        return self.identities[self.path]

    def verify(self):
        if self.expected is not None and self.expected != self.identity():
            raise RuntimeError("TERMINAL_IDENTITY_MISMATCH")

    def rows(self, *_):
        return 0

    def available_start(self, now):
        return now - timedelta(days=1), True

    def read(self, *_):
        self.verify()
        self.reads.append(self.path)
        return []

    def close(self):
        pass


class RegistrationService:
    def __init__(self):
        self.results = {}
        self.calls = []
        self.lose = False

    def factory(self, _):
        return self

    def call(self, path, body):
        self.calls.append(body)
        if body["request_id"] not in self.results:
            self.results[body["request_id"]] = (
                {"state": "metadata_required", "required": list(META)}
                if body["metadata"] is None
                else {
                    "state": "created",
                    "binding_id": str(uuid.uuid4()),
                    "account_id": str(uuid.uuid4()),
                }
            )
        if self.lose:
            self.lose = False
            raise ConnectionError("NETWORK_UNAVAILABLE")
        return self.results[body["request_id"]]


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "v2"
    root.mkdir()
    (root / "bindings").mkdir()
    Terminal.identities = {}
    Terminal.reads = []
    Terminal.unavailable = set()
    with_device = DeviceStore(root.parent / "device-v3", P)
    with_device.save(
        {
            "state": "paired",
            "token": "synthetic-" + uuid.uuid4().hex,
            "device_id": str(uuid.uuid4()),
        }
    )
    with_device.close()
    return root


def selected(root, name="one", identity=None):
    directory = root / name
    directory.mkdir()
    path = directory / "terminal64.exe"
    path.write_bytes(b"synthetic")
    Terminal.identities[str(path)] = identity or IDENTITY
    key = terminal_key(path)
    c = Catalog(root, P)
    state = c.get()
    state["terminals"][key] = {"path": str(path), "running": True}
    c.save(state)
    c.close()
    discovery_turn(root, key, P, Terminal)
    return key, path


def registered(root, name="one", identity=None):
    key, path = selected(root, name, identity)
    service = RegistrationService()
    result = registration_turn(
        root, key, META, protector=P, factory=service.factory, terminal_factory=Terminal
    )
    return key, path, result, service


def allow(root, binding):
    result = transition_turn(root, binding, "drain", True, P)
    assert result.stage == "awaiting_browser_confirmation"


def test_device_pair_rotate_revoke_disconnect_and_explicit_repair(root):
    # Start with an empty isolated installation credential file.
    file = root.parent / "device-v3" / "device.dpapi"
    file.unlink()
    service = Service()
    service.lose_claim = True
    first = device_turn(
        root, "begin", {"code": "ABCD-EFGH-JKMP", "name": "Synthetic"}, P, service.factory
    )
    assert first.state == "claiming" and first.error == "NETWORK_UNAVAILABLE"
    assert (
        device_turn(root, protector=P, factory=service.factory).state
        == "awaiting_browser_confirmation"
    )
    assert service.claims[0] == service.claims[1]
    service.confirm()
    assert device_turn(root, protector=P, factory=service.factory).state == "paired"
    service.expires = datetime.now(UTC) + timedelta(days=1)
    device_turn(root, protector=P, factory=service.factory)
    service.lose_rotate = True
    device_turn(root, protector=P, factory=service.factory)
    assert device_turn(root, protector=P, factory=service.factory).state == "paired"
    assert service.rotation_count == 1
    service.accepted.clear()
    assert device_turn(root, protector=P, factory=service.factory).state == "authorization_required"
    assert (
        device_turn(root, "disconnect", protector=P, factory=service.factory).state
        == "locally_revoked"
    )
    with pytest.raises(ValueError):
        device_turn(root, "repair", {"confirmed": False}, P, service.factory)
    old = file.read_bytes()
    device_turn(
        root,
        "repair",
        {"confirmed": True, "code": "ABCD-EFGH-JKMP", "name": "New"},
        P,
        service.factory,
    )
    assert any(p.read_bytes() == old for p in (file.parent / "previous-devices").iterdir())
    dto = json.dumps(asdict(first))
    assert "token" not in dto and "claim_digest" not in dto and "code" not in asdict(first)


def test_discover_register_metadata_retry_and_independent_contexts(root):
    key, path = selected(root)
    service = RegistrationService()
    pending = registration_turn(
        root, key, protector=P, factory=service.factory, terminal_factory=Terminal
    )
    assert pending.state == "metadata_required"
    assert not (root / "device-accounts").exists()
    service.lose = True
    with pytest.raises(ConnectionError):
        registration_turn(root, key, META, pending.request_id, P, service.factory, Terminal)
    result = registration_turn(
        root, protector=P, factory=service.factory, terminal_factory=Terminal
    )
    assert result.state == "created" and service.calls[-1] == service.calls[-2]
    queue = Store(account_path(root, result.binding_id), P)
    assert queue.get("config")["identity"] == IDENTITY and "token" not in queue.get("config")
    assert "initial_balance" not in service.calls[-1]["metadata"]
    queue.close()
    _, _, other, _ = registered(root, "two", {**IDENTITY, "login": "99999"})
    assert other.binding_id != result.binding_id
    catalog = Catalog(root, P)
    assert len(catalog.get()["accounts"]) == 2
    catalog.close()


def test_registration_restart_after_server_ack_before_catalog_commit(root, monkeypatch):
    key, _ = selected(root)
    service = RegistrationService()
    original = Catalog.save

    def disk_failure(self, state):
        if state["accounts"]:
            raise OSError("synthetic disk")
        return original(self, state)

    monkeypatch.setattr(Catalog, "save", disk_failure)
    with pytest.raises(OSError):
        registration_turn(
            root, key, META, protector=P, factory=service.factory, terminal_factory=Terminal
        )
    monkeypatch.setattr(Catalog, "save", original)
    result = registration_turn(
        root, protector=P, factory=service.factory, terminal_factory=Terminal
    )
    assert result.state == "created" and len(service.calls) == 1
    c = Catalog(root, P)
    assert result.binding_id in c.get()["accounts"]
    c.close()


def test_switch_unavailable_terminal_and_shared_terminal_lock(root):
    key, path = selected(root)
    Terminal.identities[str(path)] = {**IDENTITY, "login": "555"}
    with pytest.raises(RuntimeError, match="MISMATCH"):
        registration_turn(
            root,
            key,
            META,
            protector=P,
            factory=RegistrationService().factory,
            terminal_factory=Terminal,
        )
    Terminal.identities[str(path)] = IDENTITY
    first = LazyTerminal(root, str(path), IDENTITY, Terminal)
    second = LazyTerminal(root, str(path), IDENTITY, Terminal)
    first.connect()
    with pytest.raises(RuntimeError, match="TERMINAL_BUSY"):
        second.connect()
    first.close()
    second.connect()
    second.close()


def test_unavailable_one_account_does_not_stop_other_and_delivery_needs_no_mt5(root):
    _, path, one, _ = registered(root)
    _, _, two, _ = registered(root, "two", {**IDENTITY, "login": "2222"})
    allow(root, one.binding_id)
    server = Server()
    first, _ = account_turn(root, one.binding_id, "activate", P, server.factory, Terminal)
    assert first.role == "active"
    # Queue a retained old packet; missing terminal still delivers it.
    q = Store(account_path(root, one.binding_id), P)
    raw = batches(IDENTITY, [], datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat())
    q.capture(
        str(uuid.uuid4()),
        raw,
        "capture_cursor",
        raw[0]["scanned_until"],
        provenance={
            "binding_id": one.binding_id,
            "epoch": 1,
            "window_id": str(uuid.uuid4()),
            "fragment_count": 1,
        },
    )
    q.save("last_capture", 0)
    q.close()
    Terminal.unavailable.add(str(path))
    failed, _ = account_turn(
        root, one.binding_id, protector=P, factory=server.factory, terminal_factory=Terminal
    )
    assert failed.error == "TERMINAL_UNAVAILABLE" and raw[0]["batch_id"] in server.receipts
    allow(root, two.binding_id)
    other, _ = account_turn(root, two.binding_id, "activate", P, server.factory, Terminal)
    assert other.role == "active"
    Terminal.identities[str(path)] = {**IDENTITY, "login": "333"}
    Terminal.unavailable.clear()
    changed, _ = account_turn(
        root, one.binding_id, protector=P, factory=server.factory, terminal_factory=Terminal
    )
    assert changed.error == "TERMINAL_IDENTITY_MISMATCH"


def test_restart_grant_denial_offline_queue_and_new_device_cannot_claim_old_context(root):
    _, _, r, _ = registered(root)
    allow(root, r.binding_id)
    server = Server()
    account_turn(root, r.binding_id, "activate", P, server.factory, Terminal)
    q = Store(account_path(root, r.binding_id), P)
    original = q.get("capture_cursor")
    q.save("last_capture", 0)
    q.close()

    def denied(_):
        class Api:
            def call(self, *_):
                raise RuntimeError("SYNC_PAUSED_HTTP_404")

        return Api()

    result, _ = account_turn(
        root, r.binding_id, protector=P, factory=denied, terminal_factory=Terminal
    )
    assert result.stage == "access_denied"
    q = Store(account_path(root, r.binding_id), P)
    assert q.get("capture_cursor") == original
    q.close()
    device = DeviceStore(root.parent / "device-v3", P)
    state = device.get()
    state["device_id"] = str(uuid.uuid4())
    device.save(state)
    device.close()
    result, _ = account_turn(
        root, r.binding_id, protector=P, factory=server.factory, terminal_factory=Terminal
    )
    assert result.stage == "continuity_review"


def test_explicit_legacy_drain_preserves_packet_and_checkpoint(root):
    _, _, r, _ = registered(root)
    local = str(uuid.uuid4())
    directory = root / "bindings" / local
    directory.mkdir()
    q = Store(directory / "queue-v2.sqlite", P)
    token = "synthetic-" + uuid.uuid4().hex
    device_id = str(uuid.uuid4())
    catalog = Catalog(root, P)
    account_id = catalog.get()["accounts"][r.binding_id]["account_id"]
    catalog.close()
    q.save(
        "config",
        {
            "token": token,
            "identity": IDENTITY,
            "account_id": account_id,
            "device_id": device_id,
        },
    )
    now = datetime.now(UTC).isoformat()
    raw = batches(IDENTITY, [], now, now)
    q.capture("legacy", raw, "capture_cursor", now)
    config = q.get("config")
    q.close()

    class Legacy:
        calls = []

        def __init__(self, secret):
            assert secret == token

        def call(self, path, body=None):
            self.calls.append((path, body))
            if path.endswith("/control"):
                return {
                    "account_id": config["account_id"],
                    "device_id": device_id,
                    "expires_at": (datetime.now(UTC) + timedelta(days=90)).isoformat(),
                }
            if path.endswith("/batches"):
                return receipt(body)
            return {"state": "processed"}

    view = transition_turn(root, r.binding_id, protector=P)
    assert view.stage == "draining" and view.queues[0].pending == 1
    with pytest.raises(RuntimeError, match="EXPLICIT"):
        transition_turn(root, r.binding_id, "drain", False, P)
    done = transition_turn(root, r.binding_id, "drain", True, P, Legacy)
    assert done.stage == "awaiting_browser_confirmation"
    assert [b for path, b in Legacy.calls if path.endswith("/batches")] == raw
    q = Store(directory / "queue-v2.sqlite", P)
    assert (
        q.get("config") == config
        and q.get("capture_cursor") == now
        and q.counts() == {"processed": 1}
    )
    assert q.get("v3_batch:" + raw[0]["batch_id"]) is None
    q.close()


def test_sqlite_full_does_not_advance_and_diagnostics_are_redacted(root, tmp_path):
    import zipfile

    from tanren_collector.diagnostics import export
    from tanren_collector.engine import safe_error

    _, _, r, _ = registered(root)
    allow(root, r.binding_id)
    q = Store(account_path(root, r.binding_id), P)
    q.capacity = 1
    now = datetime.now(UTC).isoformat()
    raw = batches(IDENTITY, [], now, now)
    with pytest.raises(RuntimeError, match="CAPACITY"):
        q.capture("full", raw, "capture_cursor", now)
    assert q.get("capture_cursor") is None
    q.close()
    exc = sqlite3.OperationalError("private local path secret")
    exc.sqlite_errorcode = sqlite3.SQLITE_FULL
    assert safe_error(exc) == "QUEUE_CAPACITY_REACHED"
    target = tmp_path / "diag.zip"
    export(
        target,
        [
            {
                "state": "error",
                "error": str(exc),
                "token": "not-exported",
                "raw": raw,
                "identity": IDENTITY,
            }
        ],
    )
    with zipfile.ZipFile(target) as z:
        report = z.read("diagnostics.json").decode()
    assert (
        "not-exported" not in report
        and "private local path secret" not in report
        and "records" not in report
    )


def test_application_scheduler_resume_cancel_and_bounded_real_spawn(root):
    from tanren_collector.processes import SpawnPool

    runtime = ApplicationRuntime(root, protector=P)
    assert runtime.state == ApplicationState()
    runtime.state = ApplicationState(device=DeviceView("paired"))
    runtime.device_next = 10**20
    # No GUI network operation: submission produces a waiting spawn task, not a session call.
    task = runtime.discover_accounts()
    assert task in runtime.pool.waiting and not task.done()
    runtime.pool.cancel(task)
    assert task.done() and not task.args
    runtime.control_task = None
    runtime.resume()
    assert not runtime.account_tasks and runtime.device_next == 0
    runtime.state = ApplicationState()
    runtime.close()
    # Real spawn of a production device entry point with synthetic protection/service.
    pool = SpawnPool(max_workers=1, timeout=10)
    task = pool.submit(device_turn, str(root), "poll", None, P, Service().factory)
    try:
        until = time.monotonic() + 15
        while not task.done() and time.monotonic() < until:
            pool.tick()
            time.sleep(0.02)
        assert task.result().state == "authorization_required"
    finally:
        pool.shutdown()


def test_v1_delivery_only_transition_and_unresolved_queue_blocks(root):
    from tanren_collector.protocol import ORIGIN
    from tanren_collector.storage import Queue, save_config

    _, _, r, _ = registered(root)
    catalog = Catalog(root, P)
    account = catalog.get()["accounts"][r.binding_id]["account_id"]
    catalog.close()
    secret = "synthetic-" + uuid.uuid4().hex
    save_config(
        root.parent / "config.dpapi", {"origin": ORIGIN, "token": secret, "identity": IDENTITY}, P
    )
    queue = Queue(root.parent / "outbox.sqlite", P)
    now = datetime.now(UTC).isoformat()
    raw = {
        "protocol": "mt5-v1",
        "batch_id": str(uuid.uuid4()),
        "identity": IDENTITY,
        "scanned_until": now,
        "records": [],
    }
    queue.enqueue(raw)
    queue.close()

    class Api:
        calls = []

        def __init__(self, origin, token):
            assert origin == ORIGIN and token == secret

        def call(self, path, body=None):
            if path.endswith("/control"):
                return {"account_id": account}
            self.calls.append(body)
            return {"status": "applied"}

    done = transition_turn(root, r.binding_id, "drain", True, P, legacy_factory=Api)
    assert done.stage == "awaiting_browser_confirmation" and Api.calls == [raw]
    queue = Queue(root.parent / "outbox.sqlite", P)
    assert queue.checkpoint("scan_cursor") == now and queue.pending() is None
    queue.db.execute("UPDATE outbox SET status='received'")
    queue.db.commit()
    queue.close()
    blocked = transition_turn(root, r.binding_id, "inspect", protector=P)
    assert blocked.stage == "blocked" and blocked.error == "LEGACY_REVIEW_REQUIRED"


def test_scheduler_does_not_auto_confirm_inspection_and_resumes_only_confirmed_drain(root):
    _, _, r, _ = registered(root)
    transition_turn(root, r.binding_id, "drain", True, P)
    runtime = ApplicationRuntime(root, protector=P)
    assert runtime.migration_allowed
    runtime.migrate(r.binding_id, drain=False)
    assert not runtime.migration_allowed
    task = runtime.control_task
    runtime.pool.cancel(task)
    runtime.control_task = None
    runtime.close()


def test_catalog_failure_and_corrupt_one_queue_never_resets_state(root):
    _, _, r, _ = registered(root)
    path = root / "runtime-v3.dpapi"
    original = path.read_bytes()
    runtime = ApplicationRuntime(root, protector=P)
    path.write_bytes(b"corrupt")
    assert runtime.tick() == {}
    assert runtime.state.error == "RUNTIME_CATALOG_REVIEW_REQUIRED"
    runtime.state = ApplicationState(device=DeviceView("paired"))
    runtime.close()
    assert runtime.pool.closed
    path.write_bytes(original)
    # Corrupt only one protected queue. It remains intact for review, never recreated/reset.
    target = account_path(root, r.binding_id)
    target.write_bytes(b"not a SQLite database")
    with pytest.raises(sqlite3.DatabaseError):
        account_turn(root, r.binding_id, protector=P)
    assert target.read_bytes() == b"not a SQLite database"


@pytest.mark.skipif(os.name != "nt" and not os.getenv("DISPLAY"), reason="Tk display unavailable")
@pytest.mark.parametrize("language", ["en", "uk"])
def test_tk_runtime_panel_actions_state_and_palettes(language, tmp_path):
    import tkinter as tk

    from tanren_collector.application_state import AccountView, TerminalView
    from tanren_collector.desktop import PALETTES, Window

    class Bridge:
        state = ApplicationState(
            device=DeviceView("paired"),
            terminals=(TerminalView("terminal", "Terminal 1"),),
            accounts=(
                AccountView(
                    "12345678-1234-1234-1234-123456789abc",
                    "11111111-1111-1111-1111-111111111111",
                    "terminal",
                ),
            ),
        )
        actions = []

        def bindings(self):
            return []

        def tick(self):
            return {}

        def pair_device(self, code, name, **_):
            self.actions.append(("pair", len(code), name))

        def close(self):
            pass

    bridge = Bridge()
    root = tk.Tk()
    try:
        window = Window(root, bridge, {"locale": language, "palette": "graphite"}, lambda _: None)
        window.navigate("device")
        panel = window.runtime_panel
        panel.code.set("ABCD-EFGH-JKMP")
        panel.pair()
        assert bridge.actions[0][0] == "pair" and panel.code.get() == ""
        # No implicit account/terminal selection.
        assert panel.terminal.current() == -1 and panel.accounts.current() == -1
        for palette in PALETTES:
            window.settings["palette"] = palette
            window.configure_style()
            root.geometry("620x900")
            root.update()
            assert root.winfo_width() == 620 and not window.closed
        panel.code.set("temporary-code")
        window.navigate("home")
        assert panel.code.get() == ""
    finally:
        if "window" in locals():
            if window.timer:
                root.after_cancel(window.timer)
        root.destroy()


def test_scheduler_runs_unrelated_accounts_after_one_child_crash(root):
    from dataclasses import replace

    from tanren_collector.application_state import AccountView, DeviceView

    _, _, one, _ = registered(root)
    _, _, two, _ = registered(root, "two", {**IDENTITY, "login": "999"})
    runtime = ApplicationRuntime(root, protector=P)
    runtime.state = replace(runtime.state, device=DeviceView("paired"))
    runtime.device_next = 10**20

    class Finished:
        args = ()

        def __init__(self, binding):
            self.binding = binding

        def done(self):
            return True

        def result(self):
            if self.binding == one.binding_id:
                raise RuntimeError("CHILD_PROCESS_EXITED")
            return AccountView(self.binding, "synthetic-account", "terminal", stage="processing"), 0

    runtime.account_tasks = {
        one.binding_id: Finished(one.binding_id),
        two.binding_id: Finished(two.binding_id),
    }
    runtime.tick()
    by_id = {a.binding_id: a for a in runtime.state.accounts}
    assert by_id[one.binding_id].error == "CHILD_PROCESS_EXITED"
    assert by_id[two.binding_id].stage == "processing"
    # A busy control operation must not falsely claim local disconnection or cancel good work.
    task = runtime.discover_accounts()
    with pytest.raises(RuntimeError, match="RUNTIME_BUSY"):
        runtime.disconnect_device()
    assert runtime.state.device.state == "paired"
    runtime.pool.cancel(task)
    runtime.control_task = None
    runtime.state = replace(runtime.state, device=DeviceView("disconnected"))
    runtime.close()


def test_server_retry_after_survives_independent_worker_turn(root):
    from tanren_collector.client import RetryableError

    _, _, r, _ = registered(root)
    allow(root, r.binding_id)
    server = Server()
    account_turn(root, r.binding_id, "activate", P, server.factory, Terminal)

    class Throttled:
        def __init__(self, _):
            pass

        def call(self, *_):
            raise RetryableError("RETRY_HTTP_429", 300)

    state, _ = account_turn(
        root, r.binding_id, protector=P, factory=Throttled, terminal_factory=Terminal
    )
    assert state.role == "unknown" and state.retry_after_seconds >= 299


def test_pause_resume_requires_prior_handover_and_preserves_queue(root):
    _, _, r, _ = registered(root)
    server = Server()
    with pytest.raises(RuntimeError, match="EXPLICIT"):
        account_turn(root, r.binding_id, "resume", P, server.factory, Terminal)
    allow(root, r.binding_id)
    account_turn(root, r.binding_id, "activate", P, server.factory, Terminal)
    q = Store(account_path(root, r.binding_id), P)
    before = q.get("capture_cursor")
    q.close()
    paused, _ = account_turn(root, r.binding_id, "pause", P, server.factory, Terminal)
    assert paused.stage == "paused"
    stopped, _ = account_turn(
        root, r.binding_id, protector=P, factory=server.factory, terminal_factory=Terminal
    )
    assert stopped.stage == "paused"
    resumed, _ = account_turn(root, r.binding_id, "resume", P, server.factory, Terminal)
    assert resumed.role == "active"
    q = Store(account_path(root, r.binding_id), P)
    assert q.get("capture_cursor") == before
    q.close()


def test_invalid_metadata_can_be_corrected_without_discarding_uncertain_ack(root):
    from tanren_collector.account_registration import RegistrationState

    key, _ = selected(root)

    class Invalid:
        def __init__(self, _):
            pass

        def call(self, *_):
            raise RuntimeError("SYNC_PAUSED_HTTP_422")

    with pytest.raises(RuntimeError):
        registration_turn(root, key, META, protector=P, factory=Invalid, terminal_factory=Terminal)
    store = RegistrationState(root / "registration-v3", P)
    assert not store.get().get("registration_pending") and store.get()["runtime_rejected"]
    store.close()
    result = registration_turn(
        root,
        key,
        META,
        protector=P,
        factory=RegistrationService().factory,
        terminal_factory=Terminal,
    )
    assert result.state == "created"


def test_new_account_starts_capture_when_the_server_admits_it(root):
    class Admitted(RegistrationService):
        def call(self, path, body):
            result = super().call(path, body)
            return {**result, "capture_admitted": True} if result["state"] == "created" else result

    key, _ = selected(root, "one")
    service = Admitted()
    result = registration_turn(
        root, key, META, protector=P, factory=service.factory, terminal_factory=Terminal
    )
    with closing(Store(account_path(root, result.binding_id), P)) as store:
        config = store.get("config")
    assert config["enabled"] is True and config["admitted"] is True
    with closing(Catalog(root, P)) as catalog:
        assert catalog.get()["accounts"][result.binding_id]["enabled"] is True


def test_account_without_admission_keeps_the_explicit_handover(root):
    _, _, result, _ = registered(root)
    with closing(Store(account_path(root, result.binding_id), P)) as store:
        config = store.get("config")
    assert config["enabled"] is False and not config.get("admitted")


def test_manually_chosen_terminal_is_added_and_kept(root, monkeypatch):
    import tanren_collector.application_workers as workers

    monkeypatch.setattr(workers, "discover", lambda: [])
    path = root.parent / "picked" / "terminal64.exe"
    path.parent.mkdir()
    path.write_text("x")
    assert [t.path for t in workers.add_terminal_turn(root, str(path), P)] == [str(path.resolve())]
    assert [t.path for t in workers.discovery_turn(root, protector=P)] == [str(path.resolve())]
    with pytest.raises(ValueError, match="INVALID_TERMINAL_PATH"):
        workers.add_terminal_turn(root, str(root.parent / "evil.exe"), P)


def test_registered_account_is_started_once_the_server_admits_it(root, monkeypatch):
    import tanren_collector.application_workers as workers

    _, _, result, _ = registered(root)

    class Reader:
        def get(self):
            return {"token": "t"}

    calls = []

    class Api:
        def __init__(self, token):
            pass

        def call(self, path, body):
            calls.append(body)
            return {
                "state": "linked",
                "binding_id": result.binding_id,
                "account_id": config["account_id"],
                "capture_admitted": True,
            }

    monkeypatch.setattr(workers, "RegistrationApi", Api)
    with closing(Store(account_path(root, result.binding_id), P)) as store:
        config = store.get("config")
        assert workers._admit_existing(root, config, Reader(), P, store) is True
        assert store.get("config")["enabled"] is True and store.get("config")["admitted"] is True
        assert workers._admit_existing(root, config, Reader(), P, store) is False  # Hourly at most.
    assert len(calls) == 1 and calls[0]["existing_account_id"] == config["account_id"]
    assert calls[0]["metadata"] is None
    with closing(Catalog(root, P)) as catalog:
        assert catalog.get()["accounts"][result.binding_id]["enabled"] is True
