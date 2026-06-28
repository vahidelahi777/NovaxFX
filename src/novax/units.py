"""Typed units — eliminates the ATR price-units-vs-pips ambiguity at API boundaries.

Phase 0.6 left a half-blind float guard. Here cost/risk APIs require `Pips`, so a
raw float or a `PriceUnits` value is rejected (mypy at author time, isinstance at
runtime). Wrong-unit ATR can no longer pass silently.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .instruments import Instrument

__all__ = ["Pips", "PriceUnits", "to_pips", "to_price", "require_pips"]


@dataclass(frozen=True, slots=True)
class Pips:
    value: float

    def __post_init__(self) -> None:
        if self.value != self.value or math.isinf(self.value):
            raise ValueError("Pips must be finite")
        if self.value < 0:
            raise ValueError("Pips must be >= 0")


@dataclass(frozen=True, slots=True)
class PriceUnits:
    value: float

    def __post_init__(self) -> None:
        if self.value != self.value or math.isinf(self.value):
            raise ValueError("PriceUnits must be finite")


def to_pips(instrument: Instrument, price: PriceUnits) -> Pips:
    return Pips(price.value / instrument.pip_size)


def to_price(instrument: Instrument, pips: Pips) -> PriceUnits:
    return PriceUnits(pips.value * instrument.pip_size)


def require_pips(value: object, *, name: str = "atr") -> Pips:
    """Runtime boundary check: reject raw floats / PriceUnits passed where Pips is required."""
    if isinstance(value, Pips):
        return value
    if isinstance(value, PriceUnits):
        raise TypeError(
            f"{name} was PriceUnits; convert with to_pips(instrument, value) — "
            "passing price units as pips is the silent-error this type prevents.")
    raise TypeError(f"{name} must be Pips, got {type(value).__name__} "
                    "(raw floats are not accepted at this boundary)")
