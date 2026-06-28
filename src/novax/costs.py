"""Conservative trade-cost model for Phase 0.

Costs are pessimistic by default: a strategy must survive these to count as an
edge. Spread + slippage are expressed in PIPS (instrument-relative); commission
is a currency add-on via `round_trip_cost_currency`.

Defaults are placeholders calibrated to the order of magnitude in
docs/phase-0/cost-model-spec.md — re-calibrate against realized feed spreads
before trusting any result. XAU/USD has a distinct profile; FX assumptions are
never reused for gold.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .instruments import Instrument, get_instrument
from .units import Pips, require_pips

_ZERO_PIPS = Pips(0.0)

__all__ = [
    "CostProfile",
    "CostModel",
    "DEFAULT_COST_PROFILES",
    "DEFAULT_SESSION_MULTIPLIERS",
    "DEFAULT_COST_MODEL",
]


@dataclass(frozen=True, slots=True)
class CostProfile:
    """Per-instrument cost parameters. All pip figures are in pips."""

    spread_floor_pips: float
    commission_per_side_per_lot: float  # currency units per standard lot
    slippage_fixed_pips: float
    slippage_atr_k: float  # extra slippage = k * ATR(pips)

    def __post_init__(self) -> None:
        for name in (
            "spread_floor_pips",
            "slippage_fixed_pips",
            "slippage_atr_k",
            "commission_per_side_per_lot",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"CostProfile.{name} must be >= 0")


# Placeholders — calibrate to the real feed. XAU profile deliberately distinct.
DEFAULT_COST_PROFILES: dict[str, CostProfile] = {
    "EUR/USD": CostProfile(0.8, 3.5, 0.3, 0.05),
    "GBP/USD": CostProfile(1.2, 3.5, 0.4, 0.06),
    "USD/JPY": CostProfile(0.9, 3.5, 0.3, 0.05),
    "XAU/USD": CostProfile(20.0, 5.0, 10.0, 0.10),  # METAL — wider everything
}

# Spread/slippage multiplier applied around high-impact news (spreads blow out).
NEWS_SPREAD_MULTIPLIER: float = 5.0

# Liquidity-driven multipliers; Asian session is thinner -> worse fills/spreads.
DEFAULT_SESSION_MULTIPLIERS: dict[str, float] = {
    "ASIA": 1.5,
    "LONDON": 1.0,
    "NEWYORK": 1.0,
    "OVERLAP": 1.0,
}


@dataclass(frozen=True, slots=True)
class CostModel:
    profiles: Mapping[str, CostProfile] = field(default_factory=lambda: dict(DEFAULT_COST_PROFILES))
    session_multipliers: Mapping[str, float] = field(
        default_factory=lambda: dict(DEFAULT_SESSION_MULTIPLIERS)
    )
    stress_factor: float = 1.0  # swept over {1.0, 1.25, 1.5} in validation

    def __post_init__(self) -> None:
        if self.stress_factor <= 0:
            raise ValueError("stress_factor must be > 0")

    def with_stress(self, factor: float) -> CostModel:
        """Return a copy at a different stress factor (for sensitivity sweeps)."""
        return CostModel(self.profiles, self.session_multipliers, factor)

    def _profile(self, symbol: str) -> CostProfile:
        key = symbol if symbol in self.profiles else symbol.replace("_", "/")
        if key not in self.profiles:
            raise KeyError(f"no cost profile for {symbol!r}")
        return self.profiles[key]

    def _session_mult(self, session: str | None) -> float:
        if session is None:
            return 1.0
        return self.session_multipliers.get(session, 1.0)

    def spread_cost_pips(
        self,
        symbol: str,
        *,
        realized_spread_pips: float | None = None,
        session: str | None = None,
        news: bool = False,
    ) -> float:
        """Effective spread (pips) paid once per round trip (enter ask, exit bid).

        Uses realized spread when supplied, never below the conservative floor.
        `news=True` applies the news blow-out multiplier.
        """
        p = self._profile(symbol)
        base = max(realized_spread_pips or 0.0, p.spread_floor_pips)
        news_mult = NEWS_SPREAD_MULTIPLIER if news else 1.0
        return base * self._session_mult(session) * news_mult * self.stress_factor

    def slippage_pips(
        self,
        symbol: str,
        *,
        atr: Pips = _ZERO_PIPS,
        is_stop: bool = False,
        session: str | None = None,
        news: bool = False,
    ) -> float:
        """Slippage (pips) for a single fill. Stops assume extra adverse slippage.

        `atr` MUST be Pips — raw floats / PriceUnits are rejected at this boundary.
        """
        atr = require_pips(atr)
        p = self._profile(symbol)
        per_fill = p.slippage_fixed_pips + p.slippage_atr_k * atr.value
        if is_stop:
            per_fill *= 2.0  # adverse fill on a stop-out
        news_mult = NEWS_SPREAD_MULTIPLIER if news else 1.0
        return per_fill * self._session_mult(session) * news_mult * self.stress_factor

    def round_trip_cost_pips(
        self,
        symbol: str,
        *,
        atr: Pips = _ZERO_PIPS,
        session: str | None = None,
        realized_spread_pips: float | None = None,
        exit_on_stop: bool = False,
        news: bool = False,
    ) -> float:
        """Total round-trip cost in pips: spread (once) + entry + exit slippage."""
        atr = require_pips(atr)
        spread = self.spread_cost_pips(
            symbol, realized_spread_pips=realized_spread_pips, session=session, news=news
        )
        entry = self.slippage_pips(symbol, atr=atr, is_stop=False, session=session, news=news)
        exit_ = self.slippage_pips(
            symbol, atr=atr, is_stop=exit_on_stop, session=session, news=news
        )
        return spread + entry + exit_

    def round_trip_cost_currency(
        self,
        instrument: Instrument | str,
        *,
        lots: float = 1.0,
        atr: Pips = _ZERO_PIPS,
        session: str | None = None,
        realized_spread_pips: float | None = None,
        exit_on_stop: bool = False,
    ) -> float:
        """Round-trip cost in account currency for `lots` standard lots.

        = (spread+slippage pips) * pip_value_per_lot * lots
          + commission per side * 2 * lots
        Uses NOMINAL pip values — see instruments.py caveat.
        """
        inst = instrument if isinstance(instrument, Instrument) else get_instrument(instrument)
        p = self._profile(inst.symbol)
        pip_cost = self.round_trip_cost_pips(
            inst.symbol,
            atr=atr,
            session=session,
            realized_spread_pips=realized_spread_pips,
            exit_on_stop=exit_on_stop,
        )
        spread_slip = pip_cost * inst.pip_value_per_lot * lots
        # Commission is a FIXED broker fee — it must NOT scale with the execution
        # stress factor (Phase 0.5 fix). Stress hits spread/slippage only.
        commission = p.commission_per_side_per_lot * 2.0 * lots
        return spread_slip + commission


DEFAULT_COST_MODEL = CostModel()
