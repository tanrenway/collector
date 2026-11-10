"""Server-driven chart jobs with a synthetic MT5 API: read-only, quantised, failure-safe."""

import re
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from tanren_collector.charts import ChartTurn
from tanren_collector.device_sync import ROUTE
from tanren_collector.terminal_v2 import RawTerminal

IDENT = {"login": "1", "server": "S", "broker": "B", "currency": "USD", "mode": "hedging"}
JOB = {
    "id": "11111111-1111-4111-8111-111111111111",
    "symbol": "EURUSD",
    "timeframe": "M15",
    "from": "2026-11-02T08:00:00+00:00",
    "to": "2026-11-02T12:00:00+00:00",
}


class FakeApi:
    TIMEFRAME_M15 = 15
    TIMEFRAME_H4 = 16388

    def __init__(self, rates=None, symbols=("EURUSD",)):
        self.rates, self.symbols, self.calls = rates, symbols, []

    def account_info(self):
        return SimpleNamespace(login=1, server="S", company="B", currency="USD", margin_mode=2)

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def symbol_info(self, symbol):
        self.calls.append(("symbol_info", symbol))
        return SimpleNamespace(digits=5) if symbol in self.symbols else None

    def copy_rates_range(self, symbol, timeframe, start, end):
        self.calls.append(("copy_rates_range", symbol, timeframe, start, end))
        return self.rates

    def last_error(self):
        return (1, "ok")


def terminal(api):
    value = object.__new__(RawTerminal)
    value.api, value.path, value.expected = api, "C:/mt5.exe", IDENT
    value.connect = lambda: None
    value.close = lambda: None
    return value


def bars():
    return [
        {
            "time": 1_700_000_000 + i * 900,
            "open": 1.1 + i / 1e5,
            "high": 1.10105 + i / 1e5,
            "low": 1.09905 + i / 1e5,
            "close": 1.1001 + i / 1e5,
        }
        for i in range(4)
    ]


class Server:
    def __init__(self, jobs):
        self.jobs, self.posts = jobs, []

    def call(self, path, payload=None):
        if path.endswith("/chart-jobs"):
            return {"items": self.jobs}
        self.posts.append((path, payload))
        return {"status": "ok"}


def test_rates_are_quantised_decimal_strings_and_read_only():
    api = FakeApi(bars())
    digits, candles = terminal(api).rates(
        "EURUSD", "M15", datetime(2026, 11, 2, tzinfo=UTC), datetime(2026, 11, 3, tzinfo=UTC)
    )
    assert digits == 5 and candles[0] == {
        "t": 1_700_000_000,
        "o": "1.10000",
        "h": "1.10105",
        "l": "1.09905",
        "c": "1.10010",
    }
    # Only market-data reads happened: no trade, login or screenshot call exists on the fake.
    assert {c[0] for c in api.calls} == {"symbol_info", "copy_rates_range"}


def test_unknown_timeframe_and_symbol_and_missing_history():
    with pytest.raises(RuntimeError, match="READ_METHOD_NOT_ALLOWED"):
        terminal(FakeApi(bars())).rates("EURUSD", "M1", None, None)
    with pytest.raises(RuntimeError, match="SYMBOL_NOT_FOUND"):
        terminal(FakeApi(bars())).rates("XAUUSD", "M15", None, None)
    with pytest.raises(RuntimeError, match="NO_HISTORY"):
        terminal(FakeApi(None)).rates("EURUSD", "M15", None, None)


def test_turn_uploads_candles_and_reports_permanent_failures():
    prefix = "/api/v1/mt5/collector/v3/accounts/x"
    server = Server([JOB, {**JOB, "id": "22222222-2222-4222-8222-222222222222", "symbol": "FOO"}])
    result = ChartTurn(server, prefix, terminal(FakeApi(bars()))).run()
    assert result == {"jobs": 2, "uploaded": 1, "failed": 1}
    (path1, body1), (path2, body2) = server.posts
    assert path1.endswith("/chart-jobs/" + JOB["id"] + "/ohlc") and body1["digits"] == 5
    assert path2.endswith("/failure") and body2 == {"code": "SYMBOL_NOT_FOUND"}


def test_unavailable_terminal_leaves_jobs_pending_without_reporting():
    class Busy:
        def connect(self):
            raise RuntimeError("TERMINAL_BUSY")

        close = rates = None

    server = Server([JOB])
    assert ChartTurn(server, "/p", Busy()).run() == {"jobs": 1, "uploaded": 0, "failed": 0}
    assert server.posts == []


def test_device_routes_allow_only_chart_endpoints():
    base = "/api/v1/mt5/collector/v3/accounts/" + "a" * 8 + "-aaaa-4aaa-8aaa-" + "a" * 12
    job = "11111111-1111-4111-8111-111111111111"
    for suffix in ("/chart-jobs", f"/chart-jobs/{job}/ohlc", f"/chart-jobs/{job}/failure"):
        assert ROUTE.fullmatch(base + suffix)
    for suffix in (f"/chart-jobs/{job}", f"/chart-jobs/{job}/delete", "/orders"):
        assert not ROUTE.fullmatch(base + suffix)
    assert re.compile(ROUTE.pattern)
