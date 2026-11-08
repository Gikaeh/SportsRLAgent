# Product

## What DeepSports is
A personal, agent-driven sports analytics system. Claude Code agents collect data, keep it
fresh, analyze it, make predictions, and notify the owner about upcoming games through
Google Calendar (with Discord for agent status).

## Goals
1. **Never miss a game that matters.** Upcoming games for followed teams appear on Google
   Calendar with time, TV, and the current line, and update when anything changes.
2. **A trustworthy dataset.** A complete, reproducible, locally stored history of games,
   box scores, and betting lines, refreshed automatically.
3. **Predictions worth reading.** Game predictions (winner, margin, total) that are measured
   honestly against the betting market's closing line, not just against coin flips.
4. **Scores and stats at a glance.** Semi-live scores (refreshed every ~30–60s during games)
   and box scores, readable on a **mobile web app** and on **Even Realities smart glasses**
   while doing other things.
5. **Visible system.** An always-current architecture diagram and docs, so both the owner and
   future agents can understand the repo quickly.

## Scope by phase
| Phase | Sport | Focus |
|---|---|---|
| 1 (now) | NBA | Data collection pipeline + calendar notifications |
| 2 | NBA | Live scores + mobile web app (scores, box scores, standings) |
| 3 | NBA | Even Realities glasses app: glanceable live scores for followed teams |
| 4 | NBA | Exploratory analysis, team ratings, feature engineering |
| 5 | NBA | Prediction models, backtests, predictions in calendar events and apps |
| 6 | NHL, NFL | Reuse the pipeline pattern with new sources and parsers |

## The owner
New to sports and mainly interested in **keeping score and following stats**, not betting.
Teams are followed for convenience (initially chosen by Claude: Lakers, Clippers, Warriors (local)
and Celtics (famous)). Interfaces should explain context briefly (what a stat means, why a game matters)
rather than assume fan knowledge.

Season context (Nov 2026): the NBA (2026-27), NHL, and NFL are all in season.

## Non-goals (for now)
- Placing bets or any automated wagering.
- Live, in-game predictions (data is refreshed in batches, not streamed).
- A public product or multi-user features.
- Scraping that ignores a site's blocking or terms (see DATA_SOURCES.md).

## Open questions
- Keep the initial followed teams, or change them once preferences form?
- ~~Where does the web app run?~~ Decided: on this Mac, reachable remotely through the owner's network.
- ~~Even Realities model and developer path?~~ Decided: G2, an Even Hub plugin (works, private build).
- How often should the calendar sync run, and from where (this Mac or the cloud)?
- How many past seasons of history to backfill for modeling (proposal: 2021-22 onward)?
