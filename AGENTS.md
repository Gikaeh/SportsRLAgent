# AGENTS.md — Operational Constitution

Sports betting recommendation system (NHL + NBA, MLB planned): XGBoost models predict
h2h/spread/total outcomes; a Kelly-criterion recommender turns predictions into bet
suggestions; results are graded in CSV logs. **The human places every real bet.**

Read order at session start: this file → `docs/SESSION-LOG.md` → `docs/PROJECT.md` →
`docs/DECISIONS.md`. That is everything you need. If you learn something a future
session needs, write it into one of those files — not into chat.

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
3. **Bet logs are immutable history.** `logs/**/*_bets.csv` are append-only records of
   what was actually recommended/placed and how bets were graded. Fix errors by adding
   a correcting row or an explanatory commit message — never silently edit or delete
   past rows.
4. **No silent data leakage.** Model features must be computable at prediction time
   (no season-end stats for mid-season games, no post-game info). Time-based splits only.
5. **Verify before "done".** Run `.venv\Scripts\python.exe -m pytest tests/ -v`. All green, or
   you say explicitly why not.

## Stack & commands

Python 3.12, env managed by **uv** at `.venv/`, deps from `requirements.txt`.
Windows machine — use `.venv\Scripts\python.exe` (not `.venv/bin/python`).

| When | Command |
|---|---|
| Create env + install deps | `uv venv`; then `uv pip install -r requirements.txt` |
| Verify changes | `.venv\Scripts\python.exe -m pytest tests/ -v` |
| NHL daily menu (recommendations, grade bets, retrain) | `.venv\Scripts\python.exe hockey/main.py` |
| NBA daily menu | `.venv\Scripts\python.exe basketball/main.py` |
| Add a dependency | append to `requirements.txt`, then `uv pip install -r requirements.txt` |

Interactive CLIs: choose a menu number; entering one number above the highest
listed option steps through every task in sequence ("run all"). Odds come from The
Odds API (key required — see non-negotiable #2); game/injury data from free NBA/NHL
APIs.

## Repo layout — where new files go

```
basketball/  hockey/  baseball/   One dir per sport, identical internal structure:
  ├─ main.py                   interactive CLI entry point
  ├─ data_pipeline/            fetching + feature prep (incl. odd_scraping.py)
  ├─ model/                    training/retraining per bet type
  ├─ betting/                  betting_config.py (thresholds) + betting_recommender.py
  └─ initial_*_setup.py        one-time historical backfills
shared/       BaseDataFetcher / BaseDataPreparer — sport-independent base classes;
              new shared logic goes here, sports inherit
data/<sport>/ game_data, team_data, player_data, cache (parquet), odds_data,
              injury_data, upcoming_games.csv — fetched/derived data lives here
models/       trained XGBoost JSONs + metadata/ (retrain timestamps)
logs/<sport>/betting/  *_bets.csv bet journals (IMMUTABLE — see rule #3)
plots/        generated diagnostics (regenerable, low value)
tests/        pytest smoke tests
tools/        standalone scripts (none yet); each MUST get an AGENTS.md table row on creation
docs/         PROJECT.md, DECISIONS.md, SESSION-LOG.md (+ -ARCHIVE.md)
```

Conventions (match existing code): files/modules `snake_case.py`; classes `PascalCase`;
methods/functions `camelCase` (existing style — do not "fix" it piecemeal); constants
UPPER_SNAKE. Per-sport dirs mirror each other — a change to hockey's pipeline usually
implies the same change to basketball's.

**Adding anything = update something else too:**
- New tool script → add exact invocation to the table above.
- New threshold/config → edit that sport's `betting_config.py`, note *why* in
  `docs/DECISIONS.md`.
- New sport → create `<sport>/` mirroring hockey/, plus `data/<sport>/`,
  `logs/<sport>/betting/`.
- Changed behavior → update `docs/SESSION-LOG.md`; changed *why* → `docs/DECISIONS.md`.

## Workflow

1. Start: read SESSION-LOG → do Next item.
2. Work directly on `main` (solo repo); small commits with messages describing what +
   why, like existing history.
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

This repo deliberately uses NO subagents — solo owner, small codebase, one context is
faster and safer than role-splitting. Do not fabricate reviewer/builder roles. If the
project grows a genuinely separable concern (e.g., a scraper fleet needing sandboxed
execution), propose subagents then, with scoped permissions, and record it in
`docs/DECISIONS.md`.
