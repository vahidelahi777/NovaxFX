# Phase 0.5 — Red Team Audit, Novax FX Research Platform

**Panel:** Quant Research Director · Hedge Fund Risk Manager · Statistical Methodology Expert · Market Microstructure Specialist · Senior Backtesting Engineer · Data Quality Auditor
**Mandate:** assume the platform is fooling itself until proven otherwise. Find every path to a convincing-but-false edge.

> **Framing finding (read first).** The scaffold *cannot currently produce a false edge because it cannot produce any result.* There is **no backtest engine, no ingested market data, and no feature layer** — only primitives (sessions, instruments, a static cost model, validation structures). So this audit is forward-looking: it judges whether the foundations will yield trustworthy results once an engine exists. Several will not in their current state, and one core safeguard is **silently disabled**. Treat every "passing test" and "strict type" as a comfort that has not yet been earned.

---

## SECTION 1 — Core Research Risk Assessment

The general ways a research platform fools itself, and why each is acute in FX specifically.

**Lookahead bias.** Using information not available at decision time. *FX-specific:* there is no central close — "daily" bars depend entirely on a broker's arbitrary cutoff (often 17:00 NY). A session high/low used before the session ends, or a bar's close used to act at that bar's open, manufactures edge. Continuous 24/5 trading means the "current bar" is always partially in the future at decision time. **Status here:** no feature layer exists, so there are *zero* no-lookahead tests. This is the single most dangerous untested surface.

**Data leakage.** Train/test contamination — normalizing or fitting over the whole sample, label windows overlapping the test set, using future spread/volatility. *FX-specific:* overlapping triple-barrier labels on intraday data leak heavily through autocorrelation; standard k-fold leaks on time series. The protocol mandates purged k-fold + embargo; **none of it is implemented.**

**Survivorship bias.** *FX majors rarely delist*, so the classic equity survivorship is weak — but three subtler forms apply: (a) **instrument survivorship** — we cherry-picked four of the most liquid, well-behaved instruments, exactly where edges are hardest and cleanest; (b) **broker-feed survivorship** — gaps/outages silently dropped look like clean data; (c) **strategy survivorship** — only three strategies are on the table; the ones quietly discarded during design are an unrecorded multiple-testing burden.

**Multiple testing.** 3 strategies × 4 instruments × parameter grids × 4 sessions × ≥3 regimes is **hundreds of effective trials.** The best will look great by luck alone. The platform's defense is the deflated Sharpe — which, as Section 6 shows, **does nothing by default.**

**P-hacking.** Iterating until the lockbox passes; re-opening the lockbox; widening grids; redefining "regime" post hoc. *FX-specific:* session/regime slicing multiplies the knobs. The `Lockbox` guard exists but only catches literal double-`open()`; it cannot stop a human re-running with a new split.

**Regime overfitting.** A 5-year sample is dominated by a few regimes (2020 COVID vol, 2022 USD trend, 2023–24 range). A strategy fit to those is fit to history, not structure. *FX-specific:* central-bank regime shifts (ZIRP→hiking→cutting) change pair behavior wholesale; an edge in one rate regime can invert in the next.

**Cost illusion.** Underpriced spread/slippage turns noise into "profit." *FX-specific:* spreads are broker-specific and blow out 5–20× around news and at session edges. The current cost model uses **static floors with no volatility/news dependence** — the most common source of fake intraday edge.

**Unrealistic liquidity.** Assuming fills at the touch in fast tape. *FX-specific:* breakout strategies trade *into* the move everyone else is trading — the moment your signal fires, liquidity thins and spread widens. Asian-session and rollover liquidity is genuinely poor.

**Unstable statistical metrics.** Sharpe and profit factor are high-variance at small n and assume IID, near-normal returns. *FX-specific:* returns are fat-tailed and autocorrelated; per-trade Sharpe values are tiny (0.1–0.3) and their confidence intervals swamp the point estimate at n=200.

---

## SECTION 2 — Data Integrity Audit

The platform plans Dukascopy (history) + OANDA (reference) + TwelveData (secondary), none yet ingested.

| Issue | How it fakes an edge | Detection | Mitigation |
|---|---|---|---|
| **Missing tick data / gaps** | gaps silently bridged → smooth fills that never existed | per-instrument coverage report vs expected bars (≥99.5% gate); explicit gap ledger | flag, never interpolate price; exclude gap-adjacent trades |
| **Inaccurate / synthetic spreads** | tight static spread → costs too low | compare modeled vs realized bid/ask from OANDA; distribution check | use realized spread; conservative floors; widen at news/session edge |
| **Broker-specific feeds (Dukascopy ≠ execution)** | backtest fills at prices you can't get live | cross-source delta report (Dukascopy vs OANDA close/spread) | backtest on the feed closest to execution; treat Dukascopy as robustness only |
| **Synthetic OHLC from ticks** | resampling artifacts (wrong H/L, phantom wicks) drive breakout/sweep signals | reconcile resampled bars vs vendor bars; check H/L plausibility | deterministic, tested resampling; preserve tick-true H/L |
| **Timezone / DST errors** | session mislabeling → spurious "session edge" | property tests on UTC conversion (exist for sessions, not data) | enforce tz-aware UTC at ingest boundary (Bar already does) |
| **Holiday effects** | thin holiday sessions counted as normal → inflated/garbage trades | **no holiday calendar exists** — currently undetectable | add exchange holiday + half-day calendar; exclude/flag |
| **Weekend gaps** | gap-throughs jump stops/TPs unrealistically | detect Fri→Sun price jumps; check stop fills across the gap | model weekend gap risk; no fills in closed window |
| **Rollover / swap (triple-rollover Wed)** | ignoring swap overstates carry; rollover spread spikes ignored | check spread spike at 21:00–22:00 UTC; account for held-overnight cost | model swap for overnight holds; widen rollover spread |
| **Missing liquidity events** (flash crashes, SNB-type breaks) | absent tail events → understated drawdown | scan for known events (Jan 2015 CHF, Aug 2024 JPY) in the data | ensure sample contains them; stress with synthetic shocks |
| **Gold ≠ FX** | applying FX spread/session/volume assumptions to XAU | separate XAU profile (exists for cost, not sessions/liquidity) | distinct session + cost + liquidity model for gold |

**Verdict:** data layer is unbuilt, so every row above is currently *unmitigated and untested*. The data-quality gate is specified in docs but not implemented in code.

---

## SECTION 3 — Session Logic Audit

The session *math* is the platform's strongest piece — DST conversion is correct and tested, including the 3h/4h overlap regimes. But:

- **`OVERLAP` is never emitted (verified bug).** `active_sessions()` returns `["LONDON","NEWYORK"]` during the overlap; nothing produces the string `"OVERLAP"`, yet the cost model and instrument metadata key off it. Any "overlap edge" or overlap-specific cost is currently **unreachable** — a strategy could be credited/charged wrong because the highest-liquidity window is never labeled as itself.
- **Weekend boundary is DST-wrong (verified bug).** `is_fx_market_open` hardcodes 21:00 UTC, but NY close is 22:00 UTC in winter. ~1h of Friday bars are wrongly marked closed for ~5 months/year — directly contradicting the file's own anti-hardcoding stance. Mislabeled open/closed state corrupts any session-conditioned statistic.
- **Session-boundary leakage.** A trade entered at the exact session start that uses the *prior* session's extremes is fine; but a feature computed "as of session open" that peeks at the open bar's full OHLC is lookahead. No tests cover boundary-instant feature correctness (features don't exist yet).
- **Fold handling at DST transitions.** Bounds use `combine(..., tzinfo=ZoneInfo)` with no explicit `fold`. Safe *only* because no boundary lands in 01:00–03:00 local; change a boundary and you inherit nonexistent/ambiguous-time bugs silently.
- **FX vs gold sessions.** XAU is forced into FX London/NY windows. Gold's liquidity clock is COMEX-influenced; mislabeling its active periods will create or destroy apparent session edges.

**Robust session tests to add:** (1) exhaustive boundary-instant membership across all four DST regimes (partly exists); (2) round-trip "every minute of a year maps to a consistent session set" invariant; (3) holiday-aware open/close once a calendar exists; (4) a test that *fails* if any code path consumes a hardcoded UTC session/weekend constant.

---

## SECTION 4 — Cost Model Audit

The model is conservative in shape but unrealistic in dynamics, and has two correctness issues.

- **Static spreads.** Spread = `max(realized, floor)` but **nothing populates `realized`**, so it is always the floor — flat across volatility, news, and time of day. Real FX spread is a fast-moving function of conditions; a flat spread is the textbook cost illusion.
- **No news / volatility spike model.** Around tier-1 data, spread and slippage spike 5–20×. The model has a blackout *concept* in docs but the cost code applies normal cost through any window unless the caller manually flags it.
- **Commission scaled by stress_factor (wrong).** Broker commission is fixed; inflating it under an execution-stress scenario is a modeling error (minor, but it muddies sensitivity results).
- **Slippage unit footgun.** `slippage_atr_k * atr_pips` silently produces garbage if a caller passes ATR in price units; both are `float`, so neither types nor tests catch it.
- **Gold underpricing risk.** XAU has its own profile (good), but the pip convention (pip=0.1) is arbitrary and every gold cost number scales with it. If it doesn't match the broker, gold costs are off by an unknown factor.
- **No latency / queue cost.** Intraday breakout fills assume you transact at signal price; in fast tape you don't.

**Stress methods to require:** (1) cost sweep at 1.0×/1.5×/2.0× with the hard reject rule (negative at 1.5× → dead); (2) **spread = f(realized volatility)** instead of a floor; (3) punitive news-window cost (or blackout) verified by test; (4) randomized slippage (draw per fill from a fat-tailed distribution) and require the *distribution* of outcomes to stay positive; (5) worst-case fill (always the adverse side of the bar). An edge that only survives the optimistic cost is not an edge.

---

## SECTION 5 — Backtest Engine Integrity

**There is no backtest engine.** This is itself the finding: every risk below is currently 100% unmitigated, and when the engine is built these are the traps to instrument from day one.

- **Bar-close execution lookahead (most dangerous for intraday FX).** Deciding on bar *close* and filling at that same close is using information you only have *after* the bar. Correct: decide on close `t`, fill at open `t+1` (with slippage). A 1-bar execution delay test (Section 9) is the canonical detector.
- **Optimistic fills on breakouts.** Filling at the breakout level assumes liquidity that vanishes precisely when your signal fires. Most fake intraday edge lives here.
- **Stop/TP intrabar ambiguity.** When a bar's range contains both stop and target, naive engines assume the favorable one. Must assume the adverse (stop) fill, or model with tick data.
- **Partial fills / sizing.** Assuming full fill at one price at any size is unrealistic off-peak and in gold.
- **Slippage timing & latency.** Signal→order→fill has latency; price moves in between. Ignored = free money.
- **No order-queue dynamics.** Limit-order strategies especially need queue position; market-order breakout strategies need impact.

Most dangerous for *intraday FX specifically*: bar-close lookahead and breakout fill optimism. Both inflate exactly the strategies on the roster (range/ORB breakouts, sweeps).

---

## SECTION 6 — Statistical Validation Audit

This is where the platform's self-image and reality diverge most.

- **Deflated Sharpe silently no-ops (verified, Critical).** With the default `sr_variance=0.0`, DSR returns the *same* value for `n_trials=1` and `n_trials=500`. The multiple-testing correction — the platform's entire reason to exist — is **opt-in and silently disabled.** A teammate computing DSR the obvious way gets a rigorous-looking number that corrects for nothing.
- **DSR distributional assumptions.** Bailey/LdP DSR assumes returns are IID and uses skew/kurtosis adjustments; the default `kurtosis=3` (normal) understates FX fat tails, making DSR **optimistic**. Trade returns are also autocorrelated/clustered, violating IID.
- **Doc/code threshold contradiction.** `validation-protocol.md` says "DSR > 0" (meaningless for a probability — always true); code requires > 0.5. The documented bar is non-binding.
- **Trade independence is assumed but false.** Both DSR and the Monte Carlo trade-shuffle treat trades as independent draws. Intraday FX trades cluster (same session, same regime, overlapping). Shuffling destroys autocorrelation and **understates** tail risk / overstates significance.
- **Monte Carlo reliability.** Resampling trade *order* tests path dependence but not whether the trade *distribution* itself is a fluke. Block bootstrap (preserving clusters) is needed, not naive shuffle.
- **Walk-forward not implemented.** Only a `WalkForwardWindow` dataclass exists; no window generator, no execution, no per-window aggregation. The 60%-of-windows criterion has nothing to compute it.
- **Parameter-search bias unmeasured.** Nothing logs the trial count, so even a correctly-wired DSR has no `n_trials` to consume.
- **`max_drawdown` computed but unused.** The gate trusts a caller-supplied `drawdown_pct` instead of the metric the platform computes — two sources of truth.

**Ways an overfit strategy still passes today:** DSR no-op lets the luckiest of N trials through; small-n noise clears PF≥1.25 by chance; lockbox can be re-split by a human; in-sample parameter selection leaks because there's no enforced purge; regime/session slices at n=200 are noise dressed as stability.

---

## SECTION 7 — Strategy Evaluation Risks

Each strategy is a behavioral bet that is *also* trivially overfittable.

**1. Asian Range Breakout.** *Assumes:* low-vol Asian range → London expansion breaks it directionally. *Disappears when:* Asia trends (JPY/AUD news, BoJ), holidays produce fake thin ranges, or markets chop (fakeouts dominate). *Breaks in:* ranging/whipsaw regimes; high-vol Asia. *Overfit surface:* buffer `k`, TP multiple `m`, invalidation bars `N` — a small grid still manufactures a winner across 4 instruments. *Backtest-good/live-bad path:* fakeout slippage and London-open spread widening underpriced → the losing breakouts look cheaper than they are.

**2. London Liquidity Sweep + BOS.** *Assumes:* stop-runs beyond session extremes reverse (ICT liquidity grab). *Disappears when:* the sweep is genuine continuation (strong trend), or "BOS" is in the eye of the beholder. *Breaks in:* trending regimes (sweep → run, no reversal). *Overfit surface:* **the worst of the three** — BOS/sweep detection is discretionary; defined with any hindsight it becomes a near-perfect in-sample filter and pure lookahead. *Backtest-good/live-bad path:* BOS confirmed using post-event structure; reversal entries that are physically unfillable in the fast tape after a sweep.

**3. NY Opening Range Breakout.** *Assumes:* the NY opening balance breaks directionally on US flow. *Disappears when:* the move is just the 08:30 ET data spike (un-tradeable), or double-breaks whipsaw. *Breaks in:* news-shock regimes; range days. *Overfit surface:* OR window {15,30}, TP multiple. *Backtest-good/live-bad path:* the "edge" is the data-release spike, which in reality is unfillable slippage — model normal cost and it prints; model real news slippage and it dies.

Common thread: all three are breakout/reversal strategies whose apparent edge is *most sensitive to exactly the costs and fills the current model underprices.*

---

## SECTION 8 — Hidden Sources of False Confidence

- **Overly clean data.** Dukascopy's pre-compiled bars can look gap-free because gaps were filled upstream. Smoothness ≠ truth. *Manifests as:* unrealistically consistent fills.
- **Microstructure ignored.** No spread dynamics, no impact, no queue. *Manifests as:* high win-rate scalp-like results that evaporate live.
- **Unrealistic execution.** Bar-close fills, full size at touch. *Manifests as:* Sharpe that degrades sharply under a 1-bar delay test.
- **Cherry-picked instruments.** Four of the most liquid, trend-friendly instruments. *Manifests as:* edges that don't generalize to the 6 majors we excluded.
- **Confirmation bias in design.** The SMC/ICT priors baked into the sweep strategy bias us toward "confirming" them. *Manifests as:* discretionary BOS rules tuned until they "work."
- **Silent strategy survivorship.** Only three strategies survived to documentation. Each discarded idea was a trial that never entered the DSR count. *Manifests as:* understated multiple-testing burden.
- **Green-tests illusion (the platform's own trap).** 31 passing tests and strict typing created confidence while the DSR no-op disabled the one safeguard that matters. Some tests assert vacuous facts (e.g., XAU pips > EUR pips). *Manifests as:* a team that trusts the harness more than the harness deserves.

---

## SECTION 9 — Hard Failure Tests (destructive battery)

Every candidate must survive all of these *before* it is believed.

| Test | What it checks | How to run | Failure looks like |
|---|---|---|---|
| **Randomized-entry benchmark** | does the *signal* beat random entries with the same exits/costs? | replace entries with random timestamps, same exit/SL/TP/cost, 1000×; build null distribution | strategy not above ~95th pct of random → edge is in the exits/costs, not the signal |
| **1-bar delayed execution** | lookahead / latency sensitivity | shift all fills one bar later | edge largely vanishes → it was lookahead or unfillable |
| **Shuffled trade sequence (block bootstrap)** | path dependence & sequence luck (preserving clusters) | resample trade blocks 10k×; distribution of terminal PnL & max DD | wide/negative-skewed distribution; p50 near zero |
| **Cost stress 1.5× / 2.0×** | cost fragility | re-run with stress_factor sweep | negative at 1.5× → reject |
| **Noise injection** | over-sensitivity to exact prices | jitter OHLC by a fraction of spread/ATR, re-run | results swing materially → curve-fit to noise |
| **Regime segmentation** | regime dependence | partition by trend/range/vol; per-segment metrics | profit concentrated in one regime/period |
| **Cross-instrument** | single-instrument fluke | require ≥3/4 instruments positive | works on one only → fluke |
| **Sign-flip / label-shuffle sanity** | harness correctness | shuffle labels; expectancy should be ~0 | non-zero → leakage in the harness itself |
| **Lockbox single-shot** | p-hacking via re-peeking | enforce one-open lockbox + log every access | more than one open → result void |
| **Bootstrap CI on Sharpe/PF** | metric stability at the actual n | resample trades; 95% CI | CI spans ≤0 → not significant |

The two most decisive: **randomized-entry benchmark** (is the signal real?) and **1-bar delayed execution** (is it lookahead?). A strategy that fails either is finished regardless of headline metrics.

---

## SECTION 10 — Minimal Statistical Standards (conservative)

A strategy is *not* credible unless it clears **all**:

- **Trades:** ≥ 300 out-of-sample (≥ 200 absolute floor; below that = "inconclusive," never "pass"). Per-regime/session cells need their own minimum (≥ 30) or that slice is not interpreted.
- **Out-of-sample / lockbox:** ≥ 2 years, opened exactly once, spanning ≥ 2 distinct regimes.
- **Sharpe:** positive and stable, but **never used alone** — bootstrap 95% CI must exclude 0.
- **Deflated Sharpe (probability):** **> 0.95**, computed with the *actual* trial count and FX-realistic skew/kurtosis (not the normal default). Not the doc's "> 0."
- **Profit factor:** ≥ 1.3 after conservative costs.
- **Max drawdown:** ≤ 20% backtest; Monte-Carlo p95 ≤ 30%.
- **Instrument stability:** positive on ≥ 3 of 4.
- **Session/regime stability:** no single slice > 40% of total PnL; not heavily negative in any major regime.
- **Parameter robustness:** broad plateau, not a peak; neighbors within a tolerance band.
- **Survives destructive battery:** beats randomized-entry null at 95%, survives 1-bar delay, survives 1.5× cost.

If any single bar is missed, the verdict is NO-GO. "Almost passing" is failing.

---

## SECTION 11 — Platform Weakness Ranking

### CRITICAL
1. **DSR multiple-testing correction silently disabled.** The platform's central safeguard returns identical values regardless of trial count unless a caller supplies `sr_variance`. A false edge from N trials passes undetected. *(Verified.)*
2. **No backtest engine / feature layer / ingested data.** No results can be produced, and the most dangerous surfaces (lookahead, fills, realized spread) have **zero** test coverage. Everything downstream is unvalidated.
3. **No lookahead/leakage tests and no purged-CV/embargo.** The protocol mandates them; none exist. Lookahead is the likeliest single cause of a fake FX edge and is currently untestable.

### HIGH
4. **`OVERLAP` label never emitted** → overlap costs/edges unreachable. *(Verified.)*
5. **Weekend open/close DST-wrong** → mislabeled market state ~5 months/year. *(Verified.)*
6. **Cost model is static** (no realized spread, no news/vol spikes) → cost illusion, the top fake-edge source intraday.
7. **No holiday calendar** → contaminated thin-day trades counted as normal.
8. **Trade-independence assumed** in DSR and Monte Carlo → significance overstated, tail risk understated.
9. **Walk-forward unimplemented** despite being a stated gate.

### MEDIUM
10. **Doc/code DSR threshold contradiction** (">0" vs ">0.5"); doc bar is meaningless.
11. **`max_drawdown` computed but unused**; gate trusts caller-supplied number.
12. **Vacuous tests** (cross-instrument pip comparison) create false confidence.
13. **XAU pip convention arbitrary**; all gold costs scale with it.
14. **Sample-size vs slice-criteria tension** (200 trades can't support 4×3 slices).

### LOW
15. `ZoneInfo` per-call (won't scale to tick data; vectorize later).
16. `fold` handling latent (safe only for current boundaries).
17. Packaging: no `py.typed` (types not exported), no shipped CI workflow.

---

## SECTION 12 — Recommendations Before Phase 1

**Statistical safeguards (do first)**
- Fix DSR: make `sr_variance` + `n_trials` mandatory (or estimate sr_variance internally); never let the correction no-op. Set kurtosis to an FX-realistic estimate, not 3.
- Log every configuration tried (instrument × params × variant) and feed the count into DSR automatically.
- Reconcile the DSR threshold doc↔code to **probability > 0.95**; derive `drawdown_pct` from the computed `max_drawdown`.
- Implement walk-forward (window generator + per-window aggregation) and purged k-fold + embargo.
- Replace naive trade shuffle with **block bootstrap**.

**Validation / testing infrastructure**
- Build the **destructive battery** (Section 9) as first-class, automated, required-to-pass.
- Add **no-lookahead property tests** as the *first* code in the feature layer — before any strategy.
- Add a sign-flip/label-shuffle harness-sanity test (expectancy ≈ 0).

**Cost realism**
- Drive spread from **realized bid/ask**; model spread as a function of volatility and news; verify the news blackout/punitive cost with a test.
- Add randomized/worst-case fill modes; require the *distribution* of outcomes to be positive.
- Stop scaling commission by stress; fix the ATR-unit footgun with a sanity assertion.

**Data integrity**
- Implement ingestion + the data-quality gate (coverage ≥ 99.5%, gap ledger, cross-source delta).
- Add an exchange holiday/half-day calendar; ensure the sample contains known tail events (CHF 2015, JPY 2024).
- Distinct session + liquidity model for XAU; pin its pip convention to the broker.

**Correctness fixes**
- Emit `OVERLAP` (or remove the label everywhere); make `is_fx_market_open` DST-correct.

---

## SECTION 13 — Final Verdict

**B) Needs additional safeguards first** — and within B, closer to "not yet able to do credible research" than to "almost ready."

Reasoning. The *architecture* is sound and the session math is genuinely good, so this is not a redesign (not C). But the platform cannot currently produce a credible result for three independent reasons, any one of which is disqualifying:

1. The one safeguard that justifies a "research-first, multiple-testing-aware" platform — the deflated Sharpe — **silently does nothing** by default. A platform whose anti-overfitting control is off-by-default is *more* dangerous than one with none, because it manufactures false confidence.
2. The components that actually generate results — engine, features, data — **do not exist**, so the highest-risk surfaces (lookahead, fills, realized spread) are entirely untested. There is nothing yet to trust or distrust.
3. Concrete correctness bugs (overlap label, weekend DST) and an unrealistic static cost model would bias results even once the engine exists.

It is **safe to continue building**; it is **not safe to trust any number** the platform produces until the Critical and High items are closed, and until a strategy clears the destructive battery in Section 9 — especially the randomized-entry and 1-bar-delay tests. Until then, assume any apparent edge is an artifact.

> The platform is currently optimized to *look* rigorous. The work of Phase 0.5 is to make it *be* rigorous — starting by turning the multiple-testing correction back on.
