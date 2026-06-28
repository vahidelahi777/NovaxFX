# Trial Logging Enforcement (Phase 0.7, Critical 1)

**Status:** implemented + tested (`src/novax/runner.py`, `tests/test_enforcement.py`).

## Problem
The Phase 0.6 re-audit reproduced this: log 1 of 200 trials and the registry's
`deflated_sharpe_for(...)` returns probability **1.000** and passes the 0.95 gate.
The deflated Sharpe correction is only as honest as the trial count it is given, and
nothing forced every evaluation to be logged. The fix had to be **mechanical**, not a
policy reminder.

## Why it is dangerous
Multiple-testing inflation is the single most common way a backtest lies. If a
researcher can run 200 variants and quietly register only the winner, the platform's
central defense is defeated by *omission* — the most deniable, least visible failure.

## Systemic fix
Make the **only sanctioned path to a result** a runner that logs the trial *before*
the body runs and refuses to yield a result if logging fails.

### `ExperimentRunner.evaluate` — the non-bypassable mechanism
A context manager that:
1. builds an immutable `Trial` (status `RUNNING`) and logs it **before** the body —
   if logging raises, the body never executes and no result is returned;
2. blesses the `trial_id` in the `ArtifactRegistry`, so artifacts can only attach to a
   known trial (no artifact without a trial);
3. yields an `Evaluation` handle whose `emit(...)` stamps every artifact with
   `run_id / trial_id / campaign_id` + full provenance;
4. on success marks the trial `COMPLETE` with its observed Sharpe;
5. on **any** exception marks the trial `FAILED` and re-raises — aborted trials still
   count toward the multiple-testing total.

```python
runner = ExperimentRunner(reg, arts, campaign_id="C", data_version="d1",
                          feature_version="f1", cost_model_version="cm1")
with runner.evaluate(strategy="asian", instrument="EUR/USD", timeframe="5m",
                     session="LONDON", params={"k": 7}, random_seed=42) as ev:
    pnls = backtest(...)
    ev.set_sharpe(sharpe(pnls))
    ev.emit(ArtifactType.EQUITY_CURVE, {"equity": equity_from_pnls(pnls)})
# trial is COMPLETE here; if backtest() raised, it is FAILED — either way it is logged
```

### Immutable run_id
Each `evaluate` call mints `run_id = uuid4().hex`. The `trial_id` (`result_id`) is a
content hash of the trial's identity fields. Both are stamped on every artifact.

### CI invariants (two layers)
- `audit_artifacts_match_trials(registry, artifacts)` — global: no orphan artifacts
  (every `artifact.trial_id` is a logged trial) and every `COMPLETE` trial produced
  ≥1 artifact.
- `audit_campaign_integrity(registry, artifacts, campaign_id, strategy)` — strict
  per-campaign **set equality**: the set of trial_ids referenced by artifacts equals
  the set of `COMPLETE` campaign trials. A completed trial with no artifact (silent
  discard) or an artifact pointing at an unlogged trial is a hard violation.

## Campaign-level accounting, sweeps, instrument selection
- DSR is computed from the **campaign** trial count, not a caller integer:
  `registry.campaign_n_trials(campaign_id, strategy)`.
- Parameter sweeps: each variant is a separate `evaluate` call → separately logged.
- Instrument/timeframe/session selection: each candidate is its own trial in the same
  campaign, so "pick the best of 4 instruments" contributes 4 to the trial count. See
  `dsr-hardening` and `go-no-go-redesign.md` for the family-boundary rules.
- Duplicate detection: identical identity fields collapse to one `result_id`; the
  registry warns on suspiciously low cross-trial Sharpe variance (gaming the penalty).

## Failure modes (and resulting behavior)
| Failure | Behavior |
|---|---|
| Trial log raises (disk full) | body never runs; no result; exception propagates |
| Body raises mid-evaluation | trial marked `FAILED`, logged, re-raised |
| Artifact emitted without runner | `ArtifactRegistry` rejects unblessed `trial_id` |
| Researcher bypasses runner entirely | **not mechanically preventable**; caught by CI audits + code review — documented as policy, not mechanism |

## Acceptance criteria
- [x] No result object is returned if trial logging fails. (`test_no_result_if_trial_logging_fails`)
- [x] No artifact can be created without a blessed `trial_id`. (`test_*` in enforcement suite)
- [x] A 200-trial campaign run through the runner yields `campaign_n_trials == 200`. (`test_under_logging_attack_fails_via_runner`)
- [x] `audit_campaign_integrity` flags a completed trial with no artifact. (`test_campaign_integrity_flags_silent_discard`)
- [x] Exceptions mark the trial `FAILED` and still log it.

## Adversarial cases covered
- **Under-logging:** running through the runner makes the registry see all trials; DSR
  uses the true campaign count → luck-only best-of-200 is rejected.
- **Out-of-band artifact:** artifact with an unknown `trial_id` → audit violation.
- **Silent discard:** complete trial with no artifact → audit violation.

## Honest residual
A trial that is **never logged because the runner was bypassed** cannot be detected
from inside the system — you cannot count what was never recorded. This is mitigated,
not eliminated: the runner is the sole sanctioned entry point, the CI audits run on
every campaign, and review enforces "no raw `registry.log` in research code." This is
explicitly a **policy** boundary and is documented as such.
