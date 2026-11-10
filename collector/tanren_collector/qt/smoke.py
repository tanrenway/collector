"""Explicit synthetic UI exercise only. Never opens a real profile/API/terminal."""

import json
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, QObject, QPointF, Qt
from PySide6.QtGui import QKeyEvent


def exercise(app, engine, window, bridge, service, directory=None):
    def spin():
        until = time.monotonic() + 0.12
        while time.monotonic() < until:
            app.processEvents()
            time.sleep(0.005)

    def settle():
        deadline = time.monotonic() + 3
        while bridge.command.get("phase") == "submitted" and time.monotonic() < deadline:
            spin()

    def items():
        todo = [window.contentItem()]
        seen = set()
        while todo:
            item = todo.pop()
            if item in seen:
                continue
            seen.add(item)
            yield item
            if hasattr(item, "childItems"):
                todo.extend(item.childItems())

    def layout():
        for item in items():
            if not item.isVisible() or item.width() <= 0 or not item.property("text"):
                continue
            point = item.mapToScene(QPointF(0, 0))
            if point.x() < -2 or point.x() + item.width() > window.width() + 2:
                raise AssertionError("Horizontal text overflow: " + str(item.property("text"))[:40])

    def press(code, modifiers=Qt.KeyboardModifier.NoModifier):
        for kind in [QEvent.Type.KeyPress, QEvent.Type.KeyRelease]:
            QCoreApplication.sendEvent(window, QKeyEvent(kind, code, modifiers))
        spin()

    def named(name):
        # Quick visual children are not necessarily QObject children (Repeater/Layout delegates).
        todo = [window, window.contentItem()]
        seen = set()
        while todo:
            item = todo.pop()
            if item in seen:
                continue
            seen.add(item)
            if item.objectName() == name:
                return item
            if hasattr(item, "childItems"):
                todo.extend(item.childItems())
            todo.extend(item.children())
        raise AssertionError("Missing UI object " + name)

    def click(name):
        control = named(name)
        if not control.property("enabled") or not control.property("visible"):
            raise AssertionError("Disabled " + name)
        QMetaObject.invokeMethod(control, "clicked")
        spin()
        settle()

    spin()
    deadline = time.monotonic() + 12
    while not service.spawn_ok and time.monotonic() < deadline:
        spin()
    if not service.spawn_ok:
        raise AssertionError("Spawn bootstrap failed")
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
    shots = []
    for palette in ["graphite", "ivory"]:
        bridge.preference("palette", palette)
        spin()
        settle()
        for index, key in enumerate(
            [
                "welcome",
                "dashboard",
                "accounts",
                "add",
                "details",
                "migration",
                "settings",
                "support",
                "activity",
            ]
        ):
            window.setProperty("screenIndex", index)
            spin()
            if index == 4:
                from .synthetic import BINDINGS

                selected = named("detailChoiceInput")
                selected.setProperty("currentIndex", 0)
                selected.activated.emit(0)
                spin()
            layout()
            if directory:
                file = Path(directory) / (palette + "-" + key + ".png")
                window.grabWindow().save(str(file))
                shots.append(file.name)
    from .synthetic import BINDINGS

    window.setProperty("screenIndex", 2)
    spin()
    click("listAccountMenu" + BINDINGS[0])
    if directory:
        window.grabWindow().save(str(Path(directory) / "account-context-menu.png"))
    press(Qt.Key.Key_Escape)
    window.setProperty("screenIndex", 3)
    bridge.updateCommand(
        {"id": "synthetic-progress", "action": "discover", "phase": "pending", "error": None}
    )
    spin()
    if directory:
        window.grabWindow().save(str(Path(directory) / "discovery-loading.png"))
    bridge.updateCommand(
        {"id": "synthetic-progress", "action": "discover", "phase": "confirmed", "error": None}
    )
    window.setProperty("screenIndex", 1)
    spin()
    click("refreshButton")
    if bridge.command["phase"] != "scheduled":
        raise AssertionError("Refresh falsely completed")
    window.setProperty("screenIndex", 0)
    spin()
    named("deviceNameInput").setProperty("text", "Synthetic device")
    named("pairCodeInput").setProperty("text", "ABCD-EFGH-JKMP")
    click("pairButton")
    if named("pairCodeInput").property("text") != "":
        raise AssertionError("Pair code retained")
    if bridge.state["device"]["state"] != "awaiting_browser_confirmation":
        raise AssertionError("Pair falsely completed")
    window.setProperty("screenIndex", 3)
    spin()
    # Explicit synthetic browser confirmation; registration must stay unavailable before this.
    if named("registerButton").property("enabled"):
        raise AssertionError("Registration available before device confirmation")
    service.state["device"] = {"state": "paired"}
    bridge.updateState(service.state)
    spin()
    click("discoverButton")
    choice = named("terminalChoiceInput")
    choice.setProperty("currentIndex", 0)
    # Emit actual combobox user-activation signal.
    choice.activated.emit(0)
    spin()
    click("previewButton")
    spin()
    if not named("accountNameInput").property("text") or not named("timezoneInput").property(
        "text"
    ):
        raise AssertionError("Account form was not prefilled")
    if directory:
        window.grabWindow().save(str(Path(directory) / "add-prefilled.png"))
    window.setProperty("accountAdvanced", True)
    spin()
    named("accountNameInput").setProperty("text", "")
    click("registerButton")
    if bridge.command["phase"] != "metadata_required":
        raise AssertionError("Missing metadata state")
    named("accountNameInput").setProperty("text", "Synthetic linked account")
    named("firm").setProperty("text", "User entered firm")
    named("timezoneInput").setProperty("text", "Europe/Kyiv")
    for name in ["categoryInput"]:
        field = named(name)
        field.setProperty("currentIndex", 0)
        field.activated.emit(0)
        spin()
    if named("baselineInput").property("text"):
        raise AssertionError("Unknown baseline was fabricated")
    choice = named("categoryInput")
    if choice.property("wheelEnabled"):
        raise AssertionError("Unfocused wheel changes selection")
    popup = named("categoryPopup")
    QMetaObject.invokeMethod(popup, "open")
    spin()
    if directory:
        window.grabWindow().save(str(Path(directory) / "dropdown-open.png"))
    press(Qt.Key.Key_Escape)
    if popup.property("visible"):
        raise AssertionError("Picker Escape failed")
    click("registerButton")
    if bridge.command["phase"] != "linked" or len(bridge.state["accounts"]) != 2:
        raise AssertionError("Registration/link state or duplicate prevention failed")
    window.setProperty("screenIndex", 6)
    spin()
    click("languageUk")
    if bridge.preferences["locale"] != "uk":
        raise AssertionError("Language failed")
    click("palettegraphite")
    window.setProperty("width", 680)
    window.setProperty("height", 740)
    spin()
    if directory:
        window.grabWindow().save(str(Path(directory) / "uk-small-settings.png"))
    click("repairButton")
    spin()
    named("deviceNameInput").setProperty("text", "Synthetic re-pair")
    named("pairCodeInput").setProperty("text", "ABCD-EFGH-JKMP")
    click("pairButton")
    spin()
    # Find dialog via engine root QObject tree, since popup content has a separate overlay parent.
    dialog = window.findChild(QObject, "confirmationDialog")
    if directory:
        window.grabWindow().save(str(Path(directory) / "repair-dialog.png"))
    if not dialog or not dialog.property("visible"):
        raise AssertionError("Dialog failed")
    click("confirmAccept")
    if named("pairCodeInput").property("text"):
        raise AssertionError("Re-pair secret retained")
    spin()
    # Existing cards, stage semantics, explicit migration confirmation and actions.
    from .synthetic import BINDINGS

    bridge.selectAccount(BINDINGS[0])
    window.setProperty("screenIndex", 4)
    spin()
    click("pauseButton")
    if bridge.selected["stage"] != "paused":
        raise AssertionError("Pause failed")
    click("resumeButton")
    window.setProperty("screenIndex", 5)
    spin()
    choice = named("migrationChoiceInput")
    choice.setProperty("currentIndex", 0)
    choice.activated.emit(0)
    spin()
    click("inspectButton")
    if named("drainButton").property("enabled"):
        raise AssertionError("Drain requires confirmation")
    named("drainConfirmation").setProperty("checked", True)
    click("drainButton")
    if bridge.command["phase"] != "awaiting_browser_confirmation":
        raise AssertionError("Migration falsely activated")
    choice.setProperty("currentIndex", 1)
    choice.activated.emit(1)
    spin()
    if named("drainButton").property("enabled"):
        raise AssertionError("Drain confirmation leaked to another account")
    window.close()
    spin()
    if not dialog.property("visible") or not window.isVisible():
        raise AssertionError("No-tray close lost window")
    press(Qt.Key.Key_Escape)
    if dialog.property("visible"):
        raise AssertionError("Escape did not close dialog")
    window.requestActivate()
    press(Qt.Key.Key_1, Qt.KeyboardModifier.AltModifier)
    if window.property("screenIndex") != 1:
        raise AssertionError("Navigation shortcut failed")
    press(Qt.Key.Key_Tab)
    if window.activeFocusItem() is None:
        raise AssertionError("No keyboard focus")
    for index in range(9):
        window.setProperty("screenIndex", index)
        spin()
        layout()
    # Presentation-only missing/revoked/offline/suspended snapshots. Never financial fixtures.
    from .synthetic import fixture

    for device_state in ["authorization_required", "locally_revoked", "error", "disconnected"]:
        state = json.loads(json.dumps(fixture()))
        state["device"] = {"state": device_state, "error": "SYNC_PAUSED_HTTP_401"}
        state["accounts"][0] = {
            **state["accounts"][0],
            "role": "unknown",
            "stage": "waiting",
            "error": "TERMINAL_UNAVAILABLE",
        }
        bridge.updateState(state)
        window.setProperty("screenIndex", 4)
        spin()
        layout()
    if directory:
        window.grabWindow().save(str(Path(directory) / "uk-offline-details.png"))
    state = json.loads(json.dumps(fixture()))
    state["accounts"] = []
    bridge.updateState(state)
    window.setProperty("screenIndex", 1)
    spin()
    layout()
    if bridge.summary["last_processed"] is not None:
        raise AssertionError("Fabricated processing timestamp")
    if directory:
        window.grabWindow().save(str(Path(directory) / "uk-empty-dashboard.png"))
    state = json.loads(json.dumps(fixture()))
    state["suspended"] = True
    bridge.updateState(state)
    if bridge.summary["active"]:
        raise AssertionError("Sleeping device shown active")
    for palette in ["obsidian", "midnight", "graphite", "carbon", "arctic", "ivory"]:
        bridge.preference("palette", palette)
        spin()
        settle()
        if bridge.preferences["palette"] != palette:
            raise AssertionError("Palette failed")
    return {
        "checks_passed": True,
        "spawn_bootstrap": service.spawn_ok,
        "horizontal_text_bounds": True,
        "keyboard": ["Alt+1", "Tab", "Escape"],
        "screenshots": shots,
        "commands": service.calls,
        "language": "uk",
        "small_width": window.width(),
    }
