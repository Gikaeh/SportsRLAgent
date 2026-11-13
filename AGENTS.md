# AGENTS.md: how work gets done in SportsRLAgent

Basketball betting research (NBA + NCAA men's D1), developed mostly by AI agents. This file
holds the repo-wide rules; each project's own `CLAUDE.md`/`AGENTS.md` adds its specifics.
Keep each fact in one place and point to it from everywhere else (see "Context hygiene").

## The repo

| Path | What | Start here |
|---|---|---|
| `DeepSports/` | NBA + college data warehouse (DuckDB), frozen prediction models, read API + phone web app + glasses plugin, Google Calendar alerts, watch-only paper trading and ensemble betting vote. Runs on the owner's Mac via launchd. | `DeepSports/CLAUDE.md` |
| `ManualBets/` | Handmade pipeline: XGBoost models per bet type, Kelly-sized bet suggestions, graded CSV bet logs. A human runs the menus and places bets. | `ManualBets/CLAUDE.md` |
| `BetDesk/` | Shared app for both owners on Cloudflare (Worker + PWA, behind Cloudflare Access). Phase 1: read-only live view of DeepSports' read API through a Cloudflare Tunnel to the owner's Mac. | `BetDesk/CLAUDE.md` |
| `logs/` | Bet journals `logs/<sport>/betting/*_bets.csv`. Written by ManualBets, read by DeepSports. Append-only. Only open-bet labels (never stakes) leave the Mac, via edge 3. | (rule 3 below) |
| `.claude/agents/` | Repo-wide dev agents (registry below). | |
| `docs/DECISIONS.md` | Repo-wide decisions (structure, scope, integration). Projects keep their own logs. | |

**Scope: basketball only.** `ManualBets/hockey/` and `ManualBets/baseball/` stay in the tree
but get no new work, and plans, docs and summaries leave them out unless the owner asks.

**Direction:** the projects will be merged step by step (one data source, one app: `BetDesk/`). Until
an integration step is decided in `docs/DECISIONS.md`, they stay separate: separate `uv`
environments (run `uv` inside the project folder), no imports across the boundary, and only
these read-only edges:
1. DeepSports' API reads open rows from `logs/` (`DeepSports/src/deepsports/api/bets.py`).
2. ManualBets reads `DeepSports/data/deepsports.duckdb`, read-only: `college_basketball/`
   (`college_basketball/data_pipeline/warehouse_loader.py`) and the NBA totals backtest's
   closing lines (`tools/total_walkforward.py`, `NBA_WAREHOUSE_DB` points it at a copy).
3. BetDesk's Worker reads DeepSports' read API over HTTP (GET, allowlisted endpoints) through a
   Cloudflare Tunnel to `localhost:8787` on the owner's Mac (`BetDesk/worker/src/origin.ts`;
   contract `DeepSports/docs/API.md`).
4. DeepSports' daily model picks and ensemble vote read a JSON written by `ManualBets/tools/export_predictions.py`
   (run by `DeepSports/tools/manualbets-export.py`, NBA half on the LAN Raspberry Pi;
   `analysis/manualbets_context.py`).
A new edge is an integration step: propose it, log it, then build it.

## Non-negotiables (every project, every agent)
1. **Humans place every real bet.** Never place, automate or transmit a wager. Model output,
   paper trades and the ensemble vote are recommendations or watch-only records.
2. **No new secret values** in code, docs, logs, commits or chat. Known debt: the Odds API key is
   still a literal in ManualBets' `odd_scraping.py` files (and in git history); moving it to an
   env var is open work. Never print the key. The `logs/` CSVs hold real stakes: don't quote them
   outside the repo.
3. **Bet logs are append-only history.** Never edit or delete past rows in `logs/**`; correct by
   appending. Same for the projects' paper-trade and ensemble records.
4. **No leakage.** Features use only information available before tip-off; evaluate with
   time-based (walk-forward) splits, never random ones.
5. **Verify before "done".** Run the project's checks (in its `CLAUDE.md`). A subagent's report
   is a claim: re-run its checks before telling the owner it's finished.
6. **Don't run live data jobs casually.** DeepSports allows one DuckDB writer at a time and its
   warehouse lives on an external drive; scheduled jobs own it (see `DeepSports/CLAUDE.md`).

## Git
- Never commit to `main`. Branch first (`feature/…`, `fix/…`), then open a PR to `main` on
  `Gikaeh/SportsRLAgent`. Commit or push only when the owner asks.
- Keep each commit inside one project folder, unless the change is an agreed integration step
  or a root-level file.
- No AI attribution: no `Co-Authored-By` AI lines, session links or "Generated with" footers in
  commits or PRs.

## ManualBets and the Odds API are NOT off limits
Owner's standing instruction (2026-11-10): ManualBets (its models, predictions, Kelly
recommendations, menus and scripts) and the Odds API it uses are normal tools, available to
every session and agent. **Any betting analysis, pick or panel uses all of the repo's resources:
DeepSports *and* ManualBets**, plus fresh Odds API lines when they help. Don't skip them to "save
quota" or because a menu is interactive (drive it with piped input or call its code). Spend the
shared quota sensibly: request only the sports/markets/books needed and report
`x-requests-remaining`. The only limits are the non-negotiables above (humans place bets, never
print the key, append-only logs) and DeepSports' one-writer rule.

## Working as the orchestrator
The main session owns the plan and the outcome:
- **Plan** against the project's roadmap (DeepSports `docs/ROADMAP.md`, ManualBets
  `docs/SESSION-LOG.md`); ask the owner only for decisions that are theirs.
- **Delegate** self-contained tasks to the agents below with a complete brief: goal, files,
  constraints, what "done" means. Run agents in parallel only when they don't touch the same
  files or both need the DuckDB writer. Small or tightly coupled changes are cheaper inline.
- **Integrate and verify** (rule 5), then **report** in a few phone-readable lines. Interactive
  sessions on the owner's Mac post their final message to Discord through a global Stop hook.

## Agents
Dev agents live in the root `.claude/agents/`, so sessions started at the root or in either
project see them. Runtime agents and skills that DeepSports' headless jobs call stay in
`DeepSports/.claude/`; use them from a session started inside `DeepSports/`.

| Agent | Where | Use for |
|---|---|---|
| `architect` | root | Docs, diagrams, this registry and context hygiene after structural changes |
| `data-engineer` | root | Data sources, fetchers/parsers, storage schema, collection jobs, tests (both projects) |
| `data-analyst` | root | Features, models, backtests, calibration, betting-rule research (both projects) |
| `frontend-dev` | root | `BetDesk/web/` (the project's app), `DeepSports/glasses/`; `DeepSports/web/` is frozen (LAN + glasses build) |
| `reviewer` | root | Read-only review of a diff against the non-negotiables and project rules |
| `bettor` | DeepSports | One voter in `/ensemble-betting` (runtime, headless) |
| `calendar-agent` | DeepSports | Runs `/sync-game-calendar` interactively |

Skills: `/sync-game-calendar` and `/ensemble-betting` (both in `DeepSports/.claude/skills/`, run
from `DeepSports/`). Deterministic, repeatable work belongs in a CLI subcommand or a `tools/`
script, not in a prompt.

**Adding an agent, skill or tool:** do it when work will recur. Prefer extending an existing one.
Put it at the root if it's dev work, in the project if a scheduled job calls it. Register it in
the table above (or the project's registry), and log why in the matching `DECISIONS.md`.

**Saving Claude usage:** for big implementation or simulation jobs, the owner can run a separate
DeepSeek-backed session. The orchestrator writes a brief in `DeepSports/collab/deepseek/`
(git-ignored) and gives the owner a message to paste. That session writes only there; Claude
re-checks its numbers before porting anything.

## Context hygiene (keep agent context accurate and small)
- `CLAUDE.md` files hold rules and pointers, not history or results. Target under ~80 lines.
- Where each fact goes:
  - Current state and next steps: DeepSports `docs/HANDOFF.md`, ManualBets `docs/SESSION-LOG.md`.
  - Why: the matching `DECISIONS.md` (append-only; strike through a reversal, never delete).
  - How things work: the reference docs named in each project's `CLAUDE.md`.
  - Results: dated files under `docs/results/`. Read them on demand; don't copy them into
    other docs.
- When you change behavior, update the one doc that owns that fact in the same change. When a
  doc says something the code contradicts, fix the doc or flag it.
- Never put personal details or secret values into docs.
