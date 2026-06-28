# Phase 0.7 — Implementation Patch Plan (Checklist)

**Inputs:** Phase 0.6 codebase · Phase 0.5 re-run audit vs 0.6 · Phase 0.7 enforcement plan.
**Honest status note:** much of this is already implemented and green in `novax-scaffold`
(70 tests pass, ruff clean, mypy --strict clean). Each item is flagged
**[DONE]** / **[PARTIAL]** / **[TODO]** against the live code. This is a reconciliation
plan, not a greenfield one. No strategies, ML, broker execution, or dashboard.

Legend: 🟢 DONE · 🟡 PARTIAL · 🔴 TODO

---

## 1. Files to create

| Path | Status | Purpose | Main classes/functions | Depends on | Tests required |
|---|---|---|---|---|---|
| `src/novax/units.py` | 🟢 | Typed measurement units; kill ATR float ambiguity | `Pips`, `PriceUnits`, `to_pips`, `to_price`, `require_pips` | `instruments` | ATR-price-unit-misuse rejected |
| `src/novax/artifacts.py` | 🟢 | Provenance-stamped artifact registry | `ArtifactType`, `Artifact`, `ArtifactRegistry` | `provenance` | artifact-without-trial rejected; orphan detection; dup detection |
| `src/novax/runner.py` | 🟢 | Non-bypassable trial logging | `Evaluation`, `ExperimentRunner`, `audit_artifacts_match_trials`, `audit_campaign_integrity` | `trial_registry`, `artifacts`, `provenance` | logging-fail-closed; under-logging; campaign integrity |
| `src/novax/gate.py` | 🟢 | Artifact-driven Go/No-Go | `GateDecision`, `evaluate_gate`, `REQUIRED_ARTIFACTS` | `artifacts`, `trial_registry`, `validation`, `config` | missing/mismatch rejected; drawdown computed; best-of-200 |
| `src/novax/harness.py` | 🟢 | Minimal loop to exercise safeguards (no edge) | `BaselineRandomStrategy`, `emit_required_artifacts`, `equity_from_pnls` | `runner`, `artifacts`, `validation` | best-of-200 end-to-end |
| `tests/test_enforcement.py` | 🟢 | Adversarial bypass suite (15 tests) | — | all above | (is itself the tests) |
| `scripts/ci_guards.py` | 🔴 | Static CI guards (grep/AST) | `check_no_raw_registry_log`, `check_gate_no_bool`, `check_no_raw_float_atr`, `check_docs_threshold` | stdlib only | guard self-tests |
| `docs/phase-0.7/go-no-go-redesign.md` | 🔴 | Gate redesign spec | — | — | — |
| `docs/phase-0.7/minimal-research-harness.md` | 🔴 | Harness component spec | — | — | — |
| `docs/phase-0.7/calendar-cost-hardening.md` | 🔴 | Calendar + ATR/cost spec | — | — | — |
| `docs/phase-0.7/test-plan.md` | 🔴 | Grouped test plan | — | — | — |

## 2. Files to modify

| Path | Status | Current weakness | Exact change | Back-compat impact | Tests |
|---|---|---|---|---|---|
| `src/novax/trial_registry.py` | 🟢 | family was `(strategy,instrument,timeframe)` only; no campaign count; double-count from two-phase log | add `campaign_id`+`status` to `Trial`; `campaign_*` methods; `latest()` dedup by `result_id`; low-variance warning | `Trial` gains fields (defaults keep old construction working) | instrument-selection counted; campaign count = 200 |
| `src/novax/costs.py` | 🟢 | raw-float ATR; half-blind magnitude guard | `atr: Pips` at every boundary via `require_pips`; `_ZERO_PIPS` default; commission excluded from stress scaling | **breaking**: `atr_pips=float` → `atr=Pips(...)` | ATR-unit rejected; commission-not-stressed |
| `src/novax/market_calendar.py` | 🟢 | hardcoded 7-date stub; midweek holidays missed | `CalendarProvider` protocol + `ComputedHolidayProvider` (Easter/Good Friday, Thanksgiving, July4 observed, half-days); fail-closed | `MarketCalendar(holidays=...)` → `provider=...` | Thanksgiving/Good Friday closed |
| `src/novax/validation.py` | 🟢 | `evaluate_go_no_go` trusted caller booleans; `max_drawdown` computed-but-unused | replace body with hard `raise RuntimeError` pointing to `gate.evaluate_gate` | **breaking**: legacy gate now raises | legacy-gate-removed |
| `src/novax/__init__.py` | 🟡 | exports | export Phase 0.7 symbols (`ExperimentRunner`, `evaluate_gate`, `Pips`, …) | additive | import smoke test |
| `docs/phase-0/validation-protocol.md` | 🟢 | "DSR > 0" contradicts code (0.95) | superseded note → probability > 0.95, campaign-level count | docs only | docs-threshold guard (🔴) |

## 3. Core API changes

- **ExperimentRunner** 🟢 — `evaluate(*, strategy, instrument, timeframe, session, params, random_seed, validation_split="research") -> ContextManager[Evaluation]`. `Evaluation.emit(type, payload)`, `Evaluation.set_sharpe(x)`. Logs `RUNNING` before body; `COMPLETE`/`FAILED` after; no result if log fails.
- **TrialRegistry** 🟢 — adds `campaign(campaign_id, strategy)`, `campaign_n_trials`, `campaign_sharpes`, `deflated_sharpe_for_campaign(...)`, `latest()` (dedup), `trial_ids()`. `Trial` gains `campaign_id`, `status`.
- **ArtifactRegistry** 🟢 — `register_trial_id(trial_id)`, `register(*, run_id, trial_id, campaign_id, artifact_type, provenance, payload, parent_ids=())`, `by_type(run_id, type)`, `orphans(known_ids)`, `all()`. Refuses unblessed trial_id; rejects duplicate `(run_id, type)`.
- **GoNoGoEvaluator** 🟢 — replaced by `gate.evaluate_gate(*, campaign_id, strategy, run_id, artifacts, registry, settings=SETTINGS) -> GateDecision`. **No boolean/scalar verdict params.** Computes every criterion from artifacts.
- **ValidationBatteryRunner** 🟡 — exists implicitly via `emit_required_artifacts` (emits walk-forward / randomized-entry / one-bar-delay / cost-stress / MC / lockbox artifacts). 🔴 to formalize as a named class with per-runner methods + provenance lineage.
- **DataQualityGateRunner** 🟡 — `dataquality.run_data_quality(...)` exists and produces a report; 🔴 to wire it as an emitted `DATA_QUALITY` artifact inside the harness path and make it a hard gate input.
- **CalendarProvider** 🟢 — `Protocol{ full_closures(year)->set[date]; half_days(year)->set[date] }`; default `ComputedHolidayProvider`. `MarketCalendar(provider=...)`, `is_open(dt_utc)`, `is_fx_market_open(dt)`.
- **CostModel** 🟢 — `round_trip_cost_pips(symbol, *, atr: Pips=_ZERO_PIPS, ...)`, `round_trip_cost_currency(..., atr: Pips=...)`, `with_stress(factor)` (commission excluded from scaling).
- **ATR/Pip unit types** 🟢 — `Pips(value)`, `PriceUnits(value)`, `to_pips(instrument, PriceUnits)->Pips`, `require_pips(x)` raises on raw float / PriceUnits.

## 4. Migration path

| From (Phase ≤0.6) | To (Phase 0.7) | How |
|---|---|---|
| manual `registry.log(Trial(...))` in research code | mandatory `with runner.evaluate(...) as ev:` | wrap each evaluation; runner logs + blesses + stamps automatically |
| `evaluate_go_no_go(metrics, survives_cost_stress=True, ...)` booleans | `evaluate_gate(campaign_id, strategy, run_id, artifacts, registry)` | emit required artifacts via `ev.emit(...)`; gate computes verdicts |
| `cost_model.round_trip_cost_pips(sym, atr_pips=10.0)` | `...(sym, atr=Pips(10.0))` or `to_pips(inst, PriceUnits(0.0010))` | convert call sites; raw float now raises |
| `MarketCalendar(holidays=frozenset({...}))` | `MarketCalendar(provider=ComputedHolidayProvider())` (default) | drop hardcoded set; provider computes any year |
| optional provenance fields | mandatory provenance on every artifact | runner supplies provenance dict; missing fields fail closed |

## 5. Breaking changes (with justification)

1. 🟢 **`evaluate_go_no_go` now raises.** Justification: it trusted caller booleans — the exact Critical-3 bypass. A loud removal prevents accidental use of the trust-based path.
2. 🟢 **CostModel ATR params are `Pips`, not `float`.** Justification: raw floats let price-unit ATR pass silently (Critical/High 2). Typed boundary makes the error impossible.
3. 🟢 **`MarketCalendar(holidays=...)` → `provider=...`.** Justification: the hardcoded stub missed midweek holidays; the provider computes them and fails closed.
4. 🟢 **`Trial` requires/defaults `campaign_id` + `status`.** Justification: multiple-testing must be counted at campaign scope; aborted trials must still count. Defaults preserve old positional construction.
5. 🟡 **Artifacts mandatory for Go/No-Go.** Justification: "no validation claim without an artifact path." Anything calling a gate must now produce artifacts. (Mechanically enforced in `gate.py`; 🔴 CI guard to forbid re-introducing a boolean gate.)

## 6. Test additions

All in `tests/test_enforcement.py` unless noted.

| Required test | Status | Name |
|---|---|---|
| under-logging attack fails | 🟢 | `test_under_logging_attack_fails_via_runner` |
| logging failure fail-closed | 🟢 | `test_no_result_if_trial_logging_fails` |
| artifact without trial rejected | 🟢 | `test_no_artifact_without_trial_id` |
| Go/No-Go boolean override rejected | 🟢 | `test_gate_has_no_boolean_override_params`, `test_legacy_caller_boolean_gate_is_removed` |
| missing artifact rejected | 🟢 | `test_gate_rejects_missing_artifacts` |
| mismatched run_id rejected | 🟡 | covered indirectly (lookup keyed by `run_id` ⇒ other-run artifacts read as "missing"); **🔴 add explicit `test_gate_rejects_foreign_run_id`** |
| best-of-200 random rejected | 🟢 | `test_best_of_200_random_rejected_end_to_end` |
| instrument selection counted | 🟢 | `test_instrument_selection_counts_as_multiple_testing` |
| Thanksgiving 2025 calendar | 🟢 | `test_thanksgiving_2025_handled` |
| ATR price-unit misuse rejected | 🟢 | `test_atr_price_units_rejected` |
| fixed commission stress | 🟢 | `test_commission_not_stress_multiplied` |
| artifact count == logged trial count | 🟢 | `test_campaign_integrity_flags_silent_discard` (+ `audit_campaign_integrity`) |
| provenance mismatch rejected | 🟢 | `test_gate_rejects_provenance_mismatch` |
| orphan artifact detected | 🟢 | `test_orphan_artifact_detected` |
| drawdown computed from equity curve | 🟢 | `test_drawdown_computed_from_equity_curve` |

**Net remaining test work:** 🔴 one explicit foreign-run_id test; 🔴 self-tests for the CI guard script.

## 7. CI enforcement

| Check | Status | Implementation |
|---|---|---|
| artifact count == trial count | 🟡 | `audit_campaign_integrity` exists; 🔴 wire into a `pytest` that runs it over a representative campaign in CI |
| no direct construction of result artifacts outside runner | 🔴 | grep/AST guard: forbid `ArtifactRegistry().register(` and bare `registry.log(Trial(` in `src/` research paths (allow in `runner.py`, tests) |
| no public Go/No-Go API accepting booleans | 🟡 | runtime test `test_gate_has_no_boolean_override_params` exists; 🔴 add AST guard forbidding `: bool` params in any `evaluate*gate*` signature |
| no raw float ATR at public cost boundaries | 🔴 | AST guard: cost-model public methods must annotate `atr: Pips` |
| docs threshold consistency | 🔴 | grep guard: fail if any doc contains `DSR > 0` without "superseded" |

Deliver as `scripts/ci_guards.py` (stdlib-only, exit-nonzero on violation) invoked from the test job.

## 8. Implementation order (safest)

1. 🟢 `units.py` (no deps) → migrate `costs.py` to `Pips`.
2. 🟢 `market_calendar.py` provider (independent).
3. 🟢 `provenance.py` helpers → `artifacts.py`.
4. 🟢 `trial_registry.py` campaign accounting + `latest()` dedup.
5. 🟢 `runner.py` (`ExperimentRunner` + audits) — depends on 3+4.
6. 🟢 `gate.py` artifact-driven — depends on 3+4+5.
7. 🟢 deprecate `validation.evaluate_go_no_go`.
8. 🟢 `harness.py` minimal loop — depends on 5+6.
9. 🟢 `tests/test_enforcement.py`.
10. 🔴 `scripts/ci_guards.py` + remaining docs.

Rationale: leaves zero window where a result can be produced without logging — the gate (6) cannot exist before the runner (5), and the legacy gate is removed (7) only after the replacement is proven.

## 9. Verification commands

```bash
cd novax-scaffold
PYTHONPATH=src python -m pytest -q                       # full suite (currently 70 passing)
PYTHONPATH=src python -m pytest tests/test_enforcement.py -q   # adversarial bypass suite
ruff check src tests                                     # lint (currently clean)
mypy --strict src                                        # types (currently clean, 17 files)
# 🔴 once added:
python scripts/ci_guards.py                              # static enforcement guards
```

## 10. Expected final behavior

After Phase 0.7 the system behaves as follows (🟢 = observed in the current build):

- 🟢 The **only** way to run an evaluation is `ExperimentRunner.evaluate`; if trial logging fails, the body never runs and no result is returned.
- 🟢 No artifact can exist without a blessed `trial_id`; every artifact carries full provenance + a content hash.
- 🟢 `evaluate_gate` computes **every** criterion from registered artifacts — drawdown from the equity curve, PF/expectancy from the ledger, DSR from the **campaign** trial count — and exposes no boolean/scalar override. Missing, stale, or provenance-mismatched artifacts ⇒ `NO_GO`.
- 🟢 The luckiest of 200 random trials is rejected end-to-end (campaign DSR ≈ 0.45 ≤ 0.95).
- 🟢 Selecting the best instrument/timeframe/session counts as multiple testing (campaign-scoped count).
- 🟢 ATR cannot be passed as a raw float or `PriceUnits` where pips are required; fixed commission is never stress-multiplied; Thanksgiving 2025 and Good Friday are closed.
- 🟢 The old caller-boolean gate raises if invoked.
- 🔴 CI statically forbids re-introducing any of the above bypasses (guard script pending).

**Definition of done is binary** (see `enforcement-plan.md` §16): items 1–10 there are met today except the static CI guard script and the four remaining spec docs, which are the only 🔴/🟡 work left in this plan.
