# SportsRLAgent

A **sports betting recommendation system** for the NHL and NBA (MLB is planned).
It fires up to date with free data-fetching APIs, trains **XGBoost** models to
predict game outcomes, and turns those predictions into bet suggestions using the
**Kelly criterion**. Results are graded and stored in append-only CSV bet logs.

> **You (a human) place every real bet.** This tool only produces
> recommendations. It never places, automates, or transmits wagers.

---

## What it does

For each enabled sport the system has one pipeline, mirrored across `hockey/` and
`basketball/`:

1. **Fetch** — pull game/team/player data (free NBA/NHL APIs) and odds (The Odds API).
2. **Build features** — team rolling stats, schedule/rest info, player aggregates.
   Features are strictly computable at prediction time (no post-game / season-end
   info; **time-based splits only** — no data leakage).
3. **Predict** — one XGBoost model per bet type (moneyline/h2h, spread, total)
   stored in `models/`.
4. **Recommend** — a Kelly-criterion recommender compares model probability to the
   (devigged) market price and suggests a stake, gated by configured thresholds.
5. **Grade** — results are written to `logs/<sport>/betting/*_bets.csv` and updated
   as games finish. Bet logs are immutable history.

Read `AGENTS.md` first — it is the operational constitution (non-negotiables,
commands, conventions).

---

## Repository layout

```
hockey/  basketball/   baseball/   one dir per sport, identical internal structure
  ├─ main.py                     interactive CLI entry point
  ├─ data_pipeline/              fetching + feature prep (incl. odd_scraping.py)
  ├─ model/                      training/retraining per bet type
  ├─ betting/                    betting_config.py (thresholds) + betting_recommender.py
  └─ initial_*_setup.py          one-time historical backfills
shared/          base fetchers / preparers — new shared logic goes here
data/<sport>/    game_data, team_data, player_data, cache, odds_data, ...
models/          trained XGBoost JSONs + models/metadata/ (retrain timestamps)
logs/<sport>/betting/  *_bets.csv bet journals (IMMUTABLE, see rules)
tests/           pytest smoke + regression tests
docs/            PROJECT.md, DECISIONS.md, SESSION-LOG.md (+ -ARCHIVE.md)
```

---

## Requirements

- **Python 3.12**
- **uv** for environment management
- An **Odds API** key (required for odds; see *Secrets* below)

## Setup

```powershell
# 1. Create the environment + install dependencies
uv venv
uv pip install -r requirements.txt

# 2. Verify it runs
.venv\Scripts\python.exe -m pytest tests/ -v
```

> Windows note: always use `.venv\Scripts\python.exe` (not `.venv/bin/python`).

### First-time run (per sport)

Fresh clones have no trained models or cached data. Bring a sport up in order:

1. **Fetch historical data** for the seasons you want, via the sport's
   `initial_*_setup.py` scripts (e.g. `basketball/initial_h2h_setup.py`,
   `initial_spread_setup.py`, `initial_total_setup.py`).
2. **Retrain models** (see *Model Retraining* below) so the saved models match the
   current feature semantics.
3. **Fetch today's odds/data** via the recommendations flow.

---

## Running

Each sport has its own interactive CLI. Start it from the repo root:

```powershell
# NHL
.venv\Scripts\python.exe hockey/main.py

# NBA
.venv\Scripts\python.exe basketball/main.py
```

You get a numbered menu. Enter one number to run a single task, **or enter one
number above the highest listed option to run every task in sequence**.

```text
============================
NBA BETTING SYSTEM
============================
Choose an option to run:

1. Betting Recommendations
2. Betting Update
3. Active Bets
4. Model Retraining

0. Exit
```

### 1. Betting Recommendations

Fetches odds/data for today's games, predicts, and prints suggestions. You choose
a market:

- **H2H / Moneyline** — who wins outright.
- **Spread** — margin of victory against a line.
- **Total** — over/under points (total models may be disabled for a sport).

The recommender only outputs suggestions with a sufficiently positive edge and
an implied prob/price your Kelly stake passes.

### 2. Betting Update

Refreshes the current season's results, then grades any bets that have settled
against the actual outcomes and updates the bankroll. Optionally archives the
season to the log archive.

### 3. Active Bets

Shows currently open/pending bets and their status.

### 4. Model Retraining

Checks each saved model and retrains it if its training data has gone stale.
Should run after a data backfill or a feature change.

### Outputs

- **Recommendations** — printed to the console only.
- **Bet journal** — each recommendation/grade is appended to
  `logs/<sport>/betting/*_bets.csv`. Never edit or delete past rows; correct
  errors by appending a correcting row or an explanatory commit.

---

## Secrets

Odds come from The Odds API and require an API key. **Never put the actual key in
commits, logs, or files** — reference it from an environment variable / `.env`
(gitignored) and document only *where* it lives.

> ⚠️ Known debt (see `AGENTS.md` #2 and `docs/SESSION-LOG.md`): the Odds API key is
> currently hardcoded in each sport's `odd_scraping.py` and is already in git
> history. Removing it is an in-progress deliverable, and the key should be rotated.

---

## Tests

```powershell
.venv\Scripts\python.exe -m pytest tests/ -v
```

All tests green before you call anything done (non-negotiable). If any fail, say
explicitly why rather than claiming success.

---

## Guardrails (non-negotiables)

1. **Humans place all bets** — output is recommendations only.
2. **No secrets in code/logs/commits.**
3. **Bet logs are immutable history** — append-only.
4. **No silent data leakage** — features must be computable at prediction time;
   time-based splits only.
5. **Verify before "done"** — run the test suite.

## More info

- `AGENTS.md` — operational constitution, commands, conventions.
- `docs/PROJECT.md`, `docs/DECISIONS.md`, `docs/SESSION-LOG.md` — project plan,
  decision rationale, and session history.
- `basketball/NOTES.md` — basketball audit findings + remediation spec (read it
  before touching basketball code).
- `baseball/` — MLB is planned; currently just standalone scrapers, not wired
  into a model/recommender pipeline yet.
