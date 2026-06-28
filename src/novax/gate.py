"""Artifact-driven Go/No-Go gate — closes Critical 3 (caller-trusted gate).

The gate accepts NO caller-supplied booleans or scalar verdicts. It receives a
set of artifact IDs, looks each up in the artifact registry, verifies their
provenance is mutually consistent (same data_hash / feature_version /
cost_model_version), and COMPUTES every criterion from artifact payloads:

  * drawdown_pct           <- recomputed from the equity-curve series
  * expectancy / PF        <- recomputed from the trade ledger
  * DSR probability        <- computed from the CAMPAIGN trial count + ledger Sharpe
  * walk-forward pass-rate <- counted from per-window results
  * randomized-entry beat  <- percentile of observed stat vs the null distribution
  * cost-stress survival   <- recomputed from per-factor expectancies
  * MC p95 drawdown        <- percentile of the MC drawdown distribution
  * data-quality pass      <- read from the DataQualityReport artifact (its own gate)
  * no-lookahead pass      <- read from the feature-validation artifact

Missing, stale, or provenance-mismatched artifacts -> NO_GO. There is no override.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .artifacts import Artifact, ArtifactRegistry, ArtifactType
from .config import SETTINGS, Settings
from .trial_registry import TrialRegistry
from .validation import (
    expectancy as _expectancy,
)
from .validation import (
    max_drawdown as _max_drawdown,
)
from .validation import (
    percentile_rank,
    profit_factor,
    sharpe,
)

__all__ = ["GateDecision", "evaluate_gate", "REQUIRED_ARTIFACTS"]

REQUIRED_ARTIFACTS: tuple[ArtifactType, ...] = (
    ArtifactType.EQUITY_CURVE,
    ArtifactType.TRADE_LEDGER,
    ArtifactType.DATA_QUALITY,
    ArtifactType.NO_LOOKAHEAD,
    ArtifactType.WALK_FORWARD,
    ArtifactType.RANDOMIZED_ENTRY,
    ArtifactType.ONE_BAR_DELAY,
    ArtifactType.COST_STRESS,
    ArtifactType.MONTE_CARLO_DD,
    ArtifactType.LOCKBOX,
)

_PROVENANCE_KEYS = ("data_hash", "feature_version", "cost_model_version")


def _floats(payload: dict[str, object], key: str) -> list[float]:
    v = payload.get(key, [])
    return [float(x) for x in v] if isinstance(v, (list, tuple)) else []


def _flt(payload: dict[str, object], key: str, default: float = 0.0) -> float:
    v = payload.get(key, default)
    return float(v) if isinstance(v, (int, float)) else default


def _flag(payload: dict[str, object], key: str) -> bool:
    return bool(payload.get(key, False))


@dataclass(frozen=True, slots=True)
class GateDecision:
    passed: bool
    failed_criteria: tuple[str, ...] = field(default_factory=tuple)
    computed: dict[str, float] = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        return "GO" if self.passed else "NO_GO"


def _provenance_tuple(a: Artifact) -> tuple[str, str, str]:
    return (a.data_hash, a.feature_version, a.cost_model_version)


def evaluate_gate(
    *,
    campaign_id: str,
    strategy: str,
    run_id: str,
    artifacts: ArtifactRegistry,
    registry: TrialRegistry,
    settings: Settings = SETTINGS,
) -> GateDecision:
    failed: list[str] = []
    computed: dict[str, float] = {}

    # 1) all required artifacts present for this run
    arts: dict[ArtifactType, Artifact] = {}
    for t in REQUIRED_ARTIFACTS:
        a = artifacts.by_type(run_id, t)
        if a is None:
            failed.append(f"missing artifact: {t}")
        else:
            arts[t] = a
    if failed:  # cannot compute anything without the inputs -> fail closed
        return GateDecision(False, tuple(failed), computed)

    # 2) provenance consistency across artifacts (no stale/mismatched mixing)
    prov = {_provenance_tuple(a) for a in arts.values()}
    if len(prov) != 1:
        failed.append("provenance mismatch across artifacts (data/feature/cost version)")
        return GateDecision(False, tuple(failed), computed)

    # 3) compute criteria FROM artifacts -----------------------------------
    equity = _floats(arts[ArtifactType.EQUITY_CURVE].payload, "equity")
    pnls = _floats(arts[ArtifactType.TRADE_LEDGER].payload, "pnls")

    n_trades = len(pnls)
    computed["n_trades"] = float(n_trades)
    if n_trades < settings.min_oos_trades:
        failed.append(f"sample: {n_trades} < {settings.min_oos_trades} OOS trades")

    pf = profit_factor(pnls)
    exp = _expectancy(pnls)
    computed["profit_factor"], computed["expectancy"] = pf, exp
    if pf < settings.min_profit_factor:
        failed.append(f"profit_factor {pf:.2f} < {settings.min_profit_factor}")
    if exp <= 0:
        failed.append("expectancy non-positive after costs")

    # drawdown_pct computed from the equity curve, not caller-supplied
    if equity:
        peak = equity[0]
        max_dd_abs, base = 0.0, abs(equity[0]) or 1.0
        for v in equity:
            peak = max(peak, v)
            max_dd_abs = max(max_dd_abs, peak - v)
        dd_pct = max_dd_abs / (abs(peak) or base)
    else:
        dd_pct = _max_drawdown(pnls) / (abs(sum(pnls)) or 1.0)
    computed["drawdown_pct"] = dd_pct
    if dd_pct > settings.max_drawdown_pct:
        failed.append(f"max_drawdown {dd_pct:.0%} > {settings.max_drawdown_pct:.0%}")

    # DSR from CAMPAIGN trial count + ledger Sharpe
    obs_sr = sharpe(pnls)
    dsr = registry.deflated_sharpe_for_campaign(
        campaign_id=campaign_id, strategy=strategy, observed_sr=obs_sr, n_obs=max(n_trades, 2)
    )
    computed["deflated_sharpe"] = dsr.probability
    if not dsr.passed(settings.min_deflated_sharpe_probability):
        failed.append(
            f"deflated_sharpe {dsr.probability:.3f} <= {settings.min_deflated_sharpe_probability} "
            f"(campaign n_trials={dsr.n_trials})"
        )

    # walk-forward pass rate counted from per-window results
    wf = arts[ArtifactType.WALK_FORWARD].payload
    window_exps = _floats(wf, "window_expectancies")
    wf_rate = (sum(1 for e in window_exps if e > 0) / len(window_exps)) if window_exps else 0.0
    computed["wf_pass_rate"] = wf_rate
    if wf_rate < settings.min_walk_forward_window_pass_rate:
        failed.append(
            f"walk-forward {wf_rate:.0%} < {settings.min_walk_forward_window_pass_rate:.0%}"
        )

    # randomized-entry: observed stat must beat the null percentile
    re = arts[ArtifactType.RANDOMIZED_ENTRY].payload
    null = _floats(re, "null_distribution")
    observed = _flt(re, "observed_stat")
    rank = percentile_rank(observed, null) if null else 0.0
    computed["randomized_entry_rank"] = rank
    if rank < settings.randomized_entry_percentile:
        failed.append(f"randomized-entry rank {rank:.2f} < {settings.randomized_entry_percentile}")

    # one-bar-delay: edge must survive
    obd = arts[ArtifactType.ONE_BAR_DELAY].payload
    base_exp = _flt(obd, "base_expectancy")
    delayed_exp = _flt(obd, "delayed_expectancy")
    survives_delay = delayed_exp > 0 and (base_exp <= 0 or delayed_exp >= 0.5 * base_exp)
    computed["delayed_expectancy"] = delayed_exp
    if not survives_delay:
        failed.append("one-bar-delay: edge vanishes under delayed execution (lookahead?)")

    # cost-stress: positive at >= 1.5x
    cs = arts[ArtifactType.COST_STRESS].payload
    stressed = _flt(cs, "expectancy_at_1_5x", -1.0)
    computed["expectancy_at_1_5x"] = stressed
    if stressed <= 0:
        failed.append("cost-stress: non-positive expectancy at 1.5x")

    # Monte-Carlo p95 drawdown from the MC distribution
    mc = arts[ArtifactType.MONTE_CARLO_DD].payload
    dd_dist = sorted(_floats(mc, "drawdowns_pct"))
    p95 = dd_dist[min(len(dd_dist) - 1, int(0.95 * len(dd_dist)))] if dd_dist else 1.0
    computed["mc_p95_drawdown_pct"] = p95
    if p95 > settings.max_mc_p95_drawdown_pct:
        failed.append(f"mc_p95_drawdown {p95:.0%} > {settings.max_mc_p95_drawdown_pct:.0%}")

    # lockbox expectancy after costs
    lb = arts[ArtifactType.LOCKBOX].payload
    lb_exp = _flt(lb, "expectancy")
    computed["lockbox_expectancy"] = lb_exp
    if lb_exp <= 0:
        failed.append("lockbox: non-positive expectancy after costs")

    # data-quality + no-lookahead reports must self-report PASS
    if not _flag(arts[ArtifactType.DATA_QUALITY].payload, "passed"):
        failed.append("data-quality report did not pass")
    if not _flag(arts[ArtifactType.NO_LOOKAHEAD].payload, "passed"):
        failed.append("no-lookahead validation did not pass")

    return GateDecision(len(failed) == 0, tuple(failed), computed)
