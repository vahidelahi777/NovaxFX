---
title: CTO Advisory
tags: [novaxfx/advisory, cto]
---

# 🛠️ CTO advisory — engineering & architecture

Decisions synthesized from [[sources-library]] (NautilusTrader, Freqtrade, Chan,
Davey) applied to NovaxFX. Feeds [[decision-log]].

## Backtest ↔ live parity (NautilusTrader's core lesson)
The single biggest architectural lesson: **the same strategy code runs in
backtest and live — no changes.** NovaxFX has a custom causal engine plus a
separate live daemon; keep the **strategy/signal logic single-source** so the
research result equals the live result. When [[system-capability-map|Epic X
(broker)]] arrives, the executor must consume the *same* strategy objects, not a
reimplementation. Consider adopting NautilusTrader for the execution layer later
rather than hand-rolling order management.

## Protect the anti-overfitting gate (Davey + Chan)
This is our moat — do not weaken it.
- **One-shot walk-forward:** optimize in-sample, test out-of-sample, **never
  re-touch in-sample.** Repeated retesting = overfitting. Our lockbox enforces this.
- **Add Monte Carlo** to the research engine (trade-order reshuffling → risk-of-ruin
  and drawdown distribution) before any strategy goes live. Currently planned, not built.
- Freqtrade's Hyperopt is the cautionary example of "noise discovery with a nice UI."

## Money management comes AFTER the strategy (Davey)
For [[system-capability-map|Epic K1]]: build/evaluate **position sizing separately
from entry/exit tuning** — baking sizing into initial tests lets it mask a weak
edge. Size so **max drawdown ≈ half your stated comfort zone** (traders overestimate
tolerance). Validate via Monte Carlo risk-of-ruin. The **risk gate + kill switch
(K2)** ships before any live order ([[decision-log|D-001]]).

## Control surface (Freqtrade)
Telegram + web UI as the control/monitoring surface is a proven pattern — we're
already on it (bot + admin panel [[admin-panel-plan|Epic H]]).

## State & ops (NautilusTrader)
- Add **Redis** for live/realtime state when [[system-capability-map|Epic R]] lands
  (streaming, dedup, kill-switch flag), per the blueprint.
- Keep **Docker + one-deployable** discipline; CI gate (ruff + mypy strict +
  pytest) stays the definition of done. Maintain the **pure/wiring split**.

## Sources
See [[sources-library]].
