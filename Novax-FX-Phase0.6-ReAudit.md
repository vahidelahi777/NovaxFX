# Phase 0.5 Red Team Audit — Re-run Against Phase 0.6 Code

**Panel:** same six adversarial roles · **Method:** attack the *new* code; trust nothing, including the remediation's own claims. Every finding below was reproduced by running the shipped Phase 0.6 scaffold.

> **Headline.** Phase 0.6 fixed the *primitives* — the deflated Sharpe now fails closed, lookahead is testable, sessions/weekends/holidays/bootstrap exist — and these are real improvements verified by tests. But the *system* is still bypassable. The signature Critical finding (multiple-testing correction disabled) was moved, not eliminated: it is now defeated by **under-logging**, and nothing forces logging. The go/no-go gate still trusts caller-supplied truth for nearly everything except the DSR. And the result-producing engine still does not exist, so the most dangerous surfaces remain unexercised. **Verdict unchanged: B — needs safeguards before research. Materially better, not yet safe.**

---

## 1. Verification of prior findings (evidence-based)

### CLOSED at the primitive level (verified)
| Prior finding | Evidence it's fixed |
|---|---|
| **C1** DSR silent no-op | `deflated_sharpe_ratio(..., n_trials=50, sr_variance=0)` now **raises**; more trials measurably lowers the probability (`prob(500) < prob(2)`); end-to-end best-of-200 → DSR 0.36 → rejected. |
| **C3** no lookahead/CV | `assert_no_lookahead` catches a leaky feature (raises) and passes a clean one; `purged_kfold` enforces train/test disjointness + embargo; `walk_forward_windows` yields chronological, non-overlapping windows. |
| **H4** OVERLAP unemitted | `active_sessions(overlap_instant)` now contains `"OVERLAP"`; `primary_session` returns it. |
| **H5** weekend DST-wrong | NY-17:00-anchored calendar: Fri 21:30 UTC in winter now correctly **open**; Sunday reopen correct in summer. |
| **H8** trade independence | `block_bootstrap` (moving-block, seeded, length-preserving) replaces i.i.d. shuffle. |
| **H9** walk-forward missing | generator implemented + tested. |

These are genuine. The session math, DSR function, splitters, and lookahead harness are now correct and covered.

### PARTIALLY closed / weakened
- **C1 (systemic).** The DSR is only as honest as the trial registry, and **the registry does not prevent under-logging.** *Attack reproduced:* log 1 of 200 trials → `deflated_sharpe_for(...) = 1.000`, passes the 0.95 gate. The same luck-only edge that the campaign-level proof rejected sails through if the loser trials are simply never logged. The fix moved the vulnerability from "silent default" to "discretionary logging." Mechanism to force logging is the missing piece.
- **H6 (cost realism).** News multiplier and an ATR guard were added, but the guard is **half-blind**: *attack reproduced* — passing EUR/USD ATR as price units (`0.0010`) instead of pips is silently accepted (cost computed on `0.0010`), because the guard only rejects implausibly *large* values, not small wrong-unit ones. Spread is still a static floor unless a realized value is supplied, and nothing supplies one yet; no volatility-driven spread curve exists.
- **H7 (holidays).** Only ~7 dates are hardcoded. *Attack reproduced:* Thanksgiving 2025-11-27 returns `is_fx_market_open = True` and a bar on that day passes `no_closed_market_data`. Mid-week holidays (Thanksgiving, Good Friday, July 4) and half-days are uncaught. This is a stub, not a calendar.

### STILL OPEN (carried or newly dominant)
- **C2 — no engine / feature layer / ingested data.** Unchanged by design. The safety harness exists, but the components that *produce* results don't, so randomized-entry, one-bar-delay, Monte Carlo over real trades, and realized-spread are all unexercised. This remains the structural blocker.
- **Gate trust surface (now the dominant hole).** `evaluate_go_no_go` still consumes caller-supplied `survives_cost_stress`, `beats_randomized_entry`, `survives_one_bar_delay`, `walk_forward_window_pass_rate`, `lockbox_expectancy_after_costs`, `drawdown_pct`, and `mc_p95_drawdown_pct`. Only the DSR is a computed, structured object. **The gate can be passed by passing the right booleans.** With DSR fixed, this is now the easiest way to wave a bad strategy through.
- **`max_drawdown` computed but unused (not closed).** The gate still reads a caller-supplied `drawdown_pct` (a percentage), while the computed `metrics.max_drawdown` (absolute) is never used. Two sources of truth; the computed one is decorative.
- **Doc/code threshold contradiction (not closed).** `docs/phase-0/validation-protocol.md` still says "DSR > 0" while code/config require probability > 0.95. The older document was not updated; a reader following it applies a meaningless bar.

---

## 2. New issues introduced or newly visible

- **N1 — False-solved risk (meta, High).** The trial registry makes multiple testing *look* controlled while control depends entirely on honest logging. A safeguard that appears complete but is bypassable by omission is more dangerous than a visibly absent one — it invites trust it hasn't earned. (Same failure *mode* as the original DSR no-op, one layer up.)
- **N2 — `sr_variance` gaming (Medium).** DSR's penalty grows with the cross-trial Sharpe variance. An adversary (or a naive sweep) that logs many near-identical low-variance trials shrinks `sr0` and weakens the penalty. The registry counts trials but doesn't detect a suspiciously low-variance trial population.
- **N3 — Trial-family boundary undercounts (Medium).** Families are keyed by `(strategy, instrument, timeframe)`, so choosing the best of four instruments is *uncounted* multiple testing — instrument selection is itself a comparison the DSR never sees.
- **N4 — `_as_pips` false confidence (Medium).** Named a "guard," it only catches gross over-magnitude. Naming it a guard invites reliance it doesn't merit (see N1 pattern).
- **N5 — Degenerate bootstrap test (Low).** `test_block_bootstrap_preserves_local_order_within_block` uses `block_size == n`, which forces a single full slice — it asserts the trivial case, not real block behavior.

---

## 3. Updated weakness ranking

### CRITICAL
1. **DSR bypass by under-logging.** The headline fix is circumventable; logging is policy, not mechanism. *(Reproduced.)*
2. **No engine / features / data (C2).** Nothing produces results; the highest-risk surfaces stay untested against real backtests.
3. **Go/no-go trusts unverified inputs.** Every gate criterion except DSR is a caller-supplied scalar/bool — the gate can be passed by lying.

### HIGH
4. **Holiday calendar is a 7-date stub** — mid-week holidays/half-days uncaught. *(Reproduced.)*
5. **ATR-unit guard half-blind** — small wrong-unit values pass silently. *(Reproduced.)*
6. **Cost spread still static** — no volatility curve; realized path unpopulated until data exists.
7. **N1 false-solved trial control** — appears solved, bypassable by omission.

### MEDIUM
8. **`max_drawdown` computed but unused**; gate trusts caller `drawdown_pct`.
9. **DSR IID/kurtosis optimism** + **N3 family undercount** + **N2 variance gaming**.
10. **Doc/code DSR threshold contradiction** (old Phase 0 doc).

### LOW
11. **DST `fold` handling** still latent (safe only for current boundaries; no test/guard).
12. **N5 degenerate bootstrap test**; **N4 guard naming.**

---

## 4. Remaining blockers before research (the must-fix list)

1. **Make trial logging non-bypassable.** Wrap every evaluation so a result cannot be produced without a logged trial (decorator/context manager), and add a CI check: produced-artifact count == logged-trial count. Until logging is mechanical, the DSR fix is theater. *(Closes Critical #1 systemically + N1.)*
2. **Stop the gate trusting caller truth.** `evaluate_go_no_go` should accept *artifacts* (the randomized-entry null distribution, the delayed-execution metrics, the cost-stress run, the walk-forward per-window results, the MC drawdown distribution) and compute the booleans itself — not accept pre-chewed `True`/`False`. Derive `drawdown_pct` from `metrics.max_drawdown`. *(Closes the gate trust hole + the max_drawdown finding.)*
3. **Build the engine into the harness** so randomized-entry, one-bar-delay, MC, and realized-spread are actually exercised — with the no-lookahead test mandatory per feature. *(Closes C2.)*
4. **Real holiday/half-day calendar** (sourced, not hardcoded); promote `no_closed_market_data` and coverage to hard gates once it exists. *(Closes H7.)*
5. **Harden the ATR-unit boundary** — use a dedicated `Pips` newtype at call sites or assert pip-scale against the instrument's ATR distribution; stop calling a half-check a "guard." *(Closes H6 footgun.)*
6. **Volatility-driven spread** from realized data once ingested; keep floors as a conservative fallback. *(Closes H6 spread.)*
7. **Reconcile the old Phase 0 doc** to probability > 0.95; consider counting instrument selection in the trial family (or document why not). *(Closes doc contradiction + N3.)*

---

## 5. Final verdict

**B — needs additional safeguards first.** Not a regression and not a redesign: Phase 0.6 made the primitives correct and tested, which is real progress. But credible research still cannot begin, because:

- the multiple-testing correction — the platform's reason to exist — is **defeated by simply not logging the losing trials**, and nothing prevents that (Critical, reproduced);
- the go/no-go gate **trusts caller-supplied truth** for everything except the DSR, so a bad strategy can be passed by passing the right inputs (Critical);
- the engine that would *exercise* these safeguards against real backtests **still doesn't exist** (Critical, structural).

The pattern across both audits is the same: the platform keeps converting *silent* failures into *less-silent but still bypassable* ones. The remaining work is mostly **mechanism over policy** — make the safeguards impossible to skip, not merely available — plus building the engine inside the harness. Until logging is forced and the gate computes its own verdicts from artifacts, assume any apparent edge is an artifact of an unenforced control.

> Phase 0.6 made the platform *capable* of rigor. It is not yet *incapable* of self-deception. That is the bar for "safe to begin research," and it is not met.
