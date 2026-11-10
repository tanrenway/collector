"""Selected account probes and independent registration state; no actual Windows/MT5 claim."""

import uuid

import pytest
from tanren_collector.account_registration import (
    AccountRegistration,
    RegistrationState,
    discover_active,
)
from tanren_collector.device_pairing import DeviceStore
from test_collector import TestProtector

IDENTITY = {
    "broker": "Synthetic",
    "server": "Synthetic-1",
    "login": "1234",
    "currency": "USD",
    "mode": "hedging",
}


class Terminal:
    changes = False
    calls = []

    def __init__(self, path, identity):
        self.number = 0

    def connect(self):
        self.calls.append("connect")

    def identity(self):
        self.number += 1
        return {**IDENTITY, "login": "5678"} if self.changes and self.number > 1 else IDENTITY

    def close(self):
        self.calls.append("close")


def test_selected_probe_path_validation_switch_and_no_trading(tmp_path):
    path = tmp_path / "terminal64.exe"
    path.write_bytes(b"synthetic")
    Terminal.calls = []
    Terminal.changes = False
    assert discover_active(path, Terminal) == IDENTITY
    assert Terminal.calls == ["connect", "close"]
    Terminal.changes = True
    with pytest.raises(RuntimeError, match="IDENTITY_MISMATCH"):
        discover_active(path, Terminal)
    assert Terminal.calls[-1] == "close"
    for invalid in [
        "terminal64.exe",
        str(tmp_path / "other.exe"),
        str(tmp_path / "missing" / "terminal64.exe"),
    ]:
        with pytest.raises(ValueError):
            discover_active(invalid, Terminal)
    Terminal.changes = False


def test_separate_state_lost_ack_exact_retry_multiple_terminals_and_no_queue_changes(tmp_path):
    d = DeviceStore(tmp_path / "device", TestProtector())
    credential = "synthetic-" + uuid.uuid4().hex
    d.save({"state": "paired", "token": credential})
    a = RegistrationState(tmp_path / "accounts", TestProtector())
    queue = tmp_path / "queue-v2.sqlite"
    queue.write_bytes(b"unchanged")
    terminal = tmp_path / "terminal64.exe"
    terminal.write_bytes(b"synthetic")
    calls = []
    receipt = {"state": "created", "account_id": str(uuid.uuid4()), "binding_id": str(uuid.uuid4())}

    class Api:
        fail = True

        def __init__(self, token):
            assert token == credential

        def call(self, path, body):
            calls.append(body)
            if self.fail:
                Api.fail = False
                raise ConnectionError("NETWORK_UNAVAILABLE")
            return receipt

    service = AccountRegistration(d, a, Api)
    with pytest.raises(ValueError):
        service.prepare(terminal, selected=False, terminal_factory=Terminal)
    prepared = service.prepare(terminal, selected=True, terminal_factory=Terminal)
    original = d.path.read_bytes()
    with pytest.raises(ConnectionError):
        service.deliver()
    a.close()
    a = RegistrationState(tmp_path / "accounts", TestProtector())
    service = AccountRegistration(d, a, Api)
    assert service.deliver() == receipt and calls[0] == calls[1]
    assert calls[0]["request_id"] == prepared["request_id"]
    assert d.path.read_bytes() == original and queue.read_bytes() == b"unchanged"
    assert "token" not in a.get() and "registered_accounts" not in d.get()
    other_directory = tmp_path / "second-terminal"
    other_directory.mkdir()
    other_terminal = other_directory / "terminal64.exe"
    other_terminal.write_bytes(b"synthetic")
    service.prepare(other_terminal, selected=True, terminal_factory=Terminal)
    assert service.deliver() == receipt
    a.close()
    d.close()


def test_inaccessible_terminal_does_not_leave_pending_registration(tmp_path):
    class Inaccessible(Terminal):
        def connect(self):
            raise RuntimeError("TERMINAL_UNAVAILABLE")

    device = DeviceStore(tmp_path / "device", TestProtector())
    account = RegistrationState(tmp_path / "account", TestProtector())
    device.save({"state": "paired"})
    path = tmp_path / "terminal64.exe"
    path.write_bytes(b"synthetic")
    Terminal.calls = []
    with pytest.raises(RuntimeError, match="TERMINAL_UNAVAILABLE"):
        AccountRegistration(device, account).prepare(
            path, selected=True, terminal_factory=Inaccessible
        )
    assert not account.get() and Terminal.calls == ["close"]
    account.close()
    device.close()
