# NovaxFX — Continuous AI dev team (planning · review · test · ship)

How to run NovaxFX as an always-on agent team. The core idea: **put the loop in
GitHub** so planning, code, review, tests, and deploy are one system, and add
Claude as an automated actor in it.

## The honest constraint
Cowork (the planning brain you talk to here) is not a 24/7 daemon — it runs when
invoked. To get *continuous* behavior you combine three Claude surfaces plus CI:

| Actor | Role | How it runs |
|---|---|---|
| **GitHub Projects + Issues** | The planning **board** (Todo / In-progress / Review / Done). Each task = an Issue. | Always on |
| **Claude Code GitHub Action** | Autonomous **developer + reviewer**: `@claude` on an issue → implements → opens a PR; auto-reviews every PR diff. | Runs in GitHub Actions on events |
| **CI (already built)** | Automated **test/lint/mypy/docker gate**. Must be green to merge. | On every push/PR |
| **Cowork (me)** | **PM / architect / researcher** — grooms the board, writes issue specs, second-pass architectural review, weekly research. | On a **schedule** + on demand |
| **VSCode Claude plugin** | Interactive hands-on dev when you want to drive. | When you use it |
| **You** | Approver + merge + owner of safety gates. | — |

## The continuous loop
1. **Board** holds prioritized Issues (Cowork keeps it groomed; each Issue has a
   clear spec + acceptance criteria + "green ruff/mypy/pytest" definition of done).
2. Comment **`@claude implement this`** on an Issue → the Action opens a **PR**
   with code + tests on a feature branch.
3. **CI** runs; **Claude auto-reviews** the PR diff and comments; Cowork can add a
   second-pass architectural review.
4. You **approve + merge** → `deploy.yml` ships to Hetzner.
5. A **daily Cowork standup** (scheduled) reviews new commits + the board, closes
   done Issues, writes the next Issues, flags risks.

## Setup (one-time, ~20 min)
1. In the VSCode Claude plugin / Claude Code CLI, run **`/install-github-app`** on
   this repo. It installs the Claude GitHub App **and** generates the workflow
   files (an interactive `@claude` workflow and an auto PR-review workflow).
2. Add repo secret **`ANTHROPIC_API_KEY`** (Settings → Secrets and variables →
   Actions) from console.anthropic.com.
3. Turn on **branch protection** on `main` (task DZ4): require a PR + passing CI,
   block direct pushes. Claude opens PRs; it never pushes to `main`.
4. Create a **GitHub Project** board; import the current tasks as Issues (Cowork
   can generate the Issue list from `phase-0-task-board.md` + `admin-panel-plan.md`).
5. (Optional) Cowork sets up a **daily standup scheduled task**.

## Reference: auto PR-review workflow
`/install-github-app` writes this for you; shown for reference (verify against
current docs — the action evolves):
```yaml
name: Claude PR Review
on:
  pull_request:
    types: [opened, synchronize]
jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          prompt: >
            Review this PR against CLAUDE.md conventions (3.12, pure/wiring split,
            ruff+mypy strict, tests with no network/DB, no logged secrets,
            DISCLAIMER on user surfaces). Flag correctness, security, and any
            change touching money/risk/auth. Be concise.
```
Model note: PR review defaults to a fast Sonnet model — good for most diffs. Use
Opus for diffs touching **auth, payments, broker execution, or the risk engine**.

## Safety guardrails for autonomous development (do not skip)
- **Branch protection is the backstop.** No direct pushes to `main`; every change
  is a PR gated by green CI + your approval. Automation proposes; you dispose.
- **Required human review on high-stakes paths.** Add CODEOWNERS so PRs touching
  `src/novax/live/`, the risk engine, broker/execution, and `admin/auth` require
  your explicit approval — never auto-merge these.
- **No auto-merge for real-money code.** The "no live capital until the risk
  engine + kill switch ship" rule (decision D-001) overrides any agent.
- **Least privilege.** The Action uses a scoped token and `ANTHROPIC_API_KEY`
  secret; it does not hold deploy/SSH keys. Deploy stays a separate, CI-gated job.
- **Cost control.** Pin review to Sonnet; reserve Opus for sensitive diffs.
- **Everything auditable.** Issues → PRs → CI → review comments → merge → deploy
  is a full trail, mirroring the platform's own artifact-trail philosophy.

## Board: GitHub vs the markdown files
Recommended: migrate the markdown board (`phase-0-task-board.md`,
`admin-panel-plan.md`) into **GitHub Issues + a Project**, so the plan lives with
the code, CI, and reviews. Keep the markdown docs as human-readable snapshots that
Cowork refreshes.
