# AGENTS.md: ManualBets specifics

Handmade basketball betting pipeline (NBA + NCAA men's D1): XGBoost models per bet type
(h2h, spread, total), Kelly-sized bet suggestions, graded CSV bet logs. A human runs the menus
and places every bet. Repo-wide rules (non-negotiables, git, boundary edges, agents registry,
context hygiene) are in `../AGENTS.md` and are not repeated here. `hockey/` and `baseball/` are
out of focus (see `../AGENTS.md`).

**Session read order:** this file, then the live entry in `docs/SESSION-LOG.md`. On demand:
`docs/PROJECT.md` (goal, milestone, scope), `basketball/NOTES.md` (open audit items; read
before touching basketball code), `docs/DECISIONS.md` (why things are the way they are).

## Commands
Run from `ManualBets/`. Same commands on macOS and Windows. Python >=3.12 (the Mac venv is 3.13).

| When | Command |
|---|---|
| Create env / install deps | `uv sync` |
| Add a dependency | `uv add <pkg>` (`pyproject.toml` + `uv.lock` are the source of truth, not `requirements.txt`) |
| Verify | `uv run pytest -q`: expect 2 known failures in `tests/test_opp_avg_win_pct.py` (needs `data/basketball/team_data/2024-25_team_stats.csv`, absent on the Mac, and calls a nonexistent `calculateOpponentStrengthL10`). Anything else failing is yours. |
| NBA menu | `uv run python basketball/main.py` |
| College menu (reads the DeepSports warehouse) | `uv run python college_basketball/main.py` |
| Home/away calibration of graded bets | `uv run python tools/calibration_diagnostic.py` |
| Smoke test: train in memory + predict `upcoming_games.csv` | `uv run python tools/pipeline_smoke_test.py` |
| Export the slate as JSON for DeepSports' ensemble vote (models, Kelly fractions, best Odds API prices; 2-5 credits; no logging) | `uv run python tools/export_predictions.py --out <file>` |
| College walk-forward | `uv run python tools/college_walkforward.py --start 2025-11-01 --end 2026-02-01 --out preds.csv` |

Menus: pick a number; one above the highest option runs every task in order. The NBA menu is
Betting Recommendations / Betting Update (grade + bankroll) / Active Bets / Model Retraining.
The college menu is Retrain / Predictions / Recommendations (costs 3 Odds API credits).
Running the menus and the Odds API is allowed and expected whenever betting analysis needs
ManualBets' picks or fresh odds (`../AGENTS.md`, "ManualBets and the Odds API are NOT off limits").
Spend the shared quota sensibly and report `x-requests-remaining`.

## How it works and where things live
Paths are relative to `ManualBets/`; the bet logs are at `../logs/`.

**NBA flow** (`basketball/`):
`data_pipeline/basketball_data.py` (nba_api fetch) → `data_pipeline/prepare_data.py` (features)
→ `data_pipeline/live_data_updater.py` (upcoming games via `nextSlate` in
`shared/base_data_fetcher.py`) → `data_pipeline/odd_scraping.py` (The Odds API) →
`model/model_{h2h,spread,total}.py` + `model/model_retrainer.py` →
`betting/betting_recommender.py` (devig, normal cover probability, Kelly sizing via
`shared/bankroll.py`) → appends and grades `../logs/basketball/betting/{h2h,spread,total}_bets.csv`.
`initial_*_setup.py` are one-time historical backfills.

**College flow** (`college_basketball/`):
`data_pipeline/warehouse_loader.py` (DeepSports DuckDB, read-only; override the path with
`COLLEGE_WAREHOUSE_DB`) → `data_pipeline/prepare_data.py` → `model/model_college.py` →
`betting/betting_recommender.py`. It writes no log. Owner-placed college bets are logged by hand
in `../logs/college_basketball/betting/bets.csv`, and the NBA bankroll counts them.

| What | Where |
|---|---|
| Trained models | `models/*.json`; retrain metadata (incl. `residual_std`) in `models/metadata/<sport>/` |
| Fetched/derived data | `data/<sport>/` (untracked except `odds_data/`) |
| Thresholds, bankroll ($50 from 2026-11-08) | `<sport>/betting/betting_config.py` |
| Train/val/test split (80/10/10 by date) | `shared/splitting.py::chronologicalSplit` |
| Shared base classes | `shared/base_data_fetcher.py`, `shared/base_data_preparer.py`, `shared/bankroll.py` |
| Tests | `tests/`; `conftest.py` puts `basketball/` and `hockey/` on `sys.path`, so sport modules (which share package names like `model`) are imported in subprocesses |
| Standalone scripts | `tools/` |
| Old long-term roadmaps (history only) | `docs/archive/` |

## ManualBets rules
- **Conventions:** modules `snake_case.py`, classes `PascalCase`, methods/functions `camelCase`
  (existing style; don't rename piecemeal), constants `UPPER_SNAKE`.
- **Mirror changes:** per-sport folders share structure. A fix to shared logic goes in `shared/`;
  a basketball fix that applies to college should be checked there too.
- **Odds API key:** still a literal in the `odd_scraping.py` files (`../AGENTS.md` rule 2); the
  college scraper borrows basketball's. It also travels in request URLs, so a traceback or
  logged URL can expose it: don't print exceptions or URLs from those calls verbatim.
- **Escalate to the owner before** changing betting thresholds or bankroll settings, anything that
  changes model outputs (features, drop lists, retrain settings), or anything in `../logs/`.
  Also on missing credentials, exhausted quota, or a data source that changed shape. (Running the
  menus, predictions and Odds API calls needs no escalation.)

**Every change updates its home:**
- New `tools/` script → a row in the Commands table above.
- Threshold/config change → that sport's `betting_config.py` + a `docs/DECISIONS.md` entry.
- New or fixed audit item → `basketball/NOTES.md`.
- End of session → replace the live `docs/SESSION-LOG.md` entry (move the old one verbatim to the
  top of `docs/SESSION-LOG-ARCHIVE.md`).

## Where facts go
| Fact | Home |
|---|---|
| Rules, commands, layout | this file |
| Goal, milestone, scope, constraints | `docs/PROJECT.md` |
| Current state and next steps | `docs/SESSION-LOG.md` (one live entry) |
| History of sessions | `docs/SESSION-LOG-ARCHIVE.md` |
| Why (append-only, strike through reversals) | `docs/DECISIONS.md` |
| Basketball audit findings and open fixes | `basketball/NOTES.md` |
| Repo-wide rules and agents | `../AGENTS.md`, `../docs/DECISIONS.md` |
