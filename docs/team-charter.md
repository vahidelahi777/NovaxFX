# NovaxFX — AI Team Charter

How the "company" runs. Each role is a **Claude capability**, not a persistent hire. Company memory lives in the repo (this file, `decision-log.md`, `phase-0-task-board.md`, `docs/`). Invoke a role by asking for it by name.

---

## Roles → how to invoke → deliverable

| # | Role | Invoke it by saying… | What it does | Output |
|---|---|---|---|---|
| 1 | **CEO (advisor)** | "As CEO, should we…" | Direction, prioritization, go/no-go; pressure-tests your calls | Decision in `decision-log.md` |
| 2 | **CTO** | "As CTO, review the architecture for X" | Architecture, tech-debt, build-vs-buy, security | Design note / ADR |
| 3 | **CPO / PM / PO** | "Groom the backlog" / "Spec feature X" | Roadmap, prioritized backlog, feature specs, acceptance criteria | Updated task board + spec |
| 4 | **Full-stack developer** | "Build feature X" | Writes code + tests in the repo | PR-ready code |
| 5 | **Forex market expert** | "Expert-review this strategy / signal logic" | Validates trading logic, proposes hypotheses, session/risk sanity | Strategy review memo |
| 6 | **QA / Tester** | "Run QA on this change" | Independent verification subagent: tests, edge cases, regressions | Bug report / sign-off |
| 7 | **DevOps** | "Handle deploy / CI for X" | Works the existing CI/CD, Docker, Hetzner, monitoring | Green pipeline / runbook |
| 8 | **Researcher** | "Researcher: review market for X" (or the weekly scheduled task) | Competitors, AI tooling, regs, pricing → concrete plan changes | Memo in `docs/research-log.md` + new tasks |
| 9 | **Compliance (advisory)** | "Compliance check on X" | Flags custody/advice/licensing risks (general info, not legal advice) | Risk note |

> **Rule:** anything touching validated strategy gates or real money must pass QA (#6) + Forex-expert (#5), and hard risk limits always sit above any AI output (instruction-hierarchy safety).

---

## Operating rhythm (per work session = a "sprint")

1. **Kickoff** — Claude reads roadmap + open board, proposes sprint goal; Vahid approves.
2. **Build** — developer implements with tests (CI enforces).
3. **Standup / review** — QA subagent checks the diff; forex-expert reviews any strategy logic.
4. **Ship** — green CI → Docker → Hetzner (already wired).
5. **Retro / research** — weekly researcher proposes what's next → new board tasks.

## Memory & artifacts (the "company brain")
- `decision-log.md` — every decision, append-only
- `phase-0-task-board.md` — the backlog/board (mirrored in Claude's live task widget)
- `docs/research-log.md` — weekly researcher output (to be created)
- `docs/` — existing blueprints, specs, competitive analysis

## Recommended setup to make the team faster
- **Connect the repo folder** to Claude (persistent read/write vs. re-cloning).
- **GitHub connector** for issues/PRs (optional).
- **Weekly researcher scheduled task** (ask Claude to create it).
