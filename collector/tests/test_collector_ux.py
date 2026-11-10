"""Regressions found while testing Collector 0.6.5 on a real account. Synthetic data only."""

import copy
import os
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QObject, QTimer, QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402, F401
from PySide6.QtWidgets import QApplication  # noqa: E402
from tanren_collector.engine import CAPTURE_INTERVAL, Engine  # noqa: E402
from tanren_collector.qt.bridge import ASSETS, Bridge  # noqa: E402
from tanren_collector.qt.synthetic import fixture  # noqa: E402
from test_v2 import NOW, FakeTerminal, store  # noqa: E402, F401


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def spin(ms=120):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@pytest.fixture
def loaded(app):
    bridge = Bridge(True)
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda messages: warnings.extend(m.toString() for m in messages))
    engine.rootContext().setContextProperty("ui", bridge)
    engine.load(QUrl.fromLocalFile(str(ASSETS / "qml/Main.qml")))
    window = engine.rootObjects()[0]
    yield bridge, window, warnings
    window.hide()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    spin(20)


def empty_state():
    state = copy.deepcopy(fixture())
    state["accounts"] = []
    return state


def test_first_account_does_not_freeze_the_screen(loaded):
    bridge, window, warnings = loaded
    bridge.updateState(empty_state())
    spin()
    assert window.property("onboarding") is True
    state = copy.deepcopy(fixture())
    bridge.updateState(state)
    spin()
    assert window.property("onboarding") is False
    assert not warnings, warnings
    window.setProperty("screenIndex", 1)
    spin()
    label = window.findChild(QObject, "lastSyncValue")
    before = label.property("text")
    stamp = (datetime.now(UTC) - timedelta(days=9)).isoformat()
    state = copy.deepcopy(state)
    for account in state["accounts"]:
        account["last_observed_at"] = stamp
    bridge.updateState(state)
    spin()
    assert label.property("text") != before


@pytest.mark.parametrize(("width", "height"), [(1180, 840), (640, 540)])
def test_settings_scrolls_to_the_last_card(loaded, width, height):
    bridge, window, warnings = loaded
    bridge.updateState(copy.deepcopy(fixture()))
    window.setProperty("firstSnapshot", False)
    window.setProperty("onboarding", False)
    window.setProperty("width", width)
    window.setProperty("height", height)
    window.setProperty("screenIndex", 6)
    spin(250)
    scroll = window.findChild(QObject, "pageScroll")
    card = window.findChild(QObject, "deviceCard")
    assert scroll.property("contentHeight") >= card.property("y") + card.property("height")
    assert not warnings, warnings


def test_time_is_plain_local_text_in_the_chosen_language(app):
    bridge = Bridge(True)
    bridge.updateSettings({"locale": "uk"})
    now = datetime.now(UTC).isoformat()
    assert bridge.time(now).startswith("Сьогодні о ")
    assert "UTC" not in bridge.time(now)
    assert bridge.time(None) == bridge.words["notYet"]
    bridge.updateSettings({"locale": "en"})
    assert bridge.time(now).startswith("Today at ")


def test_language_change_refreshes_state_bindings(app):
    bridge = Bridge(True)
    seen = []
    bridge.changed.connect(lambda: seen.append(True))
    bridge.updateSettings({"locale": "uk"})
    assert seen


def test_activity_merges_repeats_and_ignores_queue_counters(app):
    bridge = Bridge(True)
    state = copy.deepcopy(fixture())
    bridge.updateState(state)
    size = len(bridge.activity)
    state = copy.deepcopy(state)
    state["accounts"][0]["pending"] = state["accounts"][0]["pending"] + 5
    bridge.updateState(state)
    assert len(bridge.activity) == size
    bridge.remember("accounts", "waiting")
    bridge.remember("accounts", "waiting")
    assert [e["state"] for e in bridge.activity[:2]].count("waiting") == 1


def test_routine_reads_wait_for_the_interval_and_keep_a_boundary_overlap(store):  # noqa: F811
    terminal = FakeTerminal()
    now = [NOW]
    engine = Engine(store, terminal, lambda *_: None, lambda: now[0])
    config = store.get("config")
    engine.capture(config)
    assert len(terminal.calls) == 1
    now[0] += timedelta(seconds=CAPTURE_INTERVAL - 1)
    engine.capture(config)
    assert len(terminal.calls) == 1
    cursor = datetime.fromisoformat(store.get("capture_cursor"))
    now[0] += timedelta(seconds=2)
    engine.capture(config)
    assert len(terminal.calls) == 2
    assert terminal.calls[-1][0] < cursor


def test_manual_sync_does_not_wait_for_the_interval(store):  # noqa: F811
    terminal = FakeTerminal()
    now = [NOW]
    engine = Engine(store, terminal, lambda *_: None, lambda: now[0])
    config = store.get("config")
    engine.capture(config)
    store.save("last_capture", 0)
    engine.capture(config)
    assert len(terminal.calls) == 2


def test_quiet_update_check_finds_a_release_without_errors_or_downloads(app):
    """The background check only reads the manifest and never shows an error."""
    from tanren_collector.qt import bridge as module

    bridge = module.Bridge(synthetic=False)
    try:
        assert not bridge._update_timer.isActive()  # only installed Windows builds schedule it
        calls = []

        class Found:
            def check(self):
                calls.append("check")
                return {"version": "9.9.9"}

            def download(self, info):  # pragma: no cover - must never be called
                raise AssertionError("background check must not download")

        bridge._updater = Found()
        bridge._apply_quiet_update({"found": bridge._updater.check()})
        assert bridge.updateInfo == {"state": "available", "version": "9.9.9"}
        # A failed check keeps whatever the user saw.
        bridge._apply_quiet_update(None)
        assert bridge.updateInfo["state"] == "available"
        # Nothing newer: an idle view becomes "current", an error the user saw is kept.
        bridge._update = {"state": "error", "error": "UPDATE_FAILED"}
        bridge._apply_quiet_update({"found": None})
        assert bridge.updateInfo["state"] == "error"
        bridge._update = {"state": "idle"}
        bridge._apply_quiet_update({"found": None})
        assert bridge.updateInfo["state"] == "current"
        assert bridge._update_timer.interval() == module.UPDATE_CHECK_FIRST_MS
        assert calls == ["check"]
    finally:
        bridge.deleteLater()


@pytest.mark.parametrize(
    ("broker", "server", "category", "enabled"),
    [
        ("Some Broker Ltd", "SomeBroker-Live", "", False),
        ("ACG Markets Ltd", "ACGMarkets-Live", "prop_firm", True),
        ("Some Broker Ltd", "SomeBroker-Demo", "demo", True),
    ],
)
def test_category_is_never_guessed_as_personal(loaded, broker, server, category, enabled):
    bridge, window, warnings = loaded
    state = copy.deepcopy(fixture())
    state["terminals"] = [{**state["terminals"][0], "broker": broker, "server": server}]
    bridge.updateState(state)
    window.setProperty("firstSnapshot", False)
    window.setProperty("onboarding", False)
    window.setProperty("screenIndex", 3)
    spin()
    choice = window.findChild(QObject, "terminalChoice")
    choice.setProperty("selectedValue", state["terminals"][0]["key"])
    spin(250)
    picked = window.findChild(QObject, "category")
    button = window.findChild(QObject, "registerButton")
    hint = window.findChild(QObject, "categoryHint")
    assert picked.property("selectedValue") == category
    assert button.property("enabled") is enabled
    assert hint.property("visible") is (not enabled)
    if not enabled:
        picked.setProperty("selectedValue", "personal")
        spin()
        assert button.property("enabled") is True and hint.property("visible") is False
    assert not warnings, warnings
