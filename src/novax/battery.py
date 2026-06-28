"""Validation battery — formal runners that emit the gate's validation artifacts.

These runners turn raw per-trade PnL (and, for data quality, bars) into the
provenance-stamped artifacts the Go/No-Go gate consumes. They contain **no trading
logic**: a real strategy, its randomized-entry engine, and ingested data are Phase 1.
Every artifact is emitted through `Evaluation.emit`, so it inherits the run's
`run_id` / `trial_id` / `campaign_id` + provenance — there is no way to emit a
validation artifact that is not tied to a logged trial.

Determinism: all stochastic steps take an explicit seed. UTC only (delegated to the
artifact layer and the market calendar).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .artifacts import ArtifactType
from .data_sources import Bar
from .dataquality import DataQualityReport, run_data_quality
from .runner import Evaluation
from .validation import block_bootstrap, expectancy, max_drawdown

__all__ = [
    "BatteryInputs",
    "ValidationBatteryRunner",
    "DataQualityGateRunner",
]


@dataclass(frozen=True, slots=True)
class BatteryInputs:
    """Raw materials for the validation battery (supplied by the harness/engine).

    None of these encode an edge; they are the observable outputs a backtest would
    produce. In Phase 0.7 tests they are synthetic; in Phase 1 they come from the
    real engine.
    """

    pnls: Sequence[float]
    delayed_pnls: Sequence[float] | None = None      # same trades, +1 bar execution
    stressed_pnls: Sequence[float] | None = None     # PnL recomputed at 1.5x costs
    window_pnls: Sequence[Sequence[float]] | None = None  # per walk-forward window
    no_lookahead_passed: bool = True                 # from NoLookaheadValidator
    bars: Sequence[Bar] | None = None                # for data quality
    symbol: str = ""
    timeframe: str = ""


@dataclass(slots=True)
class ValidationBatteryRunner:
    """Emits RANDOMIZED_ENTRY, ONE_BAR_DELAY, COST_STRESS, WALK_FORWARD,
    MONTE_CARLO_DD, NO_LOOKAHEAD and (optionally) DATA_QUALITY for a single run.

    Requires an `Evaluation` (which carries run_id + trial_id + provenance); it
    cannot be used to emit free-floating artifacts.
    """

    seed: int = 0
    n_bootstrap: int = 500

    def run(self, ev: Evaluation, inputs: BatteryInputs) -> None:
        pnls = list(inputs.pnls)
        if not pnls:
            raise ValueError("validation battery requires a non-empty PnL series")

        # --- RANDOMIZED_ENTRY: null distribution of mean PnL under resampled entries
        null = self._null_distribution(pnls)
        ev.emit(ArtifactType.RANDOMIZED_ENTRY,
                {"null_distribution": null, "observed_stat": _mean(pnls)})

        # --- ONE_BAR_DELAY: edge under +1-bar execution
        delayed = list(inputs.delayed_pnls) if inputs.delayed_pnls is not None else pnls
        ev.emit(ArtifactType.ONE_BAR_DELAY,
                {"base_expectancy": expectancy(pnls),
                 "delayed_expectancy": expectancy(delayed)})

        # --- COST_STRESS: expectancy when costs are scaled to 1.5x
        stressed = list(inputs.stressed_pnls) if inputs.stressed_pnls is not None else pnls
        ev.emit(ArtifactType.COST_STRESS, {"expectancy_at_1_5x": expectancy(stressed)})

        # --- WALK_FORWARD: per-window expectancies (out-of-sample windows)
        windows = inputs.window_pnls if inputs.window_pnls is not None else [pnls]
        ev.emit(ArtifactType.WALK_FORWARD,
                {"window_expectancies": [expectancy(list(w)) for w in windows]})

        # --- MONTE_CARLO_DD: block-bootstrap drawdown distribution (preserves
        #     local autocorrelation of trade PnL — i.i.d. shuffle would understate DD)
        dd_dist = self._mc_drawdowns(pnls)
        ev.emit(ArtifactType.MONTE_CARLO_DD, {"drawdowns_pct": dd_dist})

        # --- NO_LOOKAHEAD: result of the feature recomputation check
        ev.emit(ArtifactType.NO_LOOKAHEAD, {"passed": bool(inputs.no_lookahead_passed)})

        # --- DATA_QUALITY (optional here; DataQualityGateRunner can own it)
        if inputs.bars is not None:
            report = run_data_quality(inputs.symbol, inputs.timeframe, list(inputs.bars))
            ev.emit(ArtifactType.DATA_QUALITY, _dq_payload(report))

    # -- internals ---------------------------------------------------------
    def _null_distribution(self, pnls: Sequence[float]) -> list[float]:
        """Mean PnL across block-bootstrap resamples — a harness proxy for the
        randomized-entry null. Deterministic given seed."""
        resamples = block_bootstrap(
            pnls, block_size=_block_size(len(pnls)),
            n_resamples=self.n_bootstrap, seed=self.seed)
        return [_mean(r) for r in resamples]

    def _mc_drawdowns(self, pnls: Sequence[float]) -> list[float]:
        base = abs(sum(abs(p) for p in pnls)) or 1.0
        resamples = block_bootstrap(
            pnls, block_size=_block_size(len(pnls)),
            n_resamples=self.n_bootstrap, seed=self.seed + 10_000)
        return [max_drawdown(r) / base for r in resamples]


@dataclass(slots=True)
class DataQualityGateRunner:
    """Runs `run_data_quality` and emits the DATA_QUALITY artifact.

    The gate treats a missing DATA_QUALITY artifact as NO_GO, so running this is
    mandatory for any gate-eligible run.
    """

    def run(self, ev: Evaluation, *, symbol: str, timeframe: str,
            bars: Sequence[Bar]) -> DataQualityReport:
        report = run_data_quality(symbol, timeframe, list(bars))
        ev.emit(ArtifactType.DATA_QUALITY, _dq_payload(report))
        return report


def _dq_payload(report: DataQualityReport) -> dict[str, object]:
    return {
        "passed": report.passed,
        "n_bars": report.n_bars,
        "failures": [c.name for c in report.failures()],
    }


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _block_size(n: int) -> int:
    return max(1, min(n, int(round(n ** 0.5))))
