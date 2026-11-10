"""Actual offscreen QML geometry, local display metadata and contextual notices."""

import time

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickItem  # noqa: E402, F401 - registers QQuickItem property converter
from PySide6.QtWidgets import QApplication  # noqa: E402
from tanren_collector.qt.bridge import ASSETS, Bridge  # noqa: E402
from tanren_collector.qt.synthetic import fixture  # noqa: E402


def spin(app):
    end = time.monotonic() + 0.08
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.002)


def test_success_notices_expire_but_errors_and_authorization_remain():
    app = QApplication.instance() or QApplication([])
    bridge = Bridge(True)
    bridge._notice_timer.setInterval(10)
    bridge.updateCommand({"id": "a", "phase": "confirmed"})
    assert bridge.noticeVisible
    spin(app)
    assert not bridge.noticeVisible and bridge.command["phase"] == "confirmed"
    bridge.updateCommand({"id": "a", "phase": "confirmed"})
    assert not bridge.noticeVisible  # Repeated snapshots cannot resurrect a stale success.
    for phase in ("failed", "awaiting_browser_confirmation", "pending"):
        bridge.updateCommand({"id": phase, "phase": phase})
        bridge.dismissNotice()
        spin(app)
        assert bridge.noticeVisible


def test_active_page_geometry_navigation_and_localization():
    app = QApplication.instance() or QApplication([])
    bridge = Bridge(True)
    bridge.updateState(fixture())
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda messages: warnings.extend(m.description() for m in messages))
    engine.rootContext().setContextProperty("ui", bridge)
    engine.load(QUrl.fromLocalFile(str(ASSETS / "qml/Main.qml")))
    window = engine.rootObjects()[0]
    try:
        from PySide6.QtCore import QObject

        scroll = window.findChild(QObject, "pageScroll")
        for locale in ("en", "uk"):
            bridge.updateSettings({"locale": locale})
            for width, height in ((1180, 840), (640, 540)):
                window.setProperty("width", width)
                window.setProperty("height", height)
                for index in range(9):
                    window.setProperty("screenIndex", index)
                    spin(app)
                    content = float(scroll.property("contentHeight"))
                    assert content >= 0
                    # Short Activity page must not inherit the much taller registration/settings.
                    if index == 8 and width == 1180:
                        assert content < float(scroll.property("availableHeight"))
                        assert abs(scroll.property("contentItem").property("contentY")) < 1
        assert not warnings, warnings
    finally:
        window.hide()
        engine.deleteLater()
        from PySide6.QtCore import QCoreApplication, QEvent

        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        spin(app)
