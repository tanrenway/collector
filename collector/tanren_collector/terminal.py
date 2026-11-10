"""Explicit read API allowlist. Never initialize with login/password/server parameters."""

from datetime import UTC, datetime
from decimal import Decimal

from .build_profile import require_native_mt5
from .observability import stage


def timestamp(milliseconds):
    seconds, remainder = divmod(int(milliseconds), 1000)
    return datetime.fromtimestamp(seconds, UTC).replace(microsecond=remainder * 1000).isoformat()


def money(value):
    if value is None:
        return None
    decimal = Decimal(str(value))
    if not decimal.is_finite():
        raise RuntimeError("INVALID_SOURCE_NUMBER")
    # Conversion reflects MT5 API source precision; never calculate money using floats.
    return format(decimal, "f")


def initialize_readonly(api, path, timeout=None):
    require_native_mt5()
    # MetaTrader5 accepts the executable path as its FIRST POSITIONAL argument.
    options = {"timeout": timeout} if timeout is not None else {}
    with stage("mt5_initialize"):
        return _initialize(api, path, options)


def _initialize(api, path, options):
    if not api.initialize(path, **options):
        code = api.last_error()[0]
        raise RuntimeError(
            {
                -2: "TERMINAL_INVALID_ARGUMENT",
                -6: "TERMINAL_AUTH_REQUIRED",
                -10003: "TERMINAL_IPC_FAILED",
                -10005: "TERMINAL_API_TIMEOUT",
            }.get(code, "TERMINAL_UNAVAILABLE")
        )


class Terminal:
    def __init__(self, path, identity, api=None):
        require_native_mt5()
        if api is None:
            with stage("mt5_import"):
                import MetaTrader5 as api
        self.api, self.path, self.expected = api, path, identity

    def connect(self):
        initialize_readonly(self.api, self.path)
        self.verify()

    def identity(self):
        with stage("account_identity"):
            info = self.api.account_info()
        with stage("terminal_identity"):
            terminal = self.api.terminal_info()
        if info is None or terminal is None or not terminal.connected:
            raise RuntimeError("TERMINAL_DISCONNECTED")
        return {
            "login": str(info.login),
            "server": info.server,
            "broker": info.company,
            "currency": info.currency,
            "mode": "hedging" if info.margin_mode == 2 else "netting",
        }

    def verify(self):
        if self.identity() != self.expected:
            raise RuntimeError("TERMINAL_IDENTITY_MISMATCH")

    def read(self, start, end):
        self.verify()
        deals = self.api.history_deals_get(start, end)
        if deals is None or self.api.last_error()[0] != 1:
            raise RuntimeError("DEAL_READ_FAILED")
        orders = self.api.history_orders_get(start, end)
        if orders is None or self.api.last_error()[0] != 1:
            raise RuntimeError("ORDER_READ_FAILED")
        positions = self.api.positions_get()
        if positions is None or self.api.last_error()[0] != 1:
            raise RuntimeError("POSITION_READ_FAILED")
        self.verify()  # Account switch during a scan invalidates the entire window.
        result = []
        for kind, rows in (("deal", deals), ("order", orders), ("position", positions)):
            for row in rows:
                side = "long" if row.type == 0 else "short" if row.type == 1 else None
                entry = {0: "in", 1: "out", 2: "inout", 3: "out_by"}.get(
                    getattr(row, "entry", None), "other"
                )
                if kind == "deal" and side is None:
                    entry = "cash"
                ticket = row.identifier if kind == "position" else row.ticket
                pos = row.identifier if kind == "position" else getattr(row, "position_id", 0)
                milliseconds = (
                    getattr(row, "time_msc", 0) if kind != "order" else row.time_setup_msc
                )
                milliseconds = milliseconds or int(getattr(row, "time", 0)) * 1000
                version = (
                    getattr(row, "time_update_msc", None)
                    if kind == "position"
                    else (
                        getattr(row, "time_done_msc", 0) or row.time_setup_msc
                        if kind == "order"
                        else None
                    )
                )
                result.append(
                    {
                        "kind": kind,
                        "ticket": str(ticket),
                        "position_id": str(pos) if pos else None,
                        "order_id": str(row.order) if kind == "deal" and row.order else None,
                        "symbol": row.symbol,
                        "direction": side,
                        "entry_kind": entry,
                        "time": timestamp(milliseconds),
                        "source_version": version,
                        "volume": money(
                            getattr(row, "volume", getattr(row, "volume_initial", None))
                        ),
                        "price": money(getattr(row, "price", getattr(row, "price_open", None))),
                        "profit": money(row.profit) if kind == "deal" else None,
                        "commission": money(getattr(row, "commission", None)),
                        "swap": money(getattr(row, "swap", None)),
                        "fee": money(getattr(row, "fee", None)),
                        "sl": money(getattr(row, "sl", None)),
                        "tp": money(getattr(row, "tp", None)),
                        "state": str(getattr(row, "state", "")),
                    }
                )
        return result

    def close(self):
        self.api.shutdown()
