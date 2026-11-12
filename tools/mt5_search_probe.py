"""Research probe, stage 2: drive the terminal's own broker search (Windows only).

Starts a fresh terminal without any login, waits for the account dialog, dumps its UI
Automation tree, types each broker query into the search box and records what appears.
No account is opened and no credentials are entered.
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

from PIL import ImageGrab
from pywinauto import Desktop, keyboard

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
DATA = Path(TERMINAL).parent
OUT = Path("probe-out")
OUT.mkdir(exist_ok=True)
step = 0


def dump(tag, deep_titles=("Login", "Open an Account", "MetaTrader", "Account")):
    global step
    step += 1
    ImageGrab.grab().save(OUT / f"s{step:02d}-{tag}.png")
    lines = []
    for window in Desktop(backend="uia").windows():
        title = window.window_text()
        lines.append(f"WINDOW {title!r} class={window.element_info.class_name!r}")
        if any(t in title for t in deep_titles) or window.element_info.class_name.startswith("MetaQuotes"):
            try:
                for child in window.descendants()[:800]:
                    info = child.element_info
                    lines.append(
                        f"  {info.control_type} name={info.name!r} id={info.automation_id!r} class={info.class_name!r}"
                    )
            except Exception as exc:  # noqa: BLE001
                lines.append(f"  (descendants failed: {exc!r})")
    (OUT / f"s{step:02d}-{tag}.txt").write_text("\n".join(lines), encoding="utf-8")


def windows_named(*names):
    return [w for w in Desktop(backend="uia").windows() if any(n in w.window_text() for n in names)]


subprocess.Popen([TERMINAL, "/portable"])
time.sleep(60)
dump("started")
for w in windows_named("LiveUpdate"):
    try:
        w.child_window(title="Later", control_type="Button").click_input()
    except Exception:  # noqa: BLE001
        pass
time.sleep(3)
dump("after-liveupdate")
dialogs = windows_named("Login", "Open an Account", "Account")
if not dialogs:
    main = windows_named("MetaTrader")
    if main:
        main[0].set_focus()
        keyboard.send_keys("%f")  # File menu
        time.sleep(2)
        dump("file-menu")
        keyboard.send_keys("{ESC}")
for query in sys.argv[1:]:
    dialogs = windows_named("Login", "Open an Account", "Account")
    if not dialogs:
        dump(f"no-dialog-{query}")
        continue
    dialog = dialogs[0]
    dialog.set_focus()
    edits = dialog.descendants(control_type="Edit")
    target = edits[0] if edits else None
    if target is not None:
        target.click_input()
        keyboard.send_keys("^a{BACKSPACE}")
    for ch in query:
        keyboard.send_keys(ch, with_spaces=True, pause=0.15)
    time.sleep(12)
    dump("query-" + query.replace(" ", "_"))
source = DATA / "Config" / "servers.dat"
if source.exists():
    shutil.copy(source, OUT / "servers-after-search.dat")
for log in (DATA / "logs").glob("*.log"):
    shutil.copy(log, OUT / ("journal-" + log.name))
print("saved:", sorted(p.name for p in OUT.iterdir()))
