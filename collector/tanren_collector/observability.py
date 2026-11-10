"""Bounded technical diagnostics: no exception messages, source lines, locals or user paths."""

import contextlib
import os
import re
import sys
import uuid
from collections import deque
from datetime import UTC, datetime

from . import __version__, build_target
from .build_profile import current

STAGES = frozenset(
    {
        "bootstrap",
        "child_start",
        "child_call",
        "child_timeout",
        "child_exit",
        "mt5_import",
        "mt5_initialize",
        "account_identity",
        "terminal_identity",
        "self_test",
        "gui_start",
    }
)
TYPES = (
    ImportError,
    ModuleNotFoundError,
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    TimeoutError,
    EOFError,
    ConnectionError,
    ArithmeticError,
)
EVENTS = deque(maxlen=32)
SINK = None
SENT = 0
MAX_FRAMES = 12
# Explicit source-owned module names also work when Python modules live inside a frozen PYZ archive.
MODULES = frozenset(
    {
        "bridge_probe",
        "terminal",
        "terminal_v2",
        "runtime",
        "processes",
        "engine",
        "pairing",
        "rotation",
        "client",
        "protocol",
        "storage",
        "v2_store",
        "desktop",
        "selftest",
        "discovery",
        "windows",
        "tray",
        "diagnostics",
        "observability",
    }
)


def clean(report):
    """Revalidate even incoming child reports. Never copy arbitrary strings/objects."""
    from .engine import safe_error

    report = report if isinstance(report, dict) else {}
    result = {
        "schema": 1,
        "id": str(uuid.UUID(str(report["id"]))) if _uuid(report.get("id")) else str(uuid.uuid4()),
        "stage": report.get("stage")
        if isinstance(report.get("stage"), str) and report.get("stage") in STAGES
        else "child_call",
        "code": safe_error(RuntimeError(str(report.get("code", "")))),
        "exception_type": report.get("exception_type")
        if isinstance(report.get("exception_type"), str)
        and report.get("exception_type") in {t.__name__ for t in TYPES} | {"None", "Exception"}
        else "Exception",
        "collector_version": __version__,
        "build_profile": current().name,
        "build_commit": getattr(build_target, "SOURCE_COMMIT", "unknown"),
        "frozen": bool(getattr(sys, "frozen", False)),
        "start_method": "spawn",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "architecture_bits": 64 if sys.maxsize > 2**32 else 32,
        "frames": [],
    }
    if not re.fullmatch(r"[0-9a-f]{40}", result["build_commit"]):
        result["build_commit"] = "unknown"
    # Export frame names only for files that actually belong to the installed Collector package.
    known = {name + ".py" for name in MODULES}
    frames = report.get("frames", [])
    for frame in (frames if isinstance(frames, list) else [])[:MAX_FRAMES]:
        if not isinstance(frame, dict):
            continue
        if (
            isinstance(frame.get("module"), str)
            and frame.get("module") in known
            and type(frame.get("line")) is int
        ):
            result["frames"].append(
                {"module": frame["module"], "line": max(0, min(frame["line"], 1000000))}
            )
    for key in (
        "pid",
        "parent_pid",
        "child_pid",
        "exit_code",
        "errno",
        "winerror",
        "mt5_error_code",
    ):
        value = report.get(key)
        if type(value) is int and -(2**31) <= value <= 2**32:
            result[key] = value
    if isinstance(report.get("last_stage"), str) and report["last_stage"] in STAGES:
        result["last_stage"] = report["last_stage"]
    missing = report.get("missing_module")
    if isinstance(missing, str) and missing in {
        "MetaTrader5",
        "MetaTrader5._core",
        "numpy",
        "numpy._core",
        "numpy.core",
    }:
        result["missing_module"] = missing
    value = report.get("at")
    if isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value)
            if stamp.tzinfo:
                result["at"] = stamp.astimezone(UTC).isoformat()
        except ValueError:
            pass
    return result


def _uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def capture(stage, exc=None, code=None, exit_code=None):
    from .engine import safe_error

    frames = []
    tb = exc.__traceback__ if exc else None
    while tb and len(frames) < MAX_FRAMES:
        module = tb.tb_frame.f_globals.get("__name__", "")
        name = module.removeprefix("tanren_collector.")
        if module.startswith("tanren_collector.") and name in MODULES:
            frames.append({"module": name + ".py", "line": tb.tb_lineno})
        tb = tb.tb_next
    if code is None:
        code = (
            "MT5_BRIDGE_UNAVAILABLE"
            if isinstance(exc, ImportError)
            else "MT5_NATIVE_LOAD_FAILED"
            if stage == "mt5_import" and isinstance(exc, OSError)
            else safe_error(exc)
            if exc
            else "DIAGNOSTIC_EVENT"
        )
    report = clean(
        {
            "id": str(uuid.uuid4()),
            "stage": stage,
            "code": code,
            "exception_type": type(exc).__name__
            if exc and type(exc) in TYPES
            else "Exception"
            if exc
            else "None",
            "pid": os.getpid(),
            "parent_pid": os.getppid(),
            "exit_code": exit_code,
            "missing_module": getattr(exc, "name", None),
            "errno": getattr(exc, "errno", None),
            "winerror": getattr(exc, "winerror", None),
            "mt5_error_code": getattr(exc, "mt5_error_code", None),
            "at": datetime.now(UTC).isoformat(),
            "frames": frames,
        }
    )
    EVENTS.append(report)
    global SENT
    if SINK is not None and SENT < 32:
        SENT += 1
        try:
            SINK(report)
        except (OSError, EOFError):
            pass
    if exc:
        try:
            exc.collector_diagnostic = report
        except (AttributeError, TypeError):
            pass
    return report


@contextlib.contextmanager
def stage(name):
    capture(name)
    try:
        yield
    except Exception as exc:
        if not getattr(exc, "collector_diagnostic", None):
            capture(name, exc)
        raise


def recent():
    return [clean(item) for item in EVENTS]


def remember(report):
    EVENTS.append(clean(report))


class DiagnosticFailure(RuntimeError):
    def __init__(self, code, diagnostic=None):
        super().__init__(code)
        self.collector_diagnostic = clean(diagnostic) if diagnostic else None


def set_sink(sink):
    """Child-only bounded progress channel. No network/disk or queue operations."""
    global SINK, SENT
    SINK, SENT = sink, 0
