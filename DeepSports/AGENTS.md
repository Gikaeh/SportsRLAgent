# Agents: how work gets done in DeepSports

DeepSports is agent-driven. The main Claude session is the **orchestrator**; specialist
subagents do focused work; reusable skills and tools capture anything done more than once.

## The orchestrator (main Claude session)
Role: own the plan and the outcome, not every keystroke.
- **Plan:** turn the user's goal into tasks, check them against `docs/ROADMAP.md`, and keep
  the roadmap and `docs/DECISIONS.md` current.
- **Delegate:** hand self-contained tasks to the subagents below, in parallel when they
  don't touch the same files and don't both need the DuckDB writer. Give each one a complete
  brief: the goal, relevant files and docs, constraints, and what "done" looks like.
- **Integrate and verify:** review subagent output, run the checks (ruff, pytest, the data-quality
  queries), and fix seams between pieces. A subagent's report is a claim; verify it before
  telling the user it's done.
- **Keep the system visible:** make sure the architecture diagram and docs reflect what changed.
- **Report:** a short phone-readable summary at the end of a run (it goes to Discord via
  the Stop hook). Ask the user only for decisions that are really theirs to make.
- **Do it inline when that's cheaper:** small or tightly coupled changes don't need a subagent.

## Specialist subagents (`.claude/agents/`)
| Agent | Owns | Typical tasks |
|---|---|---|
| `data-engineer` | `src/deepsports/` sources, parsers, store, pipeline, tests | New data source/sport, new tables, parser fixes, data-quality checks |
| `data-analyst` | `analysis/`, `models/` (read-only on the warehouse) | EDA, features, team ratings, prediction models, backtests |
| `calendar-agent` | Google Calendar events with a `deepsports:` key | Runs `/sync-game-calendar`; reports created/updated/deleted |
| `architect` | `docs/`, `docs/diagrams/`, `CLAUDE.md`, `AGENTS.md` | Keeps the diagram and docs in sync with the code; reviews structural changes |
| `frontend-dev` | `web/` (PWA), `glasses/` (G2 plugin) | Screens, UI features, client API integration |
| `bettor` | Nothing (Read-only, one context file) | One independent voter in `/ensemble-betting`; returns picks as JSON |

Coordination rules:
- **One DuckDB writer at a time.** Only one agent runs collection jobs at once; analysts read
  through a separate copy or wait (`duckdb.connect(path, read_only=True)` still fails while a writer holds the lock).
- Agents stay inside their own area. Cross-cutting changes go back to the orchestrator.
- Every agent follows CLAUDE.md (polite data sourcing, pure parsers, diagram rule, no commits).

## External collaborator: DeepSeek session (to save Claude usage)
The owner runs a separate Claude Code session backed by DeepSeek models (`deepseek-on` in their shell).
Use it for big implementation or simulation jobs that don't need to land in the codebase directly:
- The orchestrator writes a brief in `collab/deepseek/<NAME>_BRIEF.md` (local, git-ignored) and gives the
  owner a short message to paste into the DeepSeek session. Claude can't message it directly.
- DeepSeek writes only inside `collab/deepseek/` (code in `lab/`) and replies in `collab/deepseek/CHANNEL.md`.
- Claude reviews its results (a report is a claim; re-check the numbers) and ports what survives.
- Same rules as everyone: no writes to the live warehouse (work on a copy), no network unless the brief allows it.

## Creating new agents, skills, and tools
You and subagents **may create reusable agents, skills, and tools** when a task is likely to recur
or a capability is missing:
- **Subagent:** `.claude/agents/<name>.md` for a recurring role with its own scope.
- **Skill:** `.claude/skills/<name>/SKILL.md` for a repeatable procedure (e.g. `/sync-game-calendar`).
- **Tool:** a script in `tools/` or a `deepsports` CLI subcommand for deterministic work that
  shouldn't be re-derived by a model each time.
When you add one: give it a clear name and a one-line description, list it in this file,
add it to the architecture diagram if it's part of the system, and log the reason in
`docs/DECISIONS.md`. Prefer extending an existing agent or skill over making a near-duplicate.

## Workflows
**Add a data source or sport:** orchestrator plans → `data-engineer` (source + parser +
fixtures + tests + backfill) → `architect` (diagram, DATA_SOURCES, DATA_MODEL) → orchestrator
verifies and runs the checks.

**Daily refresh:** `calendar-agent` runs `/sync-game-calendar` (update → upcoming → reconcile)
→ Discord summary.

**Analysis or model work:** orchestrator frames the question → `data-analyst` builds it
→ orchestrator reviews the method (no leakage: features use only information from before tip-off)
→ `architect` documents the results.

## Registry
| Kind | Name | Path |
|---|---|---|
| Skill | sync-game-calendar | `.claude/skills/sync-game-calendar/SKILL.md` |
| Skill | ensemble-betting | `.claude/skills/ensemble-betting/SKILL.md` |
| Agent | bettor | `.claude/agents/bettor.md` |
| Agent | data-engineer | `.claude/agents/data-engineer.md` |
| Agent | data-analyst | `.claude/agents/data-analyst.md` |
| Agent | calendar-agent | `.claude/agents/calendar-agent.md` |
| Agent | architect | `.claude/agents/architect.md` |
| Agent | frontend-dev | `.claude/agents/frontend-dev.md` |
| Tool | data-quality checks | `deepsports check` (`src/deepsports/quality.py`) |
| Tool | read API + web server | `deepsports serve` (`src/deepsports/api/`) |
| Tool | scheduled sync | `tools/scheduled-sync.sh` + `tools/launchd/` |
| Tool | 30-min pregame line capture | `deepsports odds-snapshot` + `tools/odds-snapshot.sh` (launchd `com.deepsports.odds`) |
| Tool | pre-tip injury refresh + v1.1i predictions | `deepsports pretip` + `tools/pretip.sh` (launchd `com.deepsports.pretip`, :20/:50) |
| Tool | diagram renderer | `tools/diagram.sh` |
| Tool | deepsports CLI | `src/deepsports/cli.py` |
| Tool | paper-trade log (watch-only) | `deepsports paper log \| report` (`src/deepsports/analysis/paper.py`) |
| Tool | bet grader + 3× move audit | `src/deepsports/analysis/betting/` |
| Tool | feature walk-forward test | `src/deepsports/analysis/feature_test.py` |
| Tool | ensemble betting (watch-only vote) | `deepsports ensemble-bets context\|tally\|grade` (`src/deepsports/analysis/ensemble_bets.py`) |
