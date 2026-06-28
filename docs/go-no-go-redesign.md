# Go/No-Go Redesign (Phase 0.7, Critical 3)

**Status:** implemented + tested (`src/novax/gate.py`, `tests/test_enforcement.py`,
`tests/test_gate_rejects_foreign_run_id.py`).

## Problem
The Phase 0.6 gate `evaluate_go_no_go` accepted caller-supplied booleans and scalars
(`survives_cost_stress`, `beats_randomized_entry`, `survives_one_bar_delay`,
`drawdown_pct`, …). A strategy could be passed by passing the right `True`s. With the
DSR object fixed, this trust surface became the easiest remaining bypass.

## Redesign principle
**The gate computes every verdict from registered artifacts and accepts no caller
truth.** Its only inputs are identifiers (`campaign_id`, `strategy`, `run_id`) and the
two registries. There is no boolean/scalar override anywhere in the signature.

```python
def evaluate_gate(
    *, campaign_id: str, strategy: str, run_id: str,
    artifacts: ArtifactRegistry, registry: TrialRegistry,
    settings: Settings = SETTINGS,
) -> GateDecision
```

## What it computes (and from which artifact)
| Criterion | Source artifact | Computation |
|---|---|---|
| sample size | `TRADE_LEDGER` | `len(pnls)` ≥ `min_oos_trades` |
| profit factor | `TRADE_LEDGER` | `profit_factor(pnls)` ≥ threshold |
| expectancy | `TRADE_LEDGER` | `expectancy(pnls)` > 0 |
| **drawdown_pct** | `EQUITY_CURVE` | recomputed peak-to-trough from the equity series (not caller-supplied) |
| **deflated Sharpe** | `TRADE_LEDGER` + **campaign** registry | `registry.deflated_sharpe_for_campaign(...)` using the campaign trial count |
| walk-forward pass rate | `WALK_FORWARD` | fraction of windows with positive expectancy |
| randomized-entry | `RANDOMIZED_ENTRY` | `percentile_rank(observed_stat, null_distribution)` ≥ threshold |
| one-bar-delay | `ONE_BAR_DELAY` | delayed expectancy > 0 and ≥ ½ base |
| cost-stress | `COST_STRESS` | `expectancy_at_1_5x` > 0 |
| MC p95 drawdown | `MONTE_CARLO_DD` | p95 of the bootstrap drawdown distribution |
| lockbox | `LOCKBOX` | one-shot expectancy > 0 |
| data quality | `DATA_QUALITY` | report self-reports `passed` |
| no lookahead | `NO_LOOKAHEAD` | validator self-reports `passed` |

## What it rejects (fail-closed)
- **Missing artifact** — any of `REQUIRED_ARTIFACTS` absent for the run ⇒ `NO_GO`
  (returns immediately; it cannot compute on absent inputs).
- **Foreign / mismatched run_id** — artifacts are looked up by `(run_id, type)`, so a
  foreign run's artifacts are simply not found ⇒ "missing artifact" ⇒ `NO_GO`
  (`test_gate_rejects_foreign_run_id`).
- **Provenance mismatch** — the `(data_hash, feature_version, cost_model_version)` tuple
  must be identical across the required set; mixing a stale artifact in ⇒ `NO_GO`.
- **Caller booleans** — there is no parameter to supply one; the legacy function now
  raises (`test_legacy_caller_boolean_gate_is_removed`).

## Decision schema
```python
@dataclass(frozen=True, slots=True)
class GateDecision:
    passed: bool
    failed_criteria: tuple[str, ...]
    computed: dict[str, float]   # every numeric the gate derived
    @property
    def verdict(self) -> str: ...  # "GO" | "NO_GO"
```
`computed` is the audit trail: drawdown_pct, deflated_sharpe, wf_pass_rate, etc., all
present so a reviewer can see exactly what the gate derived.

## Migration from the old API
| Old | New |
|---|---|
| `evaluate_go_no_go(metrics, survives_cost_stress=True, drawdown_pct=0.1, ...)` | emit artifacts via the runner, then `evaluate_gate(campaign_id, strategy, run_id, artifacts, registry)` |
| caller computes booleans | gate computes them from artifacts |
| `deflated_sharpe` passed in | gate pulls campaign DSR from the registry |
The legacy function is retained only as a hard `raise` so accidental calls fail loudly.

## Tests
- [x] no boolean override params (`test_gate_has_no_boolean_override_params`)
- [x] rejects missing artifacts (`test_gate_rejects_missing_artifacts`)
- [x] rejects provenance mismatch (`test_gate_rejects_provenance_mismatch`)
- [x] rejects foreign run_id (`test_gate_rejects_foreign_run_id`)
- [x] drawdown computed from equity curve (`test_drawdown_computed_from_equity_curve`)
- [x] best-of-200 random rejected end-to-end (`test_best_of_200_random_rejected_end_to_end`)
- [x] legacy gate raises (`test_legacy_caller_boolean_gate_is_removed`)

## Failure modes
| Failure | Behavior |
|---|---|
| any required artifact missing | `NO_GO`, early return |
| provenance tuple not unanimous | `NO_GO` |
| empty equity/ledger | drawdown/PF/expectancy fail their thresholds |
| campaign has only 1 logged trial (runner bypassed) | DSR not penalized — see honest residual in `trial-logging-enforcement.md` |

## Specced for Phase 1
The randomized-entry, one-bar-delay, and cost-stress artifacts currently carry
summary statistics computed by the harness battery; Phase 1 replaces the harness
proxies with the real engine's outputs (same artifact schema, real numbers).
