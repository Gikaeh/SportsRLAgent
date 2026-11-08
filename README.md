# SportsRLAgent

Sports data, prediction, and betting-research projects. This repo has two parts:

| Folder | What it is |
|---|---|
| `basketball/`, `hockey/`, `baseball/`, `shared/` | The original SportsRLAgent pipeline: free-API data fetching, XGBoost models per bet type, and Kelly-criterion bet suggestions |
| [`DeepSports/`](DeepSports/) | An agent-driven NBA + college basketball data warehouse, prediction models, a phone web app, and Google Calendar game alerts (described below) |

The two parts are independent: each has its own dependencies and environment, and you can set up either one without the other.

---

## DeepSports

DeepSports collects NBA and NCAA men's D1 basketball data (games, box scores, betting lines, injuries) into a local DuckDB warehouse. On top of that it:

- **Predicts** upcoming games with simple, frozen models (NBA `v1.0`/`v1.1`, college `ncaab-v1`). It grades each model against results and the closing line.
- **Serves** a read API and a mobile web app (PWA) with live scores, standings, and predictions. There is also an Even Realities G2 glasses plugin.
- **Syncs** upcoming games for the teams you follow to Google Calendar, using Claude Code.
- **Paper-trades** (watch-only, no real money). Frozen betting rules and an ensemble vote of Claude "bettor" agents log picks that are graded later.

The data comes from ESPN's public JSON endpoints. Requests are rate-limited to about 1 per second and responses are cached on disk. You don't need any API keys.

Inside the folder, start with [`DeepSports/docs/HANDOFF.md`](DeepSports/docs/HANDOFF.md) for the current state. [`DeepSports/README.md`](DeepSports/README.md) has the doc index.

### Layout
```
DeepSports/
  src/deepsports/   CLI, ESPN sources + pure parsers, DuckDB store, models, read API
  tests/            pytest (offline, against saved real responses in tests/fixtures/)
  config/           calendar.toml: teams to follow, days ahead, reminder time
  web/              mobile web app (Vite + React + TypeScript)
  glasses/          Even Realities G2 plugin
  tools/            launchd jobs, scheduled scripts, diagram renderer
  .claude/          Claude Code agents and skills (/sync-game-calendar, /ensemble-betting)
  docs/             product, architecture, data sources, data model, pipeline runbook, decisions
  data/             NOT in git: raw responses + deepsports.duckdb (about 1 GB+)
```

### Requirements
- macOS or Linux, **Python 3.12**, and [**uv**](https://docs.astral.sh/uv/)
- **Node 22+** and npm, only to build the web app or glasses plugin
- [**Claude Code**](https://claude.com/claude-code), only for the agent features (calendar sync, ensemble betting). Calendar sync also needs the Google Calendar connector enabled on your claude.ai account.

### Setup
All commands run from inside `DeepSports/`.

```bash
cd DeepSports
uv sync                                   # create .venv and install dependencies
uv run pytest -q                          # should pass fully offline
```

**1. Choose where the data lives.** By default the warehouse is written to `DeepSports/data/`, which git ignores. On the owner's Mac, `data` is a symlink to an external drive. To keep the data elsewhere, either symlink it or set environment variables:

```bash
# Option A: symlink to a bigger disk
mkdir -p /path/to/big/disk/DeepSports/data && ln -s /path/to/big/disk/DeepSports/data data

# Option B: environment variables (put them in your shell profile)
export DEEPSPORTS_DATA_DIR=/path/to/DeepSports/data
export DEEPSPORTS_REPORTS_DIR=/path/to/DeepSports/reports   # default points at the owner's external drive
```

**2. Load data.** These commands are polite and resumable. Settled responses are cached, so re-running them is cheap.

```bash
uv run deepsports teams                          # NBA team list
uv run deepsports backfill --season 2025-26      # one full past NBA season (~30 min the first time)
uv run deepsports update                         # recent results + next 14 days of games and odds
uv run deepsports odds-history --with-opening    # fill closing/opening lines for past games
uv run deepsports status                         # row counts + recent runs
uv run deepsports check                          # data-quality checks
```

College basketball uses the same commands with `--league ncaab`. Run `uv run deepsports teams --league ncaab` first. A full college season takes about 2 hours to backfill. See [`docs/PIPELINE.md`](DeepSports/docs/PIPELINE.md).

**3. Predictions and the app.**

```bash
uv run deepsports predict                        # NBA model v1 for upcoming games
uv run deepsports predict --league ncaab         # college model (needs >= 5 games per team)
(cd web && npm install && npm run build)         # build the web app
uv run deepsports serve                          # API + web app on http://localhost:8787
```

Open `http://<your-computer-ip>:8787` on a phone on the same network.

**4. Calendar alerts (optional).** Set the teams you want in `config/calendar.toml`. Then start Claude Code inside `DeepSports/` and run `/sync-game-calendar`. It only touches calendar events tagged with a `deepsports:` key.

**5. Scheduled jobs (optional, macOS).** `tools/launchd/install.sh` installs three launchd agents with this checkout's path filled in:

| Job | When | What |
|---|---|---|
| `com.deepsports.serve` | always on | API + web app on port 8787 |
| `com.deepsports.sync` | 08:00 and 14:00 | `update` + `predict` + paper log, then headless Claude syncs the calendar (and runs the ensemble vote in the afternoon) |
| `com.deepsports.odds` | :15 and :45 every hour | light pregame line capture (`odds-snapshot`) |

```bash
tools/launchd/install.sh            # install all three
tools/launchd/install.sh uninstall  # remove them
```

Logs go to `~/Library/Logs/DeepSports/`. Failure alerts call an optional personal notifier (`~/.claude/tools/notify.py`). Without it the jobs still run, but no alert is sent.

### Working on it with Claude Code
Run `claude` from **inside `DeepSports/`**, not from the repo root, so that its `CLAUDE.md`, agents, and skills load. Project rules are in [`DeepSports/CLAUDE.md`](DeepSports/CLAUDE.md) and [`DeepSports/AGENTS.md`](DeepSports/AGENTS.md). The most important ones:
- Only one process writes to the DuckDB warehouse at a time, so don't run jobs in parallel.
- Run `uv run ruff format src tests && uv run ruff check src tests && uv run pytest -q` before committing.

### History
DeepSports started as its own repo (`JaeminBBQ/DeepSports`) and was moved into this repo on 2026-11-07. Its earlier git history isn't included here. The owner keeps it as a git bundle.
