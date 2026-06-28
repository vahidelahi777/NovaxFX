"""Instrument registry + pip-convention tests (the conventions that silently bite)."""
import pytest

from novax.instruments import (
    INSTRUMENTS,
    AssetClass,
    get_instrument,
    pips,
    price_from_pips,
)


def test_all_four_instruments_present():
    assert set(INSTRUMENTS) == {"EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"}


def test_pip_sizes_are_correct():
    assert get_instrument("EUR/USD").pip_size == 0.0001
    assert get_instrument("GBP/USD").pip_size == 0.0001
    assert get_instrument("USD/JPY").pip_size == 0.01     # not 0.0001
    assert get_instrument("XAU/USD").pip_size == 0.1


def test_xau_is_a_metal_not_fx():
    assert get_instrument("XAU/USD").asset_class is AssetClass.METAL
    assert get_instrument("EUR/USD").asset_class is AssetClass.FX_MAJOR


def test_lookup_by_oanda_symbol():
    assert get_instrument("EUR_USD").symbol == "EUR/USD"
    assert get_instrument("XAU_USD").symbol == "XAU/USD"


def test_unknown_instrument_raises():
    with pytest.raises(KeyError):
        get_instrument("BTC/USD")


def test_pip_math_respects_conventions():
    # A 0.0010 move is 10 pips on EUR/USD ...
    assert pips(get_instrument("EUR/USD"), 0.0010) == pytest.approx(10.0)
    # ... a 0.10 move is 10 pips on USD/JPY (pip = 0.01) ...
    assert pips(get_instrument("USD/JPY"), 0.10) == pytest.approx(10.0)
    # ... and a 1.0 move is 10 pips on XAU/USD (pip = 0.1).
    assert pips(get_instrument("XAU/USD"), 1.0) == pytest.approx(10.0)


def test_pip_round_trip():
    for sym in INSTRUMENTS:
        inst = get_instrument(sym)
        assert price_from_pips(inst, pips(inst, 0.05)) == pytest.approx(0.05)


def test_invalid_pip_size_rejected():
    from novax.instruments import Instrument

    with pytest.raises(ValueError):
        Instrument("X/Y", "X_Y", AssetClass.FX_MAJOR, 0.0, 5, 10.0, ("LONDON",))
