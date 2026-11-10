# SportsRLAgent

Basketball betting research (NBA + NCAA men's D1) in two projects that are being merged step
by step. Development is mostly done by AI agents: the rules, the project map and the agents
are in [`AGENTS.md`](AGENTS.md).

| Folder | What it is |
|---|---|
| [`DeepSports/`](DeepSports/) | NBA + college data warehouse (DuckDB), frozen prediction models, read API with a phone web app and glasses plugin, Google Calendar game alerts, watch-only paper trading and ensemble vote. |
| [`ManualBets/`](ManualBets/) | Handmade pipeline: XGBoost models per bet type, Kelly-sized bet suggestions, graded CSV bet logs. **You** place the bets. |
| `logs/` | Bet journals (`logs/<sport>/betting/*_bets.csv`), append-only. Written by ManualBets, read by DeepSports. |

Each project has its own `uv` environment; run commands from inside its folder.

## DeepSports quick start

```bash
cd DeepSports
uv sync
uv run pytest -q              # offline, fixture-based
uv run deepsports update      # recent results + upcoming games
uv run deepsports serve       # API + web app on :8787
```

Current state: [`DeepSports/docs/HANDOFF.md`](DeepSports/docs/HANDOFF.md). Commands, data
location and launchd jobs: [`DeepSports/docs/PIPELINE.md`](DeepSports/docs/PIPELINE.md).
No API keys needed.

## ManualBets quick start

```bash
cd ManualBets
uv sync
uv run pytest -q                       # verify
uv run python basketball/main.py       # NBA daily menu
uv run python college_basketball/main.py   # college menu (reads the DeepSports warehouse)
```

Odds come from The Odds API (paid, quota-limited key). Overview:
[`ManualBets/README.md`](ManualBets/README.md).
