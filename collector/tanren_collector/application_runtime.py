"""Unified nonblocking Tk/QML bridge, sharing the existing bounded spawn scheduler."""

import time
from dataclasses import replace

from . import diagnostics_log
from .application_state import AccountView, ApplicationState, DeviceView, MigrationView
from .application_workers import (
    account_turn,
    add_terminal_turn,
    device_turn,
    discovery_turn,
    registration_turn,
)
from .engine import safe_error
from .legacy_transition import transition_turn
from .runtime import Supervisor
from .storage import DPAPI, load_config


class ApplicationRuntime(Supervisor):
    def __init__(self, directory, max_workers=4, protector=None, clock=time.monotonic):
        super().__init__(directory, max_workers)
        self.protector = protector or DPAPI()
        self.clock = clock
        self.state = ApplicationState()
        self.control_task = None
        self.control_kind = None
        self.account_tasks = {}
        self.account_next = {}
        self.account_deadline = {}
        self.account_commands = {}
        self.device_stopped = False
        self.device_next = 0.0
        self.migration_next = 0.0
        self.registration_next = 0.0
        self.suspend_legacy = False
        self.migration_request = None
        self.migration_allowed = False
        try:
            migration = self.catalog().get("migration")
            if migration:
                self.state = replace(
                    self.state, migration=MigrationView(migration["binding_id"], migration["stage"])
                )
                self.migration_allowed = bool(migration.get("confirmed"))
        except Exception:
            self.state = replace(self.state, error="RUNTIME_CATALOG_REVIEW_REQUIRED")

    def catalog(self):
        path = self.directory / "runtime-v3.dpapi"
        # Read atomic replacement only; no credentials are stored in this catalog.
        return (
            load_config(path, self.protector)
            if path.exists()
            else {"accounts": {}, "terminals": {}, "legacy_paused": []}
        )

    def bindings(self):
        if self.suspend_legacy:
            return []
        paused = set(self.catalog().get("legacy_paused", []))
        return [key for key in super().bindings() if key not in paused]

    def submit_control(self, kind, function, *args):
        if self.closed:
            raise RuntimeError("WORKERS_CLOSED")
        if self.control_task:
            raise RuntimeError("RUNTIME_BUSY")
        self.state = replace(self.state, error=None)
        task = self.pool.submit(function, str(self.directory), *args)
        self.control_task, self.control_kind = task, kind
        return task

    def pair_device(self, code, name, *, repair=False, confirmed=False):
        if self.control_task:
            raise RuntimeError("RUNTIME_BUSY")
        if repair and not confirmed:
            raise ValueError("EXPLICIT_REPAIR_REQUIRED")
        self.device_stopped = False
        if repair:
            self.cancel_accounts()
        return self.submit_control(
            "device",
            device_turn,
            "repair" if repair else "begin",
            {"code": code, "name": name, "confirmed": confirmed},
        )

    def disconnect_device(self):
        if self.control_task:
            raise RuntimeError("RUNTIME_BUSY")
        self.device_stopped = True
        self.cancel_accounts()
        self.state = replace(self.state, device=DeviceView("locally_revoked"))
        return self.submit_control("device", device_turn, "disconnect")

    def discover_accounts(self):
        return self.submit_control("discover", discovery_turn)

    def add_terminal(self, path):
        return self.submit_control("discover", add_terminal_turn, path)

    def preview_account(self, key):
        return self.submit_control("preview", discovery_turn, key)

    def register_account(self, key, metadata=None, resume_id=None):
        if self.state.device.state != "paired":
            raise RuntimeError("DEVICE_NOT_PAIRED")
        return self.submit_control("registration", registration_turn, key, metadata, resume_id)

    def migrate(self, binding, *, drain=False, confirmed=False):
        if self.control_task:
            raise RuntimeError("RUNTIME_BUSY")
        if drain and not confirmed:
            raise ValueError("EXPLICIT_MIGRATION_REQUIRED")
        self.migration_allowed = drain and confirmed
        # Drain uses original transport only; wait for already-running legacy capture turns.
        self.suspend_legacy = True
        if self.pending:
            self.migration_request = (binding, drain, confirmed)
            self.state = replace(
                self.state, migration=MigrationView(binding, "waiting_for_legacy_turns")
            )
            return None
        return self.submit_control(
            "migration", transition_turn, binding, "drain" if drain else "inspect", confirmed
        )

    def account_action(self, binding, action):
        if action not in {"activate", "pause", "resume", "step", "sync"}:
            raise ValueError("INVALID_RUNTIME_ACTION")
        if self.closed or binding not in self.catalog()["accounts"]:
            raise RuntimeError("ACCOUNT_CONTEXT_MISSING")
        if binding in self.account_tasks or self.control_task:
            raise RuntimeError("BINDING_BUSY")
        task = self.pool.submit(account_turn, str(self.directory), binding, action)
        self.account_tasks[binding] = task
        return task

    def request_device_sync(self):
        for account in self.state.accounts:
            self.account_commands[account.binding_id] = "sync"
        self.account_next.clear()

    def set_device_pause(self, paused):
        for account in self.state.accounts:
            if account.stage not in {"awaiting_handover", "continuity_review"}:
                self.account_commands[account.binding_id] = "pause" if paused else "resume"
                self.account_next[account.binding_id] = 0

    def cancel_accounts(self):
        for task in self.account_tasks.values():
            self.pool.cancel(task)
        self.account_tasks.clear()
        self.account_deadline.clear()
        self.state = replace(
            self.state, accounts=tuple(replace(a, role="unknown") for a in self.state.accounts)
        )

    def resume(self):
        self.cancel_accounts()
        self.next.clear()
        self.account_next.clear()
        self.device_next = 0
        # Resume is not proof of Active; every next spawned turn revalidates server authority.

    def tick(self):
        if self.closed:
            return self.status
        now = self.clock()
        try:
            self.catalog()
        except Exception:
            self.cancel_accounts()
            self.state = replace(self.state, error="RUNTIME_CATALOG_REVIEW_REQUIRED")
            return self.status
        try:
            legacy = super().tick() or {}
        except OSError:
            legacy = self.status
        if self.control_task and self.control_task.done():
            task, kind = self.control_task, self.control_kind
            self.control_task = None
            try:
                value = task.result()
                diagnostics_log.write("control_done:" + kind)
                if kind == "device":
                    if self.device_stopped and value.state == "paired":
                        value = replace(value, state="locally_revoked")
                    self.state = replace(self.state, device=value)
                    if value.state != "paired":
                        self.cancel_accounts()
                elif kind == "registration":
                    self.state = replace(self.state, registration=value)
                elif kind == "migration":
                    self.state = replace(self.state, migration=value)
                    self.migration_next = now + 5
                    self.suspend_legacy = False
                elif kind == "discover":
                    self.state = replace(self.state, terminals=value)
                elif kind == "preview":
                    diagnostics_log.write(
                        "preview_applied",
                        f"matched={sum(t.key == value.key for t in self.state.terminals)}"
                        f" broker={bool(value.broker)}",
                    )
                    self.state = replace(
                        self.state,
                        terminals=tuple(
                            value if t.key == value.key else t for t in self.state.terminals
                        ),
                    )
            except Exception as exc:
                error = safe_error(exc)
                diagnostics_log.write("control_failed:" + kind, f"{error} {type(exc).__name__}")
                self.state = replace(self.state, error=error)
                if kind == "device":
                    self.state = replace(self.state, device=replace(self.state.device, error=error))
                elif kind == "migration":
                    self.suspend_legacy = False
                    current = self.state.migration
                    self.state = replace(
                        self.state,
                        migration=replace(current, stage="blocked", error=error)
                        if current
                        else MigrationView("", "blocked", error=error),
                    )
                elif kind == "registration":
                    self.registration_next = now + 30
                    self.state = replace(
                        self.state, registration=replace(self.state.registration, error=error)
                    )
            self.device_next = now + max(
                self.state.device.retry_after_seconds,
                (
                    5
                    if self.state.device.state in {"claiming", "awaiting_browser_confirmation"}
                    else 30
                ),
            )
        for key, task in list(self.pending.items()):
            if task.done() and key not in self.bindings():
                self.pending.pop(key)
                try:
                    self.status[key] = task.result()
                except Exception as exc:
                    self.status[key] = {"state": "error", "error": safe_error(exc)}
        if self.migration_request and not self.pending and not self.control_task:
            binding, drain, confirmed = self.migration_request
            self.migration_request = None
            self.migrate(binding, drain=drain, confirmed=confirmed)
        accounts = {a.binding_id: a for a in self.state.accounts}
        for binding, task in list(self.account_tasks.items()):
            if not task.done():
                continue
            self.account_tasks.pop(binding)
            try:
                view, remaining = task.result()
                accounts[binding] = view
                self.account_deadline[binding] = now + remaining
            except Exception as exc:
                if binding not in accounts:
                    entry = self.catalog()["accounts"][binding]
                    accounts[binding] = AccountView(
                        binding, entry["account_id"], entry["terminal_key"]
                    )
                if binding in accounts:
                    accounts[binding] = replace(
                        accounts[binding], role="unknown", stage="waiting", error=safe_error(exc)
                    )
            self.account_next[binding] = (
                now + accounts[binding].retry_after_seconds if binding in accounts else now + 30
            )
        for binding in self.account_commands:
            self.account_next[binding] = 0
        for binding, view in accounts.items():
            if view.role == "active" and now >= self.account_deadline.get(binding, 0):
                accounts[binding] = replace(view, role="unknown")
        self.state = replace(self.state, accounts=tuple(accounts.values()))
        if not self.control_task and now >= self.device_next:
            self.submit_control("device", device_turn)
        if self.state.device.state == "paired":
            # Recover pending registration/config creation after a crash before scheduling accounts.
            registration_path = self.directory / "registration-v3" / "registrations.dpapi"
            if registration_path.exists() and not self.control_task:
                registration = load_config(registration_path, self.protector)
                if now >= self.registration_next and (
                    registration.get("registration_pending")
                    or registration.get("runtime_registration")
                ):
                    self.submit_control("registration", registration_turn)
            if (
                self.state.migration
                and self.migration_allowed
                and self.state.migration.stage == "draining"
                and now >= self.migration_next
                and not self.control_task
            ):
                self.migrate(self.state.migration.binding_id, drain=True, confirmed=True)
            if not self.control_task:
                for binding in self.catalog()["accounts"]:
                    if binding not in self.account_tasks and now >= self.account_next.get(
                        binding, 0
                    ):
                        self.account_tasks[binding] = self.pool.submit(
                            account_turn,
                            str(self.directory),
                            binding,
                            self.account_commands.pop(binding, "step"),
                        )
        return legacy

    def diagnostic_statuses(self):
        return list(self.status.values()) + [
            {
                "state": "needs_attention" if a.error else "processing",
                "error": a.error,
                "queue": {"pending": a.pending, "received": a.processing, "needs_review": a.review},
            }
            for a in self.state.accounts
        ]

    def close(self):
        if self.closed:
            return
        self.cancel_accounts()
        if self.control_task:
            self.pool.cancel(self.control_task)
            self.control_task = None
        try:
            # Best effort bounded release; unreachable shutdown remains server-TTL fenced.
            if self.state.device.state == "paired":
                tasks = [
                    self.pool.submit(account_turn, str(self.directory), key, "release")
                    for key in self.catalog()["accounts"]
                ]
                deadline = time.monotonic() + 1.0
                while tasks and time.monotonic() < deadline:
                    self.pool.tick()
                    tasks = [t for t in tasks if not t.done()]
                    time.sleep(0.01)
        except Exception:
            self.state = replace(self.state, error="SHUTDOWN_RELEASE_UNCONFIRMED")
        finally:
            super().close()  # A corrupt catalog must never leave child processes running.
