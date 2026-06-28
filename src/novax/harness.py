"""Minimal research harness — exercises the safeguards end-to-end.

This is NOT a strategy engine and produces NO edge. It emits the artifact set the
Go/No-Go gate consumes, so the enforcement layer can be tested against realistic
flows (e.g. "the luckiest of 200 random trials is rejected"). Real strategies,
features, and ingested data are Phase 1.
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from .artifacts import ArtifactType
from .runner import Evaluation
from .validation import expectancy, sharpe

__all__ = ["equity_from_pnls", "BaselineRandomStrategy", "emit_required_artifacts"]


def equity_from_pnls(pnls: Sequence[float]) -> list[float]:
    eq, c = [], 0.0
    for p in pnls:
        c += p
        eq.append(c)
    return eq


class BaselineRandomStrategy:
    """A deliberately edgeless strategy: i.i.d. random per-trade PnL."""

    def __init__(self, seed: int, mean: float = 0.0, sd: float = 1.0) -> None:
        self._rng = random.Random(seed)
        self.mean, self.sd = mean, sd

    def generate(self, n: int) -> list[float]:
        return [self._rng.gauss(self.mean, self.sd) for _ in range(n)]


def emit_required_artifacts(
    ev: Evaluation,
    pnls: Sequence[float],
    *,
    lockbox_expectancy: float | None = None,
    window_expectancies: Sequence[float] | None = None,
    null_distribution: Sequence[float] | None = None,
    observed_stat: float | None = None,
    delayed_expectancy: float | None = None,
    expectancy_at_1_5x: float | None = None,
    mc_drawdowns_pct: Sequence[float] | None = None,
    data_quality_passed: bool = True,
    no_lookahead_passed: bool = True,
) -> str:
    """Emit the full REQUIRED_ARTIFACTS set for `pnls` via the evaluation handle.

    Side-artifacts default to favorable so a test can isolate which criterion fails
    (e.g. leave them favorable to prove the DSR/campaign penalty is what rejects).
    """
    exp = expectancy(pnls)
    ev.set_sharpe(sharpe(pnls))
    ev.emit(ArtifactType.EQUITY_CURVE, {"equity": equity_from_pnls(pnls)})
    ev.emit(ArtifactType.TRADE_LEDGER, {"pnls": list(pnls)})
    ev.emit(ArtifactType.DATA_QUALITY, {"passed": data_quality_passed})
    ev.emit(ArtifactType.NO_LOOKAHEAD, {"passed": no_lookahead_passed})
    ev.emit(
        ArtifactType.WALK_FORWARD, {"window_expectancies": list(window_expectancies or [0.1] * 10)}
    )
    ev.emit(
        ArtifactType.RANDOMIZED_ENTRY,
        {
            "null_distribution": list(null_distribution or [0.0] * 100),
            "observed_stat": float(observed_stat if observed_stat is not None else 1.0),
        },
    )
    ev.emit(
        ArtifactType.ONE_BAR_DELAY,
        {
            "base_expectancy": exp,
            "delayed_expectancy": float(
                delayed_expectancy if delayed_expectancy is not None else exp
            ),
        },
    )
    ev.emit(
        ArtifactType.COST_STRESS,
        {
            "expectancy_at_1_5x": float(
                expectancy_at_1_5x if expectancy_at_1_5x is not None else exp
            )
        },
    )
    ev.emit(ArtifactType.MONTE_CARLO_DD, {"drawdowns_pct": list(mc_drawdowns_pct or [0.05] * 100)})
    ev.emit(
        ArtifactType.LOCKBOX,
        {"expectancy": float(lockbox_expectancy if lockbox_expectancy is not None else exp)},
    )
    return ev.run_id
