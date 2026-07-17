---
title: NovaxFX Home
tags: [novaxfx/moc]
---

# 🏠 NovaxFX — Home (Map of Content)

Your review dashboard. Open this vault in Obsidian and start here. Links use
Obsidian wikilinks (`[[...]]`) — click through, or use Graph view to see how the
docs connect.

> **Grounding for any agent:** [[CLAUDE]] — read first (conventions, layout, status).

## 🎯 Vision & strategy
- [[NovaxFX-Company-Strategy-and-Roadmap]] — the company plan & four pillars
- [[system-capability-map]] — full app vision mapped to code (✅/🟡/🔴) + epics R/K/X/N/W
- [[world-class-feature-roadmap]] · [[competitive-analysis]] — market positioning

## 📥 Inbox
- [[inbox/README|Inbox]] — daily standup log + ad-hoc Claude captures

## 🗂️ Planning & board
- [[phase-0-task-board]] — the live backlog (A/B/DZ/G epics)
- [[admin-panel-plan]] — Epic H (admin panel) tasks
- [[decision-log]] — append-only decisions (D-001…)
- [[agent-prompts]] — ready-to-paste prompts for the VSCode plugin

## ⚙️ Process & ops
- [[dev-to-prod-workflow]] — local dev → CI → Hetzner, best practices
- [[continuous-agent-team]] — the always-on agent-team model (GitHub + CI + standup)
- [[team-charter]] — the AI "team" roles & how to invoke them
- [[phase-0-bot-integration]] — how the bot package integrates

## 🧠 Advisory board (grounded in external sources)
- [[CEO-advisory]] — strategy, pricing, go-to-market, sequencing
- [[CTO-advisory]] — backtest/live parity, anti-overfitting, risk engine, ops
- [[CPO-advisory]] — problem-first product, discovery, metrics
- [[sources-library]] — books, platforms & articles behind the above (Chan, Davey, Nautilus, Freqtrade, Cagan, SaaS pricing)

## 🏛️ Architecture & research (reference)
- [[Novax-FX-Platform-Founding-Blueprint]] · [[Novax-FX-Implementation-Blueprint]]
- [[validation-protocol]] · [[minimal-research-harness]] · [[go-no-go-redesign]] · [[dsr-redesign]]
- [[data-source-decision]] · [[data-quality-gate]] · [[instrument-universe]]
- Strategy notes: [[london-sweep-bos]] · [[asian-range-breakout]] · [[ny-opening-range-breakout]] · [[calendar-cost-hardening]]

## 📊 Status snapshot (update as you go)
| Area | Status |
|---|---|
| Research engine (backtest, walk-forward, DSR, lockbox) | ✅ done |
| Signals + scoring + daily/weekly reports | ✅ done |
| Bot A1 skeleton / A2 registry / A3 onboarding | ✅ done |
| Deploy DZ1 bot service / DZ2 Postgres / DZ3 path | ✅ done · DZ4 branch-protect, DZ5 aggregator profile pending |
| B1 signal fan-out | ✅ done · **B5 wire-to-daemon in progress** |
| Admin panel | **H1 in progress** → H2–H7 |
| Realtime data (R) · Risk/money (K) · Broker (X) · News+LLM (N) · Web (W) | 🔴 planned |

## 🔒 Non-negotiables
- No live-money execution before the **risk engine + kill switch** (K2 / [[decision-log|D-001]]).
- Bots run on the **user's own account & keys** — no custody, no pooled funds, no profit promises.
- Legal review before charging money or enabling live broker execution.

---
*Tip: enable the **Kanban** and **Dataview** community plugins to turn the task board
into an interactive board — ask NovaxFX-in-Cowork to generate those formats.*
