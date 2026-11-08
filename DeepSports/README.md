# DeepSports

Agent-driven sports data collection, analysis, and prediction. Phase 1 is the NBA:
live scores on your phone (and soon your G2 glasses),
a data pipeline that keeps a local warehouse of games, box scores, and betting lines,
plus a Claude Code agent that puts upcoming games on your Google Calendar.

![Architecture](docs/diagrams/architecture.svg)

## Quickstart
```bash
uv sync                                   # install (Python 3.12, uv)
uv run deepsports update                  # last 3 days of results + next 14 days of games/odds
uv run deepsports backfill --season 2025-26   # a full past season (~10 min, cached after)
uv run deepsports upcoming --teams GS,LAL # what's coming up
uv run deepsports status                  # row counts + recent ingest runs
uv run deepsports check                   # data-quality checks
(cd web && npm install && npm run build)  # build the mobile web app
uv run deepsports serve                   # API + web app on http://<mac-ip>:8787
uv run pytest                             # tests (offline, fixture-based)
```
Calendar notifications: set `teams` in `config/calendar.toml`, then ask Claude to run
`/sync-game-calendar`.

## Docs
| Doc | What's in it |
|---|---|
| [docs/HANDOFF.md](docs/HANDOFF.md) | **Start here:** what's running, current state, next steps |
| [docs/PRODUCT.md](docs/PRODUCT.md) | Goals, scope, phases, non-goals |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, data flow, agent layer, constraints |
| [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) | ESPN endpoints, rate limits, what didn't work |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Warehouse tables and columns |
| [docs/PIPELINE.md](docs/PIPELINE.md) | How to run, storage, cache rules, scheduling, troubleshooting |
| [docs/API.md](docs/API.md) | Read API contract for the web app and glasses |
| [docs/research/even-realities-g2.md](docs/research/even-realities-g2.md) | G2 glasses developer platform research |
| [docs/research/fundamental-data-sources.md](docs/research/fundamental-data-sources.md) | Which fundamental/news data is worth adding (and what to skip) |
| [docs/research/sportsrlagent-review.md](docs/research/sportsrlagent-review.md) | Lessons from a friend's betting project (what to adopt and avoid) |
| [web/README.md](web/README.md) | Mobile web app |
| [docs/ROADMAP.md](docs/ROADMAP.md) | What's next |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Decision log |
| [CLAUDE.md](CLAUDE.md) | Working rules for Claude in this repo |
