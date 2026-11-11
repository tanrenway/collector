"""Runtime owner on a dedicated Qt thread. QML never receives this QObject or runtime."""

import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from .. import diagnostics_log
from ..application_runtime import ApplicationRuntime
from ..diagnostics import export
from ..engine import safe_error
from ..observability import clean, recent
from ..palette_tokens import LEGACY_PALETTES, PALETTES
from ..storage import DPAPI, load_config, save_config
from ..windows import autostart, autostart_enabled

# Palettes used by the automatic theme ("system"): same mapping as the web (owner decision
# 2026-11-11). New installs follow Windows light/dark; a saved explicit palette is kept.
SYSTEM_PALETTES = {"dark": "graphite", "light": "ivory"}
DEFAULTS = {
    "palette": "system",
    "locale": "en",
    "reduced_motion": False,
    "close_to_tray": True,
    "notifications": True,
    "autostart": False,
    "window_width": 1180,
    "window_height": 840,
    "window_maximized": False,
}


class RuntimeService(QObject):
    snapshotReady = Signal("QVariantMap")
    settingsReady = Signal("QVariantMap")
    commandChanged = Signal("QVariantMap")
    finished = Signal()

    def __init__(self, root, runtime_factory=ApplicationRuntime, protector_factory=DPAPI):
        super().__init__()
        self.root, self.runtime_factory, self.protector_factory = (
            Path(root),
            runtime_factory,
            protector_factory,
        )
        self.runtime = None
        self.pending = {}
        self.command = None
        self.settings = dict(DEFAULTS)
        self.suspended = False
        self.timer = None
        self.last_view = None
        self.stopping = False
        self.stop_timer = None

    @Slot()
    def start(self):
        try:
            self.protector = self.protector_factory()
            self.path = self.root / "settings.dpapi"
            saved = load_config(self.path, self.protector) if self.path.exists() else {}
            self.settings = {**DEFAULTS, **saved}
            palette = LEGACY_PALETTES.get(self.settings["palette"], self.settings["palette"])
            self.settings["palette"] = (
                palette if palette in PALETTES or palette == "system" else DEFAULTS["palette"]
            )
            if os.name == "nt":
                self.settings["autostart"] = autostart_enabled()
            self.runtime = self.runtime_factory(self.root)
            self.settingsReady.emit({k: self.settings[k] for k in DEFAULTS})
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(250)
            self.tick()
        except Exception as exc:
            self.snapshotReady.emit(
                {
                    "error": safe_error(exc),
                    "device": {"state": "error"},
                    "accounts": [],
                    "terminals": [],
                }
            )

    def report(self, ticket, action, phase, error=None):
        if phase == "failed":
            diagnostics_log.write("command_failed:" + action, error)
        self.command = {"id": ticket, "action": action, "phase": phase, "error": error}
        self.commandChanged.emit(self.command)

    @Slot(str, "QVariantMap", str)
    def dispatch(self, action, body, ticket):
        diagnostics_log.write("command_received:" + action)
        if self.stopping or not self.runtime or len(self.pending) >= 8:
            self.report(ticket, action, "failed", "RUNTIME_BUSY")
            return
        try:
            state = self.runtime.state
            terminals = {t.key for t in state.terminals}
            accounts = {a.binding_id for a in state.accounts}
            if action in {"preview", "register"} and body["key"] not in terminals:
                raise ValueError("EXPLICIT_ACCOUNT_SELECTION_REQUIRED")
            if action in {"account", "migrate"} and body["binding"] not in accounts:
                raise ValueError("EXPLICIT_ACCOUNT_SELECTION_REQUIRED")
            if action == "pair":
                task = self.runtime.pair_device(
                    body["code"], body["name"], repair=body["repair"], confirmed=body["confirmed"]
                )
            elif action == "disconnect":
                task = self.runtime.disconnect_device()
            elif action == "discover":
                task = self.runtime.discover_accounts()
            elif action == "addTerminal":
                task = self.runtime.add_terminal(body["path"])
            elif action == "preview":
                task = self.runtime.preview_account(body["key"])
            elif action == "register":
                prior = state.registration
                resume = (
                    prior.request_id
                    if prior.state == "metadata_required" and prior.terminal_key == body["key"]
                    else None
                )
                task = self.runtime.register_account(body["key"], body["metadata"] or None, resume)
            elif action == "account":
                task = self.runtime.account_action(body["binding"], body["action"])
            elif action == "migrate":
                task = self.runtime.migrate(
                    body["binding"], drain=body["drain"], confirmed=body["confirmed"]
                )
            elif action == "settings":
                updated = dict(self.settings)
                for key, value in body.items():
                    if key not in DEFAULTS:
                        raise ValueError("INVALID_RUNTIME_ACTION")
                    if key in {"palette", "locale"}:
                        if key == "locale" and value not in {"en", "uk"}:
                            raise ValueError("INVALID_RUNTIME_ACTION")
                        if key == "palette" and value not in PALETTES and value != "system":
                            raise ValueError("INVALID_RUNTIME_ACTION")
                    elif key in {"window_width", "window_height"}:
                        low, high = (640, 2560) if key == "window_width" else (540, 1600)
                        if type(value) is not int or not low <= value <= high:
                            raise ValueError("INVALID_RUNTIME_ACTION")
                    elif not isinstance(value, bool):
                        raise ValueError("INVALID_RUNTIME_ACTION")
                    if key == "autostart":
                        if os.name != "nt" or not getattr(sys, "frozen", False):
                            raise RuntimeError("AUTOSTART_REQUIRES_INSTALLED_BUILD")
                        autostart(value)
                    updated[key] = value
                save_config(self.path, updated, self.protector)
                self.settings = updated
                self.settingsReady.emit({k: self.settings[k] for k in DEFAULTS})
                self.report(ticket, action, "confirmed")
                return
            elif action == "diagnostic":
                export(Path(body["destination"]), self.runtime.diagnostic_statuses())
                self.report(ticket, action, "confirmed")
                return
            elif action == "refresh":
                self.runtime.request_device_sync()
                self.report(ticket, action, "scheduled")
                return
            elif action == "pauseAll":
                self.runtime.set_device_pause(body["paused"])
                self.report(ticket, action, "scheduled")
                return
            else:
                raise ValueError("INVALID_RUNTIME_ACTION")
            self.pending[ticket] = (action, task)
            self.report(ticket, action, "pending")
        except Exception as exc:
            self.report(ticket, action, "failed", safe_error(exc))

    @Slot()
    def tick(self):
        if self.stopping or not self.runtime:
            return
        try:
            started = time.monotonic()
            self.runtime.tick()
            if time.monotonic() - started > 3:
                diagnostics_log.write("slow_tick", round(time.monotonic() - started, 1))
            view = asdict(self.runtime.state)
            view["suspended"] = self.suspended
            events = recent()
            view["diagnostic"] = (
                {k: v for k, v in clean(events[-1]).items() if k in {"id", "stage", "code"}}
                if events
                else {}
            )
            self.last_view = view
            self.snapshotReady.emit(view)
            for ticket, (action, task) in list(self.pending.items()):
                if task is not None and not task.done():
                    continue
                if task is not None:
                    try:
                        task.result()  # Failures are never a confirmed UI action.
                    except Exception as exc:  # One failed command must not abort this tick.
                        self.pending.pop(ticket)
                        self.report(ticket, action, "failed", safe_error(exc))
                        continue
                phase = "confirmed"
                if action == "pair" and self.runtime.state.device.state != "paired":
                    phase = self.runtime.state.device.state
                if action == "register":
                    phase = self.runtime.state.registration.state
                if action == "migrate" and self.runtime.state.migration:
                    phase = self.runtime.state.migration.stage
                self.report(ticket, action, phase)
                self.pending.pop(ticket)
            if (
                self.command
                and self.command["action"] == "pair"
                and self.command["phase"] in {"claiming", "awaiting_browser_confirmation"}
            ):
                state = self.runtime.state.device.state
                if state == "paired":
                    self.report(self.command["id"], "pair", "confirmed")
                elif state in {"authorization_required", "locally_revoked", "error"}:
                    self.report(
                        self.command["id"], "pair", "failed", self.runtime.state.device.error
                    )
            if (
                self.command
                and self.command["action"] == "migrate"
                and self.runtime.state.migration
            ):
                stage = self.runtime.state.migration.stage
                if stage != self.command["phase"]:
                    self.report(
                        self.command["id"], "migrate", stage, self.runtime.state.migration.error
                    )
        except Exception as exc:
            diagnostics_log.write("tick_failed", safe_error(exc))
            if self.last_view:
                failed = {
                    **self.last_view,
                    "error": safe_error(exc),
                    "accounts": [
                        {**a, "role": "unknown", "stage": "waiting"}
                        for a in self.last_view.get("accounts", [])
                    ],
                }
                self.snapshotReady.emit(failed)
            if self.pending:
                ticket, (action, _) = next(iter(self.pending.items()))
                self.pending.pop(ticket)
                self.report(ticket, action, "failed", safe_error(exc))

    @Slot(bool)
    def suspension(self, suspended):
        if self.stopping:
            return
        self.suspended = suspended
        if not self.runtime:
            return
        self.runtime.resume()
        if suspended:
            self.timer.stop()
        else:
            self.timer.start(250)
        self.tick()

    @Slot()
    def stop(self):
        if self.stopping:
            return
        self.stopping = True
        if self.timer:
            self.timer.stop()
        self.finish_stop()

    @Slot()
    def finish_stop(self):
        try:
            pool = getattr(self.runtime, "pool", None)
            if pool is not None:
                pool.tick(draining=True)
                if pool.active:
                    if self.stop_timer is None:
                        self.stop_timer = QTimer(self)
                        self.stop_timer.timeout.connect(self.finish_stop)
                        self.stop_timer.start(25)
                    return
            if self.runtime:
                self.runtime.close()
        except Exception:
            # Unknown closure state: keep the thread/profile lock, never announce safe exit.
            if self.stop_timer:
                self.stop_timer.stop()
            self.report("shutdown", "shutdown", "failed", "SHUTDOWN_FAILED")
            return
        if self.stop_timer:
            self.stop_timer.stop()
        self.finished.emit()
