"""Read the server names of every company in the catalog (Windows research tool).

Restores probe-out/servers-catalog.dat from the previous step into the terminal, opens the native
'Open an Account' wizard and, for each company, goes to 'Connect with an existing trade account'
to read the company's server list; then checks each server with a synthetic login.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path

from PIL import ImageGrab
from pywinauto import Application

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
DATA = Path(TERMINAL).parent
OUT = Path("probe-out")
OUT.mkdir(exist_ok=True)
report = {"companies": [], "errors": []}


def controls(window):
    rows = []
    for child in window.descendants():
        try:
            rows.append(f"{child.class_name()} id={child.control_id()} text={child.window_text()!r}")
        except Exception:  # noqa: BLE001
            continue
    return rows


def back():
    """The wizard's Back button: the Button whose text mentions Back (mnemonic-safe)."""
    for button in dlg.descendants(class_name="Button"):
        if "back" in button.window_text().replace("&", "").lower():
            button.click()
            return
    raise RuntimeError("no Back button")


subprocess.Popen([TERMINAL, "/portable"])
time.sleep(60)
app = Application(backend="win32").connect(path=TERMINAL, timeout=60)
try:
    app.window(title="Welcome to LiveUpdate").child_window(title="Later").click()
except Exception as exc:  # noqa: BLE001
    report["errors"].append(repr(exc))
dlg = app.window(title="Open an Account")
dlg.wait("visible", timeout=60)
listview = dlg.child_window(control_id=10729).wrapper_object()
total = listview.item_count()
for index in range(total):
    entry = {"index": index, "servers": []}
    try:
        listview.select(index)
        dlg.child_window(control_id=12324).click()
        time.sleep(4)
        if index == 0:
            (OUT / "page2-controls.txt").write_text("\n".join(controls(dlg)), encoding="utf-8")
            ImageGrab.grab().save(OUT / "page2.png")
        for button in dlg.descendants(class_name="Button"):
            if "existing" in button.window_text().lower():
                button.click()
                time.sleep(2)
                break
        if index == 0:
            (OUT / "page2-existing-controls.txt").write_text("\n".join(controls(dlg)), encoding="utf-8")
            ImageGrab.grab().save(OUT / "page2-existing.png")
        for combo in dlg.descendants(class_name="ComboBox"):
            texts = [t for t in combo.item_texts() if t]
            if len(texts) > len(entry["servers"]):
                entry["servers"] = texts
        for edit in dlg.descendants(class_name="Static"):
            text = edit.window_text()
            if text and len(text) < 80 and ("Ltd" in text or "Limited" in text or "LLC" in text):
                entry.setdefault("labels", []).append(text)
        back()
        time.sleep(3)
    except Exception as exc:  # noqa: BLE001
        entry["error"] = repr(exc)[:200]
        try:
            back()
        except Exception:  # noqa: BLE001
            pass
    report["companies"].append(entry)
    print(json.dumps(entry), flush=True)
subprocess.run(["taskkill", "/IM", "terminal64.exe", "/F"], check=False)  # noqa: S607
time.sleep(10)
shutil.copy(DATA / "Config" / "servers.dat", OUT / "servers-catalog.dat")

import MetaTrader5 as mt5  # noqa: E402

servers = sorted({s for c in report["companies"] for s in c["servers"]})
report["logins"] = []
for server in servers[:200]:
    started = time.monotonic()
    mt5.initialize(TERMINAL, login=10000001, password="synthetic-probe", server=server, timeout=30000, portable=True)
    report["logins"].append({"server": server, "error": mt5.last_error()[0], "seconds": round(time.monotonic() - started, 1)})
    mt5.shutdown()
(OUT / "report-servers.json").write_text(json.dumps(report, indent=1))
print("servers:", len(servers), "ok:", sum(1 for l in report["logins"] if l["error"] == -6))
print("saved:", sorted(p.name for p in OUT.iterdir()))
