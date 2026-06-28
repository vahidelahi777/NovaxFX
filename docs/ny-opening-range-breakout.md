# Strategy Hypothesis — New York Opening Range Breakout (ORB)

**Status:** hypothesis (untested) · **Owner:** Quant + Senior Trader
**This is a falsifiable hypothesis, not a known edge.** It must pass [`../validation-protocol.md`](../validation-protocol.md) before it means anything.

## Market thesis
The first X minutes of the New York session define an opening range; the break of that range signals directional intent driven by US flow.

## Behavioral reason the edge may exist
US data and flow at the open create an initial balance. Once participants commit a direction, the break of the opening range tends to carry.

## Session dependency
**New York open** (DST-correct NEWYORK bounds from `sessions.py` — note NY open shifts in UTC across DST).

## Instrument dependency
USD majors (EUR/USD, USD/JPY, USD/CAD), XAU/USD. Phase 0 tests: **EUR/USD, USD/JPY, XAU/USD**.

## Entry logic
Break of the opening-range high/low (range = first 15–30 min of NY) + a thrust confirmation.

## Exit logic
`OR_height · m` or the NY session extreme.

## Stop-loss logic
Opposite side of the opening range.

## Take-profit logic
`OR_height · m`, `m ∈ {1, 1.5}`.

## Invalidation rules
Re-entry back into the opening range within `N` bars after the break (failed break) → exit/cancel.

## Market regime filter
Require **non-ranging** conditions; skip days that stay inside the opening range.

## News filter
**Mandatory** handling around 08:30 ET prints — these are often the *cause* of the move. Decide explicitly per variant: trade momentum **after** the spike settles, or blackout through it. Never apply normal cost across a data spike.

## Spread/liquidity filter
Spreads widen at the data release; model explicitly (news cost or blackout). Skip if spread > cap.

## Required data
1m OHLCV, spread series, economic calendar (08:30 ET prints), session calendar.

## Expected failure modes
- Whipsaw on the data spike (both sides break).
- Double breaks / failed breakouts.
- Holiday / half-day sessions with thin liquidity.

## Testable predictions
- OR-break continuation probability > random.
- Better performance on data days **after** the initial spike settles than during it.
- Edge sensitive to OR window length (too short = noise, too long = late).

## Metrics to evaluate
Expectancy, PF, win-rate, **realized post-news slippage**, DSR, max DD, MC p95 DD, trade count.

## Minimum viable backtest
EUR/USD + XAU/USD + USD/JPY, 1m/5m bars, ≥ 5y, conservative costs, **≥ 200 OOS trades**. Walk-forward + lockbox + cost sweep.

## Parameter grid (keep small)
- OR window `∈ {15, 30} min`
- TP `m ∈ {1, 1.5}`
- Fixed (not optimized): risk-per-trade, cost model, session boundaries, news rule, `N` invalidation bars.

## Reasons to reject
- [ ] The "edge" is just the data-spike move (un-tradeable slippage) — reject.
- [ ] Single-instrument only.
- [ ] Negative at 1.5× cost (esp. once realistic news slippage is applied).
- [ ] No parameter plateau / DSR ≤ 0.
- [ ] < 200 OOS trades.
- [ ] Performance collapses once 08:30 ET slippage is modeled honestly.
