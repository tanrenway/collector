"""One bounded scheduling turn. Capture and upload failures are independent; state is durable."""

import random
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from .protocol import PREFIX, VERSION, V2Api, batches
from .rotation import refresh

# Seconds between routine MT5 reads. Manual and server-requested syncs do not wait for it.
CAPTURE_INTERVAL = 300


def stamp(value):
    return datetime.fromisoformat(value)


def safe_error(exc):
    if (
        isinstance(exc, sqlite3.Error)
        and getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL
    ):
        return "QUEUE_CAPACITY_REACHED"
    code = str(exc)
    # Arbitrary exception messages/paths, bridge last_error and HTTP bodies are NEVER diagnostics.
    known = {
        "RUNTIME_BUSY",
        "ACCOUNT_PREVIEW_REQUIRED",
        "REGISTERED_IDENTITY_IMMUTABLE",
        "REGISTRATION_CONTEXT_REVIEW_REQUIRED",
        "ACCOUNT_CONTEXT_MISSING",
        "DEVICE_CONTINUITY_REVIEW_REQUIRED",
        "EXPLICIT_MIGRATION_REQUIRED",
        "LEGACY_QUEUE_NOT_DRAINED",
        "LEGACY_QUEUE_BUSY",
        "LEGACY_REVIEW_REQUIRED",
        "LEGACY_INVENTORY_INCOMPLETE",
        "LEGACY_ENROLLMENT_PENDING",
        "LEGACY_IDENTITY_REVIEW_REQUIRED",
        "LEGACY_ORIGIN_REVIEW_REQUIRED",
        "ENGINEERING_MT5_DISABLED",
        "ENGINEERING_OFFLINE",
        "ENGINEERING_PROFILE_PATH_REQUIRED",
        "ENGINEERING_CREDENTIAL_NAMESPACE_REQUIRED",
        "BINDING_BUSY",
        "TERMINAL_BUSY",
        "CAPTURE_LEASE_UNCERTAIN",
        "LEGACY_QUEUE_HANDOVER_REQUIRED",
        "DEVICE_NOT_PAIRED",
        "QUEUE_CAPACITY_REACHED",
        "QUEUE_CHECKSUM_MISMATCH",
        "QUEUE_CORRUPT",
        "MT5_BRIDGE_UNAVAILABLE",
        "MT5_NATIVE_LOAD_FAILED",
        "CHILD_PROCESS_TIMEOUT",
        "CHILD_PROCESS_EXITED",
        "CHILD_START_FAILED",
        "DIAGNOSTIC_EVENT",
        "BROWSER_UNAVAILABLE",
        "NETWORK_UNAVAILABLE",
        "TERMINAL_UNAVAILABLE",
        "TERMINAL_INVALID_ARGUMENT",
        "TERMINAL_AUTH_REQUIRED",
        "TERMINAL_IPC_FAILED",
        "TERMINAL_API_TIMEOUT",
        "ACCOUNT_INFO_UNAVAILABLE",
        "TERMINAL_DISCONNECTED",
        "TERMINAL_IDENTITY_MISMATCH",
        "TERMINAL_READ_FAILED",
        "SYMBOL_SPECIFICATION_UNAVAILABLE",
        "SOURCE_PRECISION_UNSUPPORTED",
        "SOURCE_TIMESTAMP_UNAVAILABLE",
        "SOURCE_RECORD_TOO_LARGE",
        "SOURCE_DENSITY_LIMIT",
        "UNSUPPORTED_ACCOUNT_MODE",
        "TLS_VALIDATION_FAILED",
        "INVALID_SERVER_RECEIPT",
        "CREDENTIAL_SCOPE_MISMATCH",
        "BINDING_ACCOUNT_IMMUTABLE",
        "BINDING_IDENTITY_IMMUTABLE",
    }
    if code in known:
        return code
    if code in {"SYNC_PAUSED_HTTP_" + str(n) for n in (400, 401, 403, 404, 409, 410, 422)}:
        return code
    if isinstance(exc, ConnectionError):
        return "NETWORK_UNAVAILABLE"
    return "COLLECTOR_OPERATION_FAILED"


def backoff(attempts, retry_after=0):
    return max(min(retry_after, 86400), min(300, 2 ** min(attempts, 8)) + random.uniform(0, 3))  # noqa: S311 - retry jitter only


class Engine:
    def __init__(self, store, terminal, api_factory=V2Api, clock=None):
        self.store, self.terminal, self.factory = store, terminal, api_factory
        self.now = clock or (lambda: datetime.now(UTC))

    def capture(self, config):
        db = self.store
        now = self.now()
        jobs = db.get("sync_jobs", {})
        active = next(
            (
                j
                for j in jobs.values()
                if j["state"] not in ("complete", "needs_attention", "cancelled")
                and (
                    not db.get("force:" + j["id"])
                    or stamp(db.get("force:" + j["id"])) < stamp(j["history_end"])
                )
            ),
            None,
        )
        manual = db.get("manual_sync", False)
        if (
            not active
            and not manual
            and now.timestamp() - db.get("last_capture", 0) < CAPTURE_INTERVAL
        ):
            return
        self.terminal.connect()
        self.terminal.verify()
        if not db.get("available_start"):
            beginning, has_history = self.terminal.available_start(now)
            with db.db:
                db.put("available_start", beginning.isoformat())
                db.put("history_exposed", has_history)
                db.put("last_full_scan", now.timestamp())
        cursor_key = "capture_cursor"
        sync_id = None
        if active:
            cursor_key = "force:" + active["id"]
            sync_id = active["id"]
            start = stamp(db.get(cursor_key, active["history_start"]))
            limit = min(stamp(active["history_end"]), now)
        else:
            if manual or (
                now.timestamp() - db.get("last_full_scan", 0) > 86400 and not db.get("replay_end")
            ):
                beginning, has_history = self.terminal.available_start(now)
                with db.db:
                    db.put("replay_cursor", beginning.isoformat())
                    db.put("replay_end", now.isoformat())
                    db.put("last_full_scan", now.timestamp())
                    db.put("manual_sync", False)
                    db.put("history_exposed", has_history)
            if db.get("replay_end"):
                cursor_key = "replay_cursor"
                start = stamp(db.get(cursor_key))
                limit = stamp(db.get("replay_end"))
            else:
                start = stamp(db.get(cursor_key, db.get("available_start")))
                # Boundary overlap catches recent records; daily replay catches older ones.
                if now - start < timedelta(seconds=CAPTURE_INTERVAL + 120):
                    start = max(stamp(db.get("available_start")), start - timedelta(minutes=2))
                limit = now
        end = min(limit, start + timedelta(days=7))
        if end < start:
            raise RuntimeError("SOURCE_TIMESTAMP_UNAVAILABLE")
        # Bound historical read memory before fetching; no truncation of a dense instant.
        while (
            sum(
                self.terminal.rows(name, start, end)
                for name in ("history_deals_total", "history_orders_total")
            )
            > 5000
        ):
            if end - start <= timedelta(milliseconds=1):
                raise RuntimeError("SOURCE_DENSITY_LIMIT")
            end = start + (end - start) / 2
        records = self.terminal.read(start, end)
        bodies = batches(config["identity"], records, start.isoformat(), end.isoformat(), sync_id)
        db.capture(str(uuid.uuid4()), bodies, cursor_key, end.isoformat())
        with db.db:
            db.put("last_capture", now.timestamp() if end >= limit else 0)
            if cursor_key == "replay_cursor" and end >= limit:
                db.put("replay_end", None)

    def step(self):
        db = self.store
        config = db.get("config")
        state = {
            "state": "connected",
            "operation": "idle",
            "error": None,
            "terminal_connected": False,
        }
        if not config or config.get("paused"):
            return {**state, "state": "disconnected", "queue": db.counts()}
        now = self.now().timestamp()
        # Read source independently of transport backoff. Network loss must not suppress snapshots.
        try:
            self.capture(config)
            state["terminal_connected"] = True
        except Exception as exc:
            from .observability import capture

            diagnostic = getattr(exc, "collector_diagnostic", None) or capture("child_call", exc)
            code = diagnostic["code"]
            state["diagnostic"] = diagnostic
            state.update(
                state="waiting_for_terminal" if code.startswith("TERMINAL_") else "needs_attention",
                error=code,
            )
        if now < db.get("network_after", 0):
            return {
                **state,
                "state": db.get("transport_state", "waiting_for_network"),
                "error": db.get("transport_error"),
                "queue": db.counts(),
            }
        pending = None
        try:
            if now - db.get("last_control", 0) >= 60 or db.get("rotation"):
                control = refresh(db, self.factory, self.now())
                if control.get("account_name"):
                    db.save("account_name", control["account_name"])
                db.save("last_control", now)
                config = db.get("config")
            api = self.factory(config["token"])
            if now - db.get("last_sync_poll", 0) >= 30:
                remote = api.call(PREFIX + "/sync-jobs")["items"]
                jobs = db.get("sync_jobs", {})
                for job in remote:
                    prior = jobs.get(job["id"])
                    if prior and (prior["history_start"], prior["history_end"]) != (
                        job["history_start"],
                        job["history_end"],
                    ):
                        raise RuntimeError("INVALID_SERVER_RECEIPT")
                    jobs.setdefault(job["id"], {**job, "state": "scanning"})
                with db.db:
                    db.put("sync_jobs", jobs)
                    db.put("last_sync_poll", now)
            pending = db.due(now)
            if pending:
                key, body = pending
                receipt = api.call(PREFIX + "/batches", body)
                db.received(key, receipt)
                state["operation"] = "uploading"
            if now - db.get("last_job_poll", 0) >= 5:
                unsettled = db.unsettled()
                if unsettled:
                    key, receipt = unsettled
                    result = api.call(PREFIX + "/jobs/" + receipt["job_id"])
                    db.processed(key, result["state"])
                    if result["state"] == "processed":
                        db.save("processing_success_at", self.now().isoformat())
                jobs = db.get("sync_jobs", {})
                for job in jobs.values():
                    if job["state"] in ("complete", "cancelled"):
                        continue
                    cursor = db.get("force:" + job["id"])
                    if (
                        cursor
                        and stamp(cursor) >= stamp(job["history_end"])
                        and db.sync_ready(job["id"])
                    ):
                        server = api.call(PREFIX + "/sync-jobs/" + job["id"])
                        if server["state"] == "processed":
                            job["state"] = "complete"
                            job["finished_at"] = self.now().isoformat()
                            db.put("last_success", self.now().isoformat())
                        elif server["state"] in ("partial", "needs_review", "cancelled"):
                            job["state"] = (
                                "cancelled" if server["state"] == "cancelled" else "needs_attention"
                            )
                with db.db:
                    db.put("sync_jobs", jobs)
                    db.put("last_job_poll", now)
            counts = db.counts()
            if state["error"] is None:
                state["state"] = (
                    "queued"
                    if counts.get("pending")
                    else "processing"
                    if counts.get("received")
                    else "needs_attention"
                    if any(
                        counts.get(s) for s in ("partial", "needs_review", "paused", "cancelled")
                    )
                    else "syncing"
                    if stamp(db.get("capture_cursor", db.get("available_start")))
                    < self.now() - timedelta(minutes=3)
                    else "up_to_date"
                )
            if state["state"] == "up_to_date" and db.get("processing_success_at"):
                db.save("last_success", db.get("processing_success_at"))
            if now - db.get("last_heartbeat", 0) >= 60:
                api.call(
                    PREFIX + "/heartbeat",
                    {
                        "state": state["state"],
                        "queue_depth": counts.get("pending", 0),
                        "collector_version": VERSION,
                        "terminal_connected": state["terminal_connected"],
                        "operation": state["operation"],
                    },
                )
                db.save("last_heartbeat", now)
            with db.db:
                db.put("network_failures", 0)
                db.put("network_after", 0)
            if not any(
                j["state"] not in ("complete", "needs_attention", "cancelled")
                for j in db.get("sync_jobs", {}).values()
            ):
                db.compact()
        except Exception as exc:
            code = safe_error(exc)
            if isinstance(exc, ConnectionError):
                failures = db.get("network_failures", 0) + 1
                delay = backoff(failures, getattr(exc, "retry_after", 0))
                with db.db:
                    db.put("network_failures", failures)
                    db.put("network_after", now + delay)
                if pending:
                    db.retry(pending[0], code, delay, now)
                state.update(state="waiting_for_network", error=code)
            else:
                state.update(
                    state="authentication_expired"
                    if code == "SYNC_PAUSED_HTTP_401"
                    else "needs_attention",
                    error=code,
                )
                db.save("network_after", now + 300)
            with db.db:
                db.put("transport_state", state["state"])
                db.put("transport_error", state["error"])
        return {
            **state,
            "queue": db.counts(),
            "last_success": db.get("last_success"),
            "captured_until": db.get("capture_cursor"),
            "received_until": db.get("received_cursor"),
            "history_exposed": db.get("history_exposed"),
            "force_jobs": {key: job["state"] for key, job in db.get("sync_jobs", {}).items()},
        }
