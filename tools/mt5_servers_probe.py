"""Research probe: can the official MT5 terminal on Windows reach prop-firm servers by name?

For each server name: initialize the terminal with a synthetic login (never a real account),
record the API error, then save servers.dat, the terminal journal, a screenshot and a UI
Automation dump of any visible terminal dialog (to plan automation of the broker search).
"""

import json
import shutil
import sys
import time
from pathlib import Path

import MetaTrader5 as mt5

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
DATA = Path(TERMINAL).parent
OUT = Path("probe-out")
OUT.mkdir(exist_ok=True)


def snapshot(tag):
    try:
        from PIL import ImageGrab

        ImageGrab.grab().save(OUT / f"screen-{tag}.png")
    except Exception as exc:  # noqa: BLE001 - research diagnostics only
        (OUT / f"screen-{tag}.txt").write_text(repr(exc))
    try:
        from pywinauto import Desktop

        lines = []
        for window in Desktop(backend="uia").windows():
            title = window.window_text()
            lines.append(f"WINDOW {title!r} {window.element_info.control_type}")
            if "MetaTrader" in title or title in ("Login", "Open an Account"):
                for child in window.descendants()[:400]:
                    info = child.element_info
                    lines.append(f"  {info.control_type} name={info.name!r} id={info.automation_id!r}")
        (OUT / f"uia-{tag}.txt").write_text("\n".join(lines), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        (OUT / f"uia-{tag}.txt").write_text(repr(exc))


results = []
for server in sys.argv[1:]:
    started = time.monotonic()
    ok = mt5.initialize(
        TERMINAL, login=10000001, password="synthetic-probe", server=server, timeout=90000, portable=True
    )
    results.append(
        {"server": server, "ok": ok, "error": mt5.last_error(), "seconds": round(time.monotonic() - started, 1)}
    )
    print(json.dumps(results[-1]), flush=True)
    snapshot(server)
    mt5.shutdown()
    time.sleep(5)

(OUT / "results.json").write_text(json.dumps(results, indent=1))
for name in ("servers.dat", "accounts.dat"):
    source = DATA / "Config" / name
    if source.exists() and name == "servers.dat":
        shutil.copy(source, OUT / name)
for log in (DATA / "logs").glob("*.log"):
    shutil.copy(log, OUT / ("journal-" + log.name))
print("saved:", sorted(p.name for p in OUT.iterdir()))
