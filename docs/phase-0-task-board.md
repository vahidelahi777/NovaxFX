# NovaxFX — Phase 0 Task Board (Interactive Telegram Product)

Goal: turn the existing broadcast daemon into a **multi-user product bot** across the four pillars — Learn, Analyze, Signals, Bot-trading hooks. Mirrored in Claude's live task widget.

Legend: 🔴 not started · 🟡 in progress · 🟢 done · Role = who leads (see `team-charter.md`)

---

## Epic A — Bot foundation
| ID | Task | Role | Depends on | Status |
|---|---|---|---|---|
| A1 | Bot skeleton on python-telegram-bot; `/start`, `/help`, `/disclaimer` | Dev | D-003 confirm | 🟢 done |
| A2 | User registry (Postgres): users, tiers, prefs, created_at | Dev | A1 | 🟢 done |
| A3 | Onboarding flow (inline keyboards) → capture pair/session prefs | Dev | A2 | 🔴 next |
| A4 | Config/secrets: extend `.env`, encrypted per-user secrets store | DevOps | A2 | 🔴 |
| A5 | Coexist with existing prod daemon (no regressions) | DevOps/QA | A1 | 🟢 done |

## Epic B — Signals (pillar)
| ID | Task | Role | Depends on | Status |
|---|---|---|---|---|
| B1 | Per-user signal fan-out from existing `signal_store`/`signal_score` | Dev | A2 | 🔴 |
| B2 | Signal message: entry/SL/TP + 0–100 score + **why** breakdown | Dev | B1 | 🔴 |
| B3 | Filters: pair, session, min-score; free=delayed, premium=real-time | Dev | B1 | 🔴 |
| B4 | `/track` — public backtested track record (artifact-trail powered) | Dev+Forex | B2 | 🔴 |

## Epic C — Learn (pillar)
| ID | Task | Role | Depends on | Status |
|---|---|---|---|---|
| C1 | Lesson engine (markdown-driven, inline-keyboard navigation) | Dev | A1 | 🔴 |
| C2 | Core curriculum v1: sessions, SMC basics, risk sizing, reading a signal | Forex | C1 | 🔴 |
| C3 | Quizzes + glossary | Dev | C1 | 🔴 |
| C4 | "Explain this signal" (RAG-grounded, disclaimered) | Dev | B2, C1 | 🔴 |

## Epic D — Analyze (pillar)
| ID | Task | Role | Depends on | Status |
|---|---|---|---|---|
| D1 | `/analyze <pair>` → multi-TF confluence read from `multi_tf_scanner` | Dev | A1 | 🔴 |
| D2 | AI market commentary — RAG over levels/session/calendar (no invented prices) | Dev+Forex | D1 | 🔴 |
| D3 | Economic-calendar context injection | Dev | D1 | 🔴 |

## Epic E — Bot-trading hooks (pillar, opt-in beta)
| ID | Task | Role | Depends on | Status |
|---|---|---|---|---|
| E1 | Risk engine: pre-trade gate, position limits, kill switch (repo P3) | Dev+Forex | — | 🔴 |
| E2 | `/connect` broker OAuth/keys (OANDA v20), encrypted at rest | Dev+DevOps | A4, E1 | 🔴 |
| E3 | Paper execution path through risk engine | Dev+QA | E1 | 🔴 |
| E4 | Semi-auto (human-confirm) live execution on user's own account | Dev+QA | E2, E3 | 🔴 |
| E5 | MetaApi adapter (any MT4/5 broker) — later | Dev | E4 | 🔴 |

## Epic F — Monetization
| ID | Task | Role | Depends on | Status |
|---|---|---|---|---|
| F1 | Tiers: Free / Premium / Pro definition + gating logic | PM | A2 | 🔴 |
| F2 | Payments: Telegram Payments 2.0 / Stars / crypto provider | Dev | F1 | 🔴 |
| F3 | Subscription lifecycle (renew, expire, downgrade) | Dev | F2 | 🔴 |

## Epic G — Compliance & ops
| ID | Task | Role | Depends on | Status |
|---|---|---|---|---|
| G1 | ToS + risk warning + jurisdiction note on every surface | Compliance | A1 | 🔴 |
| G2 | Lawyer review before charging / live execution | Vahid | F2, E4 | 🔴 |
| G3 | Monitoring: bot uptime, error alerts, heartbeat | DevOps | A1 | 🔴 |

---

## Suggested Sprint 1 (this week)
A1 → A2 → A3 (foundation) + G1 (disclaimer) + B1 (signal fan-out), with A5/QA guarding the existing daemon.

## Backlog / later phases
Website (FastAPI + Next.js), signal marketplace, ML layer, more strategies (S1–S14), WebSocket streaming, mobile push.
