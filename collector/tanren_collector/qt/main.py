"""Qt entry. Frozen multiprocessing bootstrap is performed by desktop_entry BEFORE this import."""

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, QtMsgType, QUrl, qInstallMessageHandler
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase, QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QSystemTrayIcon

from .. import diagnostics_log
from ..build_profile import current
from ..build_target import ORIGIN
from .bridge import ASSETS, Bridge
from .lifecycle import NativeEvents, reduced_motion
from .shutdown import ShutdownGuard
from .smoke_report import run_report


def qt_trail(mode, _context, message):
    if mode not in {QtMsgType.QtDebugMsg, QtMsgType.QtInfoMsg}:
        diagnostics_log.qt_message(message)


def main(background=False):
    parser = argparse.ArgumentParser()
    parser.add_argument("--qt-smoke", action="store_true")
    parser.add_argument("--screenshot-dir")
    parser.add_argument("--smoke-report")
    parser.add_argument("--background", action="store_true")
    args = parser.parse_args()
    synthetic = args.qt_smoke
    if getattr(sys, "frozen", False) and not synthetic:
        qInstallMessageHandler(qt_trail)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv[:1])
    app.setApplicationName(current().display_name)
    app.setQuitOnLastWindowClosed(False)
    QQuickStyle.setStyle("Basic")
    family = (
        "Inter"
        if "Inter" in QFontDatabase.families()
        else "Segoe UI"
        if "Segoe UI" in QFontDatabase.families()
        else "DejaVu Sans"
    )
    app.setFont(QFont(family, 10))
    mutex = lock = None
    if not synthetic:
        from ..windows import AppMutex, FileLock, data_directory, show_existing

        root = data_directory()
        try:
            mutex = AppMutex()
            lock = FileLock(root / "instance.lock")
        except (RuntimeError, OSError):
            if mutex:
                mutex.close()
            show_existing()
            return 0
        from .service import RuntimeService

        service = RuntimeService(root)
    else:
        from .synthetic import SyntheticService

        service = SyntheticService()
    bridge = Bridge(synthetic)
    bridge._os_reduced = reduced_motion()
    thread = QThread()
    service.moveToThread(thread)
    bridge.requested.connect(service.dispatch, Qt.ConnectionType.QueuedConnection)
    bridge.suspensionRequested.connect(service.suspension, Qt.ConnectionType.QueuedConnection)
    exit_code = None
    shutdown = ShutdownGuard(service, thread)
    bridge.stopRequested.connect(shutdown.request)
    if not synthetic:
        QTimer.singleShot(8000, bridge.checkUpdate)

    def shutdown_failed():
        nonlocal exit_code
        if synthetic:
            exit_code = 3
        bridge.updateCommand(
            {"id": "shutdown", "action": "shutdown", "phase": "failed", "error": "SHUTDOWN_TIMEOUT"}
        )

    shutdown.failed.connect(shutdown_failed)
    service.snapshotReady.connect(bridge.updateState)
    service.settingsReady.connect(bridge.updateSettings)
    service.commandChanged.connect(bridge.updateCommand)
    thread.finished.connect(app.quit)
    thread.started.connect(service.start)
    engine = QQmlApplicationEngine()
    errors = []
    engine.warnings.connect(lambda messages: errors.extend(m.description() for m in messages))
    engine.rootContext().setContextProperty("ui", bridge)
    engine.load(QUrl.fromLocalFile(str(ASSETS / "qml/Main.qml")))
    if not engine.rootObjects():
        if lock:
            lock.close()
        if mutex:
            mutex.close()
        return 2
    window = engine.rootObjects()[0]
    app.setWindowIcon(QIcon(str(ASSETS / "assets/app.svg")))
    tray = QSystemTrayIcon(app.windowIcon(), app)
    tray.setToolTip(current().display_name)
    menu = QMenu()

    def show():
        window.show()
        window.raise_()
        window.requestActivate()

    open_action = menu.addAction("Open Tanren", show)
    refresh_action = menu.addAction("Refresh", lambda: bridge.send("refresh", {}))
    pause_action = menu.addAction("Pause", lambda: bridge.send("pauseAll", {"paused": True}))
    resume_action = menu.addAction("Resume", lambda: bridge.send("pauseAll", {"paused": False}))
    menu.addSeparator()
    quit_action = menu.addAction("Quit", bridge.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: show() if reason == QSystemTrayIcon.ActivationReason.Trigger else None
    )
    bridge._tray = QSystemTrayIcon.isSystemTrayAvailable()
    if bridge._tray:
        tray.show()

    def localize():
        text = bridge.words
        for action, key in [
            (open_action, "welcome"),
            (refresh_action, "refresh"),
            (pause_action, "pause"),
            (resume_action, "resume"),
            (quit_action, "quit"),
        ]:
            action.setText(text[key])

    def notify():
        if (
            bridge._tray
            and bridge.preferences["notifications"]
            and bridge.command.get("phase") == "failed"
        ):
            tray.showMessage(
                current().display_name,
                bridge.words["support"],
                QSystemTrayIcon.MessageIcon.Warning,
                5000,
            )

    bridge.commandChanged.connect(notify)
    bridge.settingsChanged.connect(localize)
    dialogs = []

    def export_dialog():
        if dialogs:
            dialogs[0].raise_()
            return
        dialog = QFileDialog()
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setNameFilter("ZIP (*.zip)")
        dialog.setDefaultSuffix("zip")
        dialog.setWindowTitle(bridge.words["export"])
        dialog.fileSelected.connect(
            lambda filename: bridge.send("diagnostic", {"destination": filename})
        )
        dialogs.append(dialog)
        dialog.finished.connect(lambda _result: dialogs.remove(dialog))
        dialog.finished.connect(dialog.deleteLater)
        dialog.open()

    bridge.exportRequested.connect(export_dialog)

    def pick_terminal():
        path, _ = QFileDialog.getOpenFileName(
            None, "MetaTrader 5", "C:/Program Files", "terminal64.exe (terminal64.exe)"
        )
        if path:
            bridge.addTerminalPath(path)

    bridge.terminalPickRequested.connect(pick_terminal)
    bridge.accountPageRequested.connect(
        lambda account: (
            QDesktopServices.openUrl(QUrl(ORIGIN + "/accounts/" + account))
            if not synthetic
            else None
        )
    )
    bridge.browserRequested.connect(
        lambda: QDesktopServices.openUrl(QUrl(ORIGIN + "/collector")) if not synthetic else None
    )
    events = NativeEvents(bridge)
    app.installNativeEventFilter(events)
    if (background or args.background) and bridge._tray:
        window.hide()
    if synthetic:
        from .smoke import exercise

        evidence = (
            Path(args.smoke_report)
            if args.smoke_report
            else Path(args.screenshot_dir or ".") / "qt-smoke.json"
        )

        def run_smoke():
            nonlocal exit_code

            def exercise_report():
                result = exercise(app, engine, window, bridge, service, args.screenshot_dir)
                result["qml_errors"] = ["QML_WARNING"] * min(len(errors), 32)
                result["tray_available"] = bridge._tray
                result["device_pixel_ratio"] = window.devicePixelRatio()
                result["checks_passed"] = (
                    result.get("checks_passed") is True
                    and result.get("spawn_bootstrap") is True
                    and not errors
                )
                return result

            exit_code = run_report(
                evidence,
                exercise_report,
                {
                    "schema": 1,
                    "synthetic": True,
                    "frozen": bool(getattr(sys, "frozen", False)),
                },
            )
            shutdown.request()

        QTimer.singleShot(500, run_smoke)
    thread.start()
    try:
        while True:
            result = app.exec()
            if not thread.isRunning():
                return exit_code if exit_code is not None else result
            # External Qt quit/session requests must not destroy a live QThread or release its
            # profile lock. Re-enter the responsive event loop until cooperative stop completes.
            shutdown.request()
    finally:
        tray.hide()
        if lock:
            lock.close()
        if mutex:
            mutex.close()
