"""Validation framework — Phase 0.6 hardened.

Changes vs Phase 0:
  * Deflated Sharpe is FAIL-CLOSED: sr_variance has no default; multiple-trial DSR
    with sr_variance<=0 raises instead of silently no-opping. Output carries its
    assumptions and warning flags.
  * Adds walk-forward windows, purged k-fold + embargo, block bootstrap, and the
    statistical helpers behind the destructive battery (randomized-entry rank,
    one-bar-delay, label-shuffle sanity).

Pure stdlib (statistics.NormalDist). DSR follows Bailey & López de Prado.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from statistics import NormalDist, variance

from .config import SETTINGS

_N = NormalDist()
_EULER_MASCHERONI = 0.5772156649015329

__all__ = [
    "Verdict",
    "TradeRecord",
    "StrategyMetrics",
    "GoNoGoResult",
    "WalkForwardWindow",
    "Lockbox",
    "DeflatedSharpeResult",
    "profit_factor",
    "expectancy",
    "win_rate",
    "max_drawdown",
    "sharpe",
    "estimate_sr_variance",
    "expected_max_sharpe",
    "deflated_sharpe_ratio",
    "compute_metrics",
    "evaluate_go_no_go",
    "walk_forward_windows",
    "purged_kfold",
    "block_bootstrap",
    "bootstrap_statistic",
    "percentile_rank",
    "shuffle_pnls_mean",
]


class Verdict(StrEnum):
    GO = "GO"
    NO_GO = "NO_GO"
    ITERATE = "ITERATE"


@dataclass(frozen=True, slots=True)
class TradeRecord:
    entry_ts: datetime
    exit_ts: datetime
    symbol: str
    pnl: float  # net of costs; be consistent (currency OR R) across a run
    session: str | None = None
    regime: str | None = None

    def __post_init__(self) -> None:
        for label, dt in (("entry_ts", self.entry_ts), ("exit_ts", self.exit_ts)):
            if dt.tzinfo is None:
                raise ValueError(f"TradeRecord.{label} must be tz-aware UTC")


# ----------------------------- metric helpers ------------------------------ #


def profit_factor(pnls: Sequence[float]) -> float:
    gains = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    if losses == 0:
        return math.inf if gains > 0 else 0.0
    return gains / losses


def expectancy(pnls: Sequence[float]) -> float:
    return sum(pnls) / len(pnls) if pnls else 0.0


def win_rate(pnls: Sequence[float]) -> float:
    return sum(1 for p in pnls if p > 0) / len(pnls) if pnls else 0.0


def max_drawdown(pnls: Sequence[float]) -> float:
    """Max peak-to-trough drawdown (absolute) of the cumulative-PnL curve."""
    peak = equity = mdd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        mdd = max(mdd, peak - equity)
    return mdd


def sharpe(returns: Sequence[float]) -> float:
    """Per-trade Sharpe (mean/std). Not annualized — relative use only."""
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    sd = math.sqrt(var)
    return mean / sd if sd > 0 else 0.0


def estimate_sr_variance(trial_sharpes: Sequence[float]) -> float:
    """Variance of Sharpe estimates ACROSS trials (drives the DSR penalty).

    Requires >=2 trials. This is the value that, if defaulted to 0, would silently
    disable the multiple-testing correction — so it is computed, never assumed.
    """
    if len(trial_sharpes) < 2:
        raise ValueError("need >= 2 trial Sharpes to estimate sr_variance")
    return variance(trial_sharpes)


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """E[max Sharpe] across n_trials independent trials (López de Prado)."""
    if n_trials < 2 or sr_variance <= 0:
        return 0.0
    g = _EULER_MASCHERONI
    a = (1 - g) * _N.inv_cdf(1 - 1 / n_trials)
    b = g * _N.inv_cdf(1 - 1 / (n_trials * math.e))
    return math.sqrt(sr_variance) * (a + b)


@dataclass(frozen=True, slots=True)
class DeflatedSharpeResult:
    probability: float
    observed_sharpe: float
    benchmark_sharpe: float  # expected max Sharpe across trials (sr0)
    n_trials: int
    n_obs: int
    sr_variance: float
    skew: float
    kurtosis: float
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def passed(self, threshold: float = SETTINGS.min_deflated_sharpe_probability) -> bool:
        return self.probability > threshold


def deflated_sharpe_ratio(
    observed_sr: float,
    *,
    n_obs: int,
    n_trials: int,
    sr_variance: float,  # NO DEFAULT — fail closed
    skew: float = 0.0,
    kurtosis: float = SETTINGS.fx_kurtosis_estimate,
) -> DeflatedSharpeResult:
    """Probability the true Sharpe beats the trial-adjusted benchmark (0..1).

    FAIL-CLOSED rules:
      * n_trials >= 1 required.
      * n_obs >= 2 required.
      * For n_trials > 1, sr_variance MUST be > 0 (estimate it from the trial
        registry). sr_variance <= 0 with multiple trials raises — the Phase 0
        silent no-op is now impossible.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if n_obs < 2:
        raise ValueError("n_obs must be >= 2")
    if n_trials > 1 and sr_variance <= 0:
        raise ValueError(
            "sr_variance must be > 0 for multiple-trial DSR; estimate it from the "
            "trial registry (estimate_sr_variance). Refusing to silently skip the "
            "multiple-testing correction."
        )

    warnings: list[str] = []
    if math.isclose(kurtosis, 3.0):
        warnings.append("kurtosis=3 (normal) assumed; FX is fat-tailed -> DSR optimistic")
    if n_obs < 200:
        warnings.append(f"small sample (n_obs={n_obs}); DSR unstable")
    if n_trials == 1:
        warnings.append("n_trials=1: no multiple-testing penalty applied")

    sr0 = expected_max_sharpe(n_trials, sr_variance) if n_trials > 1 else 0.0
    denom = math.sqrt(max(1e-12, 1 - skew * observed_sr + ((kurtosis - 1) / 4) * observed_sr**2))
    z = (observed_sr - sr0) * math.sqrt(n_obs - 1) / denom
    return DeflatedSharpeResult(
        probability=_N.cdf(z),
        observed_sharpe=observed_sr,
        benchmark_sharpe=sr0,
        n_trials=n_trials,
        n_obs=n_obs,
        sr_variance=sr_variance,
        skew=skew,
        kurtosis=kurtosis,
        warnings=tuple(warnings),
    )


# ------------------------------- aggregates -------------------------------- #


@dataclass(frozen=True, slots=True)
class StrategyMetrics:
    n_trades: int
    expectancy: float
    profit_factor: float
    win_rate: float
    sharpe: float
    max_drawdown: float

    @property
    def is_profitable(self) -> bool:
        return self.expectancy > 0 and self.profit_factor > 1.0


def compute_metrics(trades: Sequence[TradeRecord]) -> StrategyMetrics:
    pnls = [t.pnl for t in trades]
    return StrategyMetrics(
        n_trades=len(pnls),
        expectancy=expectancy(pnls),
        profit_factor=profit_factor(pnls),
        win_rate=win_rate(pnls),
        sharpe=sharpe(pnls),
        max_drawdown=max_drawdown(pnls),
    )


# ----------------------------- splitters ----------------------------------- #


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime

    def __post_init__(self) -> None:
        for label, dt in (
            ("train_start", self.train_start),
            ("train_end", self.train_end),
            ("test_start", self.test_start),
            ("test_end", self.test_end),
        ):
            if dt.tzinfo is None:
                raise ValueError(f"WalkForwardWindow.{label} must be tz-aware UTC")
        if not (self.train_start < self.train_end <= self.test_start < self.test_end):
            raise ValueError("walk-forward windows must be chronological & non-overlapping")


def walk_forward_windows(
    start: datetime,
    end: datetime,
    *,
    train: timedelta,
    test: timedelta,
    step: timedelta | None = None,
) -> list[WalkForwardWindow]:
    """Rolling anchored walk-forward windows. step defaults to `test` (non-overlapping tests)."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start/end must be tz-aware UTC")
    step = step or test
    out: list[WalkForwardWindow] = []
    train_start = start
    while True:
        train_end = train_start + train
        test_start = train_end
        test_end = test_start + test
        if test_end > end:
            break
        out.append(WalkForwardWindow(train_start, train_end, test_start, test_end))
        train_start = train_start + step
    return out


def purged_kfold(
    n_samples: int,
    *,
    n_splits: int,
    embargo: int,
) -> list[tuple[list[int], list[int]]]:
    """Purged k-fold over a time-ordered index, with an embargo gap.

    Each test fold is a contiguous block. Train excludes the test block AND any
    index within `embargo` samples of the block boundaries (purge + embargo), to
    prevent label leakage from autocorrelation.
    """
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")
    if embargo < 0:
        raise ValueError("embargo must be >= 0")
    fold = n_samples // n_splits
    folds: list[tuple[list[int], list[int]]] = []
    for k in range(n_splits):
        lo = k * fold
        hi = n_samples if k == n_splits - 1 else (k + 1) * fold
        test_idx = list(range(lo, hi))
        purge_lo, purge_hi = max(0, lo - embargo), min(n_samples, hi + embargo)
        train_idx = [i for i in range(n_samples) if i < purge_lo or i >= purge_hi]
        folds.append((train_idx, test_idx))
    return folds


# ----------------------------- bootstrap ----------------------------------- #


def block_bootstrap(
    values: Sequence[float],
    *,
    block_size: int,
    n_resamples: int,
    seed: int = 0,
) -> list[list[float]]:
    """Moving-block bootstrap: resample contiguous blocks to preserve autocorrelation.

    Naive i.i.d. shuffling destroys trade clustering and understates tail risk;
    block resampling keeps local dependence intact.
    """
    if block_size < 1:
        raise ValueError("block_size must be >= 1")
    n = len(values)
    if n == 0:
        return [[] for _ in range(n_resamples)]
    rng = random.Random(seed)
    max_start = max(1, n - block_size + 1)
    out: list[list[float]] = []
    for _ in range(n_resamples):
        series: list[float] = []
        while len(series) < n:
            s = rng.randrange(max_start)
            series.extend(values[s : s + block_size])
        out.append(series[:n])
    return out


def bootstrap_statistic(
    values: Sequence[float],
    stat_fn: Callable[[Sequence[float]], float],
    *,
    block_size: int,
    n_resamples: int,
    seed: int = 0,
) -> list[float]:
    return [
        stat_fn(s)
        for s in block_bootstrap(values, block_size=block_size, n_resamples=n_resamples, seed=seed)
    ]


# ------------------------- destructive-battery stats ----------------------- #


def percentile_rank(value: float, distribution: Sequence[float]) -> float:
    """Fraction of `distribution` below `value` (0..1). For randomized-entry nulls."""
    if not distribution:
        raise ValueError("empty distribution")
    return sum(1 for d in distribution if d < value) / len(distribution)


def shuffle_pnls_mean(pnls: Sequence[float], *, n_shuffles: int, seed: int = 0) -> float:
    """Mean of per-shuffle means under label permutation; harness-sanity (≈0 expected)."""
    rng = random.Random(seed)
    pool = list(pnls)
    if not pool:
        return 0.0
    means = []
    for _ in range(n_shuffles):
        rng.shuffle(pool)
        means.append(sum(pool) / len(pool))
    return sum(means) / len(means)


# ------------------------------- lockbox ----------------------------------- #


@dataclass(slots=True)
class Lockbox:
    """Out-of-sample guard. May be opened exactly once."""

    name: str = "lockbox"
    _opened: int = 0

    @property
    def opened_count(self) -> int:
        return self._opened

    def open(self) -> None:
        self._opened += 1
        if self._opened > 1:
            raise RuntimeError(
                f"{self.name} opened {self._opened} times — no longer out-of-sample. "
                "Re-create the split; do not peek twice."
            )


# ------------------------------ go/no-go ----------------------------------- #


@dataclass(frozen=True, slots=True)
class GoNoGoResult:
    verdict: Verdict
    failed_criteria: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return self.verdict is Verdict.GO


def evaluate_go_no_go(*_args: object, **_kwargs: object) -> GoNoGoResult:
    """REMOVED in Phase 0.7 — this gate trusted caller-supplied booleans/scalars.

    The Phase 0.6 re-audit showed a strategy could be passed by simply passing the
    right ``True`` values (cost-stress, randomized-entry, one-bar-delay) and a
    flattering ``drawdown_pct``. Phase 0.7 replaces it with the artifact-driven
    ``novax.gate.evaluate_gate``, which COMPUTES every verdict from registered
    artifacts and refuses to read caller-supplied truth. Calling this raises so the
    trust-based path cannot be invoked even by accident.
    """
    raise RuntimeError(
        "evaluate_go_no_go was removed in Phase 0.7: it trusted caller-supplied "
        "booleans. Use novax.gate.evaluate_gate, which computes every criterion "
        "from registered artifacts (run_id + provenance) and has no override."
    )
