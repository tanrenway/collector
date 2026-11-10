"""Frozen presentation DTOs. No credentials, handles, DB/config or source payload fields."""

from dataclasses import dataclass
from typing import Literal

DeviceConnection = Literal[
    "disconnected",
    "claiming",
    "awaiting_browser_confirmation",
    "paired",
    "authorization_required",
    "locally_revoked",
    "error",
]
Role = Literal["unknown", "active", "standby"]


@dataclass(frozen=True)
class DeviceView:
    state: DeviceConnection = "disconnected"
    verification_phrase: str | None = None
    error: str | None = None
    retry_after_seconds: int = 0


@dataclass(frozen=True)
class TerminalView:
    key: str
    label: str
    running: bool = False
    broker: str | None = None
    server: str | None = None
    login_suffix: str | None = None
    error: str | None = None
    path: str | None = None
    currency: str | None = None
    starting_balance: str | None = None


@dataclass(frozen=True)
class RegistrationView:
    terminal_key: str | None = None
    state: Literal[
        "idle",
        "created",
        "linked",
        "metadata_required",
        "identity_conflict",
        "account_policy_blocked",
    ] = "idle"
    request_id: str | None = None
    binding_id: str | None = None
    required: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class ForceView:
    id: str
    state: str


@dataclass(frozen=True)
class AccountView:
    binding_id: str
    account_id: str
    terminal_key: str
    name: str | None = None
    broker: str | None = None
    server: str | None = None
    login_suffix: str | None = None
    last_observed_at: str | None = None
    last_processed_at: str | None = None
    stage: str = "awaiting_handover"
    role: Role = "unknown"
    pending: int = 0
    processing: int = 0
    review: int = 0
    force: tuple[ForceView, ...] = ()
    retry_after_seconds: int = 30
    error: str | None = None


@dataclass(frozen=True)
class LegacyView:
    key: str
    protocol: str
    pending: int
    processing: int
    review: int


@dataclass(frozen=True)
class MigrationView:
    binding_id: str
    stage: str
    queues: tuple[LegacyView, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class ApplicationState:
    error: str | None = None
    device: DeviceView = DeviceView()
    terminals: tuple[TerminalView, ...] = ()
    registration: RegistrationView = RegistrationView()
    accounts: tuple[AccountView, ...] = ()
    migration: MigrationView | None = None
