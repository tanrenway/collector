"""Allowlist-only diagnostic export. Never collect configs, DB, logs, paths or payloads."""

import json
import platform
import zipfile
from datetime import UTC, datetime

from .build_profile import check_storage_path, current, profile_root
from .engine import safe_error
from .observability import clean, recent
from .protocol import VERSION

ALLOWED_STATES = {
    "connected",
    "syncing",
    "up_to_date",
    "waiting_for_terminal",
    "waiting_for_network",
    "queued",
    "processing",
    "needs_attention",
    "authentication_expired",
    "paused",
    "disconnected",
    "error",
}


def export(destination, statuses):
    check_storage_path(destination)
    safe = []
    for index, item in enumerate(statuses):
        if index >= 100:
            break
        # No identity/login, account/device UUID, URL, filesystem path or arbitrary error strings.
        counts = item.get("queue", {})
        safe.append(
            {
                "state": item.get("state") if item.get("state") in ALLOWED_STATES else "error",
                "terminal_connected": item.get("terminal_connected") is True,
                "error_code": safe_error(RuntimeError(str(item.get("error", ""))))
                if item.get("error")
                else None,
                "queue": {
                    key: value
                    for key, value in counts.items()
                    if key
                    in {
                        "pending",
                        "received",
                        "processed",
                        "partial",
                        "needs_review",
                        "paused",
                        "cancelled",
                    }
                    and isinstance(value, int)
                    and 0 <= value <= 1000000
                },
            }
        )
    report = {
        "collector_version": VERSION,
        "build_profile": current().name,
        "os": platform.system(),
        "architecture": platform.machine(),
        "exported_at": datetime.now(UTC).isoformat(),
        "bindings": safe,
        "events": recent()[-32:],
        "omitted": "credentials, identities, IDs, paths, URLs, source payloads, database and logs",
    }
    for item in statuses[:100]:
        if isinstance(item.get("diagnostic"), dict):
            report["events"] = (report["events"] + [clean(item["diagnostic"])])[-32:]
    encoded = json.dumps(report, indent=2).encode()
    if len(encoded) > 128000:
        raise RuntimeError("DIAGNOSTIC_REPORT_TOO_LARGE")
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.json", encoded)


def write_bootstrap_report():
    """Best-effort sanitized rotating report; never opens a binding/store or mutates sync state."""
    import os

    if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        return
    try:
        directory = profile_root() / "diagnostics"
        check_storage_path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        # Safe allowlisted JSON only; no raw exception text needs to be stored or exported.
        temporary = directory / "bootstrap.tmp"
        check_storage_path(temporary)
        check_storage_path(directory / "bootstrap.json")
        temporary.write_text(json.dumps({"events": recent()[-32:]}), encoding="utf-8")
        temporary.replace(directory / "bootstrap.json")
    except OSError:
        pass  # Reporting cannot hide the original failure or alter queue recovery.
