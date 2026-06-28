# Strategy Hypothesis — Asian Range Breakout

**Status:** hypothesis (untested) · **Owner:** Quant + Senior Trader
**This is a falsifiable hypothesis, not a known edge.** It must pass [`../validation-protocol.md`](../validation-protocol.md) before it means anything.

## Market thesis
The low-volatility Asian session builds a price range that is broken with momentum as London liquidity arrives.

## Behavioral reason the edge may exist
Overnight positioning compresses price into a range. London participants inject volume and volatility, and resting stops cluster just beyond the Asian extremes — providing fuel for a directional break.

## Session dependency
Entry around **London open**. Range is defined by the **Asian session** (see `sessions.py` ASIA bounds, 00:00–09:00 UTC).

## Instrument dependency
EUR/USD, GBP/USD, EUR/JPY, GBP/JPY, XAU/USD. Phase 0 tests: **EUR/USD, GBP/USD, XAU/USD**.

## Entry logic
Break of Asian-session high/low + buffer (`k · ATR`), confirmed by a range-expansion thrust (e.g. bar range or ATR rising vs Asian average).

## Exit logic
Measured move (`range_height · m`) or the London–NY overlap extreme, whichever comes first.

## Stop-loss logic
Opposite side of the Asian range, or the nearest structural swing.

## Take-profit logic
`range_height · m` with `m ∈ {1, 1.5, 2}` (small grid).

## Invalidation rules
Close back inside the range within `N` bars after the break (fakeout) → exit/cancel.

## Market regime filter
Require a **non-ranging** London regime. Skip days where London itself stays compressed.

## News filter
Skip if a high-impact EUR/GBP/USD event falls within the entry window (news-blackout from cost-model-spec).

## Spread/liquidity filter
Skip if spread > cap, or pre-London liquidity is thin (Asian session multiplier applies).

## Required data
1m+ OHLCV, spread series, session calendar, economic calendar.

## Expected failure modes
- False breakouts on choppy days.
- Holiday thinness producing fake ranges/breaks.
- Double-sided sweeps (stop-runs both ways) before any real move.

## Testable predictions
- Breakout continuation probability > random baseline.
- Edge concentrated in the first 1–2 hours of London.
- Worse performance on low-ATR Asian days (small/no range).

## Metrics to evaluate
Expectancy, profit factor, win-rate, MAE/MFE, **fakeout rate**, DSR, max DD, MC p95 DD, trade count.

## Minimum viable backtest
EUR/USD + GBP/USD (+ XAU/USD), 5m bars, ≥ 5y, conservative costs, **≥ 200 OOS trades**. Walk-forward + lockbox + cost sweep.

## Parameter grid (keep small)
- buffer `k ∈ {0.1, 0.25, 0.5} · ATR`
- TP `m ∈ {1, 1.5, 2}`
- Fixed (not optimized): risk-per-trade, cost model, session boundaries, news-blackout rule, `N` invalidation bars.

## Reasons to reject
- [ ] Edge < costs (negative after spread/slippage/commission).
- [ ] Only works on one instrument.
- [ ] Only works pre-2021 (regime-specific, decayed).
- [ ] Negative at 1.5× cost stress.
- [ ] No parameter plateau (sharp optimum only).
- [ ] DSR ≤ 0.
- [ ] < 200 OOS trades (inconclusive, not pass).
