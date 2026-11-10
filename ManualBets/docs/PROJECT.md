# PROJECT.md: goal, milestone, scope

## Goal

A personal basketball betting recommendation system for the NBA and NCAA men's D1: XGBoost
models predict h2h, spread and total outcomes; a Kelly-criterion recommender turns predictions
and live odds into stake suggestions for a small real bankroll; bets and outcomes are graded in
append-only CSV logs. The owner places every bet by hand. ManualBets and DeepSports will be
merged step by step (`../AGENTS.md`). The old long-term roadmaps are kept for history in
`docs/archive/`.

## Current milestones

**M1: secrets cleanup (open since 2026-08-21, not done).** The Odds API key is still a literal
in the `odd_scraping.py` files and in git history, and it travels in request URLs.
Done when:
- No API key or credential literal is left in tracked source.
- Every `odd_scraping.py` reads the key from an environment variable, and `AGENTS.md` says how
  to set it (never its value).
- The NBA and college menus still run with the key from the environment.
- `uv run pytest -q` shows no new failures.
- Rotating the key is the owners' call (the key is shared).

**Batch 4 hardening** (`basketball/NOTES.md`): A3, A5, C-R3, C3/C4 and the pending B bugs.

Day-to-day order of work: the live entry in `docs/SESSION-LOG.md`.

## Out of scope (until explicitly re-decided)

- Automated or agent-driven bet placement of any kind.
- Hockey and baseball: the code stays but is out of focus (`docs/DECISIONS.md` 2026-11-10).
  Known hockey bug if that work restarts: `hockey/data_pipeline/odd_scraping.py` overwrites
  the "not started yet" filter (see `docs/SESSION-LOG-ARCHIVE.md`).
- Production infrastructure (Postgres, Redis, Docker, alerting): the CSV/uv stack stays until
  volume demands otherwise.
- An RL injury-adaptation layer before the ML baseline shows positive ROI.
- New sports; new bet types beyond h2h/spread/total.
- Renaming camelCase methods to PEP 8 style repo-wide.

## Constraints

- Owner-run, part-time; a daily tool during the basketball season.
- Free data sources preferred. The Odds API is the only paid, quota-limited service.
- Real bankroll: $50 from 2026-11-08 (`basketball/betting/betting_config.py`); college results
  count toward it. Conservative sizing is intentional, not a bug to fix.
- Data sources are free, unofficial APIs that can break without notice: treat a fetcher failure
  as a data-source change and escalate.
