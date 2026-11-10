"""Explicit synthetic preview service. Never instantiates runtime, API, MT5 or local profile."""

from dataclasses import asdict

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..application_state import (
    AccountView,
    ApplicationState,
    DeviceView,
    ForceView,
    MigrationView,
    TerminalView,
)
from ..processes import SpawnPool
from .service import DEFAULTS

BINDINGS = ["12345678-1234-1234-1234-123456789abc", "22345678-1234-1234-1234-123456789abc"]
TERMINAL = "a" * 64


def fixture():
    return asdict(
        ApplicationState(
            device=DeviceView("paired"),
            terminals=(
                TerminalView(
                    TERMINAL,
                    "MetaTrader 5 · Synthetic",
                    True,
                    "Synthetic Broker",
                    "Demo-Server",
                    "1234",
                ),
            ),
            accounts=(
                AccountView(
                    BINDINGS[0],
                    "33333333-3333-3333-3333-333333333333",
                    TERMINAL,
                    name="Primary trading account",
                    broker="Synthetic Broker",
                    server="Demo-Server",
                    last_observed_at="2026-10-26T09:00:00+00:00",
                    last_processed_at="2026-10-26T08:59:00+00:00",
                    stage="processing",
                    role="active",
                    pending=2,
                    processing=1,
                    force=(ForceView("44444444-4444-4444-4444-444444444444", "received"),),
                ),
                AccountView(
                    BINDINGS[1],
                    "55555555-5555-5555-5555-555555555555",
                    "b" * 64,
                    name="Research account",
                    broker="Synthetic Broker",
                    server="Demo-Server",
                    stage="standby",
                    role="standby",
                ),
            ),
            migration=MigrationView(BINDINGS[0], "awaiting_browser_confirmation"),
        )
    )


def echo(value):
    return value


class SyntheticService(QObject):
    snapshotReady = Signal("QVariantMap")
    settingsReady = Signal("QVariantMap")
    commandChanged = Signal("QVariantMap")
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.state = fixture()
        self.settings = dict(DEFAULTS)
        self.calls = []
        self.pool = None
        self.task = None
        self.spawn_ok = False

    @Slot()
    def start(self):
        self.pool = SpawnPool(max_workers=1, timeout=10)
        self.task = self.pool.submit(echo, "synthetic-bootstrap")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(25)
        self.snapshotReady.emit(self.state)
        self.settingsReady.emit(self.settings)

    @Slot()
    def poll(self):
        self.pool.tick()
        if self.task.done():
            self.spawn_ok = self.task.result() == "synthetic-bootstrap"
            self.timer.stop()

    @Slot(str, "QVariantMap", str)
    def dispatch(self, action, body, ticket):
        # Test command count/action only. Never retain pairing code or arbitrary input.
        self.calls.append(action)
        phase = "confirmed"
        if action == "settings":
            self.settings.update(body)
            self.settingsReady.emit(self.settings)
        elif action in {"refresh", "pauseAll"}:
            phase = "scheduled"
        elif action == "pair":
            self.state["device"] = {
                "state": "awaiting_browser_confirmation",
                "verification_phrase": "A1B2 C3D4 E5F6",
            }
            phase = "awaiting_browser_confirmation"
        elif action == "disconnect":
            self.state["device"] = {"state": "locally_revoked"}
        elif action == "discover":
            self.state["terminals"] = fixture()["terminals"]
        elif action == "register":
            self.state["registration"] = {
                "state": "linked" if body.get("metadata") else "metadata_required",
                "required": ["name", "firm", "category", "journal_mode", "timezone"],
            }
            phase = self.state["registration"]["state"]
        elif action == "account":
            for a in self.state["accounts"]:
                if a["binding_id"] == body["binding"]:
                    a["stage"] = "paused" if body["action"] == "pause" else "active"
                    a["role"] = "unknown" if body["action"] == "pause" else "active"
        elif action == "migrate":
            self.state["migration"] = {
                "binding_id": body["binding"],
                "stage": "awaiting_browser_confirmation" if body["drain"] else "draining",
                "queues": [],
            }
            phase = self.state["migration"]["stage"]
        self.snapshotReady.emit(self.state)
        self.commandChanged.emit({"id": ticket, "action": action, "phase": phase, "error": None})

    @Slot(bool)
    def suspension(self, value):
        self.state["suspended"] = value
        self.snapshotReady.emit(self.state)

    @Slot()
    def stop(self):
        if self.pool:
            self.timer.stop()
            self.pool.shutdown()
        self.finished.emit()
