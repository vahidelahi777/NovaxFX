# Validation Protocol

**Status:** spec · **Owner:** Quant Lead · **Module target:** `libs/backtest/validation.py`

This protocol exists to stop us fooling ourselves. Most of the engineering rigor in Phase 0 lives here.

## Go / No-Go criteria (strict — most candidates should fail)

A strategy advances **only if it clears all of the following**:

| # | Criterion | Threshold |
|---|---|---|
| 1 | Data quality | ≥ 99.5% expected bars in trading hours; gaps quantified |
| 2 | Reproducibility | re-run from same commit + data_hash reproduces metrics **bit-for-bit** |
| 3 | Instruments | passes on **≥ 3 of 4** {EUR/USD, GBP/USD, USD/JPY, XAU/USD} |
| 4 | Date range | **≥ 5 years**, multiple regimes (incl. 2020 vol, 2022 trends) |
| 5 | Sample size | **≥ 200** OOS trades per strategy; thin samples → "inconclusive", not "pass" |
| 6 | Walk-forward | positive expectancy in **≥ 60%** of WF windows; no single window dominates PnL |
| 7 | Lockbox (OOS) | net-positive expectancy **after costs** on the never-touched lockbox |
| 8 | Max drawdown | backtest max DD ≤ 20% of risked notional; MC p95 DD ≤ 30% |
| 9 | Profit factor | **PF ≥ 1.25** after costs (≥ 1.3 preferred for thin samples) + positive per-trade expectancy |
| 10 | Cost degradation | survives **1.5× cost** stress (see cost-model-spec) |
| 11 | Stability | no single session/regime > **50%** of PnL; not heavily negative in any major regime |
| 12 | Statistical confidence | **Deflated Sharpe Ratio > 0** (corrected for # trials); naive Sharpe inadmissible |

> If a strategy "barely passes" several criteria, treat it as a **fail**. The expensive mistake in Phase 0 is a false positive that triggers a build.

## Kill conditions (immediate reject)

- Edge vanishes after costs.
- Works on only one instrument / one window / one regime.
- Depends on data the live system won't have at decision time (lookahead).
- Requires parameter precision — a sharp optimum with no plateau.
- Sample too small to be statistically meaningful.

## Methodology

### Splitting
- **Chronological only.** Never shuffle time series.
- Reserve a final **lockbox** slice on day 1. Open it **once**, at go/no-go. Touch it twice → it is no longer out-of-sample.

### Walk-forward
- Rolling optimize→test windows. Report per-window expectancy.
- No single window may contribute the majority of total PnL.

### Purged k-fold + embargo (when any fitting/labeling occurs)
- **Purge** train samples whose labels overlap the test window.
- **Embargo** a gap after each test window to kill leakage from autocorrelation.
- Standard k-fold leaks on time series and is forbidden here.

### Labeling
- Use the **triple-barrier method** (profit target / stop / time limit, whichever hits first). No naive fixed-horizon labels.

### Monte Carlo
- Resample trade order/returns → distribution of drawdown and terminal wealth.
- Judge the **distribution**, not a single equity curve. Report p50 and p95 DD.

### Deflated Sharpe Ratio
- Discount the Sharpe for the **number of configurations tested**.
- Require the **Deflated Sharpe probability > 0.95** (i.e. ≥95% chance the edge is real after correcting for the number of trials). **Superseded note (Phase 0.7):** an earlier draft said "DSR > 0", which is far too weak — a probability just above zero still means the result is almost certainly luck. The code and `config.Settings.min_deflated_sharpe_probability` enforce 0.95, and the trial count is taken from the **campaign-level** trial registry (every evaluation logged via `ExperimentRunner`), not a caller-supplied integer. See `docs/phase-0.7/go-no-go-redesign.md` and `dsr-hardening`. This is the antidote to "we tested 200 variants and one looked great."

### Parameter robustness
- Require a **plateau**: neighboring parameter values perform similarly.
- A lone sharp peak is overfitting; reject it regardless of headline metrics.

### Multiple-testing control
- Log **every** configuration tested (instrument × params × variant) to the experiment log.
- Feed the count into the DSR. Wide grids manufacture fake winners — keep grids small.

### Breakdowns (always report)
- Performance sliced by **session** and **regime**.
- Performance by sub-period (early vs late) to detect decay.

### Cost sensitivity
- {1.0×, 1.25×, 1.5×} stress is part of validation, not optional. See cost-model-spec.

## Reproducibility requirement

Every result row records: `code_commit`, `data_hash`, `params`, `cost_model`, `cost_stress_factor`. A second run from the same tuple must reproduce metrics bit-for-bit, or the result is void.

## Acceptance criteria

- [ ] Walk-forward implemented with per-window reporting.
- [ ] Lockbox enforced in code (access counter; warns/fails on second open).
- [ ] Purged k-fold + embargo available for any fitted component.
- [ ] Triple-barrier labeling implemented + unit-tested.
- [ ] Monte Carlo trade-sequence simulation with p50/p95 DD.
- [ ] Deflated Sharpe computed from logged trial count.
- [ ] Parameter-robustness (plateau) report generated.
- [ ] Session/regime/sub-period breakdowns produced automatically.
- [ ] Reproducibility test: same inputs → identical metrics.
