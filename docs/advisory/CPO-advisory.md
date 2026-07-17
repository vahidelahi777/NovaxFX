---
title: CPO Advisory
tags: [novaxfx/advisory, cpo]
---

# 🎯 CPO advisory — product

Decisions synthesized from [[sources-library]] (Marty Cagan, *Inspired/Transformed*)
applied to NovaxFX. Feeds [[decision-log]].

## Solve the problem, not the feature list
Cagan: great teams ask "what problem needs solving?" not "what did stakeholders
ask for?" **NovaxFX's core user problem:** retail FX/gold traders lose money to
overfit signals and undisciplined execution. So the product promise is
**disciplined, validated signals + education + guardrailed execution** — not "more
indicators."

## Discovery before delivery
Validate before building the expensive parts.
- **Prototype `/analyze` and `/learn`** with the first users and confirm they'd
  pay *before* investing in payments (F2/F3) and the web platform (Epic W).
- Test **willingness-to-pay** with the first cohort (ties to [[CEO-advisory]] pricing).

## Design the experience first
- Onboarding ([[phase-0-task-board|A3]], done) and the **signal message with a
  "why"** ([[phase-0-task-board|B1/B2]], done) are the core UX — keep them simple
  and legible. Clarity of the score + rationale is the product.
- Every surface carries the disclaimer ([[phase-0-task-board|G1]]).

## Small, decoupled, frequent releases
Cagan's delivery principle already matches our practice: **one task per PR + green
CI + auto-deploy**. Keep shipping small; avoid big-bang features.

## Empowered team
The [[continuous-agent-team]] model (agents propose, human approves) is Cagan's
"empowered team solving problems" pattern — principles over process, learning over
failure.

## Product metrics (define + instrument)
- **Activation:** user onboarded AND received their first matched signal.
- **Engagement:** `/analyze` and `/learn` usage; signals acted on.
- **Conversion:** free → premium.
- **Trust:** track-record integrity (the differentiator).
Wire these into the admin **signal monitoring** ([[admin-panel-plan|H3]]) + a
metrics view.

## Sources
See [[sources-library]].
