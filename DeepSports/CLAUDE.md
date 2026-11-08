# DeepSports

Agent-driven sports data collection, analysis, and prediction. Phase 1: NBA data pipeline +
Google Calendar game notifications. Start with docs/HANDOFF.md (current state), then README.md;
details live in docs/.

You are the **orchestrator**: plan, delegate to the specialist subagents, create reusable
agents/skills/tools when useful, verify, and report. Full guide:
@AGENTS.md

## Source of truth
- `docs/PRODUCT.md`: goals, phases, non-goals, open questions
- `docs/ARCHITECTURE.md` + `docs/diagrams/architecture.mmd`: components and data flow
- `docs/DATA_SOURCES.md`: endpoints, odds conventions, what's blocked
- `docs/DATA_MODEL.md`: warehouse tables (must match `src/deepsports/store.py`)
- `docs/PIPELINE.md`: commands, cache rules, troubleshooting
- `docs/ROADMAP.md`: checklist of what's next; tick items as they land
- `docs/DECISIONS.md`: append-only decision log; add an entry for any non-obvious choice

## Rules
- **Architecture diagram stays current.** Any change that adds, removes, renames, or rewires a
  component (module, table, data source, agent/skill, external service) updates
  `docs/diagrams/architecture.mmd`, re-renders it with `tools/diagram.sh`, and updates
  ARCHITECTURE.md in the same change. Mention the diagram update to the user.
- **Schema changes** update `store.py`, `docs/DATA_MODEL.md`, and tests together.
- **Data sources:** be polite: rate-limit (`PoliteClient`, ≥1 req/s by default) and cache responses.
  Prefer public APIs. If a source blocks plain HTTP clients, browser automation (Playwright/Selenium)
  or browser-like headers are allowed. Propose it to the owner first, keep the same rate limits, and
  record the method in DATA_SOURCES.md.
- **Parsers stay pure** and are tested against real saved responses in `tests/fixtures/`.
- **One DuckDB writer at a time.** Don't run deepsports jobs in parallel.
- **Large files go on the external drive.** `data/` → `/Volumes/ExFATStorag/DeepSports/data`. Anything
  big that's added later (model artifacts, exports, caches) goes under `/Volumes/ExFATStorag/DeepSports/`,
  never on the internal disk (~14 GB free).
- **Calendar:** only touch events whose description contains a `deepsports:` key. Never bulk-create
  every game unless the user asked for that. Use the `/sync-game-calendar` skill.
- Before finishing a code change: `uv run ruff format src tests && uv run ruff check src tests && uv run pytest -q`.
- Don't commit or push unless asked.

## Commands
```bash
uv run deepsports update | backfill --season 2025-26 | upcoming --json | status
uv run pytest -q
tools/diagram.sh                      # render docs/diagrams/*.mmd -> .svg
```

## Code navigation: Serena (MCP)
Registered in `.mcp.json` (pinned v2.1.0, config `.serena/project.yml`). Prefer it over
grep/reading whole files for anything symbol-related:
- `get_symbols_overview` on a file before reading it
- `find_symbol` to locate a definition (`include_body` only when you need the code)
- `find_referencing_symbols` before changing a signature
- `find_implementations` / `find_declaration` to move between interfaces and concrete code
- `rename_symbol` for renames across the codebase
Use Grep for plain text (strings, config keys, comments).

## Diagrams: Mermaid
- Sources in `docs/diagrams/*.mmd`; `tools/diagram.sh [file]` renders an SVG next to the source (`FORMAT=png` for PNG).
- When explaining architecture, data flow, or a non-trivial change, draw it and give the user the SVG path.
- Prefer `flowchart TB` with subgraphs per layer; wide LR layouts become unreadable.
- A render failure means invalid Mermaid syntax; fix it and re-run.
