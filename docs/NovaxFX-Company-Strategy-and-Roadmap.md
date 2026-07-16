# NovaxFX — Company Strategy & Roadmap

**Run as an AI-operated startup with Claude**
Prepared: 16 July 2026 · Owner: Vahid · Product posture: **Education + Signals + Analysis** (bots run on the user's own broker account; no pooled funds, no personalized advice)

---

## 0. TL;DR — read this first

You already have a serious asset. The NovaxFX repo is **not** an empty "phase 0" — it is a research-grade FX engine with 491 passing tests, a live Telegram alert daemon, paper trader, signal scoring, walk-forward validation, and CI/CD auto-deploy to Hetzner. Its stated posture ("*Not financial advice. No promise of profit.*") is exactly the low-regulatory lane you chose.

So the job is **not** "build a trading engine from scratch." The job is:

1. **Wrap the existing engine in a customer-facing product** — an interactive, multi-user Telegram bot (**Phase 0**) then a website (**Phase 1**) — around four pillars: **Learn, Analyze, Signals, Bot-trading hooks**.
2. **Run the build like a company** using Claude features as your team (this doc, Section 2).
3. **Keep a researcher loop** that reviews the market weekly and proposes plan changes (Section 9).

The moat is already built: **structural research integrity** (deflated Sharpe, out-of-sample lockbox, tamper-proof artifact trail). No retail competitor — TradingView, MT5, Trade Ideas, Freqtrade — has this. We sell *trustworthy* signals, not hype.

---

## 1. What exists today (grounding the plan)

| Layer | Status in repo | Reuse for the product |
|---|---|---|
| Research core (sessions, instruments, costs, causal engine, walk-forward, metrics, validation) | ✅ Complete, 491 tests | Backend brain — unchanged |
| Enforcement (artifact registry, trial log, go/no-go gate, CI guards) | ✅ Complete | Our credibility / marketing proof |
| Strategies (WeeklyBOSRetest, GoldPullback, EMACross) + 14 planned | ✅ 3 active | The signal source |
| Live daemon (event scheduler, multi-TF scanner, **Telegram alerts**, level store, paper trader, signal score 0–100) | ✅ Complete | **Broadcast** alerts exist — needs to become an **interactive multi-user product** |
| Data (Dukascopy tick→Parquet, TwelveData REST) | ✅ Complete | Market data feed |
| API + web dashboard | ❌ Planned (P4) | **Phase 1 website** |
| Risk engine, broker execution | ❌ Planned (P3/P6) | **Bot-trading hooks** (Phase 0.5+) |

**Gap to close for a product:** the current Telegram piece pushes alerts to one channel. A *product* bot needs multi-user onboarding, `/learn` lessons, on-demand `/analyze`, subscription tiers, per-user signal preferences, and opt-in broker hooks.

---

## 2. The Claude "company" — how you actually run this

You can't hire persistent 24/7 employees inside Claude, but every role you listed maps to a **real, repeatable Claude capability**. Think of it as an org where each "hire" is a way of invoking me.

### 2.1 Org chart → Claude feature

| Your role | How it runs in Claude | What it produces |
|---|---|---|
| **CEO** (you + me as advisor) | This strategy doc + decision log; I challenge/pressure-test | Direction, go/no-go calls |
| **CTO** | A `general-purpose` or `Plan` **subagent** briefed as architect | Architecture decisions, tech-debt reviews |
| **CPO / PM / PO** | I maintain the roadmap + **task list** (the widget you see) + backlog | Prioritized sprint backlog, specs |
| **Full-stack developer** | Me writing/editing code directly in the repo | Working code + tests |
| **Forex market expert** | A subagent briefed with the strategy library + market context | Strategy logic review, new hypotheses |
| **Tester / QA** | A **verification subagent** run against each change | Bug reports, test coverage |
| **DevOps** | Me working with the existing CI/CD + Docker/Hetzner setup | Deploy pipeline, monitoring |
| **Researcher** | Me + **scheduled tasks** (Section 9) | Weekly market/tech/competitor review + plan updates |

> Reality check: subagents are powerful but **stateless** — each starts cold. So the *company's memory* lives in the repo (`/docs`, this file, the task list, decision log), not in the agents. That's a feature: it's auditable, exactly like your artifact trail.

### 2.2 Operating rhythm (the "sprints")

- **Kickoff of each work session:** I read the roadmap + open tasks, propose the sprint goal, you approve.
- **Build:** I implement, writing tests as I go (your repo already enforces this via CI).
- **Review ("standup"):** a QA/verification subagent checks the diff; a forex-expert subagent sanity-checks any strategy logic.
- **Ship:** green CI → Docker → Hetzner (already wired).
- **Retro / research:** weekly scheduled researcher pass proposes what to build next.

### 2.3 How you invoke the "team" (concretely)

- *"Act as CTO and review the architecture for the Phase 0 bot"* → I spawn an architect subagent.
- *"Build the `/learn` module"* → I write code + tests in the repo.
- *"Run QA on this"* → verification subagent.
- *"Set up a weekly researcher"* → I create a scheduled task.
- The **task-list widget** is your project board; **artifacts** (live HTML) can be your KPI dashboard.

### 2.4 Recommended supporting setup

- **Connect the repo folder** to Claude so I read/write real files (right now I clone it; connecting is faster and persistent).
- **GitHub connector** (optional) for issues/PRs.
- **A `/decision-log.md`** in the repo so every CEO/CTO call is recorded (I'll maintain it).

---

## 3. Product strategy — the four pillars

Positioning: **"The honest signals platform. Every edge is validated before you see it."**

| Pillar | What the user gets | Built on |
|---|---|---|
| **Learn** | Structured lessons (sessions, SMC, risk sizing, reading a signal), quizzes, glossary, "explain this signal" | New content + existing session/strategy docs |
| **Analyze** | On-demand: chart snapshot, multi-TF confluence read, AI market commentary (RAG-grounded), economic-calendar context | `multi_tf_scanner`, `signal_score`, TwelveData |
| **Signals** | Validated entry/SL/TP with a decomposable 0–100 score + *why*, delivered to Telegram/web, with backtested track record | `signal_store`, `signal_score`, validation gates |
| **Bot-trading hooks** | Opt-in: connect *your own* broker (OANDA v20 or any MT4/5 via MetaApi) and auto/semi-auto execute signals | `paper_trader` → risk engine → broker adapter |

**Critical compliance boundary (keeps us in the low-regulation lane):** signals are *general, non-personalized* market information; bots execute **only on the user's own account with their own keys**; we never pool funds, never take custody, never promise profit, never give tailored advice. Every surface carries the risk disclaimer already in your README.

---

## 4. Phased roadmap

Your framing ("Phase 0 = Telegram, Phase 1 = website") is the **go-to-market** layer on top of the repo's internal P0–P8 engineering roadmap. Reconciled:

### Phase 0 — Interactive Telegram product (weeks 1–6)
Turn the broadcast daemon into a real multi-user bot.
- 0.1 Bot skeleton: onboarding, `/start`, user registry (SQLite/Postgres), profile & preferences
- 0.2 **Signals**: per-user delivery, pair/session filters, the 0–100 score with explanation
- 0.3 **Learn**: lesson engine (inline keyboards), quizzes, glossary, "explain this signal"
- 0.4 **Analyze**: `/analyze XAUUSD` → multi-TF confluence + AI commentary (RAG-grounded, disclaimered)
- 0.5 Monetization: free vs. premium tiers (Telegram Payments 2.0 / Stars / crypto provider)
- 0.6 **Bot-trading hooks (opt-in beta)**: paper first → OANDA v20 semi-auto (human-confirm) on user's own account

### Phase 0.5 — Risk engine (parallel, ships *before* any live execution)
Pre-trade gate, position limits, kill switch (repo's P3). Non-negotiable before real-money hooks.

### Phase 1 — Website (weeks 6–14)
- FastAPI backend exposing signals/analytics/track-record (repo's P4 API)
- Next.js + TradingView Lightweight-Charts dashboard
- Public **validated track record** page (your differentiator — powered by the artifact trail)
- Account, subscription, broker-connect UI, learn portal
- Telegram ↔ web single account

### Phase 2+ — Scale
Signal marketplace, more strategies (S1–S14), ML layer, multi-asset, mobile push.

---

## 5. Phase 0 Telegram bot — build spec

**Framework:** `python-telegram-bot` v22.x (mature, huge community, matches your Python stack) — or `aiogram` if you want fully-async from day one. Recommendation: **python-telegram-bot** for speed of build; it coexists with the existing daemon.

**Architecture (extends existing `src/novax/live/`):**
```
Telegram users ─┐
                ├─► bot service (python-telegram-bot)
web users ──────┘        │
                         ├─ user_registry (Postgres): users, tiers, prefs, broker links
                         ├─ command handlers: /start /learn /analyze /signals /connect /upgrade
                         ├─ signal fan-out ◄── existing signal_store / signal_score
                         ├─ content engine ◄── lessons/quizzes (markdown-driven)
                         ├─ AI commentary ◄── LLM + RAG over calendar/levels/session context
                         └─ broker adapter (opt-in) ─► OANDA v20 / MetaApi (user keys, encrypted)
```

**Commands (v1):** `/start`, `/learn`, `/analyze <pair>`, `/signals`, `/settings`, `/track` (record), `/connect` (broker, beta), `/upgrade`, `/disclaimer`.

**Data:** reuse Dukascopy/TwelveData feed; add Postgres for users. Secrets already handled via `.env` (`TELEGRAM_TOKEN`, `TWELVEDATA_API_KEY`) + deploy secrets.

**AI best practices (from 2026 research):**
- **RAG, not raw generation** — ground every AI commentary in retrieved facts (current levels, session, calendar events) to cut hallucination. Never let the model invent prices.
- **Multi-agent read** — bull/bear/risk-supervisor pattern outperforms a single model; map the "risk supervisor" to your existing structural risk gate.
- **Instruction hierarchy** — hard risk limits must sit *above* model output; the model can *explain* a signal but **cannot** override the validated gate or a user's risk cap. This is the known LLM failure mode; your artifact-driven gates already enforce it structurally.
- **No profit claims, always disclaimed** — every AI message ends with the risk line.

---

## 6. Broker & data decisions (for bot-trading hooks)

| Need | Option A | Option B | Recommendation |
|---|---|---|---|
| Execution API | **OANDA v20** — clean REST, no extra subscription, `oandapyV20` Python lib, TP/SL native | **MetaApi cloud** — works with *any* MT4/5 broker, more flexible | Start **OANDA v20** (repo already targets it; simplest, cleanest). Add **MetaApi** later to support users who already have MT4/5 broker accounts. |
| Market data | TwelveData REST (in repo) | Dukascopy tick (in repo) | Keep both; add WebSocket streaming later (current gap vs. TradingView) |

Execution is **semi-auto first** (user confirms each trade), on the **user's own account with their own encrypted keys**. Never move or hold user money.

---

## 7. Monetization

- **Free tier:** delayed signals, `/learn` basics, limited `/analyze`.
- **Premium (subscription):** real-time signals, full analysis, AI commentary, more pairs.
- **Pro:** broker hooks / semi-auto execution, priority signals, track-record API.
- **Payments:** Telegram Payments 2.0 or Stars for in-chat; crypto provider (e.g. CryptoBot) as alternative; Stripe on the Phase 1 website.
- **Later:** signal marketplace / affiliate broker partnerships (disclosed).

Pricing to be validated by the researcher against 2026 competitors (ForexBrokers/FXEmpire lists).

---

## 8. Risk, legal & compliance (do not skip)

Your chosen posture keeps burden low **only if** you hold these lines:
- **No personalized advice.** Signals are general market information.
- **No custody, no pooled funds.** Bots run on the user's own account, their keys.
- **No profit promises.** Keep the README disclaimer on every surface.
- **Disclose performance honestly** — past results, drawdowns, the fact that validation ≠ future profit.
- **Clear ToS + risk warning + jurisdiction note.** Regulators referenced in 2026 guidance: FCA (UK), CySEC/MiFID (EU), ASIC (AU), CFTC/NFA (US). Copy-trading or discretionary management would trip licensing — **stay out of that lane**.
- **Get a lawyer** before charging money or launching broker execution. *I'm not a lawyer; this is general information, not legal advice.*

---

## 9. The researcher loop (ongoing "review & suggest plan")

This is the "researcher to review and research and suggest plan" you asked for. I set it up as a **scheduled task** so it runs on its own:

- **Weekly researcher pass** (e.g. Monday 08:00): scan competitor features/pricing, new AI-trading techniques, broker-API and regulatory changes; then output a short memo appended to `/docs/research-log.md` with **concrete plan changes** and re-prioritized backlog.
- **On demand:** *"Researcher: should we add crypto pairs?"* → I research + write a recommendation.
- Every recommendation lands as tasks in the board, so research → plan → build stays connected.

Say the word and I'll create this scheduled task now.

---

## 10. Immediate next actions (proposed sprint 1)

1. **Connect the repo folder** to me (or confirm I keep working from the clone).
2. **Decision:** confirm `python-telegram-bot` + OANDA-first (or override).
3. I scaffold **Phase 0.1** — bot skeleton + user registry + `/start` onboarding + tests, alongside the existing daemon.
4. I stand up the **weekly researcher** scheduled task.
5. I create `/docs/decision-log.md` and a Phase 0 task board.

Pick a starting point and I'll begin building this session.

---

### Sources
- python-telegram-bot docs — https://docs.python-telegram-bot.org/en/stable/examples.html · aiogram — https://aiogram.dev/
- Telegram payments 2026 — https://payrequest.io/blog/telegram-payment-providers-2026
- OANDA v20 REST API — https://developer.oanda.com/rest-live-v20/introduction/
- MetaApi cloud (MT4/5) — https://metaapi.cloud/
- Forex signals regulation/disclaimers — https://www.forexbrokers.com/guides/forex-signals-providers · https://www.axi.com/int/blog/education/signal-providers
- LLM/RAG trading analysis 2026 — https://arxiv.org/html/2502.00415v2 · https://arxiv.org/html/2605.19337v1
- NovaxFX repo — https://github.com/vahidelahi777/NovaxFX (README, docs/, src/novax/)
