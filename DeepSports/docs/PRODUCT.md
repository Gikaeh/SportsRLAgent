# Product

## What DeepSports is
A personal, agent-driven basketball system (NBA + NCAA men's D1) on the owner's Mac. Claude Code
agents collect data, keep it fresh, build and grade predictions, run watch-only betting research,
and keep the owner informed through Google Calendar, a phone web app, G2 glasses and Discord.

It is one of two projects in this repo. The other, ManualBets, is the owner's handmade pipeline:
it suggests bets, the owner places real bets by hand, and the bets are logged in `../logs/`.
The two will be integrated step by step (one data source, one app); see `../AGENTS.md` and
`../docs/DECISIONS.md`.

## Goals
1. **Never miss a game that matters.** Upcoming games for followed teams appear on Google
   Calendar with time, TV and the current line, and update when anything changes.
2. **A trustworthy dataset.** A complete, reproducible, locally stored history of games,
   box scores, betting lines and pre-tip injury reports, refreshed automatically.
3. **Predictions measured honestly.** Win probability, margin and total per game, graded against
   the betting market's closing line, not just against coin flips.
4. **Betting research without real money.** Test betting rules and agent votes forward
   (paper trades, the ensemble vote) and grade them (ROI with confidence intervals, CLV), so any
   claimed edge is measured before anyone acts on it.
5. **Scores and stats at a glance.** Semi-live scores (refreshed every ~10–60 s during games),
   box scores, the owner's open bets and model context on the **phone web app** and the
   **Even Realities G2 glasses**.
6. **Visible system.** An always-current architecture diagram and docs, so the owner and future
   agents can understand the project quickly.

## Scope
Basketball only: the NBA and NCAA men's Division I. What is built and what is open is in
[ROADMAP.md](ROADMAP.md).

## The owner
Follows the games for stats and for betting; places real bets by hand through ManualBets.
Followed teams: Lakers, Clippers, Warriors, Celtics, and Nevada (college); see
`config/calendar.toml`. Interfaces explain context briefly (what a stat means, why a game matters)
rather than assume fan knowledge.

## Non-goals (for now)
- Placing bets or any automated wagering (DeepSports output is context and watch-only records).
- Live, in-game predictions (data is refreshed in batches, not streamed).
- A public product or multi-user features.
- Scraping that ignores a site's blocking or terms (see DATA_SOURCES.md).

## Open questions
- Keep the current followed teams, or change them as preferences form?
- Pay for a multi-sportsbook odds API (the-odds-api.com) for DeepSports?
- ~~Where does the web app run?~~ Decided: on this Mac, reachable remotely through the owner's network.
- ~~Even Realities model and developer path?~~ Decided: G2, an Even Hub plugin (works, private build).
- ~~How often should the calendar sync run, and from where?~~ Decided: 08:00 and 14:00 on this Mac (launchd).
- ~~How much history to backfill?~~ Decided: NBA 2021-22 onward, college 2023-24 onward.
