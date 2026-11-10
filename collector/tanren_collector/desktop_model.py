"""Pure presentation policy. No protected storage, transport or financial computation."""

from .engine import safe_error


def masked_login(value):
    text = str(value or "")
    return "•••• " + text[-4:] if text else "—"


def effective_state(item):
    state = item.get("state", "connected")
    if item.get("pairing") == "awaiting_browser_confirmation":
        return "pending_pair"
    if state == "up_to_date" and (
        not item.get("last_success")
        or any(
            item.get("queue", {}).get(s)
            for s in ("pending", "received", "partial", "paused", "needs_review")
        )
    ):
        return "processing"
    return state


def error_hint(code):
    code = safe_error(RuntimeError(code))
    if code == "NETWORK_UNAVAILABLE":
        return "net_hint"
    if code in {"MT5_BRIDGE_UNAVAILABLE", "MT5_NATIVE_LOAD_FAILED"}:
        return "bridge_hint"
    if code == "TERMINAL_IDENTITY_MISMATCH":
        return "identity_hint"
    if code == "TLS_VALIDATION_FAILED":
        return "tls_hint"
    if code == "QUEUE_CAPACITY_REACHED":
        return "disk_hint"
    if code in {"TERMINAL_AUTH_REQUIRED", "ACCOUNT_INFO_UNAVAILABLE", "TERMINAL_DISCONNECTED"}:
        return "auth_hint"
    if code.startswith("CHILD_"):
        return "ipc_hint"
    if code.startswith("TERMINAL_"):
        return "ipc_hint"
    if code == "SYNC_PAUSED_HTTP_401":
        return "reauth_hint"
    return "generic_hint"


def display_time(value):
    from datetime import UTC, datetime

    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            return None
        return stamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return None
