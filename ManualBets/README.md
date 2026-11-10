# ManualBets

A handmade basketball betting recommendation pipeline (NBA + NCAA men's D1). It fetches game
data and odds, trains one XGBoost model per bet type (moneyline/h2h, spread, total), compares
the model's probability with the devigged market price, and suggests Kelly-sized stakes. Bets
and their results are kept in append-only CSV logs at `../logs/`.

> **You place every real bet.** The tool only prints suggestions; it never places or transmits
> wagers.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+. Works the same on macOS and Windows.
Run everything from this folder:

```bash
uv sync                                   # create .venv and install dependencies
uv run pytest -q                          # verify (2 known failures, see AGENTS.md)
uv run python basketball/main.py          # NBA menu
uv run python college_basketball/main.py  # college menu
```

Odds come from The Odds API, which needs a key and has a limited monthly quota.

A fresh clone has no trained models or data. For the NBA, run the `basketball/initial_*_setup.py`
backfills, then **Model Retraining** from the menu. College basketball needs the DeepSports
warehouse (`../DeepSports/data/deepsports.duckdb`, or set `COLLEGE_WAREHOUSE_DB`).

## The menus

Enter a number to run one task, or one number above the highest option to run them all.

- **NBA:** Betting Recommendations (fetch odds and data, predict, print suggestions and log
  them), Betting Update (grade settled bets, update the bankroll), Active Bets, Model Retraining.
- **College:** Retrain models, Show predictions, Show recommendations (uses 3 Odds API
  credits; prints only, logs nothing).

## More

- `AGENTS.md`: commands, data flow, file map and rules for working on the code.
- `docs/SESSION-LOG.md`: current state and next steps. `docs/PROJECT.md`: goal and scope.
- `docs/DECISIONS.md`: why things are the way they are.
- Repo overview and the DeepSports project: `../README.md`.
