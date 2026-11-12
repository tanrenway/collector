"""Research probe, stage 3: add companies through the terminal's native 'Open an Account' dialog
(search box + 'Find your company'), then check that their servers are reachable with a synthetic
login. Usage: mt5_catalog_probe.py "<query>" ... -- <server> ...  No account is opened.
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PIL import ImageGrab
from pywinauto import Application

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
DATA = Path(TERMINAL).parent
OUT = Path("probe-out")
OUT.mkdir(exist_ok=True)
args = sys.argv[1:]
split = args.index("--") if "--" in args else len(args)
queries, servers = args[:split], args[split + 1 :]
report = {"queries": [], "logins": []}


def shot(tag):
    ImageGrab.grab().save(OUT / f"{tag}.png")


subprocess.Popen([TERMINAL, "/portable"])
time.sleep(60)
app = Application(backend="win32").connect(path=TERMINAL, timeout=60)
for title in ("Welcome to LiveUpdate",):
    try:
        app.window(title=title).child_window(title="Later").click()
    except Exception:  # noqa: BLE001
        pass
dlg = app.window(title="Open an Account")
dlg.wait("visible", timeout=60)
for query in queries:
    edit = dlg.child_window(control_id=10814)
    edit.set_edit_text(query)
    dlg.child_window(control_id=10815).click()
    time.sleep(20)
    listview = dlg.child_window(control_id=10729).wrapper_object()
    items = [listview.get_item(i).text() for i in range(listview.item_count())]
    report["queries"].append({"query": query, "companies": items})
    print(json.dumps(report["queries"][-1]), flush=True)
    shot("query-" + query.replace(" ", "_").replace(".", "_"))
try:
    dlg.child_window(title="Cancel").click()
except Exception:  # noqa: BLE001
    pass
time.sleep(5)
subprocess.run(["taskkill", "/IM", "terminal64.exe", "/F"], check=False)
time.sleep(10)
shutil.copy(DATA / "Config" / "servers.dat", OUT / "servers-catalog.dat")

import MetaTrader5 as mt5  # noqa: E402

for server in servers:
    started = time.monotonic()
    ok = mt5.initialize(TERMINAL, login=10000001, password="synthetic-probe", server=server, timeout=90000, portable=True)
    report["logins"].append(
        {"server": server, "ok": ok, "error": mt5.last_error(), "seconds": round(time.monotonic() - started, 1)}
    )
    print(json.dumps(report["logins"][-1]), flush=True)
    mt5.shutdown()
    time.sleep(5)
(OUT / "report.json").write_text(json.dumps(report, indent=1))
for log in (DATA / "logs").glob("*.log"):
    shutil.copy(log, OUT / ("journal-" + log.name))
print("saved:", sorted(p.name for p in OUT.iterdir()))
