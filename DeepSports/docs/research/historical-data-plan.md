# Historical odds + college data: what to buy and grab (research, 2026-11-19)

**Owner's question:** is it worth paying for an odds API to backtest on older data (fetch once, cache
forever), and what other data, paid or free, would add useful features?

**Answer (owner liked the plan, starts 2026-11-20):** free work first, then one month of The Odds
API's 100K-credit plan ($59), pulled in one go and cancelled. Status markers as in
`fundamental-data-sources.md`: [confirmed] checked on a primary page or with a live call; [vendor] the
provider's own claim; [unconfirmed].

## Why: the et-v1 doubt
et-v1's 56.8% (results/2026-11-15-early-totals-preregistration.md) is an upper bound because the
warehouse's opening lines have no posting time. Timestamped snapshots let us rebuild the board as it
stood at 21:00 the night before on past seasons, run et-v1 exactly as live, and get ~5 seasons of bets
instead of one.

## Our keys today (checked 2026-11-19)
- **The Odds API:** free Starter plan, 500 credits/month (380 left after 3 checks this session). History
  needs a paid plan [confirmed].
- **OddsPapi:** free tier, 250 requests/month, ~90 used by the daily and evening grabs.

## Odds providers compared
| Provider | College history | Cost for a one-off pull | Verdict |
|---|---|---|---|
| **The Odds API** | Featured markets (h2h, spreads, totals) from mid-2020, 5-min snapshots since Sept 2022 [confirmed]. One historical call = every game in a sport at one timestamp, 10 credits per market per region [confirmed] | $30 = 20K credits, $59 = 100K, $119 = 5M (monthly) [confirmed] | **Buy one month** |
| OddsPapi | Depth not published; per-fixture history, max 3 books per call [vendor]. Has Circa + Caesars | Free tier far too small (~6,000 college games a season); paid $99+/mo [vendor, unverified] | Optional probe only (about 2 requests: how far back does Caesars go?) |
| SportsGameOdds | About 1 season [competitor's claim] | History on Pro, ~$299/mo [vendor, conflicting] | No |
| OpticOdds | "Several years" [vendor], no college detail | Enterprise sales | No |
| Odds-API.io, odds-api.net | 30-365 days | Base plan + history add-on | No, too shallow |
| TheOddsAPI.com, TheOddsGap, BALLDONTLIE | Start 2025-26 or 2026 | | No, too recent |
| BigDataBall spreadsheets | Many seasons, open/close only | Paid | No, ESPN gives the same free |

**Books in The Odds API's college feed (live calls, 2026-11-19, totals):**
- `us`: DraftKings, FanDuel, BetMGM, BetRivers, Bovada, BetOnline, LowVig, BetUS. **No Caesars.**
- `eu`: **Pinnacle** (13 of 29 games mid-afternoon), William Hill UK, 1xBet, Unibet, 888, GTbets.

So the backtest uses DraftKings and Pinnacle at 21:00 as stand-ins for the Caesars line; the live et-v1
test stays the Caesars check.

## Credit budget
- College totals, `us`, 5 seasons (2021-22 → 2025-26; skip COVID 2020-21) x ~150 days x 2 snapshots
  (21:00 PT night before + morning) ≈ 15K.
- Adding `eu` (Pinnacle) doubles it to ≈ 30K, already over the $30 plan. Spreads and NBA bring the total to
  ≈ 50K, and extra snapshot times (to see when night-before lines post) need room too. **Hence $59,
  not $30:** buying Pinnacle later would mean a second paid month.
- On day one, spend ~100 credits probing night-before coverage before the bulk pull. Cache every
  response (raw zone, like the ESPN cache). The new key goes in `~/.config/deepsports/` (mode 600), never in code.

## Other data, ranked for college totals
| # | Data | Cost | Notes |
|---|---|---|---|
| 1 | ESPN backfill, college 2021-22 + 2022-23 (`deepsports backfill --league ncaab`, then `odds-history --with-opening`) | Free; ~1.8 h + ~1.8 h per season; warehouse writer | Must come before the paid pull so both models have walk-forward numbers for those seasons. Run between scheduled jobs (one-writer rule). Check that ESPN core-API college lines exist for those seasons. |
| 2 | Barttorvik T-Rank daily archive (end-of-day ratings: adjusted offense, defense, **tempo**, barthag, WAB) | Free (cbbdata key) | **Fetched 2026-11-19** from the cbbdata API (`deepsports torvik fetch`; DATA_SOURCES.md, cbbdata): 2014-15 → 2024-25, ~50-84K rows a season [confirmed]. cbbdata has nothing for 2025-26 or 2026-27 [confirmed]; barttorvik.com 403s plain clients and toRvik's GitHub mirror stops in 2023. A row dated D includes D's games, so join on `as_of_date <= D-1` [confirmed vs ESPN dates]. Team map to ESPN ids: `config/torvik_teams.csv` (378 of 379 names). A third model number and tempo features. No published terms. |
| 3 | Unused fields in the ESPN summaries we already cache: officials, `conferenceCompetition`, play-by-play pace / 3PA / FTA rates | Free, offline | The referee-vs-totals test is already on the roadmap. |
| 4 | College arena coordinates (static table) | Free, one-time | `travel_km` is mostly NULL for college; adds travel and altitude. |
| 5 | The Odds API: extra snapshot times in the same month | In the $59 | Line-movement path (open → night before → morning → close); the edge seems to live in timing. |
| 6 | CollegeBasketballData.com (free key) | Free | Says it has lines from several books back to 2013 [vendor]; cross-check ESPN's older lines. Free-tier limits unconfirmed. |
| 7 | KenPom API ($95/yr, archive ratings + FanMatch predictions) | Paid | Only if Barttorvik's archive has gaps; mostly overlaps. |

Skip: sentiment, X, Reddit and news APIs (see `fundamental-data-sources.md`).

## Sources
- The Odds API pricing https://the-odds-api.com/ · history https://the-odds-api.com/historical-odds-data/ · NCAAB https://the-odds-api.com/sports/ncaab-odds.html
- OddsPapi history https://oddspapi.io/blog/?p=2824 · pricing comparison https://oddspapi.io/blog/?p=2498
- SportsGameOdds FAQ https://sportsgameodds.com/docs/faq · review https://sportsapis.dev/apis/sportsgamesodds
- OpticOdds https://opticodds.com/historical-odds · odds-api.net https://odds-api.net/historical-odds-api
- cbbdata API (Barttorvik archive) https://cbbdata.aweatherman.com/ · status issue https://github.com/andreweatherman/cbbdata/issues · toRvik `bart_archive` (GitHub mirror, stops 2023) https://rdrr.io/cran/toRvik/man/bart_archive.html
- KenPom API https://kenpom.com/register-api.php
- cbbd-python https://www.github.com/willscot/cbbd-python
