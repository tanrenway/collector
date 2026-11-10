"""Portable windowed smoke reporting: no console or native Windows claim."""

import json
import sys

from tanren_collector.qt.smoke_report import LIMIT, run_report


def test_success_and_failure_without_console(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    good = tmp_path / "success.json"
    assert run_report(good, lambda: {"checks_passed": True}, {"synthetic": True}) == 0
    assert json.loads(good.read_text())["checks_passed"] is True

    def fail():
        raise RuntimeError("token=SECRET C:/Users/private/account.json")

    bad = tmp_path / "failure.json"
    assert run_report(bad, fail, {"synthetic": True}) != 0
    assert json.loads(bad.read_text())["error"] == "QT_SMOKE_FAILED"
    assert "SECRET" not in bad.read_text() and "private" not in bad.read_text()


def test_bounded_missing_and_stale_evidence_fail_closed(tmp_path):
    path = tmp_path / "evidence.json"
    assert run_report(path, lambda: {"checks_passed": True, "data": "x" * LIMIT}, {}) != 0
    assert path.stat().st_size < LIMIT
    original = path.read_bytes()
    assert run_report(path, lambda: {"checks_passed": True}, {}) != 0
    assert path.read_bytes() == original
    assert run_report(tmp_path, lambda: {"checks_passed": True}, {}) != 0


def test_frozen_evidence_rejects_missing_or_failed_checks(tmp_path):
    import runpy
    from pathlib import Path

    import pytest

    validate = runpy.run_path(str(Path(__file__).parents[1] / "build/check_qt_smoke.py"))[
        "validate"
    ]
    proof = {
        "schema": 1,
        "synthetic": True,
        "frozen": True,
        "checks_passed": True,
        "spawn_bootstrap": True,
        "qml_errors": [],
    }
    path = tmp_path / "qt-smoke.json"
    path.write_text(json.dumps(proof))
    assert validate(path)  # Synthetic schema test, never native Windows evidence.
    for key in proof:
        missing = {k: v for k, v in proof.items() if k != key}
        path.write_text(json.dumps(missing))
        with pytest.raises(ValueError):
            validate(path)
    for key in ("synthetic", "frozen", "checks_passed", "spawn_bootstrap"):
        path.write_text(json.dumps({**proof, key: "true"}))
        with pytest.raises(ValueError):
            validate(path)
    path.write_bytes(b" " * (LIMIT + 1))
    with pytest.raises(ValueError, match="limit"):
        validate(path)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        validate(path)
