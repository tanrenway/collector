"""Opt-in per-binding v3 transport; no Tk protocol switch or new financial processing."""

import re
import time
import uuid
from datetime import UTC, datetime

from .charts import ChartTurn
from .device_pairing import PREFIX, DeviceApi
from .engine import Engine, backoff, safe_error
from .protocol import VERSION

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
ROUTE = re.compile(
    re.escape(PREFIX)
    + "/accounts/"
    + UUID
    + r"/(?:lease|batches|replays|heartbeat|sync-jobs|chart-jobs|(?:jobs|sync-jobs)/"
    + UUID
    + "|chart-jobs/"
    + UUID
    + "/(?:ohlc|failure))"
)


# Server codes that reject THIS batch's content/provenance (FastAPI ``detail``); retrying the
# same immutable bytes can never succeed. Everything else (auth, revoked grant, frozen account,
# lease/handover state, unknown codes) is account-level: keep strict order and retry later.
BATCH_REJECTED = frozenset(
    {
        "INVALID_INPUT",
        "BODY_TOO_LARGE",
        "MT5_BATCH_KEY_CONFLICT",
        "CAPTURE_FRAGMENT_CONFLICT",
        # Same batch key held under other provenance. The server compares provenance only,
        # never content, so its copy is no proof of these facts: keep them (quarantine).
        "CAPTURE_REQUEST_CONFLICT",
        "SYNC_WINDOW_MISMATCH",
        "SYNC_JOB_NOT_FOUND",
    }
)
PAUSED = re.compile(r"SYNC_PAUSED_HTTP_([0-9]{3})")
SERVER_ERROR = re.compile(r"RETRY_HTTP_(5[0-9]{2})")
EXHAUSTED_AFTER = 86400  # Seconds of 5xx for one batch while the heartbeat still succeeds.
EXHAUSTED_ATTEMPTS = 10


def rejection(exc):
    """Quarantine reason for a definitive batch-specific HTTP answer, else None.

    A bare 400/409/422 (no API code, e.g. from an intermediary) is never enough to dead-letter
    facts; a 413 is, because the same bytes can never fit.
    """
    if isinstance(exc, ConnectionError):
        return None  # Timeouts, network loss, 429 and 5xx are transient.
    match = PAUSED.fullmatch(str(exc))
    if not match:
        return None
    status, code = int(match.group(1)), getattr(exc, "server_code", None)
    if code in BATCH_REJECTED or status == 413:
        return "HTTP_" + str(status) + (":" + code if code else "")
    return None


class SyncApi(DeviceApi):
    def allowed_path(self, path):
        return super().allowed_path(path) or bool(ROUTE.fullmatch(path))


class AccountSync:
    """One context/store/terminal per binding; queues survive expiry and missing terminals.

    v3 transport metadata lives in protected Store.metadata; immutable v2 payload/checkpoints stay
    unchanged. Legacy pending rows without v3 provenance are paused for explicit handover review.
    Methods are scheduling turns intended for existing spawn workers, never the GUI thread.
    """

    def __init__(
        self,
        store,
        device_store,
        binding_id,
        terminal,
        api_factory=SyncApi,
        monotonic=time.monotonic,
    ):
        self.store, self.device = store, device_store
        self.binding = str(uuid.UUID(binding_id))
        self.terminal, self.factory, self.monotonic = terminal, api_factory, monotonic
        self.prefix = PREFIX + "/accounts/" + self.binding
        self.deadline = 0.0
        self.renew_at = 0.0
        self.epoch = None
        self.role = "unknown"  # Never restore Active from local disk after a restart.
        self.network_after = 0.0
        self.clock = time.time  # Wall clock for durable per-batch backoff in SQLite.
        self.exhausted = None
        self.chart_after = 0.0
        config = store.get("config")
        if not config or config.get("binding_id") != self.binding:
            raise RuntimeError("BINDING_ACCOUNT_IMMUTABLE")
        self.engine = Engine(store, terminal)

    def api(self):
        state = self.device.get()
        if state.get("state") != "paired":
            raise RuntimeError("DEVICE_NOT_PAIRED")
        return self.factory(state["token"])

    def lease(self, action=None):
        action = action or (
            "renew" if self.role == "active" and self.monotonic() < self.deadline else "acquire"
        )
        pending = self.store.get("v3_lease_request")
        replayed = pending is not None
        if pending is None:
            pending = {
                "request_id": str(uuid.uuid4()),
                "action": action,
                "epoch": self.epoch if action != "acquire" else None,
            }
            self.store.save("v3_lease_request", pending)
        started = self.monotonic()
        try:
            response = self.api().call(self.prefix + "/lease", pending)
        except Exception as exc:
            if str(exc) in {
                "SYNC_PAUSED_HTTP_" + str(n) for n in (400, 401, 403, 404, 409, 410, 422)
            }:
                self.store.save("v3_lease_request", None)
            self.role = "unknown"
            self.deadline = 0
            raise
        # A replayed renewal/acquire receipt is HISTORICAL. A lost ACK always requires a fresh
        # request before capture. Mark it consumed before any next request; restart stays Unknown.
        self.store.save("v3_lease_request", None)
        self.epoch = response.get("epoch", self.epoch)
        self.role = "unknown" if replayed and response["role"] == "active" else response["role"]
        ttl = 0
        if self.role == "active":
            ttl = (
                datetime.fromisoformat(response["expires_at"])
                - datetime.fromisoformat(response["server_time"])
            ).total_seconds()
        self.deadline = started + max(0, min(ttl, 120) - 10)
        self.renew_at = started + 30
        return response

    def refresh(self):
        # Two requests after restart/uncertain delivery: first resolves persisted ACK, second
        # obtains a fresh server-clock lease decision. Cached response alone never authorizes scan.
        uncertain = self.role == "unknown" or bool(self.store.get("v3_lease_request"))
        response = self.lease()
        if uncertain and response["role"] == "active":
            self.lease("renew")

    def capture(self):
        if self.role != "active" or self.monotonic() >= self.deadline:
            raise RuntimeError("CAPTURE_LEASE_UNCERTAIN")
        # Reuse the existing bounded scan/cursor logic. Transactionally attach provenance to
        # each fragment in the SAME capture commit, without modifying the RawBatch envelope.
        original = self.store.capture

        def persist(window_id, bodies, cursor_key, end):
            if self.monotonic() >= self.deadline:
                raise RuntimeError("CAPTURE_LEASE_UNCERTAIN")
            original(
                window_id,
                bodies,
                cursor_key,
                end,
                provenance={
                    "binding_id": self.binding,
                    "epoch": self.epoch,
                    "window_id": window_id,
                    "fragment_count": len(bodies),
                },
            )
            self.store.save("last_observed_at", datetime.now(UTC).isoformat())

        self.store.capture = persist
        try:
            self.engine.capture(self.store.get("config"))
        finally:
            self.store.capture = original

    def deliver(self):
        now = self.clock()
        due = self.store.next_delivery(now)
        if not due:
            return None
        key, raw = due
        provenance = self.store.get("v3_batch:" + key)
        if not provenance or provenance["binding_id"] != self.binding:
            raise RuntimeError("LEGACY_QUEUE_HANDOVER_REQUIRED")
        body = {
            k: provenance[k] for k in ("epoch", "window_id", "fragment_index", "fragment_count")
        }
        # Already accepted packets may be retried without a live capture lease. Unaccepted stale
        # packets use an explicit server-issued recovery permit; never rewrite body IDs/cursors.
        failures = []
        try:
            try:
                receipt = self.api().call(self.prefix + "/batches", {**body, "batch": raw})
            except RuntimeError as exc:
                if str(exc) != "SYNC_PAUSED_HTTP_409":
                    raise
                failures.append(exc)
                permit = self.api().call(
                    self.prefix + "/replays", {"epoch": body["epoch"], "batch": raw}
                )
                receipt = self.api().call(
                    self.prefix + "/batches",
                    {**body, "batch": raw, "recovery_id": permit["recovery_id"]},
                )
            self.store.received(key, receipt)
        except Exception as exc:
            verdict = rejection(exc)
            if verdict is None and failures and str(exc) == "SYNC_PAUSED_HTTP_409":
                # The replay itself was refused with a definitive 409 (e.g. recovery denied
                # while the lease is current): the first upload's batch-specific code decides.
                # Never after auth/grant/network answers or a malformed receipt.
                if getattr(exc, "server_code", None) == "CAPTURE_RECOVERY_DENIED":
                    verdict = rejection(failures[0])
            if verdict:
                # Dead-letter only this batch: its facts stay on disk, later batches continue
                # (later fragments of the same window are held, see Store.next_delivery).
                self.store.quarantine(key, verdict, now)
                return {"batch_id": key, "delivery_status": "quarantined", "reason": verdict}
            attempts = self.store.attempts(key) + 1
            delay = backoff(attempts, getattr(exc, "retry_after", 0))
            server = SERVER_ERROR.fullmatch(str(exc))
            self.store.retry(key, safe_error(exc), delay, now, server_error=bool(server))
            since, streak = self.store.server_streak(key) if server else (None, 0)
            if since is not None and now - since > EXHAUSTED_AFTER and streak >= EXHAUSTED_ATTEMPTS:
                # Quarantined by step() only if the heartbeat proves the server is reachable.
                self.exhausted = (key, "RETRY_EXHAUSTED:HTTP_" + server.group(1), now)
            raise
        return receipt

    def poll_processing(self):
        row = self.store.unsettled()
        if row:
            key, receipt = row
            result = self.api().call(self.prefix + "/jobs/" + receipt["job_id"])
            self.store.processed(key, result["state"])
            if result["state"] == "processed" and result.get("updated_at"):
                try:
                    stamp = datetime.fromisoformat(str(result["updated_at"]).replace("Z", "+00:00"))
                except ValueError:
                    stamp = None  # Optional presentation metadata cannot fail delivery/processing.
                if stamp is not None and stamp.tzinfo is not None:
                    prior = self.store.get("last_processed_at")
                    if prior is None or stamp > datetime.fromisoformat(prior):
                        self.store.save("last_processed_at", stamp.astimezone(UTC).isoformat())
            return result
        return None

    def force_jobs(self):
        remote = self.api().call(self.prefix + "/sync-jobs")["items"]
        jobs = self.store.get("sync_jobs", {})
        for job in remote:
            key = job["id"]
            if self.role == "active" and job.get("epoch") == self.epoch:
                old = jobs.get(key)
                if old is None or old.get("epoch") != self.epoch:
                    # New epoch must rescan full range; old capture cursor cannot certify it.
                    self.store.save("force:" + key, job["history_start"])
                jobs[key] = {
                    **job,
                    "state": "needs_attention"
                    if job["state"] in {"needs_review", "partial"}
                    else "requested",
                }
        self.store.save("sync_jobs", jobs)
        return remote

    def poll_force(self):
        jobs = self.store.get("sync_jobs", {})
        for key, job in jobs.items():
            if job["state"] in {"complete", "cancelled"}:
                continue
            result = self.api().call(self.prefix + "/sync-jobs/" + key)
            job["server_state"] = result["state"]
            if result["state"] == "processed" and result.get("epoch") == job.get("epoch"):
                cursor = self.store.get("force:" + key)
                if (
                    cursor
                    and datetime.fromisoformat(cursor) >= datetime.fromisoformat(job["history_end"])
                    and self.store.sync_ready(key)
                ):
                    job["state"] = "complete"
            elif result["state"] in {"cancelled", "needs_review", "partial"}:
                job["state"] = "cancelled" if result["state"] == "cancelled" else "needs_attention"
        self.store.save("sync_jobs", jobs)

    def heartbeat(self, data):
        return self.api().call(self.prefix + "/heartbeat", data)

    def step(self):
        # Delivery is independent of a terminal. A bad/absent terminal never discards pending data.
        if self.role == "active" and self.monotonic() >= self.deadline:
            self.role = "unknown"
        result = {"role": self.role, "errors": []}
        if self.monotonic() < self.network_after:
            return {**result, "queue": self.store.counts()}
        try:
            if self.role == "unknown" or self.monotonic() >= self.renew_at:
                self.refresh()
            if self.role == "active":
                self.force_jobs()
                self.capture()
        except Exception as exc:
            code = safe_error(exc)
            result["errors"].append(code)
            if getattr(exc, "retry_after", 0):
                self.network_after = max(
                    self.network_after, self.monotonic() + min(86400, exc.retry_after)
                )
            if code.startswith(("TERMINAL_", "CHILD_", "MT5_")) and self.role == "active":
                try:
                    self.lease("release")
                except Exception:
                    self.role = "unknown"
        capture_errors = list(result["errors"])
        self.exhausted = None
        # Delivery, processing polls and the heartbeat are independent: one failing or poisoned
        # batch must never silence liveness or later uploads.
        offline = False
        try:
            outcome = self.deliver()
            if outcome and outcome.get("delivery_status") == "quarantined":
                result["quarantined"] = outcome["reason"]
        except Exception as exc:
            result["errors"].append(safe_error(exc))
            # No HTTP answer at all: skip the polls, but still probe liveness with a heartbeat.
            offline = isinstance(exc, ConnectionError) and not str(exc).startswith("RETRY_HTTP_")
        for poll in () if offline else (self.poll_processing, self.poll_force):
            try:
                poll()
            except Exception as exc:
                result["errors"].append(safe_error(exc))
                if isinstance(exc, ConnectionError):
                    break
        counts = self.store.counts()
        try:
            self.heartbeat(
                {
                    "state": "queued"
                    if counts.get("pending")
                    else "needs_attention"
                    if counts.get("quarantined")
                    else "connected",
                    "queue_depth": counts.get("pending", 0),
                    "collector_version": VERSION,
                    "terminal_connected": self.role == "active" and not capture_errors,
                    "operation": "idle",
                }
            )
            if self.store.get("v3_network_failures", 0):
                self.store.save("v3_network_failures", 0)
            if self.exhausted:
                # Server reachable, yet this batch kept failing with 5xx for over a day: a
                # deterministic server-side rejection. Dead-letter it (re-queueable).
                key, reason, now = self.exhausted
                self.store.quarantine(key, reason, now, attempted=False)
                result["quarantined"] = reason
        except Exception as exc:
            # Only a failed liveness call backs off the whole turn; per-batch backoff is durable.
            failures = self.store.get("v3_network_failures", 0) + 1
            self.store.save("v3_network_failures", failures)
            self.network_after = self.monotonic() + backoff(
                failures, getattr(exc, "retry_after", 0)
            )
            result["errors"].append(safe_error(exc))
        self.charts(result)
        result.update(role=self.role, queue=self.store.counts())
        return result

    def charts(self, result):
        """Chart jobs never delay or fail trade-fact delivery."""
        if self.role != "active" or self.monotonic() < self.chart_after:
            return
        self.chart_after = self.monotonic() + 60
        try:
            result["charts"] = ChartTurn(self.api(), self.prefix, self.terminal).run()
        except Exception as exc:
            result["chart_error"] = safe_error(exc)
