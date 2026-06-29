"""Causal bar-by-bar backtest engine — Phase 1 Batch 1.

Causal guarantee: strategy receives BarView(bars[:i+1]) at step i — never a
future bar. Enforced structurally: the engine slices a tuple before passing it.

Fill timing: signal at bar i → fill at bars[i+1].open. Last-bar signals are
silently dropped (no next bar exists for the fill). Any open position at the
last bar is force-closed at bars[-1].close — that price is already visible in
the final BarView so it is causal.

PnL: computed internally from fill prices and CostModel. The strategy returns
only a Signal; it has zero influence over cost or PnL figures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from .costs import DEFAULT_COST_MODEL, CostModel
from .data_sources import Bar
from .dataquality import DataQualityReport
from .instruments import Instrument, get_instrument
from .units import Pips
from .validation import TradeRecord

__all__ = [
    "Signal",
    "BarView",
    "Position",
    "StrategyBase",
    "BacktestResult",
    "BacktestEngine",
]


class Signal(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


@dataclass(frozen=True, slots=True)
class BarView:
    """Immutable causal window. Contains exactly bars[:i+1] at engine step i."""

    bars: tuple[Bar, ...]

    @property
    def last(self) -> Bar:
        return self.bars[-1]

    def __len__(self) -> int:
        return len(self.bars)


@dataclass(frozen=True, slots=True)
class Position:
    """Read-only snapshot passed to the strategy. Engine owns mutable state."""

    direction: str  # "FLAT" | "LONG" | "SHORT"
    entry_price: float | None = None
    entry_ts: datetime | None = None
    size: float = 1.0

    @property
    def is_flat(self) -> bool:
        return self.direction == "FLAT"

    @property
    def is_long(self) -> bool:
        return self.direction == "LONG"

    @property
    def is_short(self) -> bool:
        return self.direction == "SHORT"


_FLAT = Position(direction="FLAT")


class StrategyBase(Protocol):
    def on_bar(self, view: BarView, position: Position) -> Signal: ...


@dataclass(frozen=True, slots=True)
class BacktestResult:
    trades: tuple[TradeRecord, ...]
    equity: tuple[float, ...]

    @property
    def pnls(self) -> list[float]:
        return [t.pnl for t in self.trades]


@dataclass(slots=True)
class BacktestEngine:
    """Single-instrument bar-by-bar engine.

    `lots` is the notional lot size passed to the cost model. Default 1.0.
    `session` is the session label used for session-multiplied cost lookups.
    `atr_period` controls Wilder's ATR used for ATR-scaled slippage. Default 14.
    `atr_warmup_floor_pips` sets a minimum ATR (in pips) during the warmup
    period before full ATR history is available, preventing zero-cost early
    fills on unusually quiet opening bars. Default 2.0 pips.
    """

    symbol: str
    timeframe: str
    cost_model: CostModel = field(default_factory=lambda: DEFAULT_COST_MODEL)
    lots: float = 1.0
    atr_period: int = 14
    atr_warmup_floor_pips: float = 2.0

    def __post_init__(self) -> None:
        if self.atr_period < 1:
            raise ValueError(f"atr_period must be >= 1, got {self.atr_period}")
        if self.atr_warmup_floor_pips < 0:
            raise ValueError(
                f"atr_warmup_floor_pips must be >= 0, got {self.atr_warmup_floor_pips}"
            )

    def run(
        self,
        bars: list[Bar] | tuple[Bar, ...],
        strategy: StrategyBase,
        report: DataQualityReport,
        *,
        session: str | None = None,
    ) -> BacktestResult:
        """Run the strategy bar-by-bar and return trades + equity curve.

        Raises ValueError if:
          - report.symbol / report.timeframe do not match the engine's own fields
          - report.passed is False (data quality gate)
          - fewer than 2 bars are supplied (no trade can execute)
        """
        if report.symbol != self.symbol:
            raise ValueError(
                f"report.symbol {report.symbol!r} does not match engine symbol {self.symbol!r}"
            )
        if report.timeframe != self.timeframe:
            raise ValueError(
                f"report.timeframe {report.timeframe!r} does not match "
                f"engine timeframe {self.timeframe!r}"
            )
        if not report.passed:
            failures = "; ".join(c.detail for c in report.failures())
            raise ValueError(f"data quality gate failed — engine refuses to run: {failures}")
        if len(bars) < 2:
            raise ValueError("engine requires at least 2 bars to execute any trade")

        inst = get_instrument(self.symbol)
        bars_t: tuple[Bar, ...] = tuple(bars)
        n = len(bars_t)

        trades: list[TradeRecord] = []
        equity: list[float] = []
        cumulative = 0.0
        pos = _FLAT

        # --- Incremental causal ATR state (Wilder's smoothing) ---------------
        # ATR is maintained in price units and converted to Pips at each step.
        # Causality: TR at step i uses bars_t[i] and bars_t[i-1] only — both
        # already visible in the strategy's BarView at step i. No future bar
        # is accessed. Warmup uses a running mean of available TRs floored at
        # atr_warmup_floor_pips to avoid zero-cost fills on quiet early bars.
        _atr_floor = self.atr_warmup_floor_pips * inst.pip_size
        _tr_sum: float = 0.0
        _tr_count: int = 0
        _current_atr: float = _atr_floor  # price units; updated each step
        _atr_warm: bool = False

        for i in range(n):
            # -- True Range at step i (causal: uses only bars[i] and bars[i-1])
            bar_i = bars_t[i]
            if i == 0:
                tr = bar_i.high - bar_i.low
            else:
                prev_close = bars_t[i - 1].close
                tr = max(
                    bar_i.high - bar_i.low,
                    abs(bar_i.high - prev_close),
                    abs(bar_i.low - prev_close),
                )

            # -- Wilder's incremental ATR update
            if not _atr_warm:
                _tr_sum += tr
                _tr_count += 1
                _current_atr = max(_tr_sum / _tr_count, _atr_floor)
                if _tr_count == self.atr_period:
                    _atr_warm = True
            else:
                _current_atr = (_current_atr * (self.atr_period - 1) + tr) / self.atr_period

            # Convert ATR to Pips for the cost model at this step.
            atr_pips = Pips(_current_atr / inst.pip_size)

            # The strategy only ever receives bars up to and including bar i.
            view = BarView(bars_t[: i + 1])
            signal = strategy.on_bar(view, pos)

            if i == n - 1:
                # Last bar: force-close any open position at this bar's close.
                # That price is already visible in `view`, so it is causal.
                if not pos.is_flat:
                    trade, cumulative = _close(
                        pos,
                        exit_price=bars_t[i].close,
                        exit_ts=bars_t[i].ts,
                        inst=inst,
                        cost_model=self.cost_model,
                        lots=self.lots,
                        session=session,
                        cumulative=cumulative,
                        atr=atr_pips,
                    )
                    trades.append(trade)
                    equity.append(cumulative)
                # Entry signals on the last bar are silently dropped.
                break

            fill_bar = bars_t[i + 1]
            fill_price = fill_bar.open
            fill_ts = fill_bar.ts

            if pos.is_flat:
                if signal is Signal.LONG:
                    pos = Position("LONG", fill_price, fill_ts, self.lots)
                elif signal is Signal.SHORT:
                    pos = Position("SHORT", fill_price, fill_ts, self.lots)
                # FLAT → FLAT: no action.

            elif pos.is_long:
                if signal is Signal.FLAT:
                    trade, cumulative = _close(
                        pos,
                        fill_price,
                        fill_ts,
                        inst,
                        self.cost_model,
                        self.lots,
                        session,
                        cumulative,
                        atr=atr_pips,
                    )
                    trades.append(trade)
                    equity.append(cumulative)
                    pos = _FLAT
                elif signal is Signal.SHORT:
                    # Flatten existing LONG, then open SHORT at the same fill.
                    trade, cumulative = _close(
                        pos,
                        fill_price,
                        fill_ts,
                        inst,
                        self.cost_model,
                        self.lots,
                        session,
                        cumulative,
                        atr=atr_pips,
                    )
                    trades.append(trade)
                    equity.append(cumulative)
                    pos = Position("SHORT", fill_price, fill_ts, self.lots)
                # LONG → LONG: duplicate signal, ignored.

            elif pos.is_short:
                if signal is Signal.FLAT:
                    trade, cumulative = _close(
                        pos,
                        fill_price,
                        fill_ts,
                        inst,
                        self.cost_model,
                        self.lots,
                        session,
                        cumulative,
                        atr=atr_pips,
                    )
                    trades.append(trade)
                    equity.append(cumulative)
                    pos = _FLAT
                elif signal is Signal.LONG:
                    # Flatten existing SHORT, then open LONG at the same fill.
                    trade, cumulative = _close(
                        pos,
                        fill_price,
                        fill_ts,
                        inst,
                        self.cost_model,
                        self.lots,
                        session,
                        cumulative,
                        atr=atr_pips,
                    )
                    trades.append(trade)
                    equity.append(cumulative)
                    pos = Position("LONG", fill_price, fill_ts, self.lots)
                # SHORT → SHORT: duplicate signal, ignored.

        return BacktestResult(tuple(trades), tuple(equity))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _close(
    pos: Position,
    exit_price: float,
    exit_ts: datetime,
    inst: Instrument,
    cost_model: CostModel,
    lots: float,
    session: str | None,
    cumulative: float,
    *,
    atr: Pips,
) -> tuple[TradeRecord, float]:
    """Close `pos` at `exit_price`, return (TradeRecord, new_cumulative_equity).

    `atr` is the Wilder ATR at the bar that generated the close signal,
    expressed in Pips. It drives the ATR-scaled slippage component of the
    cost model. Must be provided by the caller — Pips(0.0) is never correct
    for a real bar series.
    """
    assert pos.entry_price is not None  # guaranteed by Position construction path
    assert pos.entry_ts is not None

    sign = 1.0 if pos.is_long else -1.0
    raw_pnl = sign * (exit_price - pos.entry_price) / inst.pip_size * inst.pip_value_per_lot * lots
    cost = cost_model.round_trip_cost_currency(inst, lots=lots, atr=atr, session=session)
    net_pnl = raw_pnl - cost

    trade = TradeRecord(
        entry_ts=pos.entry_ts,
        exit_ts=exit_ts,
        symbol=inst.symbol,
        pnl=net_pnl,
        session=session,
    )
    return trade, cumulative + net_pnl
