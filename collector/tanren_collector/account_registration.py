"""Explicit selected-terminal read and registration, independent of synchronization queues."""

import uuid
from pathlib import Path

from .build_profile import check_storage_path
from .device_pairing import PREFIX, DeviceApi
from .discovery import discover
from .processes import SpawnPool
from .storage import load_config, save_config
from .terminal_v2 import RawTerminal
from .windows import FileLock


class RegistrationApi(DeviceApi):
    def allowed_path(self, path):
        return super().allowed_path(path) or path == PREFIX + "/accounts/register"


def discover_active(path, terminal_factory=RawTerminal, details=None):
    selected = Path(path)
    if (
        not selected.is_absolute()
        or selected.name.lower() != "terminal64.exe"
        or not selected.is_file()
        or str(selected).startswith("\\\\")
    ):
        raise ValueError("INVALID_TERMINAL_PATH")
    terminal = terminal_factory(str(selected), None)
    try:
        terminal.connect()
        identity = terminal.identity()
        if identity != terminal.identity():
            raise RuntimeError("TERMINAL_IDENTITY_MISMATCH")
        if details is not None:
            try:  # A convenience for the form: it must never block reading the account.
                terminal.expected = identity  # History is read only for the account just verified.
                details["starting_balance"] = terminal.starting_balance()
            except Exception:  # noqa: BLE001 - unknown stays unknown, whatever the cause.
                details["starting_balance"] = None
        return identity
    finally:
        terminal.close()


class AccountRegistration:
    def __init__(self, device_store, account_store, api_factory=RegistrationApi):
        self.device_store, self.store, self.factory = device_store, account_store, api_factory

    def prepare(
        self,
        path,
        *,
        selected,
        metadata=None,
        existing_account_id=None,
        terminal_factory=RawTerminal,
        resume_id=None,
        context=None,
    ):
        if selected is not True:
            raise ValueError("EXPLICIT_ACCOUNT_SELECTION_REQUIRED")
        state = self.store.get()
        if self.device_store.get().get("state") != "paired":
            raise RuntimeError("DEVICE_NOT_PAIRED")
        if state.get("registration_pending"):
            raise RuntimeError("REGISTRATION_PENDING")
        identity = discover_active(path, terminal_factory)
        body = {
            "request_id": str(uuid.uuid4()),
            "identity": identity,
            "selected": True,
            "metadata": metadata,
            "existing_account_id": existing_account_id,
            "resume_id": resume_id,
        }
        # New device metadata only; never creates/relabels an account queue or transport token.
        state["registration_pending"] = body
        if context is not None:
            state["runtime_registration"] = {"request": body, "association": context}
        self.store.save(state)
        return {"request_id": body["request_id"], "identity": identity}

    def deliver(self):
        state = self.store.get()
        pending = state.get("registration_pending")
        if not pending:
            raise RuntimeError("NO_REGISTRATION_PENDING")
        result = self.factory(self.device_store.get()["token"]).call(
            PREFIX + "/accounts/register", pending
        )
        if result["state"] in {"created", "linked"}:
            bindings = state.setdefault("registered_accounts", {})
            key = result["binding_id"]
            if key in bindings and (
                bindings[key]["identity"] != pending["identity"]
                or bindings[key]["account_id"] != result["account_id"]
            ):
                raise RuntimeError("REGISTERED_IDENTITY_IMMUTABLE")
            bindings[key] = {"account_id": result["account_id"], "identity": pending["identity"]}
        state.setdefault("registration_results", {})[pending["request_id"]] = result
        state.pop("registration_pending")
        self.store.save(state)
        return result


class RegistrationState:
    """Own protected metadata and lock; never stores device secrets or account outbox data."""

    def __init__(self, directory, protector):
        directory = Path(directory)
        check_storage_path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.path, self.protector = directory / "registrations.dpapi", protector
        self.lock = FileLock(directory / "registrations.lock")

    def get(self):
        return load_config(self.path, self.protector) if self.path.exists() else {}

    def save(self, value):
        save_config(self.path, value, self.protector)

    def close(self):
        self.lock.close()


class AccountDiscovery:
    """Only user-selected terminal probes; each MT5 IPC operation gets a spawn process."""

    def __init__(self):
        self.pool = SpawnPool(max_workers=4)

    def candidates(self):
        return self.pool.submit(discover)

    def active(self, path, *, selected):
        if selected is not True:
            raise ValueError("EXPLICIT_ACCOUNT_SELECTION_REQUIRED")
        return self.pool.submit(discover_active, path)

    def tick(self):
        self.pool.tick()

    def close(self):
        self.pool.shutdown()
