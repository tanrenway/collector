"""MT5 v2 read allowlist. Sequential per-process IPC, no login/trade/modify calls."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .observability import stage
from .terminal import Terminal, initialize_readonly, money, timestamp


def numeric(value):
    text = money(value)
    if text is not None:
        decimal = Decimal(text)
        if abs(decimal) >= Decimal(10) ** 26 or decimal.as_tuple().exponent < -12:
            raise RuntimeError("SOURCE_PRECISION_UNSUPPORTED")
    return text


def observation(kind, row):
    actual_type = row.type
    side = (
        "long" if actual_type in (0, 2, 4, 6) else "short" if actual_type in (1, 3, 5, 7) else None
    )
    if kind != "order":
        side = "long" if actual_type == 0 else "short" if actual_type == 1 else None
    milliseconds = (
        getattr(row, "time_setup_msc", 0) if kind == "order" else getattr(row, "time_msc", 0)
    )
    milliseconds = (
        milliseconds or int(getattr(row, "time_setup" if kind == "order" else "time", 0)) * 1000
    )
    if milliseconds <= 0:
        raise RuntimeError("SOURCE_TIMESTAMP_UNAVAILABLE")
    result = {
        "kind": kind,
        "ticket": str(row.ticket),
        "symbol": row.symbol,
        "direction": side,
        "position_id": str(row.identifier)
        if kind == "position"
        else str(row.position_id)
        if getattr(row, "position_id", 0)
        else None,
        "identifier": str(row.identifier) if kind == "position" else None,
        "order_id": str(row.order) if kind == "deal" and row.order else None,
        "position_by_id": str(row.position_by_id) if getattr(row, "position_by_id", 0) else None,
        "entry_kind": (
            {0: "in", 1: "out", 2: "inout", 3: "out_by"}.get(row.entry, "other") if side else "cash"
        )
        if kind == "deal"
        else "other",
        "raw_type": actual_type,
        "time": timestamp(milliseconds),
        "time_msc": milliseconds,
        "reason": getattr(row, "reason", None),
        "magic": str(row.magic) if hasattr(row, "magic") else None,
        "comment": getattr(row, "comment", None),
        "state": str(row.state) if hasattr(row, "state") else None,
    }
    for field in (
        "volume",
        "price",
        "profit",
        "commission",
        "swap",
        "fee",
        "sl",
        "tp",
        "volume_initial",
        "volume_current",
        "price_open",
        "price_current",
    ):
        result[field] = numeric(getattr(row, field, None))
    if kind == "order":
        result["volume"] = result["volume_initial"]
        result["price"] = result["price_open"]
    elif kind == "position":
        result["price"] = result["price_open"]
    for field in ("time_setup", "time_done", "time_update", "time_expiration"):
        ms = getattr(row, field + "_msc", 0) or int(getattr(row, field, 0)) * 1000
        result[field] = timestamp(ms) if ms else None
        if field != "time_expiration":
            result[field + "_msc"] = ms or None
    result["source_version"] = (
        result.get("time_update_msc")
        if kind == "position"
        else (result.get("time_done_msc") or result.get("time_setup_msc"))
        if kind == "order"
        else None
    )
    return result


class RawTerminal(Terminal):
    def connect(self):
        initialize_readonly(self.api, self.path, timeout=10000)
        if self.expected is not None:
            self.verify()

    def info_identity(self, info):
        if info is None:
            raise RuntimeError("ACCOUNT_INFO_UNAVAILABLE")
        if info.margin_mode not in (0, 1, 2):
            raise RuntimeError("UNSUPPORTED_ACCOUNT_MODE")
        return {
            "login": str(info.login),
            "server": info.server,
            "broker": info.company,
            "currency": info.currency,
            "mode": "hedging" if info.margin_mode == 2 else "netting",
        }

    def identity(self):
        with stage("account_identity"):
            info = self.api.account_info()
            if info is None:
                raise RuntimeError("ACCOUNT_INFO_UNAVAILABLE")
        with stage("terminal_identity"):
            terminal = self.api.terminal_info()
        if terminal is None or not terminal.connected:
            raise RuntimeError("TERMINAL_DISCONNECTED")
        return self.info_identity(info)

    def rows(self, name, *args):
        if name not in {
            "history_deals_total",
            "history_orders_total",
            "history_deals_get",
            "history_orders_get",
            "orders_get",
            "positions_get",
        }:
            raise RuntimeError("READ_METHOD_NOT_ALLOWED")
        self.verify()
        values = getattr(self.api, name)(*args)
        if values is None or self.api.last_error()[0] != 1:
            raise RuntimeError("TERMINAL_READ_FAILED")
        self.verify()
        if name.endswith("_total"):
            if not isinstance(values, int) or isinstance(values, bool) or values < 0:
                raise RuntimeError("TERMINAL_READ_FAILED")
        elif len(values) > 10000:
            raise RuntimeError("SOURCE_DENSITY_LIMIT")
        return values

    def starting_balance(self):
        """Deposits that precede the first trade, or None when the history does not prove them.

        The current balance is never used. Any other leading deal (credit, bonus, withdrawal) means
        the starting amount is unknown, and unknown stays unknown.
        """
        deals = sorted(
            self.rows(
                "history_deals_get",
                datetime(1970, 1, 1, tzinfo=UTC),
                datetime.now(UTC) + timedelta(days=2),
            ),
            key=lambda deal: (deal.time_msc, deal.ticket),
        )
        if not deals:  # Nothing has happened on the account, so its balance is the starting one.
            balance = Decimal(str(self.api.account_info().balance))
            return format(balance.normalize(), "f") if balance.is_finite() and balance > 0 else None
        total = Decimal(0)
        for deal in deals:
            if deal.type in (0, 1):  # First buy or sell.
                break
            amount = Decimal(str(deal.profit))
            if deal.type != 2 or not amount.is_finite() or amount <= 0:  # 2 is a balance operation.
                return None
            total += amount
        return format(total.normalize(), "f") if total > 0 else None

    TIMEFRAMES = ("M5", "M15", "M30", "H1", "H4", "D1", "W1")

    def rates(self, symbol, timeframe, start, end):
        """Read-only market data for a trade chart: broker candles, never ticks or orders.

        Prices are quantised to the symbol's own digits and returned as decimal strings so the
        server renders exactly what the broker published.
        """
        if timeframe not in self.TIMEFRAMES or not isinstance(symbol, str) or not symbol:
            raise RuntimeError("READ_METHOD_NOT_ALLOWED")
        self.verify()
        info = self.api.symbol_info(symbol)
        if info is None:
            raise RuntimeError("SYMBOL_NOT_FOUND")
        digits = int(info.digits)
        values = self.api.copy_rates_range(
            symbol, getattr(self.api, "TIMEFRAME_" + timeframe), start, end
        )
        if values is None or len(values) == 0:
            raise RuntimeError("NO_HISTORY")
        if self.api.last_error()[0] != 1:
            raise RuntimeError("TERMINAL_READ_FAILED")
        self.verify()
        quantum = Decimal(1).scaleb(-digits)
        candles = []
        for row in values[-600:]:
            candle = {"t": int(row["time"])}
            for key in ("open", "high", "low", "close"):
                number = Decimal(str(row[key]))
                if not number.is_finite() or number <= 0:
                    raise RuntimeError("INVALID_SOURCE_NUMBER")
                candle[key[0]] = format(number.quantize(quantum), "f")
            candles.append(candle)
        return digits, candles

    def available_start(self, now):
        """Find earliest UTC day exposed by totals; no inferred initial balance."""
        self.verify()
        floor = datetime(1970, 1, 1, tzinfo=UTC)

        def count(end):
            values = [
                self.rows(name, floor, end)
                for name in ("history_deals_total", "history_orders_total")
            ]
            return sum(values)

        if not count(now):
            return now - timedelta(days=1), False
        low, high = floor, now
        while high - low > timedelta(days=1):
            middle = low + (high - low) / 2
            if count(middle):
                high = middle
            else:
                low = middle
        self.verify()
        return low.replace(hour=0, minute=0, second=0, microsecond=0), True

    def read(self, start, end):
        self.verify()
        result = []
        for kind, name, args in (
            ("deal", "history_deals_get", (start, end)),
            ("order", "history_orders_get", (start, end)),
            ("order", "orders_get", ()),
            ("position", "positions_get", ()),
        ):
            result.extend(observation(kind, row) for row in self.rows(name, *args))
        info = self.api.account_info()
        if self.info_identity(info) != self.expected:
            raise RuntimeError("TERMINAL_IDENTITY_MISMATCH")
        observed = datetime.now(UTC).isoformat()
        result.append(
            {
                "kind": "account",
                "time": observed,
                "time_source": "collector_utc",
                "currency": info.currency,
                **{
                    field: numeric(getattr(info, attr, None))
                    for field, attr in (
                        ("balance", "balance"),
                        ("equity", "equity"),
                        ("profit", "profit"),
                        ("margin", "margin"),
                        ("free_margin", "margin_free"),
                    )
                },
            }
        )
        for symbol in sorted({row["symbol"] for row in result if row.get("symbol")}):
            spec = self.api.symbol_info(symbol)
            if spec is None:
                raise RuntimeError("SYMBOL_SPECIFICATION_UNAVAILABLE")
            result.append(
                {
                    "kind": "symbol",
                    "time": observed,
                    "symbol": symbol,
                    "digits": spec.digits,
                    "profit_currency": spec.currency_profit,
                    "margin_currency": spec.currency_margin,
                    "calculation_mode": spec.trade_calc_mode,
                    **{
                        field: numeric(getattr(spec, attr, None))
                        for field, attr in (
                            ("point", "point"),
                            ("tick_size", "trade_tick_size"),
                            ("tick_value", "trade_tick_value"),
                            ("contract_size", "trade_contract_size"),
                        )
                    },
                }
            )
        self.verify()
        return result
