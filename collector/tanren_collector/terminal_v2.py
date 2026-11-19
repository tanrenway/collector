"""MT5 v2 read allowlist. Sequential per-process IPC, no login/trade/modify calls."""

import math
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation

from .observability import stage
from .terminal import Terminal, initialize_readonly, money, timestamp

# Storage contract of every MT5 number on the backend: Numeric(38,12) / Money (12 decimal places,
# integer part below 10**26). Three kinds of source numbers meet it differently:
#
# * Trade facts (deal, order and position source values: volume, price, deal P/L components,
#   SL/TP, ...) - numeric(): the double's shortest decimal, exactly. A fact that does not fit fails
#   the read (SOURCE_PRECISION_UNSUPPORTED / INVALID_SOURCE_NUMBER); it is never rounded or dropped.
# * Live computed values (account equity, floating profit, margin, free margin; open-position
#   profit, swap and current price; tick value) - measured(): the terminal recomputes them on every
#   tick in binary floating point, so float artefacts such as 0.30000000000000004 or a tick value of
#   0.6779661016949152 are normal. An artefact (the 15-significant-digit decimal, DBL_DIG, lies
#   within ARTEFACT_ULPS units in the last place of the double) is removed; otherwise the exact
#   value is rounded half-even to 12 decimal places (error at most 5e-13). A value that cannot be
#   kept without distortion (out of range, or so small that rounding would make it 0 or move it by
#   more than a billionth of itself) becomes null: unknown, never 0.
# * Reference values (account balance; symbol point, tick size and contract size) - reference():
#   short decimals configured on the server. Kept exactly; a float artefact is removed as above;
#   anything that would need rounding becomes null (unknown) instead of a guessed value.
#
# A null never fails the sync; each one is recorded in `issues` (field and reason, no values) so the
# caller can log it.
LIMIT = Decimal(10) ** 26
QUANTUM = Decimal(1).scaleb(-12)
DOUBLE_DIGITS = Context(prec=15, rounding=ROUND_HALF_EVEN)
ARTEFACT_ULPS = 4
MAX_RELATIVE_ROUNDING = Decimal("1e-9")


def fits(decimal):
    return abs(decimal) < LIMIT and decimal.as_tuple().exponent >= -12


def text(decimal):
    # Plain notation without trailing zeros ("0.3", "100"), never an exponent.
    value = decimal.normalize()
    return format(value if value != 0 else Decimal(0), "f")


def numeric(value):
    """Trade fact: exact, or the read fails."""
    text_value = money(value)
    if text_value is not None and not fits(Decimal(text_value)):
        raise RuntimeError("SOURCE_PRECISION_UNSUPPORTED")
    return text_value


def _source(value, field, issues):
    """The exact decimal of a source number, or None (recorded) when it is not a finite number."""
    if value is None:
        return None, None
    try:
        exact = money(value)
        return exact, Decimal(exact)
    except (RuntimeError, InvalidOperation, ValueError, TypeError):
        issues.append((field, "INVALID_SOURCE_NUMBER"))
        return None, None


def artefact_free(decimal):
    """The short decimal behind a float artefact, or None when the digits are real."""
    short = DOUBLE_DIGITS.plus(decimal).normalize()
    if not fits(short):
        return None
    ulp = Decimal(math.ulp(float(decimal)))
    return short if abs(short - decimal) <= ARTEFACT_ULPS * ulp else None


def measured(value, field, issues):
    """Live computed value: float artefacts normalized to the storage contract, else unknown."""
    exact, decimal = _source(value, field, issues)
    if decimal is None or fits(decimal):
        return exact
    if abs(decimal) >= LIMIT:
        issues.append((field, "SOURCE_OUT_OF_RANGE"))
        return None
    short = artefact_free(decimal)
    if short is not None:
        issues.append((field, "FLOAT_ARTEFACT_REMOVED"))
        return text(short)
    rounded = decimal.quantize(QUANTUM, rounding=ROUND_HALF_EVEN)
    if rounded == 0 or abs(rounded - decimal) / abs(decimal) > MAX_RELATIVE_ROUNDING:
        # Below the contract's resolution: rounding would turn the value into 0 or distort it.
        issues.append((field, "SOURCE_BELOW_RESOLUTION"))
        return None
    issues.append((field, "ROUNDED_TO_CONTRACT"))
    return text(rounded)


def reference(value, field, issues):
    """Server-configured value: exact (up to a double's own precision), else unknown."""
    exact, decimal = _source(value, field, issues)
    if decimal is None or fits(decimal):
        return exact
    if abs(decimal) >= LIMIT:
        issues.append((field, "SOURCE_OUT_OF_RANGE"))
        return None
    short = artefact_free(decimal)
    if short is not None:
        issues.append((field, "FLOAT_ARTEFACT_REMOVED"))
        return text(short)
    issues.append((field, "SOURCE_PRECISION_UNSUPPORTED"))
    return None


# Per record kind: which observation fields are live values (everything else is a trade fact).
LIVE_FIELDS = {"position": ("profit", "swap", "price_current"), "order": ("price_current",)}


def observation(kind, row, issues=None):
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
        source = getattr(row, field, None)
        if field in LIVE_FIELDS.get(kind, ()):
            result[field] = measured(
                source, f"{kind}.{field}", issues if issues is not None else []
            )
        else:
            result[field] = numeric(source)
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
        # Normalized or unknown live/reference values of this read: (field, reason), no values.
        self.issues = issues = []
        result = []
        for kind, name, args in (
            ("deal", "history_deals_get", (start, end)),
            ("order", "history_orders_get", (start, end)),
            ("order", "orders_get", ()),
            ("position", "positions_get", ()),
        ):
            result.extend(observation(kind, row, issues) for row in self.rows(name, *args))
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
                "balance": reference(getattr(info, "balance", None), "account.balance", issues),
                **{
                    field: measured(getattr(info, attr, None), "account." + field, issues)
                    for field, attr in (
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
                    "point": reference(getattr(spec, "point", None), "symbol.point", issues),
                    "tick_size": reference(
                        getattr(spec, "trade_tick_size", None), "symbol.tick_size", issues
                    ),
                    # Recomputed from current exchange rates on every tick: a live value.
                    "tick_value": measured(
                        getattr(spec, "trade_tick_value", None), "symbol.tick_value", issues
                    ),
                    "contract_size": reference(
                        getattr(spec, "trade_contract_size", None), "symbol.contract_size", issues
                    ),
                }
            )
        self.verify()
        # Across all reads of this terminal object (a sync job may read several windows).
        counts = getattr(self, "issue_counts", None)
        if counts is None:
            counts = self.issue_counts = {}
        for field, reason in issues:
            key = f"{field}:{reason}"
            counts[key] = counts.get(key, 0) + 1
        kinds = getattr(self, "record_counts", None)
        if kinds is None:
            kinds = self.record_counts = {}
        for record in result:
            kinds[record["kind"]] = kinds.get(record["kind"], 0) + 1
        return result
