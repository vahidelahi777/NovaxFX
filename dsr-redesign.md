# DSR Redesign — Deflated Sharpe Ratio (fail-closed)

**Module:** `src/novax/validation.py` · **Owner:** Statistical Methodology Expert
**Closes:** Phase 0.5 Critical #1 (multiple-testing correction silently disabled).

## Problem

The Phase 0 implementation defaulted `sr_variance=0`. With zero variance the expected-max-Sharpe benchmark collapsed to 0, so `n_trials=1` and `n_trials=500` returned identical probabilities. The correction the platform exists to provide did **nothing** unless a caller happened to pass `sr_variance` — and nothing forced them to.

## Requirements (all enforced)

- `n_trials` is **mandatory**.
- `sr_variance` has **no default**; for `n_trials > 1`, `sr_variance <= 0` **raises**.
- `sr_variance` is **estimated from the trial registry**, not guessed.
- Realistic **skew/kurtosis** supported; kurtosis defaults to an FX estimate (6), never 3 (normal); a warning fires if 3 is used.
- Output is a **result object** echoing all inputs + the benchmark Sharpe + **warning flags**.
- Threshold is a **probability > 0.95** (the Phase 0 doc's "> 0" was meaningless for a probability).
- The trial count comes from the registry (`deflated_sharpe_for`), so hidden trials can't deflate the penalty.

## API

```python
@dataclass(frozen=True)
class DeflatedSharpeResult:
    probability: float
    observed_sharpe: float
    benchmark_sharpe: float       # expected max Sharpe across trials (sr0)
    n_trials: int
    n_obs: int
    sr_variance: float
    skew: float
    kurtosis: float
    warnings: tuple[str, ...]
    def passed(self, threshold: float = 0.95) -> bool: ...

def estimate_sr_variance(trial_sharpes: Sequence[float]) -> float          # needs >= 2
def expected_max_sharpe(n_trials: int, sr_variance: float) -> float        # López de Prado
def deflated_sharpe_ratio(observed_sr: float, *, n_obs: int, n_trials: int,
                          sr_variance: float,                # NO DEFAULT
                          skew: float = 0.0, kurtosis: float = 6.0) -> DeflatedSharpeResult

# Blessed path (registry-driven; cannot disable the correction):
TrialRegistry.deflated_sharpe_for(*, strategy, instrument, timeframe,
                                  observed_sr, n_obs, skew=0.0, kurtosis=None) -> DeflatedSharpeResult
```

## Pseudocode

```
deflated_sharpe_ratio(sr, n_obs, n_trials, sr_variance, skew, kurtosis):
    if n_trials < 1: raise
    if n_obs   < 2: raise
    if n_trials > 1 and sr_variance <= 0: raise   # <-- the fix
    warnings = []
    if kurtosis == 3: warn("normal kurtosis; FX fat-tailed -> optimistic")
    if n_obs < 200:   warn("small sample")
    if n_trials == 1: warn("no multiple-testing penalty")
    sr0  = expected_max_sharpe(n_trials, sr_variance) if n_trials > 1 else 0
    den  = sqrt(max(eps, 1 - skew*sr + (kurtosis-1)/4 * sr^2))
    z    = (sr - sr0) * sqrt(n_obs - 1) / den
    return Result(prob=Phi(z), benchmark=sr0, ..., warnings)
```

## Edge cases

- `n_trials == 1`: PSR vs 0 (single hypothesis); benchmark 0; warned.
- `n_obs < 2`: raise (no inference possible).
- `n_trials > 1, sr_variance == 0`: raise (the no-op scenario).
- `kurtosis == 3`: allowed but warned (understates FX tails ⇒ optimistic DSR).
- Registry path with 0 logged trials: raise ("log trials before computing DSR").

## Tests (shipped, passing)

- `test_dsr_rejects_multi_trial_without_variance` — the no-op raises.
- `test_dsr_requires_valid_n_trials_and_obs` — guards.
- `test_dsr_penalizes_more_trials` — `prob(500) < prob(2)`, `sr0(500) > sr0(2)`.
- `test_dsr_warns_on_normal_kurtosis_and_small_sample`.
- `test_estimate_sr_variance_needs_two`.
- `test_registry_counts_and_dsr_uses_them` — variance comes from the registry.
- End-to-end proof: best-of-200 random-trial Sharpe → DSR ≈ 0.36 → **rejected** at 0.95.

## Acceptance criteria

- [x] `sr_variance` mandatory; multi-trial-with-zero-variance raises.
- [x] More trials measurably lowers the probability.
- [x] Registry supplies `n_trials` + `sr_variance`.
- [x] Output carries inputs + warnings.
- [x] Threshold is probability > 0.95 in `config`.

## Implementation notes / known limits

DSR assumes returns are IID; FX trades cluster, so even a passing DSR should be paired with **block-bootstrap** confidence intervals (see validation hardening). The kurtosis default (6) is a placeholder estimate — compute the empirical skew/kurtosis of the actual return series and pass them in for a Phase 1 result.
