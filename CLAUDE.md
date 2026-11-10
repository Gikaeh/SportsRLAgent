# SportsRLAgent

Repo-wide rules, agents and the project map:
@AGENTS.md

Claude-specific notes:
- Claude loads `CLAUDE.md` files from the start folder upward, and a subfolder's `CLAUDE.md`
  only when it reads files there. When you work in a project, read its `CLAUDE.md` first
  (`DeepSports/CLAUDE.md`, `ManualBets/CLAUDE.md`).
- A root session doesn't see the agents in `DeepSports/.claude/agents` (bettor, calendar-agent).
  Its skills show up only after you work on files under `DeepSports/`, and they assume that
  folder as the working directory. Run `/ensemble-betting` and `/sync-game-calendar` from a
  session started in `DeepSports/`.
- Diagrams: Mermaid sources in `DeepSports/docs/diagrams/*.mmd`, rendered with
  `DeepSports/tools/diagram.sh [file]`. Prefer `flowchart TB` with one subgraph per layer; draw planned items dashed. When
  explaining architecture or a non-trivial change, draw it and give the owner the SVG path.
