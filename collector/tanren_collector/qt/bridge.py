"""Narrow typed Qt slots + presentation properties; no secret/store/API/native objects exposed."""

import contextlib
import json
import re
import threading
import uuid
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import (
    Property,
    QDate,
    QDateTime,
    QLocale,
    QObject,
    Qt,
    QTimer,
    QTimeZone,
    Signal,
    Slot,
)

from .. import __version__, diagnostics_log
from ..prop_firms import PROP_FIRMS, suggest_firm
from ..updater import Updater
from .service import DEFAULTS, SYSTEM_PALETTES
from .strings import words

ASSETS = Path(__file__).parent
DESIGN = json.loads((ASSETS / "design.json").read_text())
ICONS = {p.stem: p.read_text() for p in (ASSETS / "assets").glob("*.svg")}
UPDATE_CHECK_FIRST_MS = 60_000
UPDATE_CHECK_EVERY_MS = 6 * 60 * 60 * 1000
BUSY_OR_READY = {"checking", "downloading", "available", "ready"}
QML_CHECKPOINTS = {("ui_previewed", "row"), ("ui_previewed", "none"), ("ui_prefilled", "ok")}


def _previewed(state):
    return sum(bool(row.get("broker")) for row in state.get("terminals", []))


class Bridge(QObject):
    changed = Signal()
    settingsChanged = Signal()
    commandChanged = Signal()
    requested = Signal(str, "QVariantMap", str)
    browserRequested = Signal()
    accountPageRequested = Signal(str)
    terminalPickRequested = Signal()
    exportRequested = Signal()
    quitRequested = Signal()
    stopRequested = Signal()
    suspensionRequested = Signal(bool)
    updateChanged = Signal()
    _updateFinished = Signal(object)
    _quietUpdate = Signal(object)

    def __init__(self, synthetic=False):
        super().__init__()
        self._settings = dict(DEFAULTS)
        self._state = {
            "device": {"state": "disconnected"},
            "accounts": [],
            "terminals": [],
            "registration": {"state": "idle"},
            "migration": None,
        }
        self._command = {}
        self._outstanding = set()
        self._selected = ""
        self._tray = False
        self._synthetic = synthetic
        self._update = {"state": "idle"}
        self._update_manifest = None
        self._update_file = None
        # "system" palette follows the Windows light/dark setting (Qt colour scheme) live.
        # No GUI application (tests, probes): the palette simply stays static.
        with contextlib.suppress(Exception):
            from PySide6.QtGui import QGuiApplication

            hints = QGuiApplication.styleHints()
            if hints is not None and hasattr(hints, "colorSchemeChanged"):
                hints.colorSchemeChanged.connect(lambda *_: self.settingsChanged.emit())
        self._update_busy = False
        self._updater = Updater()
        self._updateFinished.connect(self._apply_update)
        self._quietUpdate.connect(self._apply_quiet_update)
        self._os_reduced = False
        self._activity = []
        self._notice_visible = False
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.setInterval(4000)
        self._notice_timer.timeout.connect(self.dismissNotice)
        # A quiet check for a newer published version: first a minute after start, then every
        # six hours. It only reads the release manifest; downloading and installing stay
        # user-started, and a failed check never shows an error or touches capture.
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(UPDATE_CHECK_FIRST_MS)
        self._update_timer.timeout.connect(self._background_check)
        if self.installedWindows and not synthetic:
            self._update_timer.start()

    @Property("QVariantMap", notify=changed)
    def state(self):
        return self._state

    @Property("QVariantMap", notify=commandChanged)
    def command(self):
        return self._command

    @Property(bool, notify=commandChanged)
    def noticeVisible(self):
        return self._notice_visible

    @Slot()
    def dismissNotice(self):
        # Only terminal success is transient; outstanding authorization/errors must remain visible.
        if self._command.get("phase") in {
            "confirmed",
            "scheduled",
            "created",
            "linked",
            "processed",
        }:
            self._notice_timer.stop()
            self._notice_visible = False
            self.commandChanged.emit()

    @Property("QVariantMap", notify=settingsChanged)
    def preferences(self):
        return self._settings

    @Property("QVariantMap", notify=settingsChanged)
    def words(self):
        return words(self._settings["locale"])

    @Property(str, notify=settingsChanged)
    def resolvedPalette(self):
        """Effective palette id: the saved choice, or the system scheme's palette for "system"."""
        palette = self._settings.get("palette", DEFAULTS["palette"])
        if palette != "system":
            return palette if palette in DESIGN["palettes"] else SYSTEM_PALETTES["dark"]
        scheme = "dark"
        try:
            from PySide6.QtGui import QGuiApplication

            hints = QGuiApplication.styleHints()
            if hints is not None and hints.colorScheme() == Qt.ColorScheme.Light:
                scheme = "light"
        except Exception:  # noqa: BLE001 - headless/older Qt: dark default
            scheme = "dark"
        return SYSTEM_PALETTES[scheme]

    @Property("QVariantMap", notify=settingsChanged)
    def colors(self):
        result = dict(DESIGN["palettes"][self.resolvedPalette])
        for key, value in result.items():
            if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{8}", value):
                result[key] = "#" + value[-2:] + value[1:-2]
        return result

    @Property("QVariantList", constant=True)
    def paletteCatalog(self):
        fields = ("id", "name", "scheme", "canvas", "navigation", "surface", "accent", "muted")
        return [
            {field: DESIGN["palettes"][key][field] for field in fields}
            for key in ("obsidian", "midnight", "graphite", "carbon", "arctic", "ivory")
        ]

    @Property("QVariantMap", notify=updateChanged)
    def updateInfo(self):
        return self._update

    def _set_update(self, state, **values):
        self._update = {"state": state, **values}
        self.updateChanged.emit()

    def _apply_update(self, result):
        self._update_busy = False
        self._set_update(**result)

    def _start_update(self, state, work):
        if self._synthetic or self._update_busy:
            return False
        self._update_busy = True
        self._set_update(state, version=self._update.get("version", ""))

        def run():
            try:
                result = work()
            except RuntimeError as exc:
                code = str(exc)
                offline = code == "ENGINEERING_OFFLINE"
                result = {"state": "idle"} if offline else {"state": "error", "error": code}
            except Exception:  # noqa: BLE001 - a failed update must never affect capture.
                result = {"state": "error", "error": "UPDATE_FAILED"}
            self._updateFinished.emit(result)

        threading.Thread(target=run, daemon=True).start()
        return True

    def _background_check(self):
        self._update_timer.setInterval(UPDATE_CHECK_EVERY_MS)
        if self._synthetic or self._update_busy or self._update.get("state") in BUSY_OR_READY:
            return False

        def run():
            try:
                found = self._updater.check()
            except Exception:  # noqa: BLE001 - quiet: the user can still check by hand.
                self._quietUpdate.emit(None)
                return
            self._quietUpdate.emit({"found": found})

        self._update_busy = True
        threading.Thread(target=run, daemon=True).start()
        return True

    def _apply_quiet_update(self, result):
        self._update_busy = False
        if result is None or self._update.get("state") in BUSY_OR_READY:
            return
        found = result["found"]
        if found:
            self._update_manifest, self._update_file = found, None
            self._set_update("available", version=found["version"])
        elif self._update.get("state") in {"idle", "current"}:
            self._set_update("current")

    @Slot(result=bool)
    def checkUpdate(self):
        def work():
            found = self._updater.check()
            self._update_manifest, self._update_file = found, None
            return (
                {"state": "available", "version": found["version"]}
                if found
                else {"state": "current"}
            )

        return self._start_update("checking", work)

    @Slot(result=bool)
    def downloadUpdate(self):
        found = self._update_manifest
        if not found or not self.installedWindows:
            return False

        def work():
            self._update_file = self._updater.download(found)
            return {"state": "ready", "version": found["version"]}

        return self._start_update("downloading", work)

    @Slot(result=bool)
    def installUpdate(self):
        if not self._update_manifest or not self._update_file or self._update_busy:
            return False
        try:
            self._updater.launch(self._update_file, self._update_manifest)
        except (RuntimeError, OSError):
            self._set_update("error", error="UPDATE_INSTALL_FAILED")
            return False
        self.stopRequested.emit()  # Normal shutdown frees the app so the installer can replace it.
        return True

    @Property("QVariantList", constant=True)
    def propFirms(self):
        return list(PROP_FIRMS)

    @Slot(str, str, result=str)
    def suggestFirm(self, broker, server):
        return suggest_firm(broker, server)

    @Property(str, constant=True)
    def systemTimezone(self):
        zone = bytes(QTimeZone.systemTimeZoneId()).decode()
        return "Europe/Kyiv" if zone == "Europe/Kiev" else zone

    @Property("QVariantMap", constant=True)
    def tokens(self):
        return DESIGN["tokens"]

    @Property(bool, notify=settingsChanged)
    def reducedMotion(self):
        return self._os_reduced or self._settings["reduced_motion"]

    @Property(bool, constant=True)
    def synthetic(self):
        return self._synthetic

    @Property(bool, notify=changed)
    def trayAvailable(self):
        return self._tray

    @Property(bool, constant=True)
    def installedWindows(self):
        import os
        import sys

        return os.name == "nt" and bool(getattr(sys, "frozen", False))

    @Property("QVariantMap", constant=True)
    def build(self):
        from .. import build_target

        return {
            "version": __version__,
            "commit": getattr(build_target, "SOURCE_COMMIT", "source"),
            "qt": __import__("PySide6").__version__,
        }

    @Property("QVariantMap", notify=changed)
    def selected(self):
        return next(
            (a for a in self._state.get("accounts", []) if a["binding_id"] == self._selected), {}
        )

    @Property("QVariantMap", notify=changed)
    def summary(self):
        rows = self._state.get("accounts", [])
        stamps = [a.get("last_processed_at") for a in rows if a.get("last_processed_at")]
        synced = [a.get("last_observed_at") for a in rows if a.get("last_observed_at")]
        return {
            "accounts": len(rows),
            "active": sum(a["role"] == "active" for a in rows),
            "standby": sum(a["role"] == "standby" for a in rows),
            "pending": sum(a["pending"] for a in rows),
            "processing": sum(a["processing"] for a in rows),
            "last_processed": max(stamps) if stamps else None,
            "last_synced": max(synced) if synced else None,
        }

    @Slot("QVariantMap")
    def updateState(self, value):
        value = json.loads(json.dumps(value))
        if value == self._state:
            return
        prior = self._state
        if prior.get("device", {}).get("state") != value.get("device", {}).get("state"):
            self.remember("device", value.get("device", {}).get("state", "unknown"))
        old = {a["binding_id"]: a for a in prior.get("accounts", [])}
        for account in value.get("accounts", []):
            before = old.get(account["binding_id"], {})
            if (
                account.get("last_processed_at")
                and before.get("last_processed_at") != account["last_processed_at"]
            ):
                self.remember("accounts", "processed")
            if any(before.get(k) != account.get(k) for k in ["stage", "role", "error"]):
                self.remember("accounts", account.get("stage", "unknown"))
        self._state = value
        if not self._synthetic and _previewed(value) > _previewed(prior):
            diagnostics_log.write("bridge_previewed", f"rows={_previewed(value)}")
        if value.get("suspended"):
            for row in self._state.get("accounts", []):
                row["role"] = "unknown"
        self.changed.emit()

    @Slot(str, str)
    def trace(self, event, code):
        """Fixed checkpoints from QML; field values never pass through here."""
        if not self._synthetic and (event, code) in QML_CHECKPOINTS:
            diagnostics_log.write(event, code)

    @Property("QVariantList", notify=changed)
    def activity(self):
        return self._activity

    def remember(self, subject, state):
        if self._activity and (self._activity[0]["subject"], self._activity[0]["state"]) == (
            subject,
            state,
        ):
            self._activity = self._activity[1:]
        self._activity = (
            [
                {
                    "subject": subject,
                    "state": state,
                    "observed_at": QDateTime.currentDateTimeUtc().toString(Qt.DateFormat.ISODate),
                }
            ]
            + self._activity
        )[:50]

    @Slot(str, result=str)
    def explain(self, code):
        key = (
            "busyHelp"
            if code in {"RUNTIME_BUSY", "BINDING_BUSY"}
            else "shutdownHelp"
            if code in {"SHUTDOWN_TIMEOUT", "SHUTDOWN_FAILED"}
            else "terminalHelp"
            if "TERMINAL" in code or "MT5_" in code
            else "authHelp"
            if any(
                v in code
                for v in [
                    "401",
                    "403",
                    "DEVICE_NOT_PAIRED",
                    "DEVICE_STATE",
                    "PAIRING",
                    "AUTHORIZATION",
                ]
            )
            else "continuityHelp"
            if "CONTINUITY" in code
            else "conflictHelp"
            if "409" in code or "CONFLICT" in code or "IDENTITY" in code
            else "scopeHelp"
            if "SCOPE" in code
            else "networkHelp"
        )
        return self.words[key]

    @Slot("QVariantMap")
    def updateSettings(self, value):
        self._settings.update({k: v for k, v in value.items() if k in DEFAULTS})
        self.settingsChanged.emit()
        self.changed.emit()

    @Slot("QVariantMap")
    def updateCommand(self, value):
        if value == self._command:
            return
        self._command = value
        self._notice_visible = True
        self._notice_timer.stop()
        if value.get("phase") in {"confirmed", "scheduled", "created", "linked", "processed"}:
            self._notice_timer.start()
        if value["phase"] not in {"pending", "submitted"}:
            self._outstanding.discard(value["id"])
        self.commandChanged.emit()

    def send(self, action, body):
        if len(self._outstanding) >= 8:
            self.updateCommand(
                {
                    "id": str(uuid.uuid4()),
                    "action": action,
                    "phase": "failed",
                    "error": "RUNTIME_BUSY",
                }
            )
            return False
        ticket = str(uuid.uuid4())
        self._outstanding.add(ticket)
        self._notice_visible = True
        self._notice_timer.stop()
        self._command = {"id": ticket, "action": action, "phase": "submitted", "error": None}
        self.commandChanged.emit()
        self.requested.emit(action, body, ticket)
        return True

    @Slot(str, str, bool, bool, result=bool)
    def pair(self, code, name, repair=False, confirmed=False):
        if (
            not 1 <= len(code) <= 32
            or not 1 <= len(name.strip()) <= 100
            or (repair and not confirmed)
        ):
            return False
        return self.send(
            "pair", {"code": code, "name": name, "repair": repair, "confirmed": confirmed}
        )

    @Slot(result=bool)
    def disconnect(self):
        return self.send("disconnect", {})

    @Slot()
    def pickTerminal(self):
        self.terminalPickRequested.emit()

    def addTerminalPath(self, path):
        if isinstance(path, str) and path and len(path) <= 1024:
            self.send("addTerminal", {"path": path})

    @Slot(str)
    def openAccountPage(self, account_id):
        if re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", account_id):
            self.accountPageRequested.emit(account_id)

    @Slot(result=bool)
    def discover(self):
        return self.send("discover", {})

    @Slot(result=bool)
    def refresh(self):
        return self.send("refresh", {})

    @Slot(str, result=bool)
    def preview(self, key):
        return len(key) == 64 and self.send("preview", {"key": key})

    @Slot(str, "QVariantMap", result=bool)
    def registerAccount(self, key, metadata):
        if len(key) != 64 or set(metadata) - {
            "name",
            "firm",
            "category",
            "journal_mode",
            "timezone",
            "initial_balance",
        }:
            return False
        if any(not isinstance(v, str) or len(v) > 200 for v in metadata.values()):
            return False
        return self.send("register", {"key": key, "metadata": metadata})

    @Slot(str, str, result=bool)
    def accountAction(self, binding, action):
        if action not in {"activate", "pause", "resume", "step", "sync"}:
            return False
        try:
            uuid.UUID(binding)
        except ValueError:
            return False
        return self.send("account", {"binding": binding, "action": action})

    @Slot(str, bool, bool, result=bool)
    def migrate(self, binding, drain=False, confirmed=False):
        try:
            uuid.UUID(binding)
        except ValueError:
            return False
        if drain and not confirmed:
            return False
        return self.send("migrate", {"binding": binding, "drain": drain, "confirmed": confirmed})

    @Slot(str, "QVariant", result=bool)
    def preference(self, key, value):
        if key not in DEFAULTS:
            return False
        return self.send("settings", {key: value})

    @Slot(int, int, bool, result=bool)
    def saveWindow(self, width, height, maximized):
        if not 640 <= width <= 2560 or not 540 <= height <= 1600:
            return False
        return self.send(
            "settings",
            {"window_width": width, "window_height": height, "window_maximized": maximized},
        )

    @Slot(str)
    def selectAccount(self, binding):
        if binding != self._selected and any(
            a["binding_id"] == binding for a in self._state.get("accounts", [])
        ):
            self._selected = binding
            self.changed.emit()

    @Slot()
    def openBrowser(self):
        self.browserRequested.emit()

    @Slot()
    def exportDiagnostics(self):
        self.exportRequested.emit()

    @Slot()
    def quit(self):
        self.quitRequested.emit()

    @Slot("QVariant", result=str)
    def time(self, stamp):
        if not isinstance(stamp, str):
            return self.words["notYet"]
        value = QDateTime.fromString(stamp, Qt.DateFormat.ISODate)
        if not value.isValid():
            return self.words["notYet"]
        local = value.toLocalTime()
        locale = QLocale("uk_UA" if self._settings["locale"] == "uk" else "en_US")
        clock = locale.toString(local.time(), "HH:mm")
        days = local.date().daysTo(QDate.currentDate())
        if days == 0:
            return self.words["todayAt"].replace("{time}", clock)
        if days == 1:
            return self.words["yesterdayAt"].replace("{time}", clock)
        return locale.toString(local, "d MMM yyyy, HH:mm")

    @Slot(str, str, result=str)
    def icon(self, name, color):
        if name not in ICONS or not re.fullmatch(r"#[0-9a-fA-F]{6,8}", color):
            return ""
        return "data:image/svg+xml;utf8," + quote(
            ICONS[name].replace("currentColor", color), safe=""
        )

    @Slot(str, str, str, result=str)
    def mark(self, line, arc, sun):
        """The Tanren mark in the active palette; same geometry as the web HorizonMark."""
        roles = {"markLine": line, "markArc": arc, "markSun": sun}
        if not all(re.fullmatch(r"#[0-9a-fA-F]{6,8}", color) for color in roles.values()):
            return ""
        svg = ICONS["mark"]
        for role, color in roles.items():
            svg = svg.replace(role, color)
        return "data:image/svg+xml;utf8," + quote(svg, safe="")
