# Phase 0 Go / No-Go Report — <YYYY-MM-DD>

**Author:** <name> · **Reviewers:** <names> · **Commit:** `<git_sha>` · **Data hash:** `<hash>`

> Fill every section with evidence. Do not advance to Phase 1 unless the decision is **GO** under the strict criteria in [`validation-protocol.md`](./validation-protocol.md). A defensible **NO-GO** is a successful Phase 0 outcome.

---

## 1. Data summary

| Instrument | Source(s) | Range | Bars (tf) | Coverage % | Gaps (count / cause) |
|---|---|---|---|---|---|
| EUR/USD | | | | | |
| GBP/USD | | | | | |
| USD/JPY | | | | | |
| XAU/USD | | | | | |

- Data-quality gate (≥ 99.5%): **PASS / FAIL**
- Known limitations: <...>
- Cross-source divergence (OANDA vs Dukascopy): <...>

## 2. Strategy summary

For each strategy: what was actually implemented vs the hypothesis doc, and any deviations.

| Strategy | Implemented as specced? | Deviations |
|---|---|---|
| Asian Range Breakout | | |
| London Sweep + BOS | | |
| NY ORB | | |

## 3. Validation results

Per strategy × instrument (after costs, on the **lockbox** unless noted):

| Strategy | Instrument | Trades (OOS) | Expectancy | PF | Sharpe | **DSR** | WF win-window % | Max DD | MC p95 DD |
|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | |

- Number of configurations tested (feeds DSR): **<N>**
- Lockbox opened: **once / more** (must be once)

## 4. Cost sensitivity

| Strategy | Instrument | Expectancy @1.0× | @1.25× | @1.5× | Survives 1.5×? |
|---|---|---|---|---|---|
| | | | | | ✅/❌ |

Any strategy negative at 1.5× → **rejected** here.

## 5. Robustness

- Parameter plateau evidence (per strategy): <plot/table ref>
- Monte Carlo drawdown distribution (p50 / p95): <...>
- Session breakdown (no slice > 50% of PnL): **PASS / FAIL**
- Regime breakdown: <...>
- Sub-period (early vs late) decay check: <...>

## 6. Failure modes observed

- What broke: <...>
- What is fragile: <...>
- What is unexplained: <...>

## 7. Decision (per strategy)

| Strategy | Criteria met | Criteria missed | **Verdict** |
|---|---|---|---|
| Asian Range Breakout | | | GO / NO-GO / ITERATE |
| London Sweep + BOS | | | GO / NO-GO / ITERATE |
| NY ORB | | | GO / NO-GO / ITERATE |

### Go/No-Go checklist (all required for a GO on a given strategy)
- [ ] Data quality ≥ 99.5%
- [ ] Reproducible bit-for-bit
- [ ] ≥ 3 of 4 instruments
- [ ] ≥ 5y range, multiple regimes
- [ ] ≥ 200 OOS trades
- [ ] WF positive in ≥ 60% windows, no single window dominates
- [ ] Lockbox net-positive after costs
- [ ] Max DD ≤ 20%, MC p95 DD ≤ 30%
- [ ] PF ≥ 1.25 + positive expectancy
- [ ] Survives 1.5× cost
- [ ] No session/regime > 50% of PnL
- [ ] Deflated Sharpe probability > 0.95 (superseded note: an earlier "DSR > 0" draft was far too weak; the bar is ≥95% after campaign-level trial-count correction)

## 8. Recommendation

<Proceed to Phase 1 / iterate Phase 0 / stop — and the explicit reasoning. If iterating, name the *specific* gap to fix; do not loosen criteria.>

## 9. Next-phase verdict

- **Overall:** GO / NO-GO / ITERATE
- If GO: the **narrow** Phase 1 scope to start with (which strategy, which instruments, what to build first):
  <...>
- If NO-GO: what is being stopped and why:
  <...>
