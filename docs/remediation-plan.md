# Phase 0.6 — Remediation & Research Hardening

**Status:** in progress · **Source of truth:** the Phase 0.5 Red Team Audit · **Gate:** no strategy research begins until every Critical and High finding is closed and verified by tests.

> This is a **hardening phase, not a strategy phase.** No signals, no parameter optimization, no edge claims, no ML, no broker execution, no dashboard. The single objective is to make it impossible for a future backtest to *quietly* produce false confidence.

---

## 1. Objective

Close every Critical and High finding from the Phase 0.5 audit so that the research platform fails loudly instead of silently. The audit's central indictment — "the platform is optimized to *look* rigorous while its most important safeguard does nothing by default" — is the thing this phase exists to fix. Success is measured by tests that *prove* a fooled result is now caught (e.g., the luckiest of 200 random trials is rejected), not by adding capability.

## 2. Remediation Principles

- **Fail closed.** Missing or invalid inputs raise; they never silently fall back to a permissive default. (The DSR no-op is the canonical violation being fixed.)
- **No silent statistical defaults.** Any parameter whose default could disable a correction (e.g. `sr_variance=0`) is mandatory, not defaulted.
- **Single source of truth for thresholds.** All go/no-go numbers live in `config.Settings`; docs reference them, never re-state them as independent copies.
- **No metric without provenance.** A reported metric must carry commit + data hash + config hash + seed, or it is inadmissible.
- **No backtest without a data-quality report.** The data gate runs first and must pass (fail-closed) before any backtest is accepted.
- **No feature without no-lookahead tests.** Every feature ships with a property test proving its value at *t* doesn't depend on data after *t*.
- **No strategy without the destructive battery.** Randomized-entry, one-bar-delay, cost-stress, block-bootstrap, and regime/cross-instrument tests are required to pass.
- **Explicit trial accounting.** The DSR trial count comes from the trial registry, never a human guess; hidden trials are impossible by construction.
- **UTC-only internal timestamps.** Naive datetimes are rejected at every boundary.

## 3. Critical Fix Plan

### C1 — Deflated Sharpe silently disabled
- **Failure:** `deflated_sharpe_ratio(..., n_trials=N)` returned the same value for any N because `sr_variance` defaulted to 0, which zeroed the expected-max-Sharpe benchmark. The multiple-testing correction did nothing.
- **Danger:** the luckiest of many trials passes as if it were a single tested hypothesis — the textbook fabricated edge.
- **Fix:** make `sr_variance` a **required** argument (no default); raise when `n_trials > 1` and `sr_variance <= 0`. Compute the trial count and cross-trial Sharpe variance from the **trial registry**. Return a `DeflatedSharpeResult` that echoes inputs and carries warning flags (normal-kurtosis, small-sample, single-trial). Default kurtosis to an FX-realistic estimate (6), not 3.
- **Code changes:** `validation.py` (`deflated_sharpe_ratio`, `estimate_sr_variance`, `expected_max_sharpe`, `DeflatedSharpeResult`); `trial_registry.py` (`deflated_sharpe_for`); `config.py` (`min_deflated_sharpe_probability=0.95`, `fx_kurtosis_estimate=6`).
- **Tests required:** reject multi-trial with zero variance; reject invalid n_trials/n_obs; **prove more trials ⇒ lower probability**; warnings present; registry path computes variance from logged trials; end-to-end "best-of-200 random trials is rejected."
- **Acceptance:** the no-op is impossible (raises), and the campaign-level proof rejects a luck-only winner. **Status: DONE & verified.**

### C2 — No backtest engine / feature layer / ingested data
- **Failure:** high-risk surfaces (lookahead, fills, realized spread) had zero coverage because the components that produce results didn't exist.
- **Danger:** nothing could be trusted *or* tested.
- **Fix (Phase 0.6 scope):** build the *safety scaffolding* those components will sit on — no-lookahead test harness, validation splitters, data-quality gate, cost realism hooks, provenance — **before** the engine. The engine itself is Phase 1, but it must be born into a harness that catches its mistakes.
- **Code changes:** `lookahead.py`, `validation.py` (splitters/bootstrap), `dataquality.py`, `provenance.py`, `costs.py` (realized-spread/news/worst-case).
- **Tests required:** lookahead helper catches a leaky feature; splitters have no leakage; data gate flags contamination.
- **Acceptance:** when the engine is built, every dangerous surface already has a failing-by-default test waiting for it. **Status: scaffolding DONE; engine remains Phase 1.**

### C3 — No lookahead/leakage tests, no purged-CV/embargo
- **Failure:** the protocol mandated purged k-fold + embargo and no-lookahead tests; none existed.
- **Danger:** lookahead is the most likely single cause of a fake FX edge and was entirely untested.
- **Fix:** ship `assert_no_lookahead`/`find_lookahead_indices` (recompute on truncated history, diff), `purged_kfold(n, n_splits, embargo)` (contiguous test folds, purge + embargo around boundaries), and `walk_forward_windows` (chronological, non-overlapping).
- **Code changes:** `lookahead.py`, `validation.py`.
- **Tests required:** clean feature passes; leaky feature is caught; purged folds have no train/test overlap and enforce the embargo gap; walk-forward windows are chronological/non-overlapping.
- **Acceptance:** a leaky feature cannot pass CI; CV cannot leak across the embargo. **Status: DONE & verified.**

## 4. High Fix Plan

### H4 — `OVERLAP` never emitted
- **Fix:** `active_sessions` appends `"OVERLAP"` when London∩NewYork; add `primary_session` returning `"OVERLAP"` first for cost lookup.
- **Tests:** overlap instant yields `"OVERLAP"`; `primary_session` resolves correctly.
- **Acceptance:** the overlap multiplier and instrument metadata now fire. **Files:** `sessions.py`. **Status: DONE.**

### H5 — DST-wrong weekend open/close
- **Fix:** `MarketCalendar` anchors the week boundary at NY 17:00 *local*, so the UTC boundary shifts with DST (22:00 UTC winter / 21:00 UTC summer). `is_fx_market_open` delegates to it.
- **Tests:** Fri 21:30 UTC winter = open (was the bug); Fri 22:30 UTC winter = closed; Sunday reopen correct in summer; holiday closes market.
- **Acceptance:** no hardcoded UTC weekend constant remains. **Files:** `market_calendar.py`, `sessions.py`. **Status: DONE.**

### H6 — Static cost model
- **Fix:** realized-spread path (already present, now never below floor), `news=True` blow-out multiplier on spread+slippage, ATR-unit guard (`_as_pips`), commission **no longer** scaled by stress (fixed fee), worst-case fill via adverse-stop slippage.
- **Tests:** news widens cost; ATR-unit guard rejects implausible values; commission unaffected by stress; spread floor enforced.
- **Acceptance:** cost responds to conditions; commission modeling correct. **Files:** `costs.py`. **Status: core DONE; full volatility-driven spread curve is Phase 1.**

### H7 — No holiday calendar
- **Fix:** injectable holiday set on `MarketCalendar`; data-quality gate flags closed-market (weekend/holiday) bars.
- **Tests:** holiday closes market; data gate flags weekend/holiday contamination.
- **Acceptance:** holiday-contaminated bars fail the gate. **Files:** `market_calendar.py`, `dataquality.py`. **Status: DONE (minimal set; extend per venue).**

### H8 — Trade-independence assumed
- **Fix:** `block_bootstrap` (moving-block) replaces naive i.i.d. shuffle, preserving clustering; DSR documents its IID assumption and uses FX kurtosis.
- **Tests:** block bootstrap preserves length, is seed-deterministic, preserves local order within a full-length block.
- **Acceptance:** resampling no longer destroys autocorrelation. **Files:** `validation.py`. **Status: DONE.**

### H9 — Walk-forward missing
- **Fix:** `walk_forward_windows` generator (train/test/step) producing validated, chronological, non-overlapping windows.
- **Tests:** ≥2 windows, all chronological/non-overlapping; aware-datetime required.
- **Acceptance:** the 60%-of-windows criterion now has windows to compute against. **Files:** `validation.py`. **Status: DONE (per-window aggregation wires up with the engine in Phase 1).**

## 5. Proposed Code Architecture Changes

Minimal, research-appropriate. Modules added/changed in `src/novax/`:

| Module | Role |
|---|---|
| `sessions.py` | sessions + `OVERLAP` emission + `primary_session` |
| `market_calendar.py` | DST-correct open/close + holidays (new) |
| `costs.py` | realized spread, news multiplier, ATR guard, fixed commission |
| `validation.py` | metrics, fail-closed DSR, walk-forward, purged k-fold + embargo, block bootstrap, destructive-battery stats |
| `trial_registry.py` | append-only trial log feeding DSR (new) |
| `lookahead.py` | no-lookahead property-test helpers (new) |
| `dataquality.py` | data-quality report + checks (new) |
| `provenance.py` | run provenance + hashing (new) |
| `config.py` | single source of truth incl. new thresholds |

No service, no engine, no ML — by design.

## 6–16

Sections 6 (DSR redesign), 7 (trial registry), 10 (validation hardening), 11 (data-quality gate) are delivered as standalone specs in this directory. Sections 8–9, 12–13 are realized directly in code + tests (see the scaffold). The revised go/no-go and definition of done are below.

### Updated Go/No-Go (post-0.6)
A strategy is eligible for consideration only when **all** hold:
required tests green (incl. no-lookahead for every feature) · a passing `DataQualityReport` for each instrument · walk-forward + purged-CV artifacts · DSR (from the registry) probability **> 0.95** · PF ≥ 1.25 and positive expectancy after costs · max DD ≤ 20%, MC p95 DD ≤ 30% · ≥ 3/4 instruments · no slice > 50% of PnL · survives cost stress (≥1.5×) · **beats the randomized-entry null** · **survives the one-bar-delay test** · full provenance recorded.

### Definition of Done (strict)
Phase 0.6 is complete when, and only when:
1. All Critical (C1–C3) and High (H4–H9) findings are closed with code **and** tests proving the fix.
2. `ruff`, `mypy --strict`, and the full `pytest` suite pass in CI.
3. The DSR no-op is impossible (raises) **and** the "best-of-200-random-trials → reject" proof passes.
4. Every feature-style function has a no-lookahead test; CV uses purge + embargo.
5. A `DataQualityReport` is required (fail-closed) before any backtest path runs.
6. Provenance is captured for any produced metric.
7. The five Phase 0.6 specs exist and match the shipped code.
No item is "mostly done." Any open item ⇒ Phase 0.6 is not complete.

---

*Hardening only. No edge is claimed or implied. The deliverable is a platform that fails loudly.*
