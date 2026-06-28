"""Cost-model behavior tests — conservatism, XAU distinctness, stress, slippage."""

import pytest

from novax.costs import DEFAULT_COST_MODEL, CostModel
from novax.units import Pips


def test_round_trip_cost_is_positive():
    assert DEFAULT_COST_MODEL.round_trip_cost_pips("EUR/USD", atr=Pips(10)) > 0


def test_xau_costs_more_than_eurusd_in_pips():
    cm = DEFAULT_COST_MODEL
    eur = cm.round_trip_cost_pips("EUR/USD", atr=Pips(10))
    xau = cm.round_trip_cost_pips("XAU/USD", atr=Pips(10))
    assert xau > eur


def test_stress_factor_scales_cost_up():
    base = DEFAULT_COST_MODEL.round_trip_cost_pips("EUR/USD", atr=Pips(10))
    stressed = DEFAULT_COST_MODEL.with_stress(1.5).round_trip_cost_pips("EUR/USD", atr=Pips(10))
    assert stressed == pytest.approx(base * 1.5)


def test_asian_session_is_more_expensive_than_london():
    cm = DEFAULT_COST_MODEL
    london = cm.round_trip_cost_pips("EUR/USD", atr=Pips(10), session="LONDON")
    asia = cm.round_trip_cost_pips("EUR/USD", atr=Pips(10), session="ASIA")
    assert asia > london


def test_stop_exit_adds_adverse_slippage():
    cm = DEFAULT_COST_MODEL
    normal = cm.round_trip_cost_pips("GBP/USD", atr=Pips(20), exit_on_stop=False)
    stopped = cm.round_trip_cost_pips("GBP/USD", atr=Pips(20), exit_on_stop=True)
    assert stopped > normal


def test_spread_floor_enforced():
    cm = DEFAULT_COST_MODEL
    # A realized spread below the floor must not lower the charged spread.
    tiny = cm.spread_cost_pips("EUR/USD", realized_spread_pips=0.1)
    assert tiny == pytest.approx(0.8)  # floor for EUR/USD
    # A realized spread above the floor is used instead.
    wide = cm.spread_cost_pips("EUR/USD", realized_spread_pips=2.0)
    assert wide == pytest.approx(2.0)


def test_higher_atr_increases_slippage():
    cm = DEFAULT_COST_MODEL
    low = cm.round_trip_cost_pips("EUR/USD", atr=Pips(5))
    high = cm.round_trip_cost_pips("EUR/USD", atr=Pips(50))
    assert high > low


def test_currency_cost_includes_commission():
    cm = DEFAULT_COST_MODEL
    cur = cm.round_trip_cost_currency("EUR/USD", lots=1.0, atr=Pips(10))
    # commission alone is 3.5 * 2 = 7.0; total must exceed it.
    assert cur > 7.0


def test_unknown_symbol_raises():
    with pytest.raises(KeyError):
        DEFAULT_COST_MODEL.round_trip_cost_pips("BTC/USD")


def test_invalid_stress_factor_rejected():
    with pytest.raises(ValueError):
        CostModel(stress_factor=0.0)
