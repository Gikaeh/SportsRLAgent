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
