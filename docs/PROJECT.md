# PROJECT.md

## Goal

A personal sports-betting recommendation system: XGBoost models predict NHL/NBA
game outcomes (moneyline/h2h, spread, total); a Kelly-criterion recommender converts
predictions + live odds into bet suggestions sized against a small real bankroll;
every suggestion and its outcome is graded in append-only CSV logs. The human places
every bet manually. MLB is planned next, mirroring the existing per-sport layout.

Long-term direction lives in `basketball/nba_betting_project_roadmap.md` (pure ML →
market intelligence → live betting) and `baseball/mlb_betting_project_roadmap.md`
(ML baseline first, RL injury-adaptation only after a profitable baseline).

## Current milestone

**M1 — Secrets cleanup** (see `docs/SESSION-LOG.md` Next item):

Success criteria:
- No API key or credential literal anywhere in tracked source.
- All three `odd_scraping.py` files read the Odds API key from an environment
  variable (documented injection method in AGENTS.md).
- Daily menus still run end-to-end with the key injected via env var.
- pytest green.

## Out of scope (until explicitly re-decided)

- Automated or agent-driven bet placement of any kind (non-negotiable #1).
- Production infrastructure from the roadmaps' Phase 5 (Postgres, Redis, Docker,
  alerting) — the solo CSV/venv stack stays until volume demands otherwise.
- RL injury-adaptation layer before each sport's ML baseline shows positive ROI.
- New sports beyond baseball; new bet types beyond h2h/spread/total.
- Refactoring camelCase method names to PEP-8 style repo-wide.

## Constraints

- Solo owner, part-time; daily-use tool during NBA/NHL season.
- Free data sources preferred; The Odds API is the only paid/quota-limited service.
- Real bankroll starts at $40 — sizing conservatism in `betting_config.py` is
  intentional, not a bug to "fix".
- Data sources are free/unofficial APIs that may break without notice; treat fetcher
  failures as data-source changes and escalate (AGENTS.md escalation rules).
