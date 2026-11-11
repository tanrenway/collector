"""Qt contract and offscreen interaction tests. Synthetic profiles only; no native claims."""

import json
import os
import subprocess
import sys
import threading
from concurrent.futures import Future
from pathlib import Path
from urllib.parse import unquote

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QThread  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from tanren_collector.application_state import ApplicationState, DeviceView  # noqa: E402
from tanren_collector.qt.bridge import Bridge  # noqa: E402
from tanren_collector.qt.service import RuntimeService  # noqa: E402
from tanren_collector.qt.strings import PAIRS  # noqa: E402
from tanren_collector.qt.synthetic import BINDINGS, TERMINAL, fixture  # noqa: E402
from tanren_collector.storage import load_config, save_config  # noqa: E402
from test_collector import TestProtector  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_bridge_bounded_commands_and_no_qml_secret_surface(app):
    bridge = Bridge(True)
    sent = []
    bridge.requested.connect(lambda action, body, ticket: sent.append((action, body, ticket)))
    assert not bridge.pair("code", "Device", True, False)
    assert not bridge.migrate(BINDINGS[0], True, False)
    assert not bridge.accountAction("../../profile", "activate")
    assert not bridge.accountAction(BINDINGS[0], "delete")
    assert not bridge.preview("C:/Users/private/terminal.exe")
    assert not bridge.registerAccount(TERMINAL, {"token": "forbidden"})
    assert not bridge.preference("api_url", "https://invalid.example")
    assert not sent
    assert bridge.pair("TEST-CODE", "Device", False, False)
    assert "TEST-CODE" not in json.dumps(bridge.state) + json.dumps(bridge.command)
    for _ in range(7):
        assert bridge.discover()
    assert not bridge.discover()
    bridge.updateCommand({"id": sent[0][2], "phase": "confirmed"})
    assert bridge.discover()
    meta = bridge.metaObject()
    exposed = [
        bytes(meta.method(i).methodSignature()).decode()
        for i in range(meta.methodOffset(), meta.methodCount())
    ]
    assert not any(
        word in method
        for method in exposed
        for word in ["save_config", "sqlite", "send(", "runtime(", "token("]
    )
    assert bridge.icon("../../private", "#ffffff") == ""
    assert bridge.mark("#111111", "#222222", "url(evil)") == ""


def test_horizon_mark_uses_palette_roles_and_matches_the_web_icon(app):
    bridge = Bridge(True)
    colors = ["#111111", "#222222", "#444444"]
    svg = unquote(bridge.mark(*colors))
    assert all(color in svg for color in colors) and "mark" not in svg
    root = Path(__file__).resolve().parents[2]
    assets = root / "collector/tanren_collector/qt/assets"
    from conftest import monorepo_file

    assert (assets / "app.svg").read_bytes() == monorepo_file("frontend/app/icon.svg").read_bytes()
    assert not (assets / "arrow.svg").exists()


def test_dto_tuples_suspension_locales_and_palette_contract(app):
    bridge = Bridge(True)
    bridge.updateState(fixture())
    assert isinstance(bridge.state["accounts"], list)
    assert bridge.summary == {
        "accounts": 2,
        "active": 1,
        "standby": 1,
        "pending": 2,
        "processing": 1,
        "last_processed": "2026-10-26T08:59:00+00:00",
        "last_synced": "2026-10-26T09:00:00+00:00",
    }
    bridge.selectAccount(BINDINGS[0])
    assert bridge.selected["force"][0]["state"] == "received"
    for palette in ["obsidian", "midnight", "graphite", "carbon", "arctic", "ivory"]:
        # Preferences remain confirmed-only until service ACK.
        prior = bridge.preferences["palette"]
        bridge.preference("palette", palette)
        assert bridge.preferences["palette"] == prior
        bridge.updateSettings({"palette": palette})
        assert bridge.colors["canvas"].startswith("#")
    for language in ["en", "uk"]:
        bridge.updateSettings({"locale": language})
        assert all(bridge.words[key] for key in PAIRS)
        assert bridge.time(None) == bridge.words["notYet"]
        assert bridge.time("invalid") == bridge.words["notYet"]
        assert "UTC" not in bridge.time("2026-10-26T09:00:00Z")
    value = fixture()
    value["suspended"] = True
    bridge.updateState(value)
    assert bridge.summary["active"] == bridge.summary["standby"] == 0
    bridge._os_reduced = True
    assert bridge.reducedMotion


class Runtime:
    def __init__(self, root):
        self.thread = threading.get_ident()
        self.state = ApplicationState(device=DeviceView("awaiting_browser_confirmation"))
        self.task = Future()
        self.closed = False
        self.failed = False

    def tick(self):
        assert self.thread == threading.get_ident()
        if self.failed:
            raise ConnectionError("secret-token C:/Users/private")

    def pair_device(self, *args, **kwargs):
        return self.task

    def close(self):
        self.closed = True

    def resume(self):
        pass

    def diagnostic_statuses(self):
        return [
            {"error": "secret-token C:/Users/private", "token": "secret-token", "state": "error"}
        ]


def test_service_confirmation_failure_persistence_redaction(app, tmp_path, monkeypatch):
    service = RuntimeService(tmp_path, Runtime, TestProtector)
    reports, snapshots = [], []
    service.commandChanged.connect(reports.append)
    service.snapshotReady.connect(snapshots.append)
    service.start()
    service.timer.stop()
    service.dispatch(
        "pair", {"code": "TEST", "name": "Device", "repair": False, "confirmed": False}, "pair"
    )
    assert reports[-1]["phase"] == "pending"
    service.tick()
    assert reports[-1]["phase"] == "pending"
    service.runtime.task.set_result(None)
    service.tick()
    assert reports[-1]["phase"] == "awaiting_browser_confirmation"
    service.runtime.state = ApplicationState(device=DeviceView("paired"))
    service.tick()
    assert reports[-1]["phase"] == "confirmed"
    service.dispatch("settings", {"palette": "carbon", "locale": "uk"}, "settings")
    assert reports[-1]["phase"] == "confirmed"
    assert load_config(tmp_path / "settings.dpapi", TestProtector())["palette"] == "carbon"
    service.dispatch("settings", {"palette": "forest"}, "retired-palette")
    assert reports[-1]["phase"] == "failed" and service.settings["palette"] == "carbon"
    import tanren_collector.qt.service as module

    def fail(*args):
        raise OSError("private-path secret-token")

    monkeypatch.setattr(module, "save_config", fail)
    service.dispatch("settings", {"palette": "ivory"}, "failed-settings")
    assert reports[-1]["phase"] == "failed" and service.settings["palette"] == "carbon"
    service.dispatch("preview", {"key": TERMINAL}, "invalid-selection")
    assert reports[-1]["phase"] == "failed"
    service.dispatch("diagnostic", {"destination": str(tmp_path / "safe.zip")}, "export")
    import zipfile

    with zipfile.ZipFile(tmp_path / "safe.zip") as archive:
        content = b"".join(archive.read(name) for name in archive.namelist())
    assert b"secret-token" not in content and b"C:/Users/private" not in content
    service.runtime.failed = True
    service.tick()
    assert "secret-token" not in json.dumps(snapshots)
    service.stop()
    assert service.runtime.closed


def test_runtime_starts_outside_gui_thread(app, tmp_path):
    from PySide6.QtCore import QMetaObject, Qt

    service = RuntimeService(tmp_path, Runtime, TestProtector)
    thread = QThread()
    service.moveToThread(thread)
    thread.started.connect(service.start)
    thread.start()
    try:
        QMetaObject.invokeMethod(service, "tick", Qt.ConnectionType.BlockingQueuedConnection)
        assert service.runtime.thread != threading.get_ident()
        QMetaObject.invokeMethod(service, "stop", Qt.ConnectionType.BlockingQueuedConnection)
        assert service.runtime.closed
    finally:
        thread.quit()
        assert thread.wait(5000)


@pytest.mark.parametrize("scale", ["1", "1.25", "1.5", "2"])
def test_full_qml_interactions_and_dpi(scale, tmp_path):
    result = subprocess.run(  # noqa: S603 - fixed repository synthetic entrypoint; no shell
        [
            sys.executable,
            "-c",
            "import runpy,sys; sys.stdout=None; sys.stderr=None; "
            "entry=sys.argv.pop(1); runpy.run_path(entry, run_name='__main__')",
            str(ROOT / "collector/desktop_entry.py"),
            "--qt-smoke",
            "--screenshot-dir",
            str(tmp_path),
        ],
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT / "collector"),
            "QT_QPA_PLATFORM": "offscreen",
            "QT_QUICK_BACKEND": "software",
            "QT_SCALE_FACTOR": scale,
        },
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "qt-smoke.json").read_text())
    assert report["checks_passed"] and report["spawn_bootstrap"]
    assert report["qml_errors"] == [] and report["device_pixel_ratio"] == float(scale)
    assert len(list(tmp_path.glob("*.png"))) == 26


def test_native_power_dispatch_does_not_confuse_lock_with_sleep(app):
    from tanren_collector.qt.lifecycle import NativeEvents

    bridge = Bridge(True)
    states = []
    bridge.suspensionRequested.connect(states.append)
    native = NativeEvents(bridge)
    native.dispatch(0x218, 4)
    native.dispatch(0x218, 18)
    native.dispatch(0x2B1, 7)  # WTS lock is not a power event.
    assert states == [True, False]


def test_every_qml_call_has_an_explicit_qt_method(app):
    import re

    bridge = Bridge(True)
    meta = bridge.metaObject()
    exposed = {bytes(meta.method(i).name()).decode() for i in range(meta.methodCount())}
    qml = (ROOT / "collector/tanren_collector/qt/qml/Main.qml").read_text()
    called = set(re.findall(r"ui\.(\w+)\(", qml))
    assert called <= exposed


def test_user_text_is_plain_not_rich_content(app):
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

    bridge = Bridge(True)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("ui", bridge)
    directory = ROOT / "collector/tanren_collector/qt/qml/components"
    source = (
        'import QtQuick\nimport "' + directory.as_uri() + '" as C\n'
        'C.Copy { text: "<img src=\\"https://invalid.example/private\\">"; '
        "property bool safe: textFormat === Text.PlainText }"
    )
    component = QQmlComponent(engine)
    component.setData(source.encode(), QUrl.fromLocalFile(str(directory / "test.qml")))
    item = component.create()
    assert item is not None, [error.toString() for error in component.errors()]
    assert item.property("safe")
    item.deleteLater()


def test_search_picker_keeps_selection_and_ignores_unfocused_wheel(app):
    from PySide6.QtCore import QMetaObject, QObject, QUrl
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

    bridge = Bridge(True)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("ui", bridge)
    directory = ROOT / "collector/tanren_collector/qt/qml/components"
    source = (
        'import QtQuick\nimport QtQuick.Controls\nimport "' + directory.as_uri() + '" as C\n'
        "ApplicationWindow { width: 640; height: 540; visible: true; "
        'C.Choice { objectName: "picker"; width: 300; '
        'model: Array.from({length:10},(_,i)=>({label:"Account "+i,value:"id"+i})) } }'
    )
    component = QQmlComponent(engine)
    component.setData(source.encode(), QUrl.fromLocalFile(str(directory / "test.qml")))
    window = component.create()
    assert window is not None, [e.toString() for e in component.errors()]
    app.processEvents()
    picker = window.findChild(QObject, "picker")
    control = window.findChild(QObject, "pickerInput")
    popup = window.findChild(QObject, "pickerPopup")
    assert picker.property("searchable") and not control.property("wheelEnabled")
    picker.setProperty("selectedValue", "id7")
    picker.setProperty("query", "7")
    app.processEvents()
    assert control.property("count") == 1 and picker.property("selectedValue") == "id7"
    QMetaObject.invokeMethod(popup, "open")
    app.processEvents()
    QMetaObject.invokeMethod(popup, "close")
    app.processEvents()
    assert picker.property("query") == "" and control.property("count") == 10
    bridge.updateSettings({"palette": "ivory", "locale": "uk"})
    app.processEvents()
    assert picker.property("selectedValue") == "id7"
    window.deleteLater()


def test_window_preferences_are_validated_and_saved_atomically(app, tmp_path):
    service = RuntimeService(tmp_path, Runtime, TestProtector)
    reports = []
    service.commandChanged.connect(reports.append)
    service.start()
    service.timer.stop()
    service.dispatch(
        "settings",
        {"window_width": 900, "window_height": 700, "window_maximized": False},
        "geometry",
    )
    assert reports[-1]["phase"] == "confirmed"
    service.dispatch("settings", {"window_width": 1}, "invalid")
    assert reports[-1]["phase"] == "failed" and service.settings["window_width"] == 900
    saved = load_config(tmp_path / "settings.dpapi", TestProtector())
    assert saved["window_width"] == 900 and saved["window_height"] == 700
    service.stop()


def test_first_run_advances_only_on_authoritative_device_and_account_state(app):
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlApplicationEngine

    bridge = Bridge(True)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("ui", bridge)
    engine.load(QUrl.fromLocalFile(str(ROOT / "collector/tanren_collector/qt/qml/Main.qml")))
    assert engine.rootObjects()
    window = engine.rootObjects()[0]
    value = fixture()
    value["accounts"] = []
    value["device"] = {"state": "disconnected"}
    bridge.updateState(value)
    app.processEvents()
    assert window.property("screenIndex") == 0
    value["device"] = {"state": "awaiting_browser_confirmation"}
    bridge.updateState(value)
    app.processEvents()
    assert window.property("screenIndex") == 0
    value["device"] = {"state": "paired"}
    bridge.updateState(value)
    app.processEvents()
    assert window.property("screenIndex") == 3
    bridge.updateState(fixture())
    app.processEvents()
    assert window.property("screenIndex") == 4 and not window.property("onboarding")
    window.deleteLater()


def test_activity_is_bounded_and_processing_requires_a_server_timestamp(app):
    bridge = Bridge(True)
    value = fixture()
    bridge.updateState(value)
    assert any(event["state"] == "processed" for event in bridge.activity)
    assert not any("token" in event or "binding_id" in event for event in bridge.activity)
    for index in range(80):
        bridge.remember("accounts", "waiting" if index % 2 else "active")
    assert len(bridge.activity) == 50
    value = fixture()
    value["accounts"] = [{**value["accounts"][0], "last_processed_at": None}]
    other = Bridge(True)
    other.updateState(value)
    assert not any(event["state"] == "processed" for event in other.activity)


def test_shutdown_watchdog_keeps_gui_responsive_until_service_recovers(app):
    import time

    from PySide6.QtCore import QObject, QTimer, Signal, Slot
    from tanren_collector.qt.shutdown import ShutdownGuard

    entered, release = threading.Event(), threading.Event()

    class SlowService(QObject):
        finished = Signal()

        @Slot()
        def start(self):
            entered.set()
            release.wait(5)

        @Slot()
        def stop(self):
            self.finished.emit()

    service = SlowService()
    thread = QThread()
    service.moveToThread(thread)
    thread.started.connect(service.start)
    guard = ShutdownGuard(service, thread, timeout_ms=20)
    failed, responsive = [], []
    guard.failed.connect(lambda: failed.append(True))
    thread.start()
    try:
        assert entered.wait(2)
        guard.request()
        QTimer.singleShot(5, lambda: responsive.append(True))
        deadline = time.monotonic() + 2
        while not failed and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.002)
        assert failed and responsive and thread.isRunning()
        release.set()
        deadline = time.monotonic() + 2
        while thread.isRunning() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.002)
        assert not thread.isRunning()
    finally:
        release.set()
        assert thread.wait(5000)


def test_failed_runtime_close_never_signals_safe_exit(app, tmp_path):
    service = RuntimeService(tmp_path, Runtime, TestProtector)
    service.start()
    finished, reports = [], []
    service.finished.connect(lambda: finished.append(True))
    service.commandChanged.connect(reports.append)

    def fail():
        raise OSError("token=SECRET private path")

    service.runtime.close = fail
    service.stop()
    assert not finished and service.stopping
    assert reports[-1]["error"] == "SHUTDOWN_FAILED"
    assert "SECRET" not in json.dumps(reports)


def test_stopping_service_ignores_already_queued_tick_and_resume(app, tmp_path):
    service = RuntimeService(tmp_path, Runtime, TestProtector)
    service.start()
    service.stopping = True
    calls = []
    service.runtime.tick = lambda: calls.append("tick")
    service.runtime.resume = lambda: calls.append("resume")
    service.tick()
    service.suspension(False)
    assert calls == []
    service.timer.stop()
    service.runtime.close()


def test_service_maps_retired_saved_palettes_on_load(app, tmp_path):
    # Unknown values fall back to the default automatic theme; explicit choices are kept.
    for saved, expected in (
        ("forest", "carbon"),
        ("slate", "obsidian"),
        ("unknown", "system"),
        ("obsidian", "obsidian"),
        ("system", "system"),
    ):
        save_config(tmp_path / "settings.dpapi", {"palette": saved}, TestProtector())
        service = RuntimeService(tmp_path, Runtime, TestProtector)
        service.start()
        service.timer.stop()
        assert service.settings["palette"] == expected


def test_new_install_follows_system_theme_and_resolves_palette(app, tmp_path, monkeypatch):
    from tanren_collector.qt.bridge import Bridge
    from tanren_collector.qt.service import DEFAULTS, SYSTEM_PALETTES

    assert DEFAULTS["palette"] == "system"
    assert SYSTEM_PALETTES == {"dark": "graphite", "light": "ivory"}
    service = RuntimeService(tmp_path, Runtime, TestProtector)
    service.start()
    service.timer.stop()
    assert service.settings["palette"] == "system"
    bridge = Bridge(True)
    bridge.updateSettings({"palette": "system"})
    assert bridge.resolvedPalette in {"graphite", "ivory"}
    assert bridge.colors["canvas"]
    bridge.updateSettings({"palette": "carbon"})
    assert bridge.resolvedPalette == "carbon"


def test_errors_are_explained_by_cause_not_as_network(app):
    from tanren_collector.qt.bridge import Bridge

    bridge = Bridge(True)
    bridge.updateSettings({"locale": "en"})
    words = bridge.words
    assert bridge.explain("REGISTRATION_HTTP_409") == words["conflictHelp"]
    assert bridge.explain("IDENTITY_CONFLICT") == words["conflictHelp"]
    assert bridge.explain("DEVICE_SCOPE_MISMATCH") == words["scopeHelp"]
    assert bridge.explain("SYNC_PAUSED_HTTP_401") == words["authHelp"]
    assert bridge.explain("NETWORK_TIMEOUT") == words["networkHelp"]
    assert "unlinked" in words["authHelp"]


def test_update_flow_states_and_shutdown(app, monkeypatch):
    from tanren_collector.qt import bridge as module

    class Immediate:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(module.threading, "Thread", Immediate)
    monkeypatch.setattr(Bridge, "installedWindows", property(lambda self: True))

    class Fake:
        found = {"version": "9.0.0"}
        launched = False

        def check(self):
            return self.found

        def download(self, info):
            return "installer.exe"

        def launch(self, path, info):
            self.launched = True

    bridge, stops = Bridge(False), []
    bridge._updater = Fake()
    bridge.stopRequested.connect(lambda: stops.append(True))
    assert not bridge.installUpdate() and not bridge.downloadUpdate()
    assert bridge.checkUpdate()
    assert bridge.updateInfo == {"state": "available", "version": "9.0.0"}
    assert bridge.downloadUpdate()
    assert bridge.updateInfo == {"state": "ready", "version": "9.0.0"}
    assert bridge.installUpdate() and bridge._updater.launched and stops == [True]
    bridge._updater.found = None
    assert bridge.checkUpdate() and bridge.updateInfo == {"state": "current"}


def test_update_is_inert_in_synthetic_mode_and_reports_failures(app, monkeypatch):
    from tanren_collector.qt import bridge as module

    synthetic = Bridge(True)
    assert not synthetic.checkUpdate() and synthetic.updateInfo == {"state": "idle"}

    class Immediate:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()

    class Failing:
        def check(self):
            raise RuntimeError("UPDATE_CHECK_FAILED")

    monkeypatch.setattr(module.threading, "Thread", Immediate)
    bridge = Bridge(False)
    bridge._updater = Failing()
    assert bridge.checkUpdate()
    assert bridge.updateInfo == {"state": "error", "error": "UPDATE_CHECK_FAILED"}


def test_full_queue_of_commands_is_reported_not_silent(app):
    bridge = Bridge(True)
    bridge._outstanding = {str(i) for i in range(8)}
    assert bridge.discover() is False
    assert bridge.command["phase"] == "failed" and bridge.command["error"] == "RUNTIME_BUSY"
    assert bridge.explain("RUNTIME_BUSY") == bridge.words["busyHelp"]


def test_account_page_accepts_only_an_account_id(app):
    bridge, opened = Bridge(True), []
    bridge.accountPageRequested.connect(opened.append)
    bridge.openAccountPage("../../evil")
    bridge.openAccountPage("11111111-1111-4111-8111-111111111111")
    assert opened == ["11111111-1111-4111-8111-111111111111"]
