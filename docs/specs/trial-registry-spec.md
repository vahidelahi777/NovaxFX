# Trial Registry Spec — multiple-testing control

**Module:** `src/novax/trial_registry.py` · **Owner:** Quant Research Director
**Purpose:** make hidden trials impossible. Every evaluated configuration is logged; the DSR reads its trial count and cross-trial Sharpe variance from here, so the multiple-testing penalty reflects what was actually tried.

## Why this exists

A research campaign tries hundreds of configurations (strategy × instrument × timeframe × session × params × feature/data/cost versions). If the DSR's `n_trials` is supplied by hand, a researcher can — deliberately or not — undercount and inflate significance. Sourcing `n_trials` and `sr_variance` from an append-only registry removes that discretion.

## Logged fields (per trial)

`strategy` · `instrument` · `timeframe` · `session` · `params` · `feature_version` · `data_version` (hash/tag) · `cost_model_version` · `validation_split` · `run_timestamp` (UTC) · `git_commit` · `random_seed` · `observed_sharpe` · `result_id` (uuid).

## API

```python
@dataclass(frozen=True)
class Trial: ...                     # fields above; rejects naive run_timestamp
    def family_key(self) -> tuple[str, str, str]   # (strategy, instrument, timeframe)

@dataclass
class TrialRegistry:
    path: Path | None = None         # JSONL; None = in-memory
    def log(self, trial: Trial) -> Trial
    def all(self) -> list[Trial]
    def family(self, strategy, instrument, timeframe) -> list[Trial]
    def n_trials(self, strategy, instrument, timeframe) -> int
    def sharpes(self, strategy, instrument, timeframe) -> list[float]
    def deflated_sharpe_for(*, strategy, instrument, timeframe,
                            observed_sr, n_obs, skew=0.0, kurtosis=None) -> DeflatedSharpeResult
```

## How it feeds the DSR

`deflated_sharpe_for` pulls the family's logged Sharpes, sets `n_trials = len(sharpes)`, computes `sr_variance = estimate_sr_variance(sharpes)`, and calls the fail-closed DSR. There is no parameter through which a caller can pass a smaller trial count. If only one trial is logged, it returns a single-hypothesis DSR (warned).

## Family definition

A "trial family" is `(strategy, instrument, timeframe)`. Trials within a family compete for the same significance budget; varying parameters/sessions within that triple all count. This is conservative: it treats parameter sweeps as the multiple comparisons they are.

## Persistence & provenance

JSONL, append-only. Reloaded on construction. Each record is self-describing (versions + commit + seed), so a registry file is an audit trail of the entire search — and the input to any reproducibility review.

## Preventing hidden trials (policy + mechanism)

- **Mechanism:** the only blessed route to a go/no-go DSR is `deflated_sharpe_for`; direct `deflated_sharpe_ratio` calls with hand-set `n_trials` are for tests, not gating.
- **Policy:** any backtest evaluation MUST `log()` before its result is eligible. Code review rejects evaluation paths that compute metrics without logging a trial.
- **Detection:** compare the count of produced result artifacts to logged trials; a mismatch means hidden trials.

## Tests (shipped, passing)

- `test_registry_counts_and_dsr_uses_them` — count correct; DSR `sr_variance > 0` sourced from registry.
- `test_registry_persists_to_disk` — JSONL round-trips across instances.

## Acceptance criteria

- [x] All required fields captured; naive timestamps rejected.
- [x] `n_trials` and `sr_variance` for DSR come from the registry.
- [x] Append-only JSONL persistence with reload.
- [ ] (Phase 1) CI check: result-artifact count == logged-trial count.

## Implementation notes

Keep the registry the *only* place trial counts originate. When the backtest engine lands, wrap each evaluation so logging is automatic and non-bypassable (decorator or context manager), closing the policy gap mechanically.
