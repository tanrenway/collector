"""Bounded synthetic evidence for windowed builds with no stdout/stderr."""

import json
import os
from pathlib import Path

LIMIT = 65536


def write_report(path, report):
    """Only synthetic smoke DTOs belong here; never raw exceptions or service diagnostics."""
    payload = json.dumps(report, ensure_ascii=True, allow_nan=False).encode()
    if len(payload) > LIMIT:
        payload = b'{"synthetic":true,"checks_passed":false,"error":"QT_SMOKE_REPORT_LIMIT"}'
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Reject stale evidence instead of overwriting a previous successful run.
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return len(payload) <= LIMIT and json.loads(payload).get("checks_passed") is True


def run_report(path, exercise, metadata):
    try:
        report = {**metadata, **exercise()}
    except Exception:
        # Arbitrary errors may contain local paths, tokens or provider payloads.
        report = {**metadata, "checks_passed": False, "error": "QT_SMOKE_FAILED"}
    try:
        return 0 if write_report(path, report) else 3
    except (OSError, ValueError, TypeError):
        # Missing/unwritable/stale evidence must never be a successful smoke run.
        return 4
