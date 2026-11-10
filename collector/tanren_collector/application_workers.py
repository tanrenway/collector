"""Spawn entry points. Secret/native state remains inside the child, DTOs cross to GUI."""

import time
import uuid
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from .account_registration import (
    AccountRegistration,
    RegistrationApi,
    RegistrationState,
    discover_active,
)
from .application_state import AccountView, DeviceView, ForceView, RegistrationView, TerminalView
from .device_pairing import PREFIX, DeviceStore, PairingSession
from .device_sync import AccountSync, SyncApi
from .discovery import candidates, discover
from .engine import safe_error
from .runtime_store import Catalog, DeviceReader, account_path, terminal_key
from .storage import DPAPI
from .terminal_v2 import RawTerminal
from .v2_store import Store
from .windows import terminal_lock


def device_turn(root, action="poll", payload=None, protector=None, factory=None):
    protector = protector or DPAPI()
    with closing(DeviceStore(Path(root).parent / "device-v3", protector)) as store:
        session = PairingSession(store, **({"api_factory": factory} if factory else {}))
        if action == "begin":
            session.begin(payload["code"], payload["name"])
        elif action == "repair":
            if payload.get("confirmed") is not True:
                raise ValueError("EXPLICIT_REPAIR_REQUIRED")
            import shutil

            archive = store.path.parent / "previous-devices"
            archive.mkdir(exist_ok=True)
            if store.path.exists():
                shutil.copyfile(store.path, archive / (str(uuid.uuid4()) + ".dpapi"))
            session.revoke_local()
            session.begin(payload["code"], payload["name"], replace_pending=True)
        elif action == "disconnect":
            session.revoke_local()
        try:
            value = session.advance() if store.get() else {"state": "disconnected"}
        except Exception as exc:
            return DeviceView(
                state=store.get().get("state", "error"),
                error=safe_error(exc),
                retry_after_seconds=min(86400, max(30, int(getattr(exc, "retry_after", 0)))),
            )
        state = value.get("state", store.get().get("state", "disconnected"))
        if state not in DeviceView.__annotations__["state"].__args__:
            state = "error"
        return DeviceView(state=state, verification_phrase=value.get("verification_phrase"))


def add_terminal_turn(root, path, protector=None):
    """A terminal the user picked by hand; only an existing local terminal64.exe is accepted."""
    if not candidates(installed=[path]):
        raise ValueError("INVALID_TERMINAL_PATH")
    return discovery_turn(root, protector=protector, manual=path)


def discovery_turn(root, selected=None, protector=None, terminal_factory=RawTerminal, manual=None):
    protector = protector or DPAPI()
    if selected is None:
        items = discover()
        with closing(Catalog(root, protector)) as store:
            state = store.get()
            # Terminals found or picked earlier stay available if they still exist on disk.
            known = [entry["path"] for entry in state["terminals"].values()]
            found = {terminal_key(item["path"]) for item in items}
            for item in candidates(installed=[*known, *([manual] if manual else [])]):
                if terminal_key(item["path"]) not in found:
                    items.append(item)
            # A temporary discovery miss must not drop old associations or queues.
            for item in items:
                state["terminals"][terminal_key(item["path"])] = {
                    "path": item["path"],
                    "running": item["running"],
                }
            store.save(state)
        return tuple(
            TerminalView(
                terminal_key(i["path"]),
                Path(i["path"]).parent.name or "MetaTrader 5",
                i["running"],
                path=i["path"],
            )
            for i in items
        )
    with closing(Catalog(root, protector)) as store:
        item = store.get()["terminals"][selected]
    lock = terminal_lock(root, item["path"])
    try:
        details = {}
        identity = discover_active(item["path"], terminal_factory, details)
    finally:
        lock.close()
    with closing(Catalog(root, protector)) as store:
        state = store.get()
        state["terminals"][selected]["preview"] = identity
        store.save(state)
    return TerminalView(
        selected,
        identity["broker"] + " · " + identity["server"],
        item["running"],
        identity["broker"],
        identity["server"],
        identity["login"][-4:],
        path=item["path"],
        currency=identity.get("currency"),
        starting_balance=details.get("starting_balance"),
    )


def _no_local_handover(root, result, identity, protector):
    """True only when this computer's inventory proves there is no earlier queue to deliver."""
    from .legacy_transition import inventory

    try:
        items = inventory(root, result["account_id"], identity, protector)
    except Exception:  # noqa: BLE001 - unknown stays with the explicit handover flow.
        return False
    return not any(i.pending or i.processing or i.review for i in items)


def _admit_existing(root, config, device, protector, store):
    """Start an account registered before capture admission existed, at most once an hour."""
    if time.time() < (store.get("admission_next") or 0):
        return False
    store.put("admission_next", time.time() + 3600)
    body = {
        "request_id": str(uuid.uuid4()),
        "identity": config["identity"],
        "selected": True,
        "existing_account_id": config["account_id"],
        "metadata": None,
        "resume_id": None,
    }
    try:
        result = RegistrationApi(device.get()["token"]).call(PREFIX + "/accounts/register", body)
    except Exception:  # noqa: BLE001 - the explicit handover remains available.
        return False
    if (
        result.get("state") != "linked"
        or result.get("capture_admitted") is not True
        or not _no_local_handover(root, result, config["identity"], protector)
    ):
        return False
    config.update(enabled=True, admitted=True)
    store.save("config", config)
    with closing(Catalog(root, protector)) as catalog:
        contents = catalog.get()
        contents["accounts"][result["binding_id"]]["enabled"] = True
        catalog.save(contents)
    return True


def _start_capture(root, binding, protector):
    with closing(Store(account_path(root, binding), protector)) as queue:
        config = queue.get("config")
        config.update(enabled=True, admitted=True)
        queue.save("config", config)
    with closing(Catalog(root, protector)) as catalog:
        contents = catalog.get()
        contents["accounts"][binding]["enabled"] = True
        catalog.save(contents)


def registration_turn(
    root,
    selected=None,
    metadata=None,
    resume_id=None,
    protector=None,
    factory=RegistrationApi,
    terminal_factory=RawTerminal,
):
    protector = protector or DPAPI()
    device = DeviceReader(root, protector)
    if device.get().get("state") != "paired":
        raise RuntimeError("DEVICE_NOT_PAIRED")
    with closing(RegistrationState(Path(root) / "registration-v3", protector)) as store:
        registration = AccountRegistration(device, store, factory)
        state = store.get()
        recovery = state.get("runtime_registration")
        if not state.get("registration_pending") and not recovery:
            if selected is None:
                last = state.get("runtime_last", {})
                return (
                    RegistrationView(**{**last, "required": tuple(last.get("required", ()))})
                    if last
                    else RegistrationView()
                )
            with closing(Catalog(root, protector)) as catalog:
                terminal = catalog.get()["terminals"][selected]
            expected = terminal.get("preview")
            if not expected:
                raise RuntimeError("ACCOUNT_PREVIEW_REQUIRED")
            association = {
                "key": selected,
                "path": terminal["path"],
                "device_id": device.get()["device_id"],
            }
            lock = terminal_lock(root, terminal["path"])
            try:

                def checked(path, _):
                    return terminal_factory(path, expected)

                registration.prepare(
                    terminal["path"],
                    selected=True,
                    metadata=metadata,
                    resume_id=resume_id,
                    terminal_factory=checked,
                    context=association,
                )
            finally:
                lock.close()
            state = store.get()
        recovery = state.get("runtime_registration")
        if not recovery:
            raise RuntimeError("REGISTRATION_CONTEXT_REVIEW_REQUIRED")
        pending = recovery["request"]
        try:
            result = (
                registration.deliver()
                if state.get("registration_pending")
                else state["registration_results"][pending["request_id"]]
            )
        except RuntimeError as exc:
            if str(exc) == "SYNC_PAUSED_HTTP_422":
                rejected = store.get()
                rejected.setdefault("runtime_rejected", {})[pending["request_id"]] = rejected.pop(
                    "registration_pending"
                )
                rejected.pop("runtime_registration", None)
                store.save(rejected)  # Definitive validation rejection; no server mutation.
            raise
        if result["state"] in {"created", "linked"}:
            association = recovery["association"]
            with closing(Store(account_path(root, result["binding_id"]), protector)) as queue:
                config = queue.get("config")
                proposed = {
                    "binding_id": result["binding_id"],
                    "account_id": result["account_id"],
                    "identity": pending["identity"],
                    "terminal": association["path"],
                    "device_id": association["device_id"],
                    "enabled": False,
                    "display_name": pending.get("metadata", {}).get("name")
                    if result["state"] == "created" and pending.get("metadata")
                    else None,
                }
                if config and any(
                    config[k] != proposed[k]
                    for k in ("binding_id", "account_id", "identity", "device_id")
                ):
                    raise RuntimeError("REGISTERED_IDENTITY_IMMUTABLE")
                if not config:
                    queue.save("config", proposed)
            with closing(Catalog(root, protector)) as catalog:
                contents = catalog.get()
                old = contents["accounts"].get(result["binding_id"])
                entry = {
                    "account_id": result["account_id"],
                    "terminal_key": association["key"],
                    "device_id": association["device_id"],
                    "enabled": False,
                }
                if (
                    old
                    and old != entry
                    and any(old[k] != entry[k] for k in ("account_id", "terminal_key", "device_id"))
                ):
                    raise RuntimeError("REGISTERED_IDENTITY_IMMUTABLE")
                contents["accounts"].setdefault(result["binding_id"], entry)
                catalog.save(contents)
            if result.get("capture_admitted") is True and _no_local_handover(
                root, result, pending["identity"], protector
            ):
                _start_capture(root, result["binding_id"], protector)
            with closing(Catalog(root, protector)) as catalog:
                contents = catalog.get()
                catalog.save(contents)
        last = {
            "terminal_key": recovery["association"]["key"],
            "state": result["state"],
            "request_id": pending["request_id"],
            "binding_id": result.get("binding_id"),
            "required": tuple(result.get("required", ())),
        }
        final = store.get()
        final.pop("runtime_registration", None)
        final["runtime_last"] = last
        store.save(final)
        return RegistrationView(**last)


class LazyTerminal:
    """Delivery/standby never imports MT5 or takes a terminal lock."""

    def __init__(self, root, path, identity, factory=RawTerminal):
        self.root, self.path, self.identity_value, self.factory = root, path, identity, factory
        self.terminal = self.lock = None

    def connect(self):
        try:
            self.lock = terminal_lock(self.root, self.path)
        except OSError:
            raise RuntimeError("TERMINAL_BUSY") from None
        try:
            self.terminal = self.factory(self.path, self.identity_value)
            self.terminal.connect()
        except Exception:
            self.close()
            raise

    def read(self, start, end):
        try:
            return self.terminal.read(start, end)
        finally:
            self.close()  # Delivery/status never retain a terminal lock or native connection.

    def __getattr__(self, name):
        if self.terminal is None:
            raise RuntimeError("TERMINAL_UNAVAILABLE")
        return getattr(self.terminal, name)

    def close(self):
        try:
            if self.terminal:
                self.terminal.close()
        finally:
            self.terminal = None
            if self.lock:
                self.lock.close()
                self.lock = None


def account_turn(
    root, binding, action="step", protector=None, factory=SyncApi, terminal_factory=RawTerminal
):
    protector = protector or DPAPI()
    device = DeviceReader(root, protector)
    with closing(Store(account_path(root, binding), protector)) as store:
        config = store.get("config")
        if not config:
            raise RuntimeError("ACCOUNT_CONTEXT_MISSING")
        view = AccountView(
            binding,
            config["account_id"],
            terminal_key(config["terminal"]),
            name=config.get("display_name"),
            login_suffix=str(config["identity"].get("login", ""))[-4:] or None,
            broker=config["identity"].get("broker"),
            server=config["identity"].get("server"),
            last_observed_at=store.get("last_observed_at"),
            last_processed_at=store.get("last_processed_at"),
        )
        if device.get().get("device_id") != config["device_id"]:
            return replace(
                view, stage="continuity_review", error="DEVICE_CONTINUITY_REVIEW_REQUIRED"
            ), 0.0
        if device.get().get("state") != "paired":
            return replace(view, stage="authorization_required", error="DEVICE_NOT_PAIRED"), 0.0
        terminal = LazyTerminal(root, config["terminal"], config["identity"], terminal_factory)
        sync = AccountSync(store, device, binding, terminal, factory)
        try:
            if action in {"pause", "release"}:
                if action == "pause":
                    config["enabled"] = False
                    store.save("config", config)
                try:
                    sync.refresh()
                    if sync.role == "active":
                        sync.lease("release")
                except Exception as exc:
                    return replace(view, stage="paused", error=safe_error(exc)), 0.0
                return replace(view, stage="paused"), 0.0
            if action == "activate":
                from .legacy_transition import inventory

                with closing(Catalog(root, protector)) as catalog:
                    migration = catalog.get().get("migration", {})
                if (
                    migration.get("binding_id") != binding
                    or migration.get("stage") != "awaiting_browser_confirmation"
                    or not migration.get("confirmed")
                ):
                    raise RuntimeError("EXPLICIT_MIGRATION_REQUIRED")
                items = inventory(root, config["account_id"], config["identity"], protector)
                if any(i.pending or i.processing or i.review for i in items):
                    raise RuntimeError("LEGACY_QUEUE_NOT_DRAINED")
                sync.refresh()  # Browser admission must already have committed; never bypass it.
                config["enabled"] = True
                config["admitted"] = True
                store.save("config", config)
            elif action == "resume":
                if not config.get("admitted"):
                    raise RuntimeError("EXPLICIT_MIGRATION_REQUIRED")
                sync.refresh()
                config["enabled"] = True
                store.save("config", config)
            elif not config.get("enabled") and not (
                not config.get("admitted")
                and factory is SyncApi
                and _admit_existing(root, config, device, protector, store)
            ):
                return replace(
                    view, stage="paused" if config.get("admitted") else "awaiting_handover"
                ), 0.0
            if action == "sync":
                store.save("last_capture", 0)
            result = sync.step()
            store.compact()
            counts = store.counts()
            errors = result.get("errors", [])
            error = errors[0] if errors else None
            role = (
                result["role"]
                if sync.deadline > time.monotonic() or result["role"] == "standby"
                else "unknown"
            )
            stage = (
                "access_denied"
                if error in {"SYNC_PAUSED_HTTP_401", "SYNC_PAUSED_HTTP_403", "SYNC_PAUSED_HTTP_404"}
                else "waiting"
                if error
                else "syncing"
                if counts.get("pending")
                else "processing"
                if counts.get("received")
                else role
            )
            force = tuple(
                ForceView(k, j.get("server_state", j["state"]))
                for k, j in store.get("sync_jobs", {}).items()
            )
            return replace(
                view,
                stage=stage,
                role=role,
                pending=counts.get("pending", 0),
                processing=counts.get("received", 0),
                review=sum(counts.get(k, 0) for k in ("partial", "needs_review", "paused")),
                force=force,
                last_observed_at=store.get("last_observed_at"),
                last_processed_at=store.get("last_processed_at"),
                retry_after_seconds=max(
                    30, min(86400, int(sync.network_after - time.monotonic() + 1))
                ),
                error=error,
            ), max(0, sync.deadline - time.monotonic())
        finally:
            terminal.close()
