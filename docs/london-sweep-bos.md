# Strategy Hypothesis — London High/Low Liquidity Sweep + BOS (SMC)

**Status:** hypothesis (untested) · **Owner:** Quant + Senior Trader
**This is a falsifiable hypothesis, not a known edge.** It must pass [`../validation-protocol.md`](../validation-protocol.md) before it means anything. This is the production-grade version of the existing Novax SMC logic — define sweep/BOS as **tested primitives**, not eyeballed.

## Market thesis
Price sweeps a prior session's high/low (a stop run), then reverses with a break of structure (BOS) — the classic ICT liquidity grab.

## Behavioral reason the edge may exist
Resting stops beyond obvious highs/lows are liquidity. Larger participants push through to fill orders, then price reverses once the liquidity is taken.

## Session dependency
**London**, sweeping the **Asian** session's high/low (ASIA bounds from `sessions.py`).

## Instrument dependency
GBP/USD, EUR/USD, XAU/USD, GBP/JPY. Phase 0 tests: **GBP/USD, EUR/USD, XAU/USD**.

## Entry logic
1. Sweep of Asian high/low (price trades beyond extreme by a buffer).
2. Displacement / **BOS** in the opposite direction (structural confirmation).
3. Entry on retest of the order block (OB) / fair value gap (FVG) created by the displacement.

## Exit logic
Target the opposing liquidity pool / prior-day extreme.

## Stop-loss logic
Beyond the sweep extreme.

## Take-profit logic
Opposing liquidity pool or prior-day high/low; optional partial at 1R.

## Invalidation rules
Close beyond the sweep extreme **without** a BOS → no trade / exit. If price continues through (no reversal), the sweep was continuation, not a grab.

## Market regime filter
Works in ranging→reversal and trend-resumption contexts. **Gate out** dead-flat low-ATR conditions where "sweeps" are just noise.

## News filter
Mandatory blackout around high-impact prints (sweeps in fast news tape are untradeable).

## Spread/liquidity filter
Strict — sweeps occur in fast tape with widening spreads. Apply session multiplier + spread cap.

## Required data
**1m OHLCV** (BOS needs fine structure), spread series, session calendar, economic calendar.

## Expected failure modes
- Sweep **without** reversal (it was continuation).
- Subjective/over-fit BOS detection (the biggest risk — must be a deterministic, tested rule).
- Late entries after the reversal already ran.

## Testable predictions
- Post-sweep reversal probability > base rate.
- Edge is stronger when the sweep aligns with higher-timeframe bias.
- Edge degrades if BOS lookback is made very short (noise) or very long (lag).

## Metrics to evaluate
Expectancy, PF, win-rate, R-multiples, **sweep→reversal hit-rate**, DSR, max DD, MC p95 DD, trade count.

## Minimum viable backtest
GBP/USD + XAU/USD (+ EUR/USD), 1m bars, ≥ 5y, conservative costs, **≥ 150–400 OOS trades**. Walk-forward + lockbox + cost sweep.

## Parameter grid (keep small)
- sweep buffer (pips or `k·ATR`)
- BOS lookback (small set)
- Fixed (not optimized): risk-per-trade, cost model, session boundaries, news-blackout, OB/FVG definition.

## Reasons to reject
- [ ] BOS/sweep rules require **hindsight** to define (lookahead) — automatic reject.
- [ ] Edge disappears under realistic fills/slippage.
- [ ] Sweep→reversal hit-rate not better than base rate.
- [ ] Only one instrument.
- [ ] Negative at 1.5× cost.
- [ ] No plateau / DSR ≤ 0.
- [ ] Detection logic is non-deterministic (different runs → different signals).
