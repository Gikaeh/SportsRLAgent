# Agents in DeepSports

The orchestrator role, the dev-agent registry, adding agents/skills/tools and the DeepSeek
collaborator are repo-wide: `../AGENTS.md`. This file covers DeepSports only.

## Who owns what here
| Root dev agent | DeepSports paths |
|---|---|
| `data-engineer` | `src/deepsports/` except `analysis/`; `tests/`, `config/`, `tools/` |
| `data-analyst` | `src/deepsports/analysis/`, `analysis/`, `models/` (read-only on the warehouse) |
| `frontend-dev` | `web/`, `glasses/` |
| `architect` | `docs/` (incl. `docs/diagrams/`), this file, `CLAUDE.md` |

Coordination: **one DuckDB writer at a time** (only one agent runs collection jobs; analysts work on
a copy or wait). Cross-cutting changes go back to the orchestrator.

## Workflows
- **Add a data source:** `data-engineer` (source, parser, fixtures, tests, backfill) → `architect`
  (diagram, DATA_SOURCES, DATA_MODEL) → orchestrator runs the checks.
- **Daily refresh:** launchd runs `tools/scheduled-sync.sh` (warehouse steps, then headless
  `/sync-game-calendar prefetched`); interactively, `calendar-agent` runs `/sync-game-calendar`.
- **Model work:** orchestrator frames the question → `data-analyst` builds it (walk-forward, no
  leakage) → orchestrator reviews the method → `architect` files the dated result in `docs/results/`.

## Runtime agents and skills (`DeepSports/.claude/`; the agents are seen only by sessions started here, so run the skills from here too)
| Kind | Name | Path | Use |
|---|---|---|---|
| Agent | `bettor` | `.claude/agents/bettor.md` | One Read-only voter in `/ensemble-betting` |
| Agent | `calendar-agent` | `.claude/agents/calendar-agent.md` | Runs `/sync-game-calendar` interactively |
| Skill | `/sync-game-calendar` | `.claude/skills/sync-game-calendar/SKILL.md` | Reconcile followed games with Google Calendar |
| Skill | `/ensemble-betting` | `.claude/skills/ensemble-betting/SKILL.md` | N independent bettors, majority vote, watch-only |

## Tools registry
| Tool | Path |
|---|---|
| deepsports CLI | `src/deepsports/cli.py` (commands in `docs/PIPELINE.md`) |
| data-quality checks | `deepsports check` (`src/deepsports/quality.py`) |
| read API + web server | `deepsports serve` (`src/deepsports/api/`) |
| scheduled sync | `tools/scheduled-sync.sh` + `tools/launchd/` |
| 30-min pregame line capture | `deepsports odds-snapshot` + `tools/odds-snapshot.sh` (launchd `com.deepsports.odds`) |
| pre-tip injury refresh + v1.1i predictions | `deepsports pretip` + `tools/pretip.sh` (launchd `com.deepsports.pretip`, :20/:50) |
| diagram renderer | `tools/diagram.sh` |
| paper-trade log (watch-only) | `deepsports paper log \| report` (`src/deepsports/analysis/paper.py`) |
| bet grader + 3× move audit | `src/deepsports/analysis/betting/` |
| feature walk-forward test | `src/deepsports/analysis/feature_test.py` |
| ManualBets export for the vote (NBA on the Pi, college here) | `tools/manualbets-export.py` (PIPELINE.md, "Raspberry Pi helper") |
| ensemble betting (watch-only vote) | `deepsports ensemble-bets context\|tally\|grade` (`src/deepsports/analysis/ensemble_bets.py`) |
