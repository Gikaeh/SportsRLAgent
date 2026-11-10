# SportsRLAgent

Two independent betting-research projects live in this repo. Each top-level project
folder is self-contained: its own `pyproject.toml`, its own virtual environment, its
own docs and rules. The only shared things are this README, the root `.gitignore`,
the `logs/` bet journals, and the git history.

| Folder | What it is |
|---|---|
| [`ManualBets/`](ManualBets/) | The handmade betting pipeline. Free-API data fetching, XGBoost models per bet type, Kelly-criterion bet suggestions, append-only CSV bet logs. **You** place the bets. |
| [`DeepSports/`](DeepSports/) | An agent-driven NBA + NCAA men's D1 data warehouse (DuckDB), frozen prediction models, a read API with a phone web app and glasses plugin, Google Calendar game alerts, and watch-only paper trading. |
| `logs/` | The bet journals (`logs/<sport>/betting/*_bets.csv`). Written by ManualBets, read read-only by DeepSports to label game cards. Append-only history — never edit past rows. |

## Ground rules

- **Work inside one folder at a time.** Each project has its own `AGENTS.md`
  (DeepSports also has `CLAUDE.md`); read the one in the folder you're touching.
- **Separate environments.** Run `uv` commands from inside the project folder you are
  working in. `ManualBets/.venv` and `DeepSports/.venv` are unrelated.
- **One git history, one shared `.gitignore`** at the root. Keep commits scoped to a
  single project.
- **Only two read-only edges cross the boundary:**
  1. DeepSports' API reads open bet rows from `logs/` (never writes).
  2. ManualBets' `college_basketball/` reads `DeepSports/data/deepsports.duckdb`
     (never writes).
  Nothing else is shared; removing one project folder leaves the other working.
- **Dependencies never overlap in the background either:** ManualBets is pandas /
  XGBoost / scikit-learn / nba-api; DeepSports is duckdb / fastapi / httpx / uvicorn.

## ManualBets quick start

```powershell
cd ManualBets
uv sync
.venv\Scripts\python.exe -m pytest tests/ -v      # verify
.venv\Scripts\python.exe basketball/main.py       # NBA daily menu
```

Read [`ManualBets/README.md`](ManualBets/README.md) for the full pipeline overview and
[`ManualBets/AGENTS.md`](ManualBets/AGENTS.md) for the non-negotiables. Odds need an
Odds API key (environment variable / `.env`, never in git).

## DeepSports quick start

```bash
cd DeepSports
uv sync
uv run pytest -q                                  # offline, fixture-based
uv run deepsports update                          # recent results + next 14 days
uv run deepsports serve                           # API + web app on :8787
```

Start with [`DeepSports/docs/HANDOFF.md`](DeepSports/docs/HANDOFF.md) for current state;
[`DeepSports/README.md`](DeepSports/README.md) has setup, data-location options, the
launchd jobs, and the doc index. No API keys required.
