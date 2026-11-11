# DECISIONS.md: repo-wide decisions

Decisions that span both projects: repo structure, scope, agents, integration steps.
Project-specific decisions stay in `DeepSports/docs/DECISIONS.md` and
`ManualBets/docs/DECISIONS.md`. Append-only, newest at the bottom; strike through a reversed
decision and point to the reversal.

### 2026-11-10: Agent-driven development with one root context
Development is mostly done by AI agents. The repo root now holds the shared rules
(`AGENTS.md`, with `CLAUDE.md` importing it) and the dev agents (`.claude/agents/`: architect,
data-engineer, data-analyst, frontend-dev, reviewer). Why: the two projects are going to be
merged, and a session started at the root couldn't see `DeepSports/.claude/agents` (nested
skills appear only after the session touches files under `DeepSports/`), while a session
started in a project folder does see root agents and skills (checked 2026-11-10 with Claude
Code 2.1.322). Runtime agents and skills used by DeepSports' headless launchd jobs (bettor,
calendar-agent, `/sync-game-calendar`, `/ensemble-betting`) stay in `DeepSports/.claude/`,
because those jobs run from `DeepSports/` and their skills assume that working directory.
Repo-wide rules (non-negotiables, git, boundary, context hygiene) live only in the root
`AGENTS.md`; project files keep only their own specifics. This reverses ManualBets'
2026-08-21 single-agent decision.

### 2026-11-10: Basketball only
Work focuses on NBA and NCAA men's D1 basketball. `ManualBets/hockey/` and
`ManualBets/baseball/` stay in the tree but get no new work, and NHL/NFL plans were removed
from the roadmaps. Revisit only when the owner asks.

### 2026-11-10: BetDesk, a shared app on Cloudflare (phase 1 = read-only mirror)
**Status:** decided; phase 1 built (not yet deployed). Owner answers: start with the owner's email
only (Gikaeh's later; emails stay out of the repo), name `BetDesk`, `DeepSports/web` frozen, free
`workers.dev` address. Hosting detail and BetDesk-internal choices: `BetDesk/docs/DECISIONS.md`.
Both owners need the app away from the home Wi-Fi, but DeepSports' app is LAN-only (DeepSports
DECISIONS 2026-11-03). A new top-level project `BetDesk/` (not under `DeepSports/`, because it will
use data and tools from both projects) hosts a PWA on a Cloudflare Worker (static assets) + D1, behind
Cloudflare Access for the two owners' emails. Phase 1: a pusher on the Mac reads DeepSports' read
API on `localhost:8787` and pushes snapshots; no stakes leave the Mac. Phase 2 (separate decision):
shared bet logging with a bankroll per person (owner decision), appended back to `logs/`. This adds
one boundary edge (BetDesk pusher → DeepSports read API, HTTP, read-only; edge 3 in `AGENTS.md`).
Details, alternatives and open questions: `docs/proposals/2026-11-10-betdesk-cloudflare.md`.

### 2026-11-10: ManualBets and the Odds API are normal tools, not off limits
Owner instruction, repeated because sessions kept avoiding them: betting analysis and picks use
all of the repo's resources, DeepSports and ManualBets (models, predictions, menus) plus fresh Odds
API lines. The old "only when the task needs fresh odds" wording read as a ban and was replaced
by an explicit section in `AGENTS.md`. Limits that stay: humans place bets, never print the key,
append-only logs, one DuckDB writer.
