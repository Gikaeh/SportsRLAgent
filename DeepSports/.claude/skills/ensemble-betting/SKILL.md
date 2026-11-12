---
name: ensemble-betting
description: Ask N independent bettor subagents which upcoming games (default next 3 days, NBA + college) to bet and on what, then report what a majority agrees on. Watch-only, graded later. Use when the user asks for ensemble betting, an agent vote on bets, or `/ensemble-betting [N agents] [days]`.
---

# Ensemble betting (watch-only)

## Prefetched mode (scheduled runs)
If invoked as `/ensemble-betting prefetched <dir> <N>`, `tools/ensemble-daily.sh` has already built the
slate and copied the context files into `<dir>`. **Don't run any `deepsports` command** (the
headless sandbox can't open the warehouse). Do only this:
1. The context files are `<dir>/context-a01.md` … `<dir>/context-aNN.md` (two digits, N files).
   Don't read them yourself.
2. Launch one `bettor` agent per file, **all in one message**, with exactly step 2's prompt below.
3. When all have finished, Write each reply verbatim to `<dir>/picks-aNN.json`. Never fix, trim or
   merge a reply, even one with two JSON objects or a bad pick: the tally parses the last answer and
   drops invalid picks itself, and its problems list is how we see bettor mistakes.
4. Final message: one line, e.g. `ensemble: 10 of 10 replies saved`. The script tallies and posts
   the result to Discord itself.

Goal: N bettors decide **independently** from the same facts; we report the picks a strict
majority (more than N/2) agree on. Nothing is bet for real. Every run is kept and graded later.

Arguments (all optional): number of agents (default 5), days (default 3), league (`nba`, `ncaab`,
default both), model (default sonnet; the user may ask for opus/haiku or a mix).

## 1. Build the slate (ManualBets + Odds API, then the warehouse read-only)
Bettors decide from all of the repo's tools, so first export ManualBets' view (its models, Kelly picks,
best Odds API prices; 2 credits, +3 for college once teams have 5 games). The NBA half runs on the
Raspberry Pi (nba.com blocks this Mac's VPN):
```bash
uv run python tools/manualbets-export.py --out .sync/manualbets-export.json
uv run deepsports ensemble-bets context --agents N --days D [--league nba|ncaab] \
  --manualbets .sync/manualbets-export.json   # or --manualbets none if the export failed
```
Report the export's `odds_api_remaining`.
It prints JSON: the run directory, the number of bettable games, and one context file per agent
(`context-a01.md` …, same facts, games shuffled differently). Games tipping within 60 minutes
are left out. If `games` is 0, stop and tell the user (lines usually post about a day ahead).
The command reads the warehouse; if it reports the DuckDB lock is held, wait a minute and retry.

## 2. Launch the bettors: all at once, in ONE message
For each agent name, call the Agent tool with `subagent_type: "bettor"` (and `model` if the user
asked for one), all in the same message so none can see another's output. Prompt:

> Your context file is `<absolute path to context-aNN.md>`. Read only that file and reply with
> the JSON it asks for.

Do not add hints, opinions, or anything about other agents. Same prompt shape for every agent.
If the `bettor` type isn't available (agent types load at session start), use
`subagent_type: "general-purpose"`, `model: "sonnet"`, and paste the body of
`.claude/agents/bettor.md` into the prompt (with the file path filled in). Same text for every agent.
Bettors may research (read API via `curl -s http://localhost:8787/...`, ManualBets files, the web) but
never open other bettors' picks or earlier runs; the scheduled run enforces that with permission rules
(`tools/ensemble-daily.sh`).

## 3. Save each reply, then tally
When all bettors have finished, write each agent's final reply verbatim to
`<run>/picks-aNN.json` (Write tool). Then:
```bash
uv run deepsports ensemble-bets tally <run>
```
The tally takes the line and price from the slate (never from the agent), drops invalid picks
and picks on games that have already tipped, and writes `tally.md` + `tally.json`. A run is
tallied once; later calls return the saved tally.

## 4. Report
Phone-readable summary:
- The majority picks: bet, price, game and time (PT), votes (e.g. 4/5), and one line on why.
- Picks that came close (e.g. 2/5), and any game where agents split on both sides.
- Remind the user this is watch-only. The project's models have not beaten the closing line,
  and agreement among bettors that read the same facts is not evidence of an edge.
- The run directory.

## Improving the context
The context is the lever: bettors decide only from what their file says. When changing the brief or
the facts (`src/deepsports/analysis/ensemble_bets.py`), bump `CONTEXT_VERSION`, log the change in DECISIONS.md, and
compare versions with `grade`'s `by_context_version`. Ideas are in ROADMAP (Betting research).

## Grading (any time later)
```bash
uv run deepsports ensemble-bets grade
```
Grades every tallied run's majority picks (1 unit each) and every agent's own picks against
final scores: record, units, ROI. Report it when the user asks how the ensemble is doing.
