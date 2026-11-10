"""Add-account conveniences: firm suggestion and the starting balance read from MT5 history."""

from types import SimpleNamespace

import pytest
from tanren_collector.account_registration import discover_active
from tanren_collector.prop_firms import PROP_FIRMS, suggest_firm
from tanren_collector.terminal_v2 import RawTerminal

BUY, BALANCE, CREDIT = 0, 2, 3


def deal(ticket, kind, profit=0.0):
    return SimpleNamespace(ticket=ticket, time_msc=ticket * 1000, type=kind, profit=profit)


class History(RawTerminal):
    def __init__(self, deals):
        self.deals = deals

    def rows(self, name, *args):
        assert name == "history_deals_get"
        return self.deals


@pytest.mark.parametrize(
    ("deals", "expected"),
    [
        ([deal(1, BALANCE, 100000.0), deal(2, BUY, -5.5)], "100000"),
        ([deal(2, BUY), deal(1, BALANCE, 5000.55)], "5000.55"),  # Sorted by time, not list order.
        ([deal(1, BALANCE, 5000.0), deal(2, BALANCE, 250.25), deal(3, BUY)], "5250.25"),
        ([deal(1, BALANCE, 5000.0)], "5000"),
        ([deal(1, BUY), deal(2, BALANCE, 5000.0)], None),  # Older history is missing.
        ([deal(1, CREDIT, 5000.0), deal(2, BUY)], None),
        ([deal(1, BALANCE, -100.0), deal(2, BUY)], None),
    ],
)
def test_starting_balance_is_proved_by_history_or_unknown(deals, expected):
    assert History(deals).starting_balance() == expected


class Discovered:
    expected = None

    def __init__(self, path, identity, fail=False):
        self.fail = fail

    def connect(self):
        pass

    def close(self):
        pass

    def identity(self):
        return {"login": "1234", "server": "S", "broker": "B", "currency": "USD", "mode": "hedging"}

    def starting_balance(self):
        assert self.expected == self.identity()  # The account switch guard is armed first.
        if self.fail:
            raise RuntimeError("TERMINAL_READ_FAILED")
        return "100000"


@pytest.mark.parametrize(("fail", "expected"), [(False, "100000"), (True, None)])
def test_balance_failure_never_blocks_reading_the_account(tmp_path, fail, expected):
    path = tmp_path / "terminal64.exe"
    path.write_text("x")
    details = {}
    identity = discover_active(str(path), lambda p, e: Discovered(p, e, fail), details)
    assert identity["login"] == "1234" and details == {"starting_balance": expected}


@pytest.mark.parametrize(
    ("broker", "server", "firm"),
    [
        ("Five Percent Online Ltd", "FivePercentOnline-Real", "The5ers"),
        ("FTMO S.R.O.", "FTMO-Demo", "FTMO"),
        ("ACG Markets Limited", "ACGMarkets-Main", "Alpha Capital Group"),
        ("Funding Pips LLC", "FundingPips-Live", "Funding Pips"),
        ("Some Retail Broker", "Retail-Live", ""),
    ],
)
def test_firm_is_suggested_only_when_named_in_the_identity(broker, server, firm):
    assert suggest_firm(broker, server) == firm


def test_firm_list_has_twenty_unique_names():
    assert len(PROP_FIRMS) == 20 == len(set(PROP_FIRMS))


def test_firm_names_match_the_list_on_the_site():
    from conftest import monorepo_file

    site = monorepo_file("frontend/lib/providers.ts").read_text()
    assert all(f'"{firm}"' in site for firm in PROP_FIRMS)


@pytest.mark.parametrize(("balance", "expected"), [(10000.0, "10000"), (0.0, None)])
def test_account_with_no_history_uses_its_balance(balance, expected):
    terminal = History([])
    terminal.api = SimpleNamespace(account_info=lambda: SimpleNamespace(balance=balance))
    assert terminal.starting_balance() == expected


def test_qml_errors_are_logged_without_folders(tmp_path, monkeypatch):
    from tanren_collector import diagnostics_log

    monkeypatch.setattr(diagnostics_log, "profile_root", lambda: tmp_path)
    diagnostics_log.qt_message(
        "file:///C:/Users/Some%20One/AppData/Tanren/_internal/qt/qml/Main.qml:40: TypeError: x"
    )
    line = (tmp_path / "diagnostics.log").read_text()
    assert " qt_warning Main.qml:40:_TypeError:_x" in line
    assert "Users" not in line and "Some" not in line


@pytest.mark.parametrize(
    ("event", "code", "written"),
    [("ui_prefilled", "ok", True), ("ui_prefilled", "ACG 1234", False), ("other", "ok", False)],
)
def test_only_fixed_qml_checkpoints_reach_the_log(tmp_path, monkeypatch, event, code, written):
    pytest.importorskip("PySide6")
    from tanren_collector import diagnostics_log
    from tanren_collector.qt.bridge import Bridge

    monkeypatch.setattr(diagnostics_log, "profile_root", lambda: tmp_path)
    Bridge(False).trace(event, code)
    assert (tmp_path / "diagnostics.log").exists() is written
