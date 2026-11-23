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
- **Daily refresh:** launchd runs `tools/scheduled-sync.sh` (warehouse steps; model picks at 14:00).
  Calendar sync is by hand only for now: `calendar-agent` runs `/sync-game-calendar`.
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
| The Odds API live line capture (owner's key, college + NBA totals/spreads, 10 books, ~84 credits/day, until 2026-12-24; files only) | `deepsports odds-api-history live` + `tools/oddsapi-live.sh` (launchd `com.deepsports.oddsapi-live`, 09:00 + every 30 min 12:00-21:30); rows via `src/deepsports/sources/oddsapi_live.py` |
| momentum forward-test freeze (read-only, write-once: tomorrow's college DS predictions + MB export copy at 18:30/19:00/19:30) | `deepsports momentum-freeze` (`src/deepsports/momentum_freeze.py`), run by `tools/oddsapi-live.sh` |
| pre-tip injury refresh + v1.1i predictions | `deepsports pretip` + `tools/pretip.sh` (launchd `com.deepsports.pretip`, :20/:50) |
| diagram renderer | `tools/diagram.sh` |
| paper-trade log (watch-only) | `deepsports paper log \| report` (`src/deepsports/analysis/paper.py`) |
| bet grader + 3× move audit | `src/deepsports/analysis/betting/` |
| feature walk-forward test | `src/deepsports/analysis/feature_test.py` |
| ManualBets export for the daily picks and the vote (NBA on the Pi, college here) | `tools/manualbets-export.py` (PIPELINE.md, "Raspberry Pi helper") |
| models-only daily picks (watch-only; weekdays 14:00, weekends 08:00) | `deepsports model-picks run\|grade` + `tools/model-picks-daily.sh` (`src/deepsports/analysis/model_picks.py`) |
| Circa screenshots: upload API, iCloud inbox, Claude read into lines (watch-only) | `deepsports circa read\|ingest\|status` (`src/deepsports/circa/`, `src/deepsports/api/circa.py`) |
| Circa + William Hill lines from OddsPapi (watch-only; Caesars' feed stands in for WH) | `deepsports books grab\|status` (`src/deepsports/books/`), run by `tools/model-picks-daily.sh` |
| night-before Caesars grab + et-v1 early-totals forward test (watch-only) | `deepsports books grab --early` + `deepsports early-totals log\|grade\|status` (`src/deepsports/analysis/early_totals.py`), run by `tools/books-evening.sh` (launchd `com.deepsports.books-evening`, 21:00) |
| et-v1-alt altitude shadow of et-v1 (watch-only; `ncaab-v1.1alt` total, logged by the same 21:00 run) | `deepsports early-totals grade --alt` / `status --alt` (`src/deepsports/analysis/early_totals_alt.py`; files under `reports/early-totals/alt/`) |
| et-v1 / et-v1-alt bet market context (describe-only: opener, DraftKings at bet time, Caesars feed, WH + Circa screenshots; win %/CLV split by momentum and Circa vs WH) | `deepsports early-totals context --log\|--backfill` / `context [--alt]` (`src/deepsports/analysis/early_totals_context.py`; `reports/early-totals/context.jsonl`), `--log` run by `tools/books-evening.sh` after the Circa read |
| venue geography: GeoNames download, venue backfill + geocode (elevation, tz), coverage | `deepsports venues fetch\|build\|status` (`src/deepsports/venues_cli.py`, `venue_geo.py`, `sources/geonames.py`; `build` run by `tools/scheduled-sync.sh`) |
| To The Moon lotto card (watch-only; tomorrow's et-v1 legs as a $1 top-7 test ticket + $0.25 7-leg spread tickets, rule lotto-v2; 21:00 → Discord) | `deepsports moon lotto [grade]` (`src/deepsports/moon/lotto.py`; `reports/moon/lotto/cards.jsonl`), run by `tools/books-evening.sh` |
| cash-out check ("check cashouts"): P(win) and fair cash-out value for open bets in the 2nd half (read-only, heuristic, by hand) | `uv run python tools/cashout.py [--all]` |
| ensemble betting (watch-only vote, by hand) | `deepsports ensemble-bets context\|tally\|grade` (`src/deepsports/analysis/ensemble_bets.py`) |
