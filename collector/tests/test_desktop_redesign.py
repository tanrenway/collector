"""Positional-only official MT5 signature and safe worker errors; no terminal accessed."""

from types import SimpleNamespace

import pytest
from tanren_collector.processes import Task, invoke
from tanren_collector.terminal_v2 import RawTerminal
from test_collector import IDENTITY


class Bridge:
    def initialize(self, path, /, **kwargs):
        assert path == "C:/fixture/terminal64.exe"
        assert kwargs == {"timeout": 10000}
        return True

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def account_info(self):
        return SimpleNamespace(
            login=123,
            server=IDENTITY["server"],
            company=IDENTITY["broker"],
            currency="USD",
            margin_mode=2,
        )


def test_active_account_positional_path_without_login_or_trading():
    terminal = RawTerminal("C:/fixture/terminal64.exe", IDENTITY, Bridge())
    terminal.connect()
    assert terminal.identity() == IDENTITY
    terminal.expected = None
    terminal.connect()  # Discovery probe intentionally has no prior identity.


@pytest.mark.parametrize(
    "code,expected",
    [
        (-10003, "TERMINAL_IPC_FAILED"),
        (-10005, "TERMINAL_API_TIMEOUT"),
        (-6, "TERMINAL_AUTH_REQUIRED"),
        (-2, "TERMINAL_INVALID_ARGUMENT"),
        (999, "TERMINAL_UNAVAILABLE"),
    ],
)
def test_failed_initialize_has_safe_actionable_code_not_native_error_text(code, expected):
    bridge = Bridge()
    bridge.initialize = lambda *args, **kwargs: False
    bridge.last_error = lambda: (code, "DO_NOT_EXPOSE path token broker details")
    with pytest.raises(RuntimeError, match=expected):
        RawTerminal("C:/fixture/terminal64.exe", None, bridge).connect()


def test_account_none_and_unknown_mode_have_distinct_safe_reason():
    bridge = Bridge()
    bridge.account_info = lambda: None
    with pytest.raises(RuntimeError, match="ACCOUNT_INFO_UNAVAILABLE"):
        RawTerminal("C:/fixture/terminal64.exe", None, bridge).identity()
    bridge.account_info = lambda: SimpleNamespace(margin_mode=99)
    with pytest.raises(RuntimeError, match="UNSUPPORTED_ACCOUNT_MODE"):
        RawTerminal("C:/fixture/terminal64.exe", None, bridge).identity()


def test_worker_preserves_only_allowlisted_errors():
    class Sender:
        def send(self, value):
            self.value = value

        def close(self):
            pass

    for raw, expected in [
        ("TERMINAL_IPC_FAILED", "TERMINAL_IPC_FAILED"),
        ("DO_NOT_EXPOSE password", "COLLECTOR_OPERATION_FAILED"),
    ]:

        def fail(value=raw):
            raise RuntimeError(value)

        sender = Sender()
        invoke(sender, fail, ())
        task = Task(None, ())
        task.finished, (task.ok, task.value) = True, sender.value
        with pytest.raises(RuntimeError, match=expected):
            task.result()


def test_presentation_never_claims_processing_before_server_confirmation():
    from tanren_collector.desktop_model import effective_state, masked_login

    assert effective_state({"state": "up_to_date"}) == "processing"
    assert (
        effective_state({"state": "up_to_date", "last_success": "known", "queue": {"received": 1}})
        == "processing"
    )
    assert (
        effective_state({"state": "up_to_date", "last_success": "known", "queue": {}})
        == "up_to_date"
    )
    assert (
        effective_state({"state": "connected", "pairing": "awaiting_browser_confirmation"})
        == "pending_pair"
    )
    assert masked_login("123456789") == "•••• 6789"


def test_read_probe_twice_and_shutdown_on_error(monkeypatch, tmp_path):
    import tanren_collector.runtime as runtime

    events = []

    class Terminal:
        def __init__(self, *_):
            pass

        def connect(self):
            events.append("connect")

        def identity(self):
            events.append("identity")
            return IDENTITY

        def close(self):
            events.append("close")

    monkeypatch.setattr(runtime, "RawTerminal", Terminal)
    assert runtime.probe(tmp_path, "C:/fixture/terminal64.exe") == IDENTITY
    assert events == ["connect", "identity", "identity", "close"]


def test_incremental_sync_does_not_request_full_history():
    from tanren_collector.runtime import Supervisor

    class Store:
        def __init__(self):
            self.values = {}
            self.db = self

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def put(self, k, v):
            self.values[k] = v

    store = Store()
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.next = {}
    supervisor.edit = lambda key, action: action(store)
    supervisor.request_sync("fixture")
    assert "manual_sync" not in store.values
    assert store.values["last_capture"] == 0
    assert supervisor.next["fixture"] == 0


@pytest.mark.skipif(
    __import__("os").name != "nt" and not __import__("os").getenv("DISPLAY"),
    reason="Tk display required",
)
@pytest.mark.parametrize("language", ["en", "uk"])
def test_real_wizard_local_controls_settings_and_focus(language, monkeypatch):
    import tkinter as tk

    from tanren_collector.desktop import Window
    from tanren_collector.palette_tokens import PALETTES

    class Future:
        def __init__(self, value):
            self.value = value

        def done(self):
            return True

        def result(self):
            return self.value

    class Supervisor:
        def __init__(self):
            self.rows = {}
            self.next = {}
            self.commands = []

        def bindings(self):
            return list(self.rows)

        def tick(self):
            return self.rows

        def discover(self):
            return Future([{"path": "C:/fixture/terminal64.exe", "running": True}])

        def probe(self, path):
            assert path == "C:/fixture/terminal64.exe"
            return Future(IDENTITY)

        def add(self, token, path, identity, key):
            assert token == "a" * 64 and identity == IDENTITY
            self.rows["bound"] = {
                "state": "connected",
                "pairing": "awaiting_browser_confirmation",
                "identity": identity,
                "queue": {},
            }
            return "bound"

        def request_sync(self, key):
            self.commands.append(("sync", key))

        def pause(self, key, paused):
            self.rows[key] = {**self.rows[key], "state": "paused" if paused else "connected"}

        def close(self):
            pass

    root = tk.Tk()
    callback_errors = []
    root.report_callback_exception = lambda *args: callback_errors.append(args[0])
    supervisor = Supervisor()
    saved = []
    window = Window(root, supervisor, {"locale": language, "palette": "graphite"}, saved.append)
    try:
        window.enrollment()
        serial = window.task_number
        monkeypatch.setattr("tkinter.filedialog.askopenfilename", lambda **kwargs: "")
        window.browse()  # Cancel must not invalidate in-flight automatic discovery.
        assert window.task_number == serial
        window.tick()
        root.update()
        assert window.wiz_step == 1 and window.choice.current() == 0
        window.read_choice()
        window.tick()
        root.update()
        assert window.wiz_step == 2 and window.identity == IDENTITY
        window.advance_wizard(3)
        window.token.set("invalid")
        window.connect()
        assert window.wiz_step == 3
        window.token.set("a" * 64)
        window.connect()
        window.tick()
        root.update()
        assert window.token.get() == "" and window.finish.instate(["disabled"])
        supervisor.rows["bound"] = {
            "state": "connected",
            "account_id": "11111111-1111-4111-8111-111111111111",
            "identity": IDENTITY,
            "queue": {},
        }
        window.tick()
        root.update()
        assert window.finish.instate(["!disabled"])
        window.finish.invoke()
        window.tick()
        root.update()
        window.sync_selected("bound")
        assert supervisor.commands == [("sync", "bound")]
        window.change_pause("bound", True)
        window.tick()
        root.update()
        assert window.rows["bound"]["state"] == "paused"
        window.navigate("settings")
        for palette in PALETTES:
            window.save_preference("palette", palette)
            root.update()
            assert saved[-1]["palette"] == palette
        window.pref_controls["notifications"].invoke()
        root.update()
        assert saved[-1]["notifications"] is True
        assert window.pref_controls["notifications"].instate(["selected"])
        field = window.pref_controls["palette"]
        field.focus_force()
        field.event_generate("<Alt-Down>")
        root.update()
        field.event_generate("<Escape>")
        root.update()
        assert not callback_errors
        # Custom dialog Escape restores focus without any system messagebox.
        trigger = window.pref_controls["notifications"]
        trigger.focus_force()
        root.update()
        window.dialog("quit", "quit_body", lambda: None)
        root.update()
        assert window.modal is not None
        window.modal.event_generate("<Escape>")
        root.update()
        assert window.modal is None and root.focus_get() == trigger
    finally:
        window.quit()


def test_upgrade_keeps_pending_v03_payload_id_and_checkpoint(tmp_path):
    from tanren_collector.protocol import batches
    from tanren_collector.runtime import Supervisor
    from tanren_collector.v2_store import Store
    from test_collector import TestProtector

    path = tmp_path / "queue-v2.sqlite"
    end = "2026-10-25T09:00:00+00:00"
    payload = batches(IDENTITY, [], end, end)
    payload[0]["collector_version"] = "0.3.0"
    store = Store(path, TestProtector())
    store.capture("retained", payload, "capture_cursor", end)
    supervisor = Supervisor.__new__(Supervisor)
    supervisor.next = {}
    supervisor.edit = lambda key, action: action(store)
    supervisor.request_sync("binding")
    store.close()
    store = Store(path, TestProtector())
    try:
        assert store.due() == (payload[0]["batch_id"], payload[0])
        assert store.get("capture_cursor") == end
        assert store.get("received_cursor") is None
    finally:
        store.close()


def test_review_version_matches_protocol_and_windows_package():
    from pathlib import Path

    from tanren_collector import __version__
    from tanren_collector.protocol import VERSION

    root = Path(__file__).resolve().parents[1]
    assert VERSION == __version__ == "0.7.1"
    assert '#define Version "0.7.1"' in (root / "build/installer.iss").read_text()
    assert "filevers=(0,7,1,0)" in (root / "build/version-info.txt").read_text()
