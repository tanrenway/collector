"""Read-only probe contracts with fake native API; no Windows or real account claim."""

import json
import runpy
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from tanren_collector.bridge_probe import inspect_bridge, main, run_child
from tanren_collector.observability import capture, clean
from test_collector import TestProtector

BUILD = Path(__file__).parents[1] / "build"


class Bridge:
    def __init__(self, initialize=True, switch=False):
        self.calls = []
        self.ok = initialize
        self.switch = switch
        self.reads = 0

    def initialize(self, path, /, **kwargs):
        self.calls.append(("initialize", kwargs))
        assert set(kwargs) == {"timeout"}  # No login/password/server arguments.
        return self.ok

    def last_error(self):
        return -10003, "private broker/path must never escape"

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def account_info(self):
        self.reads += 1
        return SimpleNamespace(
            login=self.reads if self.switch else 7,
            server="private",
            company="secret",
            currency="USD",
        )

    def shutdown(self):
        self.calls.append(("shutdown", {}))


def test_selected_readonly_init_reconnect_and_no_account_data():
    api = Bridge()
    result = inspect_bridge("private-terminal", lambda: api)
    assert result["identity_stable"] and result["shutdown_1"]
    assert [name for name, _ in api.calls] == ["initialize", "shutdown"] * 2
    assert "private" not in json.dumps(result) and "secret" not in json.dumps(result)


def test_import_only_does_not_initialize_terminal():
    api = Bridge()
    assert inspect_bridge(factory=lambda: api)["native_extension"]
    assert not api.calls


def test_init_failure_and_identity_switch_always_shutdown():
    api = Bridge(initialize=False)
    with pytest.raises(RuntimeError, match="TERMINAL_IPC_FAILED") as failed:
        inspect_bridge("private-terminal", lambda: api)
    assert failed.value.collector_diagnostic["mt5_error_code"] == -10003
    assert api.calls[-1][0] == "shutdown"
    api = Bridge(switch=True)
    with pytest.raises(RuntimeError, match="IDENTITY_MISMATCH"):
        inspect_bridge("private-terminal", lambda: api)
    assert api.calls[-1][0] == "shutdown"


def test_missing_module_allowlist_never_exports_private_names():
    allowed = capture("mt5_import", ModuleNotFoundError("private token", name="MetaTrader5._core"))
    assert allowed["missing_module"] == "MetaTrader5._core"
    denied = capture("mt5_import", ModuleNotFoundError("private token", name="C:/Users/private"))
    assert "missing_module" not in denied
    assert "private token" not in json.dumps([allowed, denied])
    assert "missing_module" not in clean({"missing_module": "private"})
    assert "missing_module" not in clean({"missing_module": {"private": True}})


def test_probe_pool_closes_even_if_child_fails():
    closed = []

    class Pool:
        def __init__(self, **kwargs):
            pass

        def submit(self, *args):
            return self

        def done(self):
            return True

        def result(self):
            raise RuntimeError("CHILD_PROCESS_EXITED")

        def shutdown(self):
            closed.append(True)

    with pytest.raises(RuntimeError, match="CHILD_PROCESS_EXITED"):
        run_child(pool_factory=Pool)
    assert closed == [True]


def test_non_windows_cli_is_blocked_and_does_not_create_profile(tmp_path):
    import os

    if os.name == "nt":
        pytest.skip("Non-Windows refusal case")
    report = tmp_path / "probe.json"
    assert main(["--bridge-probe", "--report", str(report)]) == 2
    value = json.loads(report.read_text())
    assert value["status"] == "BLOCKED" and value["windows_build"] is None
    assert value["checks"] == {}
    with pytest.raises(SystemExit):
        main(["--report", str(report)])


def test_pe_inventory_rejects_elf_wrong_arch_and_missing_components(tmp_path):
    module = runpy.run_path(str(BUILD / "windows_inventory.py"))
    file = tmp_path / "fake.exe"
    file.write_bytes(b"\x7fELF" + b"\0" * 100)
    with pytest.raises(ValueError, match="Windows PE"):
        module["inventory"](tmp_path)
    head = b"MZ" + b"\0" * 58 + struct.pack("<I", 64)
    file.write_bytes(head + b"PE\0\0" + struct.pack("<H", 0x14C))
    with pytest.raises(ValueError, match="AMD64"):
        module["inventory"](tmp_path)
    file.write_bytes(head + b"PE\0\0" + struct.pack("<H", 0x8664))
    assert module["pe_machine"](file) == 0x8664
    with pytest.raises(ValueError, match="component missing"):
        module["inventory"](tmp_path)


def test_representative_profile_retention_and_change_detection(tmp_path):
    module = runpy.run_path(str(BUILD / "profile_fixture.py"))
    root = tmp_path / "synthetic"
    expected = module["seed"](root, TestProtector())
    assert module["verify"](root, expected)["retained"]
    with pytest.raises(ValueError, match="existing profile"):
        module["seed"](root, TestProtector())
    (root / "v2/settings.dpapi").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        module["verify"](root, expected)


def test_complete_static_inventory_hashes_and_detects_changes(tmp_path):
    module = runpy.run_path(str(BUILD / "windows_inventory.py"))
    pe = b"MZ" + b"\0" * 58 + struct.pack("<I", 64) + b"PE\0\0" + struct.pack("<H", 0x8664)
    names = [
        "TanrenCollector.exe",
        "_internal/python312.dll",
        "_internal/MetaTrader5/_core.pyd",
        "_internal/numpy/_core/a.pyd",
        "_internal/_tkinter.pyd",
        "_internal/PySide6/Qt/plugins/platforms/qwindows.dll",
    ]
    for name in names:
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(pe)
    qml = tmp_path / "_internal/PySide6/Qt/qml/QtQuick/Controls/Basic/Button.qml"
    qml.parent.mkdir(parents=True)
    qml.write_text("synthetic inventory input, not native build")
    before = module["inventory"](tmp_path)
    qml.write_text("changed")
    after = module["inventory"](tmp_path)
    assert before != after and len(before["files"]) == 7


def test_terminal_probe_requires_explicit_ack_before_any_native_work(tmp_path):
    terminal = tmp_path / "terminal64.exe"
    terminal.write_bytes(b"synthetic argument-validation input")
    report = tmp_path / "probe.json"
    with pytest.raises(SystemExit):
        main(["--terminal", str(terminal), "--report", str(report)])
    assert not report.exists()


def test_interrupted_profile_write_preserves_all_existing_state(tmp_path, monkeypatch):
    from tanren_collector.storage import load_config, save_config

    module = runpy.run_path(str(BUILD / "profile_fixture.py"))
    root = tmp_path / "synthetic"
    protector = TestProtector()
    before = module["seed"](root, protector)
    path = root / "v2/settings.dpapi"
    original = load_config(path, protector)

    def interrupted(*_):
        raise OSError("synthetic interrupted replacement")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", interrupted)
        with pytest.raises(OSError, match="interrupted"):
            save_config(path, {"palette": "changed"}, protector)
    assert load_config(path, protector) == original
    # Leftover temporary file is retained for diagnosis; no old queue or credential is reset.
    after = module["snapshot"](root)
    assert all(after[name] == digest for name, digest in before.items())
    assert "v2/settings.tmp" in after
    save_config(path, original, protector)
    assert module["verify"](root, before)["retained"]
