"""Build the MT5 server catalog on Windows (research tool for the Tanren sync terminal).

1. Add companies through the terminal's native 'Open an Account' dialog (search box +
   'Find your company'), one query per line of tools/catalog-queries.txt.
2. Read every server the terminal now knows from the native login dialog's server list.
3. Check each server with a synthetic login (never a real account): "Authorization failed"
   (-6) means the server is known and reachable.
Outputs probe-out/servers-catalog.dat and probe-out/report.json. No account is opened.
"""

import json
import shutil
import subprocess
import time
from pathlib import Path

from PIL import ImageGrab
from pywinauto import Application, keyboard

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
DATA = Path(TERMINAL).parent
OUT = Path("probe-out")
OUT.mkdir(exist_ok=True)
queries = [q.strip() for q in Path("tools/catalog-queries.txt").read_text().splitlines() if q.strip()]
report = {"queries": [], "servers": [], "logins": []}

subprocess.Popen([TERMINAL, "/portable"])
time.sleep(60)
app = Application(backend="win32").connect(path=TERMINAL, timeout=60)
try:
    app.window(title="Welcome to LiveUpdate").child_window(title="Later").click()
except Exception as exc:  # noqa: BLE001
    report["liveupdate"] = repr(exc)
dlg = app.window(title="Open an Account")
dlg.wait("visible", timeout=60)
listview = dlg.child_window(control_id=10729).wrapper_object()
for query in queries:
    before = listview.item_count()
    dlg.child_window(control_id=10814).set_edit_text(query)
    dlg.child_window(control_id=10815).click()
    time.sleep(15)
    after = listview.item_count()
    report["queries"].append({"query": query, "companies_before": before, "companies_after": after})
    print(json.dumps(report["queries"][-1]), flush=True)
ImageGrab.grab().save(OUT / "companies.png")
dlg.child_window(title="Cancel").click()
time.sleep(3)

# Server names: the native login dialog lists every server of every known company.
main = app.window(title_re=".*MetaTrader 5.*")
main.set_focus()
try:
    main.menu_select("File->Login to Trade Account")
except Exception as exc:  # noqa: BLE001
    report["menu"] = repr(exc)
    keyboard.send_keys("%f")
    time.sleep(1)
    ImageGrab.grab().save(OUT / "file-menu.png")
time.sleep(5)
ImageGrab.grab().save(OUT / "login-dialog.png")
try:
    login = app.top_window()
    for combo in login.children(class_name="ComboBox"):
        texts = [t for t in combo.item_texts() if t]
        if len(texts) > len(report["servers"]):
            report["servers"] = texts
    login.close()
except Exception as exc:  # noqa: BLE001
    report["login_dialog"] = repr(exc)
print("servers:", json.dumps(report["servers"]), flush=True)
time.sleep(3)
subprocess.run(["taskkill", "/IM", "terminal64.exe", "/F"], check=False)  # noqa: S607
time.sleep(10)
shutil.copy(DATA / "Config" / "servers.dat", OUT / "servers-catalog.dat")

import MetaTrader5 as mt5  # noqa: E402

for server in report["servers"][:150]:
    started = time.monotonic()
    ok = mt5.initialize(
        TERMINAL, login=10000001, password="synthetic-probe", server=server, timeout=30000, portable=True
    )
    report["logins"].append(
        {"server": server, "error": mt5.last_error()[0], "seconds": round(time.monotonic() - started, 1)}
    )
    print(json.dumps(report["logins"][-1]), flush=True)
    mt5.shutdown()
(OUT / "report.json").write_text(json.dumps(report, indent=1))
print("saved:", sorted(p.name for p in OUT.iterdir()))
