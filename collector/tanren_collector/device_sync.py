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
        self.attempts = 0
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
        due = self.store.due()
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
        try:
            receipt = self.api().call(self.prefix + "/batches", {**body, "batch": raw})
        except RuntimeError as exc:
            if str(exc) != "SYNC_PAUSED_HTTP_409":
                raise
            permit = self.api().call(
                self.prefix + "/replays", {"epoch": body["epoch"], "batch": raw}
            )
            receipt = self.api().call(
                self.prefix + "/batches",
                {**body, "batch": raw, "recovery_id": permit["recovery_id"]},
            )
        self.store.received(key, receipt)
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
        try:
            self.deliver()
            self.poll_processing()
            self.poll_force()
            self.heartbeat(
                {
                    "state": "queued" if self.store.counts().get("pending") else "connected",
                    "queue_depth": self.store.counts().get("pending", 0),
                    "collector_version": VERSION,
                    "terminal_connected": self.role == "active" and not result["errors"],
                    "operation": "idle",
                }
            )
            self.attempts = 0
        except Exception as exc:
            self.attempts += 1
            self.network_after = self.monotonic() + backoff(
                self.attempts, getattr(exc, "retry_after", 0)
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
