# Phase 0.7 — Non-Bypassable Research Harness & Enforcement Layer

**Status:** implemented + verified · **Source of truth:** Phase 0.5 re-audit against Phase 0.6.
**Verification at time of writing:** ruff clean, mypy --strict (17 files), 67 tests passing, end-to-end enforcement proof green.

> **This is an enforcement phase, not a research phase.** No strategies, no profitability, no ML, no broker execution, no dashboard. The objective is to turn Phase 0.6 from *capable of rigor* into *incapable of producing unverified research results* — every safeguard mechanical, every bypass tested to fail closed.

## 1. Objective

Phase 0.6 made the primitives correct but left them bypassable: the deflated Sharpe could be defeated by under-logging, the go/no-go gate trusted caller-supplied booleans, and no engine exercised any of it. Phase 0.7 closes those by making logging non-bypassable (the runner owns trial registration and artifact emission), making the gate compute every verdict from provenance-stamped artifacts (no caller truth accepted), and shipping a minimal harness that drives the whole loop so the safeguards are proven against realistic flows.

## 2. Non-Negotiable Enforcement Principles

- **No result without a trial log.** The runner logs the trial *before* the body runs; if logging fails, the body never executes.
- **No trial log without an immutable run/result id.** Every trial and artifact carries a uuid.
- **No artifact without provenance.** Every artifact carries commit + data/config hashes + versions + seed + content hash.
- **No go/no-go from caller-supplied booleans.** The gate takes artifact IDs and computes everything itself.
- **No DSR without campaign-level trial accounting.** The penalty count comes from the registry's campaign family (spanning instruments/timeframes/sessions).
- **No backtest without a data-quality report** (artifact must self-report pass).
- **No feature without no-lookahead validation** (artifact must self-report pass).
- **No validation claim without an artifact path.** Criteria are read only from registered artifacts.
- **Fail closed on missing metadata** — missing/stale/mismatched artifacts ⇒ NO_GO.
- **UTC-only timestamps; deterministic seeded runs.**
- **Artifact count must reconcile with trial count** (`audit_artifacts_match_trials`).
- **Every metric computed, not asserted** (drawdown from the equity curve, PF/expectancy from the ledger, DSR from the registry).

## 3. Critical Remediation Plan

### A. Trial under-logging bypass — **CLOSED**
- *Failure:* the registry counted only what callers logged; logging the winner alone gave DSR ≈ 1.0.
- *Danger:* the multiple-testing correction was defeated by omission.
- *Fix:* `ExperimentRunner.evaluate` is the only supported evaluation path. It logs a `RUNNING` trial before yielding, blesses the trial_id, requires artifacts to be emitted through the yielded handle (which stamps trial_id/run_id/provenance), marks `COMPLETE`/`FAILED` on exit, and returns nothing if logging fails.
- *Files:* `runner.py`, `trial_registry.py`, `artifacts.py`.
- *Tests:* no-result-if-logging-fails; no-artifact-without-trial-id; best-of-200 rejected; `audit_artifacts_match_trials`.
- *Acceptance:* you cannot produce an artifact without a logged trial, and the campaign count reflects every trial the runner ran. **Verified.**

### B. Caller-trusted go/no-go — **CLOSED**
- *Failure:* `evaluate_go_no_go` accepted booleans/scalars (`survives_cost_stress`, `drawdown_pct`, …).
- *Danger:* a bad strategy passed by passing the right inputs.
- *Fix:* new `evaluate_gate(campaign_id, strategy, run_id, artifacts, registry)` — no boolean params exist. It loads the required artifacts, verifies mutual provenance consistency, and computes each criterion from payloads (drawdown from equity curve, DSR from campaign registry, etc.). Missing/stale/mismatched ⇒ NO_GO.
- *Files:* `gate.py`.
- *Tests:* gate has no bool params; rejects missing artifacts; rejects provenance mismatch; drawdown computed from equity curve.
- *Acceptance:* the gate accepts no caller truth and fails closed on missing inputs. **Verified.**

### C. Missing result-producing harness — **CLOSED (for safeguard exercise)**
- *Fix:* `harness.py` (`BaselineRandomStrategy`, `emit_required_artifacts`) drives the runner→artifact→gate loop with an edgeless strategy, proving the safeguards end-to-end. This is *not* a strategy engine; real features/data/strategies are Phase 1.
- *Tests:* best-of-200 random rejected end-to-end.
- *Acceptance:* the full enforcement loop runs and rejects luck. **Verified.**

## 4–16 (delivered as companion specs + code)

- Trial logging enforcement → [`trial-logging-enforcement.md`](./trial-logging-enforcement.md)
- Artifact/provenance system → [`artifact-registry-spec.md`](./artifact-registry-spec.md)
- Go/No-Go redesign → [`go-no-go-redesign.md`](./go-no-go-redesign.md)
- Minimal harness → [`minimal-research-harness.md`](./minimal-research-harness.md)
- Calendar + ATR/cost hardening → [`calendar-cost-hardening.md`](./calendar-cost-hardening.md)
- Test plan → [`test-plan.md`](./test-plan.md)

### Campaign-level accounting (Section 5)
Two family levels: **narrow** `(strategy, instrument, timeframe)` and **campaign** `(campaign_id, strategy)` which spans instruments/timeframes/sessions/params. The go/no-go DSR uses the **campaign** count, so selecting the best instrument/timeframe/session is counted as the multiple testing it is. Counts dedupe by `result_id` (the two-phase RUNNING→COMPLETE log is one trial). Aborted trials are logged `FAILED` and still count. Hidden trials are made hard because the runner is the only evaluation path and the artifact registry refuses orphans.

### Documentation reconciliation (Section 12)
`docs/phase-0/validation-protocol.md` ("DSR > 0") is superseded: the bar is **probability > 0.95**. `DSR > 0` is meaningless for a probability. This is recorded here and in [`go-no-go-redesign.md`](./go-no-go-redesign.md); the old file should carry a deprecation pointer.

### Updated Go/No-Go to allow Phase 1 (Section 15)
Research may begin only when: trial logging is mandatory (runner-only); artifact registry mandatory; gate computes all decisions from artifacts; the under-logging attack fails; the caller-truth attack fails; data-quality and no-lookahead are hard gates; DSR uses the campaign count; the cost model rejects unit ambiguity; the calendar handles known holidays/half-days; the baseline/random end-to-end test is rejected; docs match code.

### Final Definition of Done (Section 16) — strict, binary
Phase 0.7 is complete iff **all** are true:
1. The only evaluation path is `ExperimentRunner`; a body cannot run if trial logging fails (tested).
2. No artifact can be registered without a logged trial_id (tested).
3. `evaluate_gate` exposes **zero** boolean/scalar verdict overrides; it computes from artifacts and fails closed on missing/stale/mismatched (tested).
4. DSR for go/no-go uses the campaign trial count; best-of-200-random is rejected end-to-end (tested).
5. ATR cannot be passed as a raw float or PriceUnits where pips are required (tested).
6. Fixed commission is never stress-multiplied (tested).
7. Thanksgiving 2025 and Good Friday are handled by the computed calendar (tested).
8. `audit_artifacts_match_trials` returns no violations for a healthy campaign (tested).
9. ruff, mypy --strict, and the full pytest suite pass.
10. The seven Phase 0.7 docs exist and match the code.

**Current status:** all ten met at time of writing.

> Enforcement only. No edge is claimed. The deliverable is a platform that cannot emit a result without logging it, cannot grade itself on caller-supplied truth, and rejects a luck-only winner end-to-end.
