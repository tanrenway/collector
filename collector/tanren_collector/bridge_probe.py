"""Explicit read-only Windows probe. No profile, credentials, network or trading operations."""

import argparse
import importlib
import importlib.metadata
import json
import os
import platform
import re
import sys
import time
from pathlib import Path

from . import __version__, build_target
from .observability import capture, clean, recent, stage
from .processes import SpawnPool
from .terminal import initialize_readonly


def load_bridge():
    with stage("mt5_import"):
        api = importlib.import_module("MetaTrader5")
        importlib.import_module("MetaTrader5._core")
    return api


def inspect_bridge(path=None, factory=load_bridge):
    """Child-only; compare identities in memory, export booleans/codes, never account data."""
    api = factory()
    checks = {"module_import": True, "native_extension": True}
    if path is None:
        return checks
    identity = None
    for cycle in range(2):
        try:
            try:
                initialize_readonly(api, path, timeout=10000)
            except Exception as exc:
                code = api.last_error()[0]
                if type(code) is int:
                    exc.mt5_error_code = code
                capture("mt5_initialize", exc)
                raise
            checks[f"initialize_{cycle}"] = True
            with stage("terminal_identity"):
                terminal = api.terminal_info()
            with stage("account_identity"):
                account = api.account_info()
            if terminal is None or account is None or not terminal.connected:
                raise RuntimeError("TERMINAL_DISCONNECTED")
            current = (account.login, account.server, account.company, account.currency)
            if identity is not None and current != identity:
                raise RuntimeError("TERMINAL_IDENTITY_MISMATCH")
            identity = current
            checks[f"read_identity_{cycle}"] = True
        finally:
            api.shutdown()  # Disconnect IPC only. Never terminate/restart the MT5 application.
        checks[f"shutdown_{cycle}"] = True
    checks["identity_stable"] = True
    return checks


def run_child(path=None, timeout=40, pool_factory=SpawnPool):
    pool = pool_factory(max_workers=1, timeout=timeout)
    try:
        task = pool.submit(inspect_bridge, path)
        while not task.done():
            pool.tick()
            time.sleep(0.02)
        return task.result()
    finally:
        pool.shutdown()


def versions():
    result = {"python": platform.python_version(), "collector": __version__}
    for name in ["MetaTrader5", "numpy", "PySide6-Essentials", "PyInstaller"]:
        try:
            value = importlib.metadata.version(name)
            result[name] = value if re.fullmatch(r"\d+(?:\.\d+){1,3}", value) else "unknown"
        except importlib.metadata.PackageNotFoundError:
            result[name] = "not_available_in_metadata"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge-probe", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--terminal", type=Path)
    parser.add_argument("--acknowledge-test-terminal", action="store_true")
    parser.add_argument("--qt-parent", action="store_true")
    args = parser.parse_args(argv)
    if args.terminal and (
        not args.acknowledge_test_terminal
        or not args.terminal.is_absolute()
        or args.terminal.name.lower() != "terminal64.exe"
        or not args.terminal.is_file()
    ):
        parser.error(
            "An explicit existing terminal64.exe and test-terminal acknowledgement are required"
        )
    if args.report.exists():
        parser.error("Use a new private report path; never overwrite existing evidence")
    commit = getattr(build_target, "SOURCE_COMMIT", "unknown")
    report = {
        "schema": 1,
        "purpose": "internal-readonly-bridge-probe-not-release-evidence",
        "status": "BLOCKED",
        "frozen": bool(getattr(sys, "frozen", False)),
        "qt_parent": args.qt_parent,
        "terminal_selected": args.terminal is not None,
        "source_commit": commit if re.fullmatch(r"[0-9a-f]{40}", commit) else "unknown",
        "architecture_bits": 64 if sys.maxsize > 2**32 else 32,
        "versions": versions(),
        "windows_build": sys.getwindowsversion().build if os.name == "nt" else None,
        "checks": {},
        "events": [],
        "limitations": (
            "No orders/history/backend HTTP/profile read; IPC reconnect is not MT5 process restart"
        ),
    }
    mutex = None
    qt_app = qt_engine = None
    try:
        if os.name != "nt" or report["architecture_bits"] != 64:
            report["reason"] = "WINDOWS_X64_REQUIRED"
        else:
            if args.terminal:
                from .windows import AppMutex

                mutex = AppMutex()  # Refuse terminal attachment while Collector owns the profile.
            if args.qt_parent:
                with stage("gui_start"):
                    importlib.import_module("PySide6.QtSvg")
                    from PySide6.QtQml import QQmlApplicationEngine
                    from PySide6.QtQuickControls2 import QQuickStyle
                    from PySide6.QtWidgets import QApplication

                    qt_app = QApplication([])
                    QQuickStyle.setStyle("Basic")
                    qt_engine = QQmlApplicationEngine()
                    qt_engine.loadData(b"import QtQuick; import QtQuick.Controls; Button {}")
                    if not qt_engine.rootObjects():
                        raise RuntimeError("WORKER_OPERATION_FAILED")
            report["checks"] = run_child(str(args.terminal) if args.terminal else None)
            report["status"] = "PASS"
    except Exception as exc:
        report["status"] = "FAIL"
        report["events"] = [
            clean(getattr(exc, "collector_diagnostic", None) or capture("self_test", exc))
        ]
    finally:
        report["events"] = (report["events"] + recent())[-32:]
        if qt_engine:
            qt_engine.clearComponentCache()
        if qt_app:
            qt_app.quit()
        if mutex:
            mutex.close()
    # Only explicit destination, no implicit default Collector profile or real log file.
    with args.report.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    return 0 if report["status"] == "PASS" else 2
