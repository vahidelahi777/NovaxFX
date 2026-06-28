# Validation Hardening Spec

**Module:** `src/novax/validation.py` (+ `lookahead.py`) · **Owner:** Senior Backtesting Engineer + Statistical Methodology Expert
**Closes:** Phase 0.5 Critical #3, High #8, High #9, and stands up the destructive battery.

Each item: purpose · implementation sketch · acceptance.

## Walk-forward window generator
- **Purpose:** chronological optimize→test windows; defeats single-period overfitting.
- **Sketch:** `walk_forward_windows(start, end, *, train, test, step=test)` rolls anchored windows while `test_end <= end`; each `WalkForwardWindow` asserts `train_start < train_end <= test_start < test_end`; tz-aware required.
- **Acceptance:** ≥2 non-overlapping chronological windows; naive datetimes raise. *(Tested.)*

## Purged k-fold + embargo
- **Purpose:** cross-validation without label leakage from autocorrelation.
- **Sketch:** `purged_kfold(n, *, n_splits, embargo)` — contiguous test block per fold; train excludes the block **and** any index within `embargo` of its boundaries (purge + embargo).
- **Acceptance:** train∩test = ∅; no train index within `embargo` of the test boundary. *(Tested.)*
- **Note:** index-based; true purge needs label *times* — wire label spans when the engine produces them.

## Block bootstrap
- **Purpose:** resample preserving trade clustering; naive i.i.d. shuffle understates tail risk.
- **Sketch:** `block_bootstrap(values, *, block_size, n_resamples, seed)` moving-block; `bootstrap_statistic(...)` maps a stat over resamples.
- **Acceptance:** length preserved; seed-deterministic; full-length block preserves local order. *(Tested.)*

## Monte Carlo drawdown
- **Purpose:** distribution of drawdown/terminal wealth, not a single curve.
- **Sketch:** `bootstrap_statistic(pnls, max_drawdown, block_size=…, n_resamples=…)`; report p50/p95.
- **Acceptance (Phase 1 wiring):** p95 DD feeds the go/no-go (`max_mc_p95_drawdown_pct`).

## Randomized-entry benchmark
- **Purpose:** is the edge in the *signal* or just the exits/costs?
- **Sketch:** replace entries with random timestamps (same exit/SL/TP/cost), build a null of the chosen stat, compare via `percentile_rank(strategy_stat, null)`.
- **Acceptance:** strategy must exceed `randomized_entry_percentile` (0.95). Gate field `beats_randomized_entry`. *(Stat helper tested; full wiring needs the engine.)*

## One-bar-delay test
- **Purpose:** detect lookahead / un-fillable edge.
- **Sketch:** shift all fills one bar later; recompute metrics; compare to base.
- **Acceptance:** edge must survive; collapse ⇒ lookahead. Gate field `survives_one_bar_delay`. *(Engine-level; gate field exists.)*

## Label-shuffle / sign-flip sanity
- **Purpose:** prove the harness itself isn't leaking.
- **Sketch:** `shuffle_pnls_mean(pnls, n_shuffles)` — permuted mean ≈ permutation of the same values; a leaky harness shows structure.
- **Acceptance:** shuffled mean ≈ true mean (permutation invariant); harness sanity. *(Tested.)*

## Cost stress tests
- **Purpose:** reject knife-edge edges.
- **Sketch:** `CostModel.with_stress(f)` for `f ∈ {1.0,1.25,1.5,2.0}`; require positive at ≥1.5×.
- **Acceptance:** negative at 1.5× ⇒ reject. Gate field `survives_cost_stress`. *(Cost mechanics tested.)*

## Parameter robustness
- **Purpose:** require a plateau, not a peak.
- **Sketch:** evaluate neighbors of the chosen params; require neighborhood within a tolerance band.
- **Acceptance (Phase 1):** plateau check produced per strategy.

## No-lookahead property tests
- **Purpose:** the most important class — every feature proven causal.
- **Sketch:** `assert_no_lookahead(feature_fn, data)` recomputes the feature on truncated history `data[:i+1]` and asserts value[i] matches the full-history value[i]; `find_lookahead_indices` returns offenders.
- **Acceptance:** clean feature passes; leaky feature raises. **Every feature added in Phase 1 must ship one.** *(Tested with clean + leaky examples.)*

## How these enter the gate

`evaluate_go_no_go` now takes the computed `DeflatedSharpeResult` plus boolean results of `beats_randomized_entry` and `survives_one_bar_delay`, alongside the existing thresholds. Any failure ⇒ NO_GO.

## Acceptance criteria (summary)

- [x] Walk-forward, purged-CV+embargo, block bootstrap implemented + tested.
- [x] No-lookahead harness implemented; catches a leak.
- [x] Destructive-battery stat helpers (percentile rank, label-shuffle) tested.
- [x] Go/no-go consumes DSR object + randomized-entry + one-bar-delay flags.
- [ ] (Phase 1) Engine wires randomized-entry, one-bar-delay, MC, plateau end-to-end.
