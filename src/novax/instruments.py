"""Instrument universe for Phase 0.

Locked universe: EUR/USD, GBP/USD, USD/JPY, XAU/USD.
XAU/USD is a METAL, not an FX major — it carries its own pip convention and
(in costs.py) its own cost profile. Never reuse FX-major assumptions for gold.

pip_value_per_lot values are NOMINAL placeholders for Phase 0 PnL sketches; they
are not live-accurate (USD/JPY pip value floats with the rate). Calibrate before
using PnL in any decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AssetClass(StrEnum):
    FX_MAJOR = "fx_major"
    METAL = "metal"


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str             # canonical, e.g. "EUR/USD"
    oanda_symbol: str       # e.g. "EUR_USD"
    asset_class: AssetClass
    pip_size: float         # price increment of one pip
    price_precision: int    # decimal places to round prices
    pip_value_per_lot: float  # NOMINAL USD per pip per standard lot (placeholder)
    best_sessions: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.pip_size <= 0:
            raise ValueError(f"{self.symbol}: pip_size must be > 0")
        if self.price_precision < 0:
            raise ValueError(f"{self.symbol}: price_precision must be >= 0")


INSTRUMENTS: dict[str, Instrument] = {
    "EUR/USD": Instrument(
        symbol="EUR/USD", oanda_symbol="EUR_USD", asset_class=AssetClass.FX_MAJOR,
        pip_size=0.0001, price_precision=5, pip_value_per_lot=10.0,
        best_sessions=("LONDON", "NEWYORK", "OVERLAP"),
    ),
    "GBP/USD": Instrument(
        symbol="GBP/USD", oanda_symbol="GBP_USD", asset_class=AssetClass.FX_MAJOR,
        pip_size=0.0001, price_precision=5, pip_value_per_lot=10.0,
        best_sessions=("LONDON", "OVERLAP"),
    ),
    "USD/JPY": Instrument(
        symbol="USD/JPY", oanda_symbol="USD_JPY", asset_class=AssetClass.FX_MAJOR,
        pip_size=0.01, price_precision=3, pip_value_per_lot=9.0,  # nominal
        best_sessions=("ASIA", "NEWYORK"),
    ),
    "XAU/USD": Instrument(
        symbol="XAU/USD", oanda_symbol="XAU_USD", asset_class=AssetClass.METAL,
        pip_size=0.1, price_precision=2, pip_value_per_lot=10.0,  # nominal (100oz)
        best_sessions=("LONDON", "NEWYORK", "OVERLAP"),
    ),
}


def get_instrument(symbol: str) -> Instrument:
    """Look up by canonical ("EUR/USD") or OANDA ("EUR_USD") symbol."""
    if symbol in INSTRUMENTS:
        return INSTRUMENTS[symbol]
    norm = symbol.replace("_", "/")
    if norm in INSTRUMENTS:
        return INSTRUMENTS[norm]
    raise KeyError(f"unknown instrument: {symbol!r}")


def pips(instrument: Instrument, price_delta: float) -> float:
    """Convert an absolute price delta into pips for this instrument."""
    return price_delta / instrument.pip_size


def price_from_pips(instrument: Instrument, n_pips: float) -> float:
    """Convert a number of pips into an absolute price delta."""
    return n_pips * instrument.pip_size
