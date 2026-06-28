# Minimal Research Harness (Phase 0.7)

**Status:** implemented + tested (`src/novax/harness.py`, `src/novax/battery.py`,
`tests/test_battery_and_ci.py`).

> **This is not a strategy engine and produces no edge.** Its sole purpose is to drive
> the runner → artifact → gate loop with realistic-shaped data so the enforcement layer
> can be tested end-to-end. Real strategies, features, and ingested data are Phase 1.

## Components

### `BaselineRandomStrategy` (implemented)
- **Purpose:** a deliberately edgeless source of per-trade PnL (i.i.d. Gaussian).
- **Inputs:** `seed`, optional `mean`, `sd`. **Output:** `generate(n) -> list[float]`.
- **Metadata:** seed only (determinism). **Tests:** drives the best-of-200 rejection.
- **Acceptance:** identical seed ⇒ identical series; mean ≈ 0 ⇒ no edge.

### `equity_from_pnls` / `emit_required_artifacts` (implemented)
- **Purpose:** turn a PnL series into an equity curve and emit the full
  `REQUIRED_ARTIFACTS` set through `Evaluation.emit` (favorable side-artifacts by
  default so a test can isolate which criterion fails).
- **Acceptance:** every required artifact emitted; all carry run/trial provenance.

### `ValidationBatteryRunner` (implemented — `battery.py`)
Emits the validation artifacts the gate consumes, all through `Evaluation.emit`
(so each inherits run_id/trial_id/provenance — no free-floating artifacts).

| Emits | From | How (deterministic, seeded) |
|---|---|---|
| `RANDOMIZED_ENTRY` | pnls | null = mean of block-bootstrap resamples; observed = mean(pnls) |
| `ONE_BAR_DELAY` | pnls / delayed_pnls | base vs delayed expectancy |
| `COST_STRESS` | stressed_pnls | expectancy at 1.5× costs |
| `WALK_FORWARD` | window_pnls | per-window expectancy |
| `MONTE_CARLO_DD` | pnls | block-bootstrap drawdown distribution (preserves autocorrelation) |
| `NO_LOOKAHEAD` | validator flag | pass/fail |
| `DATA_QUALITY` (optional) | bars | `run_data_quality(...)` report |

- **Inputs:** `BatteryInputs(pnls, delayed_pnls?, stressed_pnls?, window_pnls?,
  no_lookahead_passed?, bars?, symbol?, timeframe?)`.
- **Required metadata:** supplied by the `Evaluation` (run_id, trial_id, campaign_id,
  provenance) — the battery cannot be called without one.
- **Acceptance:** emits all six (+ optional data-quality) artifacts; raises on empty PnL.
- **No trading logic:** it consumes observable backtest outputs, it does not generate signals.

### `DataQualityGateRunner` (implemented — `battery.py`)
- **Purpose:** run `run_data_quality` and emit the `DATA_QUALITY` artifact; the gate
  treats a missing one as `NO_GO`.
- **Inputs:** `Evaluation`, `symbol`, `timeframe`, `bars`. **Output:** the report.
- **Tests:** `test_data_quality_runner_emits_artifact_and_gate_requires_it` —
  gate is `NO_GO` (missing data_quality) before the runner, and that specific failure
  disappears after it emits.
- **Acceptance:** artifact present after `run`; report `.passed` is a real fail-closed bool.

### Component stubs specced for Phase 1
`BacktestRun`, `TradeLedger`, `FeatureMatrix`, `LabelSeries`, `StrategyStub`,
`RandomizedEntryBenchmark`, `OneBarDelayRunner`, `CostStressRunner`,
`MonteCarloDrawdownRunner`, `WalkForwardEvaluator`, `NoLookaheadValidator` — these are
the Phase 1 engine surfaces. In Phase 0.7 their *outputs* are represented by the
battery's artifact payloads (same schemas), so the gate and CI are exercised now; the
real generators replace the proxies without changing the artifact contracts.

## End-to-end flow (implemented and tested)
```
ExperimentRunner.evaluate ──┐  (logs RUNNING trial, blesses trial_id)
                            ▼
   BaselineRandomStrategy → pnls
   emit EQUITY_CURVE, TRADE_LEDGER, LOCKBOX
   ValidationBatteryRunner.run(ev, BatteryInputs(...))  → 6 validation artifacts
   DataQualityGateRunner.run(ev, bars=...)              → DATA_QUALITY
                            ▼  (marks COMPLETE)
   evaluate_gate(campaign_id, strategy, run_id, ...)    → GO / NO_GO
   audit_campaign_integrity(...)                        → [] (healthy)
```

## Acceptance criteria
- [x] The harness drives the full loop without any strategy logic.
- [x] The luckiest of 200 random trials is rejected (campaign DSR).
- [x] Distinct artifact trial-ids equal the count of completed trials
      (`test_ci_integrity_artifact_count_equals_trial_count`).
- [x] No component can emit an artifact without an `Evaluation`.
