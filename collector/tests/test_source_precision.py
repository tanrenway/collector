"""Source-number normalization: trade facts stay exact, live and reference values never fail a sync.

Regression for SOURCE_PRECISION_UNSUPPORTED (production 2026-11-17): ordinary float artefacts in
values the terminal recomputes on every tick (equity, tick value) failed the whole read.
"""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from tanren_collector.terminal_v2 import RawTerminal, measured, numeric, observation, reference
from test_collector import IDENTITY
from test_v2 import NOW

TICK_VALUE = 0.6779661016949152  # a cross-pair tick value as the terminal reports it
ARTEFACT = 0.1 + 0.2  # 0.30000000000000004


def live(value):
    issues = []
    return measured(value, "f", issues), issues


def ref(value):
    issues = []
    return reference(value, "f", issues), issues


def fits_contract(text):
    decimal = Decimal(text)
    return abs(decimal) < Decimal(10) ** 26 and decimal.as_tuple().exponent >= -12


# Trade facts: unchanged strictness.


@pytest.mark.parametrize("value", [TICK_VALUE, ARTEFACT, "0.1234567890123", 1e26, -1e26, 1e-13])
def test_trade_fact_that_does_not_fit_fails_the_read(value):
    with pytest.raises(RuntimeError, match="SOURCE_PRECISION_UNSUPPORTED"):
        numeric(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_trade_fact_that_is_not_a_number_fails_the_read(value):
    with pytest.raises(RuntimeError, match="INVALID_SOURCE_NUMBER"):
        numeric(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.08501, "1.08501"),
        (-247.47, "-247.47"),
        (0.01, "0.01"),
        (9.9e25, "99000000000000000000000000"),
        (None, None),
    ],
)
def test_trade_fact_that_fits_is_kept_exactly(value, expected):
    assert numeric(value) == expected


# Live computed values.


def test_live_tick_value_is_rounded_to_the_contract_and_recorded():
    value, issues = live(TICK_VALUE)
    assert value == "0.677966101695" and fits_contract(value)
    # 15 significant digits of the double, rounded half-even at the 12th decimal place.
    assert abs(Decimal(value) - Decimal(repr(TICK_VALUE))) < Decimal("1e-12")
    assert issues == [("f", "ROUNDED_TO_CONTRACT")]


@pytest.mark.parametrize(
    ("value", "expected"), [(ARTEFACT, "0.3"), (-ARTEFACT, "-0.3"), (10.000000000000002, "10")]
)
def test_live_float_artefact_is_removed_and_recorded(value, expected):
    assert live(value) == (expected, [("f", "FLOAT_ARTEFACT_REMOVED")])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (10001.0, "10001.0"),
        (0, "0"),
        (10234.560000000001, "10234.560000000001"),
        (-12.5, "-12.5"),
        (None, None),
    ],
)
def test_live_value_that_fits_is_kept_exactly_without_issue(value, expected):
    assert live(value) == (expected, [])


@pytest.mark.parametrize("value", [1e26, -1e26, 1e300])
def test_live_value_beyond_the_contract_is_unknown_not_truncated(value):
    assert live(value) == (None, [("f", "SOURCE_OUT_OF_RANGE")])


@pytest.mark.parametrize("value", [9.999999999999999e25, -9.9e25])
def test_live_value_just_inside_the_range_is_kept(value):
    result, issues = live(value)
    assert result is not None and fits_contract(result) and issues == []


@pytest.mark.parametrize("value", [1e-13, 4e-13, 1.5e-12, 1.234567e-9])
def test_live_value_below_the_contract_resolution_is_unknown_never_zero(value):
    # Rounding would turn it into 0 or move it by more than a billionth of its size.
    assert live(value) == (None, [("f", "SOURCE_BELOW_RESOLUTION")])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "not-a-number"])
def test_live_value_that_is_not_a_number_is_unknown(value):
    assert live(value) == (None, [("f", "INVALID_SOURCE_NUMBER")])


def test_live_rounding_never_moves_a_value_by_more_than_half_a_contract_unit():
    for value in (TICK_VALUE, 0.12345678901234568, 1234.5678901234567, -0.000123456789012345):
        result, _ = live(value)
        assert result is not None and fits_contract(result)
        assert abs(Decimal(result) - Decimal(repr(value))) <= Decimal("5e-13") + Decimal("1e-15")


# Reference values (balance, symbol specification).


@pytest.mark.parametrize(
    ("value", "expected"), [(100000.0, "100000.0"), (1e-05, "0.00001"), (0.5, "0.5"), (None, None)]
)
def test_reference_value_that_fits_is_kept_exactly(value, expected):
    assert ref(value) == (expected, [])


def test_reference_float_artefact_is_removed_because_it_is_lossless():
    assert ref(ARTEFACT) == ("0.3", [("f", "FLOAT_ARTEFACT_REMOVED")])


@pytest.mark.parametrize("value", [TICK_VALUE, 1e-13])
def test_reference_value_that_would_need_rounding_is_unknown_not_guessed(value):
    assert ref(value) == (None, [("f", "SOURCE_PRECISION_UNSUPPORTED")])


@pytest.mark.parametrize(
    ("value", "reason"), [(1e26, "SOURCE_OUT_OF_RANGE"), (float("nan"), "INVALID_SOURCE_NUMBER")]
)
def test_reference_value_out_of_range_or_invalid_is_unknown(value, reason):
    assert ref(value) == (None, [("f", reason)])


# Record level.


def position(**fields):
    base = dict(
        type=0,
        ticket=88,
        identifier=77,
        symbol="EURUSD",
        time_msc=1792843200123,
        volume=0.5,
        price_open=1.1,
        price_current=1.2,
        profit=12.5,
        swap=-1.25,
        sl=1.09,
        tp=1.2,
        time_update_msc=1792843200123,
    )
    return SimpleNamespace(**{**base, **fields})


def test_open_position_live_values_are_normalized_and_its_facts_kept():
    issues = []
    value = observation("position", position(profit=ARTEFACT, price_current=TICK_VALUE), issues)
    assert value["profit"] == "0.3" and value["price_current"] == "0.677966101695"
    assert value["price_open"] == "1.1" and value["volume"] == "0.5" and value["sl"] == "1.09"
    assert ("position.profit", "FLOAT_ARTEFACT_REMOVED") in issues
    assert ("position.price_current", "ROUNDED_TO_CONTRACT") in issues


@pytest.mark.parametrize("field", ["price_open", "volume", "sl", "tp"])
def test_open_position_fact_with_an_artefact_still_fails(field):
    with pytest.raises(RuntimeError, match="SOURCE_PRECISION_UNSUPPORTED"):
        observation("position", position(**{field: TICK_VALUE}), [])


@pytest.mark.parametrize("field", ["price", "volume", "profit", "commission", "swap", "fee"])
def test_deal_financial_fact_with_an_artefact_fails_the_read(field):
    base = dict(
        type=0,
        entry=0,
        ticket=5,
        symbol="EURUSD",
        time_msc=1792843200123,
        position_id=77,
        order=4,
        volume=0.5,
        price=1.1,
        profit=0.0,
        commission=-1.0,
        swap=0.0,
        fee=0.0,
    )
    deal = SimpleNamespace(**{**base, field: ARTEFACT})
    with pytest.raises(RuntimeError, match="SOURCE_PRECISION_UNSUPPORTED"):
        observation("deal", deal, [])


class Bridge:
    """Terminal API with float-artefact live values (as seen in production) and one deal."""

    def __init__(self, deal_price=1.1):
        self.deal_price = deal_price

    def initialize(self, path, /, **kwargs):
        return True

    def account_info(self):
        return SimpleNamespace(
            login=123,
            server=IDENTITY["server"],
            company=IDENTITY["broker"],
            currency="USD",
            margin_mode=2,
            balance=50000.0,
            equity=50000.0 + ARTEFACT,
            profit=ARTEFACT,
            margin=0.0,
            margin_free=1e-13,
        )

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def last_error(self):
        return (1, "ok")

    def history_deals_get(self, *_):
        return [
            SimpleNamespace(
                type=0,
                entry=0,
                ticket=5,
                symbol="GER40",
                time_msc=1792843200123,
                position_id=77,
                order=4,
                volume=0.5,
                price=self.deal_price,
                profit=0.0,
                commission=-1.0,
                swap=0.0,
                fee=0.0,
            )
        ]

    def history_orders_get(self, *_):
        return []

    def orders_get(self):
        return []

    def positions_get(self):
        return []

    def symbol_info(self, symbol):
        return SimpleNamespace(
            digits=1,
            currency_profit="EUR",
            currency_margin="EUR",
            trade_calc_mode=2,
            point=0.1,
            trade_tick_size=0.1,
            trade_tick_value=TICK_VALUE,
            trade_contract_size=1.0,
        )


def test_read_with_float_artefacts_in_live_values_succeeds_and_records_each():
    terminal = RawTerminal("C:/MT5/terminal64.exe", IDENTITY, Bridge())
    terminal.connect()
    records = terminal.read(NOW - timedelta(days=1), NOW)
    account = next(r for r in records if r["kind"] == "account")
    symbol = next(r for r in records if r["kind"] == "symbol")
    deal = next(r for r in records if r["kind"] == "deal")
    assert account["balance"] == "50000.0" and account["profit"] == "0.3"
    assert account["equity"] == "50000.3"  # the sum is exactly representable: kept, no issue
    assert account["free_margin"] is None  # below resolution: unknown, never 0
    assert symbol["tick_value"] == "0.677966101695" and symbol["contract_size"] == "1.0"
    assert deal["price"] == "1.1" and deal["commission"] == "-1.0"
    assert terminal.issue_counts == {
        "account.free_margin:SOURCE_BELOW_RESOLUTION": 1,
        "account.profit:FLOAT_ARTEFACT_REMOVED": 1,
        "symbol.tick_value:ROUNDED_TO_CONTRACT": 1,
    }
    # Every number that leaves the terminal fits the backend contract.
    for record in records:
        for key, value in record.items():
            if isinstance(value, str) and key not in {
                "kind",
                "time",
                "symbol",
                "ticket",
                "position_id",
                "order_id",
                "currency",
                "profit_currency",
                "margin_currency",
                "time_source",
                "magic",
                "comment",
                "state",
                "direction",
            }:
                try:
                    Decimal(value)
                except ArithmeticError:
                    continue
                assert fits_contract(value), (record["kind"], key)


def test_read_with_a_trade_fact_that_does_not_fit_fails_whole_not_partially():
    terminal = RawTerminal("C:/MT5/terminal64.exe", IDENTITY, Bridge(deal_price=TICK_VALUE))
    terminal.connect()
    with pytest.raises(RuntimeError, match="SOURCE_PRECISION_UNSUPPORTED"):
        terminal.read(NOW - timedelta(days=1), NOW)
