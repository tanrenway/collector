"""Desktop/process/lifecycle tests; native Windows checks never pretend to run on Linux."""

import os
import time
from types import SimpleNamespace

import pytest
from tanren_collector.processes import SpawnPool
from tanren_collector.storage import DPAPI


def echo(value):
    return value


def slow():
    time.sleep(5)


def test_spawn_isolation_bounded_pool_and_hard_timeout():
    pool = SpawnPool(max_workers=1, timeout=1)
    first = pool.submit(echo, {"status": "synthetic"})
    second = pool.submit(echo, 2)
    try:
        deadline = time.monotonic() + 10
        while not second.done() and time.monotonic() < deadline:
            pool.tick()
            assert len(pool.active) <= 1
            time.sleep(0.02)
        assert first.result() == {"status": "synthetic"} and second.result() == 2
        hung = pool.submit(slow)
        while not hung.done() and time.monotonic() < deadline:
            pool.tick()
            time.sleep(0.02)
        with pytest.raises(RuntimeError):
            hung.result()
    finally:
        pool.shutdown()
    assert not pool.active


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows user DPAPI/mutex required")
def test_native_dpapi_and_application_mutex():
    from tanren_collector.windows import AppMutex

    protector = DPAPI()
    plain = os.urandom(48)
    sealed = protector.seal(plain)
    assert sealed != plain and DPAPI().open(sealed) == plain
    mutex = AppMutex()
    try:
        with pytest.raises(RuntimeError, match="ALREADY_RUNNING"):
            AppMutex()
    finally:
        mutex.close()
    mutex = AppMutex()
    mutex.close()


@pytest.mark.skipif(os.name != "nt" and not os.getenv("DISPLAY"), reason="Tk display unavailable")
@pytest.mark.parametrize("language", ["en", "uk"])
def test_real_tk_window_all_palettes_metrics_and_background_recovery(language):
    import tkinter as tk

    from tanren_collector.desktop import PALETTES, Window

    class FakeSupervisor:
        def bindings(self):
            return ["synthetic-binding"]

        def tick(self):
            return {
                "synthetic-binding": {
                    "state": "queued",
                    "queue": {"pending": 2},
                    "identity": {
                        "login": "123",
                        "broker": "Synthetic",
                        "server": "Test-Demo",
                        "currency": "USD",
                        "mode": "hedging",
                    },
                }
            }

        def close(self):
            self.closed = True

    supervisor = FakeSupervisor()
    root = tk.Tk()
    window = Window(root, supervisor, {"locale": language, "palette": "graphite"}, lambda _: None)
    try:
        for palette in PALETTES:
            window.settings["palette"] = palette
            window.configure_style()
            root.update()
        window.tick()
        root.update()
        assert window.metrics["accounts"].cget("text") == "1"
        assert window.metrics["queue"].cget("text") == "2"
        window.tray = SimpleNamespace(close=lambda: None)
        window.hide()
        root.update()
        assert root.state() == "withdrawn"
        window.show()
        root.update()
        assert root.state() == "normal"
    finally:
        window.quit()


@pytest.mark.skipif(
    os.name != "nt", reason="Native Windows notification area and callbacks required"
)
def test_native_tray_and_resume_dispatch():
    import tkinter as tk

    from tanren_collector.tray import MESSAGE, Tray

    events = []
    root = tk.Tk()
    root.withdraw()
    tray = Tray(
        root,
        lambda: events.append("show"),
        lambda: events.append("sync"),
        lambda: events.append("quit"),
        lambda: events.append("resume"),
    )
    try:
        tray.dispatch(tray.hwnd, MESSAGE, 0, 0x202)
        tray.dispatch(tray.hwnd, 0x218, 18, 0)
        assert events == ["show", "resume"]
    finally:
        tray.close()
        root.destroy()


@pytest.mark.skipif(os.name != "nt", reason="Official Windows MT5 binary import required")
def test_native_bridge_import_without_terminal_attach():
    from tanren_collector.selftest import child_check

    assert child_check() is True


def test_autostart_is_quoted_current_user_only_and_removable(monkeypatch):
    import sys

    from tanren_collector.windows import autostart, autostart_enabled

    values = {}

    class Registry:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def query(key, name):
        if name not in values:
            raise FileNotFoundError
        return values[name], 1

    registry = SimpleNamespace(
        HKEY_CURRENT_USER="current-user-only",
        REG_SZ=1,
        CreateKey=lambda hive, key: Registry(),
        OpenKey=lambda hive, key: Registry(),
        SetValueEx=lambda key, name, reserved, kind, value: values.update({name: value}),
        DeleteValue=lambda key, name: values.pop(name),
        QueryValueEx=query,
    )
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\User Programs\Tanren\TanrenCollector.exe")
    autostart(True)
    assert values["TanrenCollector"] == '"' + sys.executable + '" --background'
    assert autostart_enabled() is True
    autostart(False)
    assert not values and autostart_enabled() is False
