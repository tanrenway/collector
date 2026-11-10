"""Frozen-build smoke: no enrollment, network, terminal attachment or production data."""

import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from .build_profile import ENGINEERING, check_storage_path, current, profile_root
from .processes import SpawnPool
from .storage import DPAPI
from .v2_store import Store
from .windows import AppMutex


def child_check():
    from .observability import stage

    with stage("mt5_import"):
        import MetaTrader5

        return callable(MetaTrader5.account_info)


def run():
    if os.name != "nt":
        raise RuntimeError("Windows build smoke requires Windows")
    import tkinter as tk

    protector = DPAPI()
    value = os.urandom(32)
    if protector.open(protector.seal(value)) != value:
        raise RuntimeError("DPAPI smoke failed")
    parent = profile_root() if current() == ENGINEERING else None
    if parent is not None:
        check_storage_path(parent)
        parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="Tanren-build-smoke-", dir=parent) as directory:
        store = Store(Path(directory) / "queue-v2.sqlite", protector)
        try:
            store.save("smoke", True)
            if store.get("smoke") is not True:
                raise RuntimeError("Protected storage smoke failed")
        finally:
            store.close()
    root = tk.Tk()
    root.withdraw()
    from .tray import MESSAGE, Tray

    events = []
    mutex = AppMutex()
    tray = None
    try:
        try:
            second = AppMutex()
        except RuntimeError as exc:
            if str(exc) != "COLLECTOR_ALREADY_RUNNING":
                raise
        else:
            second.close()
            raise RuntimeError("Mutex allowed duplicate application")
        tray = Tray(
            root,
            lambda: events.append("show"),
            lambda: None,
            lambda: None,
            lambda: events.append("resume"),
        )
        tray.dispatch(tray.hwnd, MESSAGE, 0, 0x202)
        tray.dispatch(tray.hwnd, 0x218, 18, 0)
        root.update()
        if events != ["show", "resume"]:
            raise RuntimeError("Native tray/resume dispatch smoke failed")
    finally:
        if tray:
            tray.close()
        mutex.close()
        root.destroy()
    pool = SpawnPool(max_workers=1)
    try:
        task = pool.submit(child_check)
        deadline = time.monotonic() + 30
        while not task.done() and time.monotonic() < deadline:
            pool.tick()
            time.sleep(0.05)
        if task.result() is not True:
            raise RuntimeError("Frozen child/bridge smoke failed")
    finally:
        pool.shutdown()
