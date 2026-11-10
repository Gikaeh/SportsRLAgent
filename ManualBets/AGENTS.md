# AGENTS.md — Operational Constitution (ManualBets)

Sports betting recommendation system (NHL + NBA, MLB planned; college basketball reads
the DeepSports warehouse): XGBoost models predict h2h/spread/total outcomes; a
Kelly-criterion recommender turns predictions into bet suggestions; results are graded in
CSV logs. **The human places every real bet.**

Read order at session start: this file → `docs/SESSION-LOG.md` → `docs/PROJECT.md` →
`docs/DECISIONS.md`. That is everything you need. If you learn something a future session
needs, write it into one of those files — not into chat.

**Where this project lives:** this file is `ManualBets/AGENTS.md` in the `SportsRLAgent`
git repo. Every path below is relative to `ManualBets/`; run commands from this folder.
The repo root also holds `DeepSports/` (its own env, deps and `AGENTS.md`) and the shared
`logs/` bet journals — don't mix changes between the two projects.

Per-area deep-dive context: `basketball/NOTES.md` (audit findings + remediation spec,
2026-08-22) — read before touching basketball code.

## Non-negotiables (never break these)

1. **Humans place all bets.** Never place, automate, or transmit wagers. Output is
   recommendations only.
2. **No secrets in code, logs, or commits.** Credentials live in environment
   variables / `.env` (gitignored). Document only *where* a secret lives and how to
   inject it — never its value. Known debt: the Odds API key is currently hardcoded in
   three `odd_scraping.py` files and already in git history; removal is the current
   deliverable (`docs/SESSION-LOG.md`). Recommend key rotation to the owner.
3. **Bet logs are immutable history.** `../logs/**/*_bets.csv` are append-only records of
   what was actually recommended/placed and how bets were graded. Fix errors by adding
   a correcting row or an explanatory commit message — never silently edit or delete
   past rows.
4. **No silent data leakage.** Model features must be computable at prediction time
   (no season-end stats for mid-season games, no post-game info). Time-based splits only.
5. **Verify before "done".** Run `.venv\Scripts\python.exe -m pytest tests/ -v`. All green, or
   you say explicitly why not.

## Stack & commands

Python 3.12, env managed by **uv** at `.venv/` inside `ManualBets/`, deps from
`requirements.txt` / `pyproject.toml`. Windows machine — use `.venv\Scripts\python.exe`
(not `.venv/bin/python`).

| When | Command |
|---|---|
| Create env + install deps | `uv sync` (or `uv venv` + `uv pip install -r requirements.txt`) |
| Verify changes | `.venv\Scripts\python.exe -m pytest tests/ -v` |
| NHL daily menu (recommendations, grade bets, retrain) | `.venv\Scripts\python.exe hockey/main.py` |
| NBA daily menu | `.venv\Scripts\python.exe basketball/main.py` |
| College basketball menu (needs the DeepSports warehouse; prints recommendations, logs nothing) | `.venv\Scripts\python.exe college_basketball/main.py` |
| Home/away calibration of graded bets (tools/) | `.venv\Scripts\python.exe tools\calibration_diagnostic.py` |
| Pipeline smoke test: train fresh in-memory + predict upcoming_games.csv (tools/) | `.venv\Scripts\python.exe tools\pipeline_smoke_test.py` |
| College walk-forward test (tools/) | `.venv\Scripts\python.exe tools\college_walkforward.py --start 2025-11-01 --end 2026-02-01 --out preds.csv` |
| Add a dependency | append to `requirements.txt`, then `uv pip install -r requirements.txt` |

Interactive CLIs: choose a menu number; entering one number above the highest
listed option steps through every task in sequence ("run all"). Odds come from The
Odds API (key required — see non-negotiable #2); game/injury data from free NBA/NHL
APIs.

## Repo layout — where new files go

Everything below is inside `ManualBets/` unless it says otherwise. There is one shared
`.gitignore` at the repo root (it also covers `DeepSports/`).

```
basketball/  hockey/  baseball/   One dir per sport, identical internal structure:
                               (college_basketball/ reads DeepSports' warehouse; no fetcher,
                                no initial_*_setup.py)
  ├─ main.py                   interactive CLI entry point
  ├─ data_pipeline/            fetching + feature prep (incl. odd_scraping.py)
  ├─ model/                    training/retraining per bet type
  ├─ betting/                  betting_config.py (thresholds) + betting_recommender.py
  └─ initial_*_setup.py        one-time historical backfills
shared/       BaseDataFetcher / BaseDataPreparer / splitting / bankroll —
              sport-independent helpers; new shared logic goes here, sports inherit
data/<sport>/ game_data, team_data, player_data, cache (parquet), odds_data,
              injury_data, upcoming_games.csv — fetched/derived data lives here
models/       trained XGBoost JSONs + metadata/ (retrain timestamps)
plots/        generated diagnostics (regenerable, low value)
tests/        pytest smoke tests
tools/        standalone scripts (e.g. calibration_diagnostic.py); each MUST get an
              AGENTS.md table row on creation
docs/         PROJECT.md, DECISIONS.md, SESSION-LOG.md (+ -ARCHIVE.md)
```

Outside this folder (repo root):

```
logs/<sport>/betting/  *_bets.csv bet journals (IMMUTABLE — see rule #3).
                       Kept at the repo root because DeepSports reads them read-only.
DeepSports/            separate project; college_basketball/ reads its DuckDB warehouse.
```

Conventions (match existing code): files/modules `snake_case.py`; classes `PascalCase`;
methods/functions `camelCase` (existing style — do not "fix" it piecemeal); constants
UPPER_SNAKE. Per-sport dirs mirror each other — a change to hockey's pipeline usually
implies the same change to basketball's.

**Adding anything = update something else too:**
- New tool script → add exact invocation to the table above.
- New threshold/config → edit that sport's `betting_config.py`, note *why* in
  `docs/DECISIONS.md`.
- New sport → create `<sport>/` mirroring hockey/, plus `data/<sport>/`, and a
  `logs/<sport>/betting/` directory at the repo root.
- Changed behavior → update `docs/SESSION-LOG.md`; changed *why* → `docs/DECISIONS.md`.

## Cross-project boundary

`ManualBets/` and `DeepSports/` are separate projects with separate environments and no
shared imports. Only two read-only edges cross the boundary:

1. **DeepSports → `../logs/`**: `DeepSports/src/deepsports/api/bets.py` reads open bet rows
   to label game cards. It never writes.
2. **`college_basketball/` → `DeepSports/data/deepsports.duckdb`**: read-only warehouse
   access via `college_basketball/data_pipeline/warehouse_loader.py`. It never writes.

Anything else shared (`.gitignore`, this README's parent, git history) lives at the repo
root. Don't add new cross-project imports without recording the decision.

## Workflow

1. Start: read SESSION-LOG → do Next item.
2. Small commits with messages describing what + why, like existing history. Keep a
   commit inside one project folder — the repo also holds `DeepSports/`.
3. Before declaring done: pytest green (rule #5), then update `docs/SESSION-LOG.md`
   (move old entry verbatim to `docs/SESSION-LOG-ARCHIVE.md`, newest on top).
4. Made a decision with a *why* worth remembering? Append to `docs/DECISIONS.md`.
   Reversed a decision? Strike it through, point to the reversal — never delete.

## Escalation (ask the human)

- Any change that alters model outputs or betting thresholds beyond tuning comments.
- Anything touching bet-log CSV contents (rule #3).
- Missing credentials, API quota exhausted, or data source breaking changes.
- Ambiguity between profit and the non-negotiables: non-negotiables always win.

## Agents: single agent by decision

This project deliberately uses NO subagents — solo owner, small codebase, one context is
faster and safer than role-splitting. Do not fabricate reviewer/builder roles. If the
project grows a genuinely separable concern (e.g., a scraper fleet needing sandboxed
execution), propose subagents then, with scoped permissions, and record it in
`docs/DECISIONS.md`.
