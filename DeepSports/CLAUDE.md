# DeepSports

Repo-wide rules (non-negotiables, git, agents, context hygiene, diagram conventions) are in
`../AGENTS.md`. This file adds only what is specific to DeepSports. Coordination, owned paths
and the tools registry: @AGENTS.md

DeepSports is the NBA + NCAA men's D1 data warehouse, frozen prediction models, read API, phone
web app, glasses plugin, calendar alerts and watch-only betting research, running on the owner's Mac.

## Read first
1. `docs/HANDOFF.md`: what's running, current state, next steps.
2. The open items in `docs/ROADMAP.md`.
Everything else on demand, through the doc index in `README.md`.

## Rules
- **Architecture diagram stays current.** A change that adds, removes, renames or rewires a
  component (module, table, data source, agent/skill, external service) updates
  `docs/diagrams/architecture.mmd`, re-renders it (`tools/diagram.sh`) and updates
  `docs/ARCHITECTURE.md` in the same change.
- **Schema changes** update `src/deepsports/store.py`, `docs/DATA_MODEL.md` and tests together.
- **Polite sourcing:** rate-limit (`PoliteClient`, ≥1 s between requests) and cache every
  response. Prefer public APIs. Browser automation or browser-like headers only after the owner
  agrees, with the same limits, recorded in `docs/DATA_SOURCES.md`.
- **Parsers stay pure** and are tested against real saved responses in `tests/fixtures/`.
- **One DuckDB writer at a time.** Never run `deepsports` jobs in parallel; scheduled launchd
  jobs own the warehouse. Even a read-only open fails while a writer holds the lock.
- **External drive:** `data/` → `/Volumes/ExFATStorag/DeepSports/data`; anything big (models,
  exports, caches, reports) goes under `/Volumes/ExFATStorag/DeepSports/`, never the internal
  disk. launchd scripts touch the drive only through `uv run python` (only uv's Python has the
  macOS "Removable Volumes" permission).
- **Calendar:** only touch events whose description has a `deepsports:` key; never bulk-create
  every game unless asked. Use `/sync-game-calendar`.
- **Finish line** for a code change:
  `uv run ruff format src tests && uv run ruff check src tests && uv run pytest -q`.

## Key commands
```bash
uv run deepsports update      # recent results + next 14 days (writer)
uv run deepsports status      # row counts + recent runs
uv run deepsports check       # data-quality checks
tools/diagram.sh              # render docs/diagrams/*.mmd -> .svg
```
Full CLI, storage, scheduling and troubleshooting: `docs/PIPELINE.md`.

Serena MCP is configured in `.mcp.json` but disabled locally; use Grep/Read.
