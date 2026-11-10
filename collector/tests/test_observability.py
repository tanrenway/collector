"""Failure injection and real spawn diagnostics; no accounts, credentials or MT5 needed."""

import builtins
import json
import os
import time
import zipfile
from types import SimpleNamespace

import pytest
from tanren_collector.diagnostics import export
from tanren_collector.observability import EVENTS, capture, clean, recent, stage
from tanren_collector.processes import SpawnPool
from tanren_collector.terminal import Terminal, initialize_readonly

ADVERSARIAL_TEXT = (
    "token=SECRET_VALUE C:/Users/private-name/password.txt https://private.example/?secret=VALUE"
)


def crash():
    os._exit(37)


def hang():
    time.sleep(10)


def fail_import():
    with stage("mt5_import"):
        raise ImportError(ADVERSARIAL_TEXT)


def success(value):
    return value


def await_task(pool, task):
    end = time.monotonic() + 10
    while not task.done() and time.monotonic() < end:
        pool.tick()
        time.sleep(0.01)
    assert task.done()


@pytest.fixture(autouse=True)
def isolated_reports():
    EVENTS.clear()
    yield
    EVENTS.clear()


@pytest.mark.parametrize(
    "error,expected",
    [
        (ImportError(ADVERSARIAL_TEXT), "MT5_BRIDGE_UNAVAILABLE"),
        (ModuleNotFoundError(ADVERSARIAL_TEXT), "MT5_BRIDGE_UNAVAILABLE"),
        (OSError(126, ADVERSARIAL_TEXT), "MT5_NATIVE_LOAD_FAILED"),
    ],
)
def test_import_failure_stage_native_code_and_no_exception_text(monkeypatch, error, expected):
    original = builtins.__import__

    def importer(name, *args, **kwargs):
        if name == "MetaTrader5":
            raise error
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", importer)
    with pytest.raises(type(error)):
        Terminal("ignored-path", None)
    report = recent()[-1]
    assert report["stage"] == "mt5_import" and report["code"] == expected
    assert report["exception_type"] == type(error).__name__
    assert any(frame["module"] == "terminal.py" for frame in report["frames"])
    assert "SECRET" not in json.dumps(report) and "private" not in json.dumps(report)


@pytest.mark.parametrize(
    "native,expected",
    [
        (-2, "TERMINAL_INVALID_ARGUMENT"),
        (-6, "TERMINAL_AUTH_REQUIRED"),
        (-10003, "TERMINAL_IPC_FAILED"),
        (-10005, "TERMINAL_API_TIMEOUT"),
    ],
)
def test_initialization_failure_preserves_existing_error(native, expected):
    api = SimpleNamespace(
        initialize=lambda *a, **kw: False, last_error=lambda: (native, ADVERSARIAL_TEXT)
    )
    with pytest.raises(RuntimeError, match=expected):
        initialize_readonly(api, "private-path")
    assert recent()[-1]["stage"] == "mt5_initialize"
    assert recent()[-1]["code"] == expected


@pytest.mark.parametrize(
    "function,code,stage_name",
    [
        (crash, "CHILD_PROCESS_EXITED", "child_exit"),
        (hang, "CHILD_PROCESS_TIMEOUT", "child_timeout"),
        (fail_import, "MT5_BRIDGE_UNAVAILABLE", "mt5_import"),
    ],
)
def test_real_spawn_failures_propagate_sanitized_report(function, code, stage_name):
    pool = SpawnPool(max_workers=1, timeout=0.8)
    try:
        task = pool.submit(function)
        await_task(pool, task)
        with pytest.raises(RuntimeError, match=code) as caught:
            task.result()
        report = caught.value.collector_diagnostic
        assert report["stage"] == stage_name
        assert report["build_commit"] == "unknown" or len(report["build_commit"]) == 40
        assert "SECRET" not in json.dumps(report)
        if function is crash:
            assert report["exit_code"] == 37
    finally:
        pool.shutdown()


def test_success_payload_unchanged_and_no_queue_side_effect(tmp_path):
    marker = tmp_path / "queue-v2.sqlite"
    marker.write_bytes(b"protected queue untouched")
    pool = SpawnPool(max_workers=1)
    try:
        task = pool.submit(success, {"exact": ["1.000000000001", None]})
        await_task(pool, task)
        assert task.result() == {"exact": ["1.000000000001", None]}
        assert marker.read_bytes() == b"protected queue untouched"
    finally:
        pool.shutdown()


def test_diagnostic_export_ring_and_binding_size_bound(tmp_path):
    for _ in range(200):
        capture("mt5_import", ImportError(ADVERSARIAL_TEXT))
    report = clean(
        {
            "stage": "mt5_import",
            "code": ADVERSARIAL_TEXT,
            "exception_type": ADVERSARIAL_TEXT,
            "frames": [{"module": ADVERSARIAL_TEXT, "line": 1}],
            "payload": ADVERSARIAL_TEXT,
            "path": ADVERSARIAL_TEXT,
        }
    )
    statuses = [
        {"diagnostic": report, "identity": ADVERSARIAL_TEXT, "queue": {"pending": 1}}
    ] * 10000
    destination = tmp_path / "safe.zip"
    export(destination, statuses)
    with zipfile.ZipFile(destination) as archive:
        body = archive.read("diagnostics.json")
        assert len(body) <= 128000
        assert b"SECRET" not in body and b"private-name" not in body
        value = json.loads(body)
        assert len(value["events"]) <= 32 and len(value["bindings"]) == 100
    assert len(recent()) == 32


def test_start_failure_does_not_escape_scheduler():
    class Process:
        def start(self):
            raise OSError(ADVERSARIAL_TEXT)

        def close(self):
            pass

    import multiprocessing

    class Context:
        Pipe = staticmethod(multiprocessing.get_context("spawn").Pipe)
        Process = staticmethod(lambda **kwargs: Process())

    pool = SpawnPool(context=Context())
    task = pool.submit(success, None)
    pool.tick()
    with pytest.raises(RuntimeError, match="CHILD_START_FAILED") as caught:
        task.result()
    assert caught.value.collector_diagnostic["stage"] == "child_start"
    pool.shutdown()


def test_identity_failure_has_own_stage():
    from tanren_collector.terminal_v2 import RawTerminal

    api = SimpleNamespace(account_info=lambda: None)
    with pytest.raises(RuntimeError, match="ACCOUNT_INFO_UNAVAILABLE"):
        RawTerminal("unused", None, api).identity()
    assert recent()[-1]["stage"] == "account_identity"
    assert recent()[-1]["exception_type"] == "RuntimeError"


@pytest.mark.parametrize(
    "poison",
    [
        None,
        [],
        {
            "stage": [],
            "exception_type": {},
            "frames": [{"module": {}, "line": True}],
            "pid": "private",
            "at": ADVERSARIAL_TEXT,
        },
        {"frames": ADVERSARIAL_TEXT},
    ],
)
def test_malformed_report_cannot_leak_or_crash_export(poison):
    safe = clean(poison)
    assert "SECRET" not in json.dumps(safe)
    assert safe["stage"] == "child_call"


def test_selftest_bridge_failure_has_import_stage(monkeypatch):
    from tanren_collector.selftest import child_check

    original = builtins.__import__

    def importer(name, *args, **kwargs):
        if name == "MetaTrader5":
            raise ImportError(ADVERSARIAL_TEXT)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", importer)
    with pytest.raises(ImportError):
        child_check()
    assert recent()[-1]["stage"] == "mt5_import"


def test_selftest_successful_bridge_import_unchanged(monkeypatch):
    import sys

    from tanren_collector.selftest import child_check

    monkeypatch.setitem(sys.modules, "MetaTrader5", SimpleNamespace(account_info=lambda: None))
    assert child_check() is True
