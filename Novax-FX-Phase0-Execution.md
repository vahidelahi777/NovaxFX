# Novax FX Platform — Phase 0: Research & Validation (Execution Plan + Artifacts)

*Strict, skeptical, falsifiable. No live capital. No invented results. The goal is to learn whether an edge plausibly exists — and to be willing to conclude it does not.*

---

## 1. Phase 0 Objective

Phase 0 exists to answer a single question before any meaningful infrastructure is built: **does a realistic, testable, cost-aware trading edge plausibly exist in our priority instruments/sessions/strategies, or not?** We are trying to *disprove* the null hypothesis that each candidate strategy's post-cost expectancy is ≤ 0 and indistinguishable from noise. We do this on real (not synthetic) market data, with conservative cost assumptions, proper out-of-sample discipline, and multiple-testing control, producing a defensible go/no-go decision. Phase 0 succeeds whether the answer is yes *or* no — a credible "no" that saves months of misdirected build is a successful outcome.

---

## 2. Phase 0 Non-Negotiable Rules

- **No live capital. No broker execution. No order routing.** Research only.
- **No ML-first.** Rule-based baselines must be validated before any ML is introduced.
- **No optimization without a sealed lockbox.** A held-out final test set is created on day one and never touched until the go/no-go.
- **No conclusions from synthetic data.** Synthetic data is for plumbing tests only; *edge claims require real historical data*.
- **No ignoring costs.** Every result is reported after spread + slippage + commission. Pre-cost numbers are inadmissible as evidence of edge.
- **No hardcoded session assumptions without DST handling.** Sessions are defined in local exchange time and converted to UTC (see §10 and the shipped `sessions.py`).
- **No "p-hacking."** Track every parameter combination tested; apply multiple-testing correction (deflated Sharpe).
- **No advancing to Phase 1** unless the §3 success criteria are met. A strategy that only passes under optimistic costs is rejected, not "kept for later."
- **Reproducibility is mandatory.** Every result ties to a code commit + data hash + parameter set + cost model.

---

## 3. Phase 0 Success Criteria (Go / No-Go — deliberately strict)

A strategy advances only if it clears **all** of the following. These are intentionally hard; most candidate strategies are expected to fail, and that is the point.

| Criterion | Threshold |
|---|---|
| Data quality | ≥ 99.5% expected bars present in trading hours; gaps quantified and explained; spread series available |
| Reproducibility | A backtest re-run from the same commit + data hash reproduces metrics **bit-for-bit** |
| Instruments | Validated on **≥ 3** of {EUR/USD, GBP/USD, USD/JPY, XAU/USD} (not a single-instrument fluke) |
| Date range | **≥ 5 years** of real data spanning multiple regimes (incl. 2020 vol, 2022 trends) |
| Sample size | **≥ 200** out-of-sample trades per strategy (per instrument where feasible); thin samples → "inconclusive," not "pass" |
| Walk-forward | Positive expectancy in **≥ 60%** of walk-forward windows, no single window dominating total PnL |
| Out-of-sample (lockbox) | Net-positive expectancy after costs on the never-touched lockbox |
| Max drawdown | Backtest max DD **≤ 20%** of notional risked; Monte-Carlo 95th-percentile DD **≤ 30%** |
| Profit factor / expectancy | **PF ≥ 1.25** AND positive expectancy per trade after costs (PF ≥ 1.3 preferred for thinner samples) |
| Cost degradation | Edge must survive a **1.5× conservative cost** stress; if 1.0×→1.5× flips it negative, **reject** |
| Stability | No single session/regime accounts for **> 50%** of PnL; not negative in any major regime by a large margin |
| Statistical confidence | **Deflated Sharpe Ratio > 0** (after correcting for number of trials); naive Sharpe alone is inadmissible |
| **Kill conditions** | Edge vanishes after costs; only works in one window/instrument/regime; depends on data the live system won't have (lookahead); requires parameter precision (sharp optimum, no plateau); sample too small to be significant |

> **Founding-team stance:** if a strategy "barely passes" several criteria, treat it as a *fail*. Phase 0 is biased toward rejection on purpose — the expensive mistake is a false positive that triggers a build.

---

## 4. Phase 0 Scope

**In scope:** data-source selection; instrument selection; DST-correct session definitions; strategy hypothesis documents (3); initial backtest specification; conservative cost-model specification; validation methodology; research scripts/notebooks (importing shared libs, not production services); go/no-go report template; the first repo task list.

**Out of scope (do not build):** live trading; broker execution; production dashboard/frontend; advanced ML; SaaS/billing/multi-tenant; strategy marketplace; Kubernetes; Kafka/Redpanda; microservices; feature store; model registry beyond a simple experiment log.

---

## 5. Phase 0 Deliverables

| Deliverable | Purpose | Owner | Format | Acceptance criteria | Dependencies |
|---|---|---|---|---|---|
| Data Source Decision Memo | Pick Phase 0 data sources | Data Eng | Memo (§17.1) | Sources chosen with rationale + ingestion approach | — |
| Instrument Universe Memo | Lock 4 instruments + specs | Quant/Trader | Memo (§17.2) | pip size, sessions, cost notes per instrument | Data memo |
| Session Calendar Spec + module | DST-correct sessions | Backend/Data | Spec (§17.3) + tested `sessions.py` | Tests pass incl. DST-mismatch week | — |
| 3× Strategy Hypothesis Docs | Falsifiable strategy specs | Quant + Trader | Filled template (§8) | All template fields complete + testable predictions | Session spec |
| Cost Model Spec | Conservative cost assumptions | Risk + Trader | Spec (§11) | Spread/slip/commission per instrument + stress factors | Instrument memo |
| Validation Protocol | Exact validation process | Quant Lead | Protocol (§12) | WF + lockbox + DSR + MC defined and parameterized | — |
| Backtest Experiment Plan | Per-strategy test design | Quant Lead | Plan (§13) | Grids, fixed params, metrics, kill criteria per strategy | Hypotheses, costs |
| Data Quality Checklist | Gate ingested data | Data Eng | Checklist | Coverage/gap/spread/dedup checks defined | Data memo |
| Risk Assumptions Doc | Phase 0 risk framing | Risk | Doc | Per-trade risk, sizing, DD caps for backtests | — |
| Go/No-Go Report Template | Decision artifact | Product/Quant | Template (§16) | All decision sections present | Validation protocol |
| Initial Repo Task List | First engineering issues | CTO | Issue list (§14) | Actionable GitHub issue titles + descriptions | — |

---

## 6. Phase 0 Task Breakdown

**Research**
- `R-1` Confirm trading conventions/sessions per instrument · Quant/Trader · P1 · 0.5d · — · session notes · cross-checked vs vendor.
- `R-2` Literature/known-failure review for the 3 strategies · Quant · P2 · 1d · — · risk notes · documented failure modes.

**Data**
- `D-1` Stand up data pull (OANDA candles + Dukascopy tick→bar) · Data Eng · P1 · 1.5d · R-1 · raw Parquet · 4 instruments, 5y, 99.5% coverage.
- `D-2` Normalize to canonical UTC OHLCV + spread · Data Eng · P1 · 1d · D-1 · curated Parquet/DuckDB · schema + gap flags.
- `D-3` Data-quality checklist + report · Data Eng · P1 · 0.5d · D-2 · QA report · thresholds met or exceptions logged.

**Quant Strategy**
- `Q-1` Fill 3 hypothesis docs · Quant+Trader · P1 · 1.5d · R-1 · specs · all fields + testable predictions.
- `Q-2` Define feature primitives (ranges, ATR, sweep/BOS) · Quant · P1 · 1d · D-2 · feature funcs · unit-tested, no lookahead.

**Backtesting**
- `B-1` Cost model implementation · Quant+Risk · P1 · 1d · cost spec · cost module · stress factors configurable.
- `B-2` Backtest runner (VectorBT screen + event-driven check) · Quant · P1 · 2d · Q-2,B-1 · runner · reproducible (commit+hash).
- `B-3` Walk-forward + lockbox + Monte Carlo + DSR · Quant Lead · P1 · 2d · B-2 · validation report · protocol implemented.

**Risk**
- `K-1` Risk assumptions doc + DD caps · Risk · P1 · 0.5d · — · doc · sizing + caps defined.
- `K-2` Cost-sensitivity sweep (1.0× / 1.25× / 1.5×) · Risk+Quant · P1 · 0.5d · B-3 · sensitivity table · kill rule applied.

**Engineering**
- `E-1` Repo scaffold + CI (lint/test) + pre-commit · CTO/Backend · P1 · 1d · — · repo · CI green.
- `E-2` Ship + test `sessions.py` · Backend · P1 · 0.5d · — · module · DST tests pass.
- `E-3` Experiment logging (MLflow or simple run log) · Backend · P2 · 0.5d · E-1 · logger · every run recorded.

**Documentation**
- `DOC-1` Go/No-Go report template · Product · P1 · 0.5d · — · template · sections complete.
- `DOC-2` Phase 0 final report (filled) · Quant Lead · P1 · 1d · B-3,K-2 · report · decision justified.

---

## 7. Day-by-Day Execution Plan (10 business days, team of 1–3)

| Day | Goal | Tasks | Output | Blocker risks | Decision |
|---|---|---|---|---|---|
| 1 | Foundation up | E-1, E-2, K-1 | Repo+CI, sessions module, risk doc | env/keys | Repo layout locked |
| 2 | Data flowing | D-1 (start), R-1 | Raw pulls begin | provider limits/rate caps | Which sources/instruments final |
| 3 | Data trustworthy | D-1 (finish), D-2 | Curated UTC OHLCV+spread | Dukascopy↔OANDA mismatch | Accept data quality? |
| 4 | QA + hypotheses | D-3, Q-1 (start) | QA report, draft specs | hidden gaps | Data passes gate? |
| 5 | Strategies specified | Q-1 (finish), Q-2 (start) | 3 hypothesis docs | spec ambiguity | Hypotheses falsifiable? |
| 6 | Features + costs | Q-2 (finish), B-1 | Feature funcs, cost model | lookahead in features | Cost assumptions agreed |
| 7 | First backtests | B-2 | Reproducible runs | reproducibility breaks | Any signal worth WF? |
| 8 | Validation | B-3 (start) | WF + lockbox wiring | overfitting temptation | Stick to protocol |
| 9 | Robustness | B-3 (finish), K-2 | DSR, MC, cost sensitivity | thin samples | Survives stress? |
| 10 | Decision | DOC-2 | Filled go/no-go report | confirmation bias | **GO / NO-GO / ITERATE** |

---

## 8. Strategy Hypothesis Template (+ 3 filled)

### Template (reusable)
`strategy_name` · `market_thesis` · `behavioral_reason_edge_exists` · `session_dependency` · `instrument_dependency` · `entry_logic` · `exit_logic` · `stop_loss_logic` · `take_profit_logic` · `invalidation_rules` · `regime_filter` · `news_filter` · `spread_liquidity_filter` · `required_data` · `expected_failure_modes` · `testable_predictions` · `metrics_to_evaluate` · `minimum_viable_backtest` · `reasons_to_reject`.

---

### 8.1 Asian Range Breakout
- **Thesis:** the low-volatility Asian session builds a range that is broken with momentum as London liquidity arrives.
- **Behavioral reason:** overnight positioning compresses price; London participants inject volume/volatility, and stops cluster just beyond the Asian extremes.
- **Session:** enter around London open. **Instruments:** EUR/USD, GBP/USD, EUR/JPY, GBP/JPY, XAU/USD.
- **Entry:** break of Asian-session high/low + buffer (k·ATR) confirmed by range-expansion thrust.
- **Exit/TP:** measured move (range_height × m) or overlap extreme. **SL:** opposite side of range / structural swing. **Invalidation:** close back inside range within N bars (fakeout).
- **Regime filter:** require London non-ranging regime. **News filter:** skip if high-impact EUR/GBP/USD print within window. **Spread/liquidity:** skip if spread > cap or thin pre-London liquidity.
- **Required data:** 1m+ OHLCV, spread, session calendar, economic calendar.
- **Expected failure modes:** false breakouts on chop, holiday thinness, double-sided sweeps.
- **Testable predictions:** breakout continuation > random; edge concentrated in first 1–2h of London; worse on low-ATR Asian days.
- **Metrics:** expectancy, PF, win-rate, MAE/MFE, fakeout rate. **MVB:** EUR/USD + GBP/USD, 5y, 5m bars, conservative costs, ≥200 OOS trades. **Reject if:** edge < costs, only one instrument, or only pre-2021.

### 8.2 London High/Low Liquidity Sweep + BOS (SMC)
- **Thesis:** price sweeps a prior session's high/low (stop run), then reverses with a break of structure — the classic ICT liquidity grab.
- **Behavioral reason:** resting stops beyond obvious highs/lows are liquidity; large players push through to fill, then reverse.
- **Session:** London (sweeping Asian liquidity). **Instruments:** GBP/USD, EUR/USD, XAU/USD, GBP/JPY.
- **Entry:** sweep of Asian high/low → displacement/BOS opposite → entry on OB/FVG retest. **SL:** beyond sweep extreme. **TP:** opposing liquidity pool / prior-day extreme. **Invalidation:** close beyond sweep extreme without BOS.
- **Regime filter:** works in both ranging→reversal and trend-resumption; gate out dead-flat low-ATR. **News filter:** mandatory around high-impact prints. **Spread/liquidity:** strict (sweeps happen in fast tape).
- **Required data:** 1m OHLCV (BOS needs fine structure), spread, session calendar, calendar.
- **Expected failure modes:** sweep without reversal (continuation), subjective BOS detection, late entries.
- **Testable predictions:** post-sweep reversal probability > base rate; edge stronger when sweep aligns with HTF bias. **Metrics:** + sweep→reversal hit-rate, R-multiples. **MVB:** GBP/USD + XAU/USD, 5y, 1m bars. **Reject if:** BOS rules require hindsight, or edge disappears under realistic fills. *(This is the production-grade version of the existing Novax SMC logic — define sweep/BOS as tested primitives.)*

### 8.3 New York Opening Range Breakout
- **Thesis:** the first X minutes of NY define a range; the break signals direction from US-driven flow.
- **Behavioral reason:** US data/flow at the open creates an initial balance; the break carries.
- **Session:** NY open (DST-correct). **Instruments:** USD majors (EUR/USD, USD/JPY, USD/CAD), XAU/USD.
- **Entry:** break of opening-range (e.g. first 15–30m) high/low + thrust. **SL:** opposite OR side. **TP:** OR_height × m or session extreme. **Invalidation:** re-entry into OR within N bars.
- **Regime filter:** non-ranging; **News filter:** mandatory around 8:30 ET data (often the *cause* — decide momentum vs avoid). **Spread/liquidity:** spreads widen at data; model explicitly.
- **Required data:** 1m OHLCV, spread, calendar (8:30 ET prints).
- **Expected failure modes:** whipsaw on the data spike, double breaks, holiday sessions.
- **Testable predictions:** OR-break continuation > random; better on data days *after* the initial spike settles. **Metrics:** expectancy, PF, post-news slippage realized. **MVB:** EUR/USD + XAU/USD + USD/JPY, 5y. **Reject if:** edge is just the data-spike (un-tradeable slippage) or single-instrument.

---

## 9. Data Source Decision (summary; full memo in §17.1)

| Source | Pros | Cons | Cost | Quality concern | Phase 0 fit |
|---|---|---|---|---|---|
| **OANDA v20 (practice)** | REST+stream, candles incl. bid/ask, **execution-aligned**, free demo | candle = base-price group (differs from account live pricing); 5000/req paging; tick vol only | Free | historical ≠ your live pricing group | **Primary** (execution-aligned reference) |
| **Dukascopy** | Free deep tick history (incl. XAU), bid/ask, ECN-sourced | not your execution broker; weekend gaps; downloader effort | Free | ECN feed ≠ retail fills | **Primary** (deep history/backtest) |
| **TwelveData** | simple REST, FX+metals, you already use it | free tier 8/min·800/day, **silent 429s**, limited deep history free | Free→$29+/mo | aggregated, shallow on free | **Secondary** (cross-check/convenience) |
| **Paid institutional** (Databento/Polygon/Refinitiv) | high quality, depth | cost, overkill pre-validation | $$$ | — | **Defer** to post-validation |

**Recommendation:** Dukascopy for deep history + OANDA practice for execution-aligned reference & streaming; TwelveData as secondary cross-check. **Backtest on the feed closest to where you'd execute (OANDA), and use Dukascopy depth to stress-test robustness.** Defer paid data until an edge is validated.

---

## 10. Session Calendar Specification (summary; full spec + verified windows in §17.3)

All instants in **UTC**; sessions defined in **local exchange tz** and converted via `zoneinfo` (DST automatic). The shipped, tested `sessions.py` implements ASIA (Tokyo, no DST), LONDON, NEWYORK, and the LONDON–NY overlap as the intersection of the two. **Verified** overlap windows: 13:00–16:00 UTC in winter, 12:00–15:00 UTC in summer, and **12:00–16:00 UTC (4 hours) during DST-mismatch weeks** — the case a hardcoded UTC window silently breaks. Tests assert all four regimes + naive-datetime rejection + weekend gating.

---

## 11. Cost Model Specification

Conservative by default — a strategy must survive pessimistic costs.

- **Spread:** per-instrument, **session- and time-dependent**; widen materially in Asian session and around news. Use realized spread from the data feed where available, else conservative fixed floors (e.g. EUR/USD wider than its tightest quote; **XAU/USD substantially wider**).
- **Slippage:** applied on every fill, larger on breakouts/news; model as fixed pips + a volatility-scaled component (k·ATR). Stops assume adverse slippage.
- **Commission:** per-side per-lot (model even on spread-only accounts to stay conservative).
- **Session liquidity:** higher slippage/spreads in Asian + rollover; reduced size assumption off-peak.
- **News-event volatility:** spreads/slippage spike; either blackout or apply punitive cost in the window.
- **XAU/USD special:** wider spreads, larger pip value, gappier, bigger ATR — never reuse FX-major cost assumptions for gold.
- **Conservative assumptions:** round costs *up*, fills *against* you, partial-fill skepticism on thin liquidity.
- **Sensitivity analysis:** run every strategy at **1.0× / 1.25× / 1.5×** cost. **Rejection rule:** if the edge is positive at 1.0× but negative at 1.5×, it is **too fragile — reject.** Edge must be robust to cost, not balanced on a knife-edge.

---

## 12. Validation Methodology

- **Train/test split:** chronological only (never random shuffle on time series).
- **Walk-forward:** rolling optimize→test windows; report per-window expectancy; no single window may dominate PnL.
- **Out-of-sample lockbox:** final slice sealed day one, opened **once** at go/no-go. Touch it twice → it's no longer out-of-sample.
- **Purged k-fold + embargo:** when any fitting/labeling occurs, purge train samples overlapping test labels and embargo a gap to kill leakage.
- **Monte Carlo:** resample trade order/returns → drawdown & terminal-wealth distribution (judge the *distribution*, not one curve).
- **Deflated Sharpe Ratio:** discount Sharpe for the **number of trials**; require DSR > 0. This is the antidote to "we tested 200 variants and one looked great."
- **Parameter robustness:** require a **plateau** (neighboring params perform similarly); a lone sharp peak = overfit.
- **Multiple-testing control:** log every configuration tested; feed the count into DSR.
- **Regime/session breakdown:** performance must be reported sliced by session and regime; no single slice > 50% of PnL.
- **Cost sensitivity:** §11 stress is part of validation, not optional.
- **Strategy decay:** compare early vs late sub-periods; flag monotonic decline.

---

## 13. Initial Backtest Experiment Plan (per strategy)

**Common:** date range ≥ 5y; conservative costs (§11); reproducibility (commit+data_hash); metrics = expectancy, PF, win-rate, Sharpe, **DSR**, max DD, MC p95 DD, trade count, MAE/MFE; **fixed (not optimized):** risk-per-trade, cost model, session boundaries, news-blackout rule.

| Strategy | Instruments | TF | Features | Param grid (small!) | Expected trades | Known weakness | Kill criteria |
|---|---|---|---|---|---|---|---|
| Asian Range Breakout | EUR/USD, GBP/USD, XAU/USD | 5m | Asian H/L, ATR, range height | buffer k∈{0.1,0.25,0.5}·ATR; TP m∈{1,1.5,2} | ~200–600 OOS | false breakouts | PF<1.25 after costs; one-instrument-only; no plateau |
| London Sweep+BOS | GBP/USD, EUR/USD, XAU/USD | 1m | sweep flag, BOS, OB/FVG | sweep buffer; BOS lookback | ~150–400 OOS | sweep w/o reversal; subjective BOS | needs hindsight; negative at 1.5× cost |
| NY ORB | EUR/USD, USD/JPY, XAU/USD | 1m/5m | opening range, ATR | OR window∈{15,30}m; m∈{1,1.5} | ~200–500 OOS | data-spike whipsaw | edge = un-tradeable spike slippage |

> Keep grids **small** — every extra combination inflates the multiple-testing penalty. Wide grids are how you manufacture a fake winner.

---

## 14. Initial Repo Task List (GitHub-issue-ready)

**Repository setup**
- `repo: scaffold monorepo (apps/libs/research/infra/docs) + pyproject + ruff/black/mypy` — base layout per architecture blueprint.
- `ci: GitHub Actions lint+type+test on PR` — block merge on red.
- `repo: pre-commit hooks (ruff, black, mypy, trailing-ws)` — enforce locally.

**Data ingestion**
- `data: OANDA v20 candle puller with 5000/req paging + retry/backoff` — base-price candles, bid/ask, M1+.
- `data: Dukascopy tick downloader → resampled bars (incl. XAU/USD)` — wrap duka/dukascopy-node; cache raw.
- `data: TwelveData secondary fetcher with rate-limit guard (handle 429)` — never silently skip.
- `data: raw landing writer (immutable Parquet, source+fetch_ts)` — reproducibility.

**Data validation**
- `data: coverage/gap report per instrument/tf (>=99.5% gate)` — fail loudly.
- `data: cross-source sanity check (OANDA vs Dukascopy deltas)` — flag divergence.
- `data: spread series extraction + sanity bounds` — no zero/negative spreads.

**Session calendar utilities**
- `lib: ship sessions.py (DST-correct) + tests` — ✅ done (this delivery).
- `lib: tag bars with session + overlap + active_sessions` — feature input.

**Research scripts/notebooks**
- `research: feature primitives (Asian H/L, ATR, sweep, BOS, OR)` — unit-tested, no lookahead.
- `research: strategy notebooks for the 3 hypotheses` — import libs, never imported by prod.

**Cost model utilities**
- `lib: cost model (spread/slippage/commission, session+news scaling, XAU profile)` — configurable stress factor.

**Backtest runner**
- `backtest: VectorBT screening runner (reproducible, logs commit+hash)` — fast triage.
- `backtest: walk-forward + lockbox + Monte Carlo + deflated Sharpe` — the validation core.
- `backtest: cost-sensitivity sweep (1.0/1.25/1.5x) + reject rule` — fragility gate.

**Reporting**
- `report: go/no-go report template (data/strategy/validation/cost/robustness/decision)` — §16.
- `report: experiment log (MLflow or sqlite run table)` — every run recorded.

**Test suite**
- `test: no-lookahead property tests for features` — invariants.
- `test: cost-model unit tests (XAU vs FX)` — correctness.
- `test: reproducibility test (same inputs → same metrics)` — bit-for-bit.

---

## 15. Phase 0 Risks

| Risk | Why it matters | Early warning | Mitigation | Kill condition |
|---|---|---|---|---|
| No real edge | The whole premise | weak/again-flat results across instruments | conservative costs, honest validation | all 3 strategies fail §3 → no-go |
| Overfitting | fake confidence → bad build | sharp param peak, great in-sample only | plateau req, DSR, lockbox | edge only at a single param point |
| Data quality | garbage in → garbage out | gaps, spread anomalies, source divergence | QA gate, cross-source check | can't reach 99.5% coverage |
| Lookahead/leakage | inflated results | "too good," uses future info | no-lookahead tests, purge+embargo | feature needs hindsight |
| Cost underestimation | live ≪ backtest | edge thin at 1.0× | 1.5× stress | negative at 1.5× |
| DST/session bug | mislabels regimes/sessions | overlap window off by ~1h | tested `sessions.py` | session logic can't pass tests |
| Small sample | noise mistaken for edge | < 200 OOS trades | require sample threshold | inconclusive → not a pass |
| Confirmation bias | we *want* it to work | rationalizing failures | strict criteria, willing "no-go" | criteria bent to pass |

---

## 16. Phase 0 Final Report Format

1. **Data summary** — sources, instruments, ranges, coverage %, gaps, known limitations.
2. **Strategy summary** — the 3 hypotheses + what was actually tested.
3. **Validation results** — per strategy: expectancy, PF, Sharpe, **DSR**, walk-forward window pass-rate, lockbox result, trade counts.
4. **Cost sensitivity** — metrics at 1.0× / 1.25× / 1.5×; survivors flagged.
5. **Robustness** — parameter plateau evidence, Monte-Carlo DD distribution, regime/session breakdown.
6. **Failure modes** — what broke, what's fragile, what's unexplained.
7. **Decision** — per strategy: **GO / NO-GO / ITERATE**, with the criteria each met/missed.
8. **Recommendation** — proceed to Phase 1, iterate Phase 0, or stop — and *why*.
9. **Next-phase approval/rejection** — explicit gate verdict; if GO, the narrow scope Phase 1 should start with.

---

# 17. Artifacts (produced now)

## 17.1 — Artifact 1: Data Source Decision Memo

**Decision:** For Phase 0, ingest from **two primary free sources** — **Dukascopy** (deep historical depth, including XAU/USD) and **OANDA v20 practice** (execution-aligned reference + streaming) — with **TwelveData** as a **secondary cross-check**. Defer all paid/institutional feeds until an edge is validated.

**Rationale & implementation notes (engineer-ready):**

**OANDA v20 (practice account) — PRIMARY (execution-aligned).**
- *Why:* it is the feed closest to where we would eventually execute, so backtests on it are the least self-deceiving. REST candles + streaming, demo account is free and gives API tokens.
- *Concrete constraints:* the `/v3/instruments/{instrument}/candles` endpoint returns **max 5000 candles per request** — page with a from/to loop (the `InstrumentsCandlesFactory` pattern handles this). Request **bid+ask** candles (`price=BA`) plus mid; do **not** assume candle data equals your account's live pricing — OANDA's historical candles are **base-price group** and can differ from your account's live pricing group. "Volume" is **tick volume**, not real volume. Use UTC throughout; symbols use underscore form (`EUR_USD`, `XAU_USD`).
- *Effort:* low. Token from the demo HUB → API access.

**Dukascopy — PRIMARY (deep history / robustness).**
- *Why:* free, high-quality **tick** data (bid/ask) sourced from its ECN/SWFX pool, with deep history (many instruments back 15+ years) and coverage of **XAU/USD** and silver. Lets us validate on data *independent* of our execution feed — a robustness cross-check.
- *Concrete approach:* use a maintained open-source downloader (Python `duka`, or `dukascopy-node` CLI) to pull ticks per instrument/day, then resample to 1m/5m bars in Polars; cache raw immutably as Parquet. Expect per-day file granularity and non-trivial download time for years of ticks (parallelize politely; don't hammer).
- *Caveats:* it is **not** our execution broker — treat its spreads/fills as a reference, not a promise. Weekend/holiday gaps must be flagged. Its tick volume is Dukascopy's.

**TwelveData — SECONDARY (cross-check / convenience).**
- *Why:* simple REST, covers FX + precious metals, already in use. Good for quick sanity cross-checks and convenience pulls.
- *Concrete constraints:* free tier is **8 API credits/min and 800/day**; **rate-limit (429) errors are easy to miss and cause silent gaps** — the fetcher **must** catch 429 and back off, never skip-and-continue. Deep historical depth on the free tier is limited; paid "Grow" (~$29/mo) lifts daily limits if needed later.

**Deferred (do not buy in Phase 0):** Databento, Polygon, Refinitiv/Bloomberg. High quality but unjustified before an edge exists. Re-evaluate at Phase 1+ if data quality is the binding constraint.

**Ingestion plan:** backfill 5y of M1 (resampled to 5m where used) for the four instruments from Dukascopy; pull OANDA bid/ask candles for the same range as the execution-aligned reference; use TwelveData only to spot-check divergences. Land everything immutably as Parquet with `source` + `fetch_ts`; build curated UTC OHLCV+spread in DuckDB. **Gate on the data-quality checklist (≥99.5% coverage) before any backtest.**

---

## 17.2 — Artifact 2: Instrument Universe Memo

**Locked Phase 0 universe (4):** EUR/USD, GBP/USD, USD/JPY, XAU/USD. Chosen for liquidity, regime diversity, and direct relevance to the 3 priority strategies; XAU/USD included because it is the existing system's actual focus and behaves distinctly (it is a *metal*, not an FX major — handle its costs/vol separately).

| Instrument | Class | Quote/pip convention | Typical character | Best-fit sessions | Cost/vol notes |
|---|---|---|---|---|---|
| **EUR/USD** | FX major | 1 pip = 0.0001; price ~1.0–1.2 | tightest spreads, deepest liquidity, cleaner ranges | London, NY, overlap | tightest costs; benchmark instrument |
| **GBP/USD** | FX major | 1 pip = 0.0001 | more volatile than EUR/USD, sharp London moves | London, overlap | wider spread than EUR/USD; good sweep candidate |
| **USD/JPY** | FX major | 1 pip = 0.01; price ~100–160 | Asian-session sensitivity, BoJ/rate-driven | Asia, NY | pip math differs (0.01); watch intervention/news |
| **XAU/USD** | Metal | price ~1.8k–2.7k; "pip" = 0.1 (define explicitly) | high ATR, gappy, news/risk-driven | London, NY, overlap | **wider spreads, larger pip value, bigger ATR — never reuse FX-major cost assumptions** |

**Per-instrument requirements:**
- Store exact `pip_size` and `price_precision` per instrument (EUR/USD & GBP/USD 0.0001; USD/JPY 0.01; XAU/USD define, commonly 0.01 with pip=0.1 — **document the chosen convention and use it consistently in cost + PnL math**).
- Attach the DST-correct session profile (from `sessions.py`) to each.
- XAU/USD gets its **own cost profile** (spread floor, slippage, pip value) — a separate config block, not the FX defaults.
- Validation requires **≥ 3 of 4** instruments to pass; a strategy that only works on one is rejected as a likely fluke.

**Out of scope for Phase 0:** the remaining majors/crosses (USD/CHF, AUD/USD, NZD/USD, USD/CAD, EUR/JPY, GBP/JPY, EUR/GBP) — add only after the core 4 show signal.

---

## 17.3 — Artifact 3: Session Calendar Specification (with shipped, tested module)

**Principle:** store and reason in **UTC**; **define** sessions in local exchange time and convert via `zoneinfo` so DST — including the London/NY mismatch weeks — is correct *by construction*. A working, tested module (`libs/data/sessions.py`) is delivered with this memo.

**Session definitions (convention — configurable per vendor):**

| Session | Local window | Timezone | DST behavior |
|---|---|---|---|
| ASIA (Tokyo) | 09:00–18:00 | Asia/Tokyo | **No DST** → always 00:00–09:00 UTC |
| LONDON | 08:00–16:00 | Europe/London | GMT ↔ BST |
| NEW YORK | 08:00–17:00 | America/New_York | EST ↔ EDT |
| LONDON–NY OVERLAP | intersection of LONDON ∩ NEWYORK | — | shifts/lengthens with DST |

**Verified overlap windows (computed by the shipped module):**

| Regime | Example date | ASIA (UTC) | LONDON (UTC) | NEW YORK (UTC) | **Overlap (UTC)** |
|---|---|---|---|---|---|
| Winter (both standard) | 2025-01-15 | 00:00–09:00 | 08:00–16:00 | 13:00–22:00 | **13:00–16:00 (3h)** |
| **Spring mismatch** (US EDT, UK GMT) | 2025-03-12 | 00:00–09:00 | 08:00–16:00 | 12:00–21:00 | **12:00–16:00 (4h)** |
| Summer (both DST) | 2025-07-15 | 00:00–09:00 | 07:00–15:00 | 12:00–21:00 | **12:00–15:00 (3h)** |
| **Autumn mismatch** (UK GMT, US EDT) | 2025-10-29 | 00:00–09:00 | 08:00–16:00 | 12:00–21:00 | **12:00–16:00 (4h)** |

The mismatch weeks are the whole point: the overlap is **4 hours**, not 3 — because the UK and US change DST on different Sundays (UK: last Sunday Mar / last Sunday Oct; US: 2nd Sunday Mar / 1st Sunday Nov). A hardcoded UTC overlap silently mislabels ~an hour of bars twice a year.

**How sessions are represented in code:** sessions are immutable `SessionWindow(name, tz, start, end)` records; membership and bounds are computed by converting via `zoneinfo`. The module **rejects naive datetimes** (forcing tz-aware UTC discipline) and includes coarse FX weekend gating (closed Fri 21:00 → Sun 21:00 UTC; refine with a holiday calendar in Phase 1).

**How session correctness is tested (shipped, 13 tests passing):**
- ASIA bounds constant at 00:00–09:00 UTC year-round (Japan no DST).
- Winter/summer overlaps are 3h; **both DST-mismatch weeks are 4h**.
- `is_in_overlap` agrees with computed bounds; end-exclusive boundary correct.
- Naive datetime raises; non-UTC aware input is normalized, not mishandled.
- Weekend gating (closed Saturday; open midweek).

> Delivered files: `libs/data/sessions.py` and `libs/data/test_sessions.py` (run `pytest -q`). This closes the single most common silent backtesting bug before any strategy is tested — and directly addresses the kind of session/regime mislabeling that produced "RANGING 100% of windows" in the existing system.

---

*Phase 0 is engineering and research only — not financial advice, no promise of profit, no live trading. The deliverable of Phase 0 is a trustworthy yes/no on edge, and the discipline to act on a "no."*
