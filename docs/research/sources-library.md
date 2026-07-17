---
title: Sources Library
tags: [novaxfx/research, moc]
---

# 📚 Sources Library — trading-bot & startup

Annotated references the [[CEO-advisory]], [[CTO-advisory]], and [[CPO-advisory]]
notes draw on. Grounding for decisions in [[decision-log]].

## Books — building trading systems
- **Ernest P. Chan — *Quantitative Trading* (2nd ed.) & *Algorithmic Trading: Winning Strategies and Their Rationale.*** How to build a retail algo-trading business; real strategies with rationale; ML techniques; discipline against data-mining bias. → informs [[CTO-advisory]] validation stance.
- **Kevin J. Davey — *Building Winning Algorithmic Trading Systems.*** Data-mining → walk-forward → Monte Carlo → live. Key rules: **one-shot walk-forward** (never re-touch in-sample = overfitting), **position sizing evaluated AFTER** entries/exits are fixed, size to keep max drawdown at **half your comfort zone**, avoid **risk of ruin** via Monte Carlo. → informs Epic K + the go/no-go gate.

## Comparable platforms (architecture lessons)
- **NautilusTrader.** Production-grade; the headline lesson: **backtest and live use the exact same event-driven code — no changes between them.** Rust core, Redis state persistence, Docker. → [[CTO-advisory]] "backtest/live parity."
- **Freqtrade.** Open-source Python bot **controlled via Telegram or web UI**, with backtesting + **money management** + strategy optimization. Its Hyperopt is the canonical **overfitting trap** (grid-search the best of 10k = noise). → validates Telegram-first UX; cautionary tale for the gate.
- **QuantConnect (LEAN).** Free backtesting + data; large community. → benchmark for research UX.

## Product management
- **Marty Cagan — *Inspired* / *Transformed.*** Solve **problems**, not stakeholder feature requests; **discovery before delivery** (validate the right thing before building); **design UX first**; empowered cross-functional teams; **small, decoupled, frequent releases**; risk-based discovery. → [[CPO-advisory]].

## Business / SaaS strategy
- **SaaS pricing research.** Startups underinvest in pricing (avg ~6 hours ever); a **1% pricing improvement ≈ 12.7% profit** — more than acquisition/retention gains. Map the model to **how value is delivered** (tiered subscription fits signals); **talk to early customers daily**; roll price changes out **gradually** (2 weeks → 15% → 50% → full). → [[CEO-advisory]].
- **Tomasz Tunguz — SaaS strategy guide.** Metrics, growth, positioning.

## Sources
- Chan, *Quantitative Trading* 2nd ed — https://www.wiley.com/en-us/Quantitative+Trading:+How+to+Build+Your+Own+Algorithmic+Trading+Business,+2nd+Edition-p-9781119800064
- Chan, *Algorithmic Trading* — https://www.amazon.com/Algorithmic-Trading-Winning-Strategies-Rationale/dp/1118460146
- Davey, *Building Winning Algorithmic Trading Systems* — https://www.amazon.com/Building-Winning-Algorithmic-Trading-Systems/dp/1118778987
- Davey, risk protection — https://kjtradingsystems.medium.com/algorithmic-trading-tip-building-risk-protection-into-your-trading-92089145b5c0
- NautilusTrader — https://nautilustrader.io/
- Freqtrade — https://www.freqtrade.io/
- QuantConnect — https://www.quantconnect.com/
- Cagan, *Inspired* principles — https://www.svpg.com/principles/
- SaaS pricing — https://www.cobloom.com/blog/saas-pricing-models · https://tomtunguz.com/saas-strategy-guide/
