# Cost Model Specification

**Status:** spec · **Owner:** Risk Manager + Quant · **Module target:** `libs/backtest/costs.py`

## Principle

Costs are conservative by default. A strategy must survive **pessimistic** costs to count as an edge. Pre-cost results are inadmissible as evidence. If an edge only exists at optimistic costs, it does not exist.

## Components

### Spread
- Per-instrument, **session- and time-dependent**. Widen materially in the Asian session and around news.
- Prefer **realized spread** from the data feed (OANDA bid/ask) where available.
- Fallback: conservative fixed floors per instrument (round **up**). XAU/USD floor substantially wider than FX majors.

### Slippage
- Applied on **every** fill. Larger on breakouts and around news.
- Model: `slippage = fixed_pips + k * ATR` (volatility-scaled). Stops assume **adverse** slippage.
- Breakout-entry strategies carry extra slippage (you trade into momentum).

### Commission
- Per-side, per-lot. Model it **even on spread-only accounts** to stay conservative.

### Session liquidity
- Asian session + rollover: higher slippage/spread, reduced effective size.
- Off-peak fills are penalized; do not assume peak-liquidity execution at 02:00 UTC.

### News-event volatility
- Spreads/slippage spike around high-impact events.
- Default: **blackout** (no entries) in the window. If a strategy deliberately trades news, apply punitive cost instead — never normal cost.

### XAU/USD special handling
- Wider spreads, **larger pip value**, gappier, bigger ATR.
- **Never** reuse FX-major cost assumptions for gold. Separate config block, separate floors, separate slippage scaling.

## Config shape (illustrative)

```yaml
cost_model:
  stress_factor: 1.0          # swept over {1.0, 1.25, 1.5} in validation
  instruments:
    EUR_USD:
      spread_floor_pips: 0.8
      commission_per_side_per_lot: 3.5
      slippage_fixed_pips: 0.3
      slippage_atr_k: 0.05
    GBP_USD:
      spread_floor_pips: 1.2
      commission_per_side_per_lot: 3.5
      slippage_fixed_pips: 0.4
      slippage_atr_k: 0.06
    USD_JPY:
      spread_floor_pips: 0.9   # pip = 0.01
      commission_per_side_per_lot: 3.5
      slippage_fixed_pips: 0.3
      slippage_atr_k: 0.05
    XAU_USD:                    # METAL — own profile, do not reuse FX
      spread_floor_pips: 20     # pip = 0.1 -> ~2.0 price units; tune to feed
      commission_per_side_per_lot: 5.0
      slippage_fixed_pips: 10
      slippage_atr_k: 0.10
  session_multipliers:
    ASIA: 1.5
    LONDON: 1.0
    NEWYORK: 1.0
    OVERLAP: 1.0
  news_blackout_minutes_before: 5
  news_blackout_minutes_after: 15
```

> Values above are **placeholders** — calibrate against realized spreads from the actual feed before trusting any result. Round up when uncertain.

## Sensitivity analysis (mandatory)

Run every strategy at **stress_factor ∈ {1.0, 1.25, 1.5}**.

### Rejection rule

> If a strategy is positive at 1.0× cost but **negative at 1.5×**, it is too fragile — **reject it**. Edge must be robust to cost, not balanced on a knife-edge.

Report the full table:

| Strategy | Instrument | Expectancy @1.0× | @1.25× | @1.5× | Survives? |
|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ✅/❌ |

## Acceptance criteria

- [ ] Cost model implemented with per-instrument profiles + XAU/USD distinct block.
- [ ] Slippage applied on every fill; stops use adverse slippage.
- [ ] Session multipliers applied via `sessions.py` tagging.
- [ ] News-blackout window enforced (or punitive cost for news strategies).
- [ ] `stress_factor` parameter sweeps {1.0, 1.25, 1.5}.
- [ ] Unit tests: XAU profile ≠ FX profile; pip conventions correct; adverse-slippage on stops.
- [ ] Calibration note committed: how floors were chosen vs realized feed spreads.
