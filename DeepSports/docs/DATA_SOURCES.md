# Data sources

## In use: ESPN public site API (NBA)
Base: `https://site.api.espn.com/apis/site/v2/sports/basketball/nba`. No key required.
It's undocumented and unofficial, so it can change without notice; parser tests run against
saved real responses in `tests/fixtures/` so a format change shows up as a test failure.

| Endpoint | Used for | Notes |
|---|---|---|
| `/teams` | 30 teams, ids, abbreviations | Refreshed on first run or `deepsports teams` |
| `/scoreboard?dates=YYYYMMDD&limit=1000` | Games for one US/Eastern day: status, scores, venue, TV, **pregame odds** | Ranges (`A-B`) return HTTP 400 |
| `/summary?event=<id>` | Team and player box scores, **closing odds** (`pickcenter`), **injuries**, plays, win probability | ~1 MB with plays. Box scores, odds, and injuries are parsed |

### ESPN core API: historical odds
`https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/<id>/competitions/<id>/odds?limit=100`
returns one item per sportsbook with `open`/`close`/`current` blocks and explicit per-side lines
(`homeTeamOdds.close.pointSpread.american`). Used by `deepsports odds-history` to fill gaps.
- **Why it's needed:** the summary's `pickcenter` is empty for 2023-24 and 2024-25 games
  (sampled 2026-11-03), while 2016-2022 and the current season have it.
- **Book choice:** one line per game, chosen in the order DraftKings → ESPN BET → Caesars → FanDuel → BetMGM → the first
  other pregame book. "Live Odds" books are in-game lines and are ignored.
- **Older games** (around 2022) have only flat fields (`spread`, `overUnder`, `moneyLine`), stored as the
  closing line. The flat `spread` is also from the home side.
- **Careful:** `open.total.value` can hold a decimal *price* rather than the total; always read the `american` strings.
- **Prices:** per side, `homeTeamOdds.<open|close>.spread.american` is the spread *price* (the
  line is `pointSpread`), and `<open|close>.over/under.american` are the total prices. The flat
  format has `homeTeamOdds.spreadOdds`, `awayTeamOdds.spreadOdds`, `overOdds`, `underOdds`.

### Known gaps (checked 2026-11-03)
- 8 games from the 2026 playoffs are `STATUS_FINAL` on the scoreboard, but `summary` returns **HTTP 404**, so there's no box score
  (401869391, 401869377, 401869373, 401869402, 401871334, 401871154, 401871337, 401873343). We have their final
  scores; box-score features for them are missing.

- College box scores: 13 of ~12,600 team-games (2025-26 → now) have player points summing to 2 fewer
  or more than the final score in ESPN's own raw data (e.g. 401824356: players 74, score 76). These are reported as known gaps.
- College betting lines are sparser: 91-93% of final games per season have a closing line (2023-24
  93%, 2024-25 92%, 2025-26 91%; the NBA is ~100%). D1-vs-D1 games are ~100% covered (2 or 3 misses a
  season); the gap is games against non-D1 opponents, which mostly have no line (checked 2026-11-05).
- **College closing lines per field (D1-vs-D1, regular + postseason; latest `closing` row; checked
  2026-11-06):**

  | season | games | any closing row | spread | total | moneyline (both sides) | all three |
  |---|---|---|---|---|---|---|
  | 2023-24 | 5,612 | 5,610 | 5,610 | 5,609 | 5,390 | 5,390 |
  | 2024-25 | 5,644 | 5,643 | 5,642 | 5,642 | 5,530 | 5,528 |
  | 2025-26 | 5,633 | 5,630 | 5,588 | 5,616 | 5,394 | 5,366 |
  | 2025-26 Nov 1 – Jan 31 | 3,678 | 3,675 | 3,633 | 3,661 | 3,445 | 3,417 |

  In that 2025-26 Nov–Jan window, 261 games lack a full line: 202 miss only the moneyline (spread and
  total present), 3 have no closing row, the rest miss the spread and/or total (before any sanity
  filter; the analyst's 212 "moneyline only" counted after the spread/total filters).
  **The missing moneylines are upstream, not a parser gap.** In the raw cache, DraftKings' pickcenter
  (and its core-API entry) shows the moneyline as `"OFF"` (`moneyline.home.close.odds = "OFF"`, no flat
  `moneyLine`); 5 games have one side priced and the other `OFF`. Games with no pickcenter fall back to
  the core API's ESPN BET entry, whose `close` block has no `moneyLine` (only `open`). Books take the
  moneyline off big mismatches: 148 of the 228 no-moneyline games had a closing spread over 20 points, 54
  were within 10. **Recoverable:** 61 of those games (46 with spreads within 10) have an ESPN BET closing
  moneyline in the cached core-API response while DraftKings is `OFF`. We don't mix books in one closing
  row today; filling them would be an offline re-parse from cache (no requests) if the owner wants it.
- **College 2023-24 player boxes are incomplete (checked 2026-11-05):** in ~360 team-games ESPN's raw
  box drops a player's line and lists a DNP row without an athlete id (stored as `noid:...`, NULL
  stats), so player points fall short of the team total (e.g. 401579052 SELA: players 67, score 77).
  Team totals and scores are right. 2024-25 has 1 such game. `deepsports check` reports them as
  known gaps (`has_noid`); don't use 2023-24 college player rows for team-level sums.
- **7 college team-games are known points gaps (checked 2026-11-05; `deepsports check` warns on exactly these
  team-games via `quality.KNOWN_POINTS_MISMATCH`, any other mismatch > 2 still fails),** all D1 vs non-D1 games
  where ESPN's own raw box disagrees with the score by more than 2 (e.g. 401597895 JWNC: players 15,
  score 61; 401722338 HAW: players 110, score 96): 401597895, 401597922, 401608976 (2023-24);
  401720664, 401722030, 401722338, 401727325 (2024-25). Upstream; the stored rows match the raw data.

What's available but not parsed yet (it's already in the raw zone for completed games):
play-by-play, win probability, season series, quarter linescores.

### Injuries: only pre-tip snapshots are usable (checked 2026-11-03)
The summary's `injuries` array is each team's **current** injury report at fetch time, not the
report before that game. Evidence from all 7,090 cached completed summaries (2021-22 → now,
fetched 2026-11-03/04):
- In every season before the current one, **100%** of entries have an update `date` more than
  30 days *after* tip-off; they're dated around 2026-10/11.
- The 2021-10-20 BOS @ NY summary lists Devin Carter (in college in 2021) and the same
  Pritchard/Tatum entries, dated 2026-11-03, as the upcoming 2026-11-05 BOS game.
- Players the list marks `Out` usually played: 241/273 (2021-22) up to 2,144/2,443 (2025-26)
  of those in the box score. Only 2/664 injury-type DNPs in 2021-22 were on the list.
So historical injuries would leak future information (and are mostly wrong anyway). They're stored
with `captured_before_tip = false`. Models must use only snapshots taken before tip-off
(`pipeline.collect_injury_snapshots` in `update`, and `deepsports pretip` 5-100 min before NBA tips;
`pregame_injuries` view). Model v1.1i reads only status `Out`. Pre-game summaries are about 17 KB
gzipped; each snapshot is kept in the raw zone under its own timestamp. Fields: `status`
(`Out` / `Day-To-Day`), `date`, `details.type/detail/side/returnDate`; no missing athlete ids seen.

### Odds conventions (verified 2026-11-03)
- Provider: DraftKings (via ESPN).
- `spread` is from the **home team's** side: negative = home favored (`ATL @ WSH`, ATL −1.5 → `spread = 1.5`).
- Moneylines are American odds; the string `"EVEN"` is stored as 100.
- **Spread/total prices (checked 2026-11-06)** are stored as American ints
  (`spread_home_price`, `spread_away_price`, `over_price`, `under_price`):
  - Scoreboard `odds[]`: `pointSpread.home/away.close.{line,odds}` and
    `total.over/under.close.{line,odds}` (`"-111"`). For an upcoming game `close` is the
    current line; `open` is the opening line (not stored from the scoreboard). All 11 NBA games
    with odds on the 2026-11-04 fixture carry all four prices.
  - Summary `pickcenter[0]`: flat `homeTeamOdds.spreadOdds`, `awayTeamOdds.spreadOdds`,
    `overOdds`, `underOdds` (floats like `-105.0`), plus the same `pointSpread`/`total` blocks
    as the scoreboard (used as a fallback). NBA and college identical.
  - Core API: see above. On NEV-UNLV (401829317) the summary and core closing prices agree.
    They don't always: on NBA 401358773 (2021-22) the summary pickcenter is `consensus`
    -1.5 / 234 at -112/-108 while the core API's DraftKings line is -1.5 / 234 at -115/-105.
    So historical prices are backfilled only from the response a row was built from
    (`deepsports prices-backfill`, offline, raw cache only; PIPELINE.md).
  - A price-only move (same line, different juice) counts as a line move and writes a new
    `pregame` row (docs/DECISIONS.md 2026-11-06).

### Etiquette
- At least 1 second between requests (`DEEPSPORTS_MIN_INTERVAL`), backoff on 429/5xx,
  honest User-Agent `DeepSports/0.1 (personal sports research project)`.
- Settled responses are cached forever and never refetched, so backfills are one-time costs.
- An NBA season backfill is ~270 scoreboards + ~1,300 summaries, about 30 minutes.
- A college (D1) season backfill is ~166 scoreboards + ~6,300 summaries (~1.8 h at 1 req/s,
  ~250 MB gzipped raw); `odds-history --league ncaab` is another ~6,300 requests (~1.8 h, ~8 MB).

## In use: ESPN public site API (NCAA men's college basketball)
Same API and JSON shape as the NBA under `.../sports/basketball/mens-college-basketball` (core API:
`.../leagues/mens-college-basketball/...`). Code: `EspnBasketball(client, "ncaab")` in
`src/deepsports/sources/espn.py`; our league key is `ncaab` (raw cache `espn/ncaab/...`, calendar
key `deepsports:ncaab:<id>`). Checked 2026-11-03 with fixtures `tests/fixtures/espn_ncaab_*.json`.

| Endpoint | Notes |
|---|---|
| `/teams?limit=1000` | 362 D1 teams (the default page is 50). Abbreviations are unique within D1. Nevada Wolf Pack = **2440** (`NEV`, Mountain West) |
| `/scoreboard?dates=YYYYMMDD&groups=50&limit=1000` | `groups=50` = all of D1 (without it you get a featured subset). 155 games on Sat 2026-02-07; 29-35 per day in opening week |
| `/summary?event=<id>` | Same box-score keys as the NBA; the parsers work unchanged. ~36 KB gzipped for a final game |
| `/teams/<id>/schedule[?season=2026]` | One team's season (Nevada: 34 games in 2025-26 incl. the MWC tournament). Not used by the pipeline yet |
| core `/events/<id>/competitions/<id>/odds` | Open/close lines like the NBA (one book, `Draft Kings`); empty `items` for some games |

What differs from the NBA:
- **Team ids collide across leagues** (NBA 5 = Cleveland, NCAA 5 = UAB; 25 = OKC / California).
  Every team key is `(league, team_id)` (docs/DATA_MODEL.md). **Event ids don't collide**: NBA and
  NCAA fixture ids are disjoint, and the NCAA summary/core API returns 404 for an NBA event id.
- **Two halves** (`linescores` has 2 entries) instead of quarters. We don't store linescores, so
  nothing changes; box-score totals and the player-points-sum check hold (NEV 89-76 UNLV).
- **Non-D1 opponents** appear on D1 scoreboards (10 of 58 sides on 2026-11-03, e.g. Lincoln (MO))
  but not in `/teams`. They're stored as `teams.listed = false` from the scoreboard so those games
  can be shown.
  `listed` follows ESPN's **current** `/teams` list, not each season's membership: Lindenwood (LIN),
  Queens (QUC), Saint Francis PA (SFPA), and Southern Indiana (USI) play full D1 schedules
  (30-35 games in each of 2023-24 → 2025-26) but are missing from `/teams`, so they're stored as
  `listed = false` and their games count as "non-D1" (checked 2026-11-05).
- **Neutral sites are common** (early-season events, conference and NCAA tournaments:
  Stateline, Palm Springs, Las Vegas). ESPN's home/away is nominal there; titles use "vs".
  `venue_cities` only has NBA cities, so `travel_km` is mostly NULL for college.
- **Odds are sparse:** 3 of 29 scoreboard games had pregame odds on opening night; summaries'
  `pickcenter` and the core API carry DraftKings lines for many games. The provider name is
  `Draft Kings` (with a space); `choose_book` prefers it after `DraftKings`.
  Older seasons differ (checked 2026-11-05): 2023-24 and 2024-25 summaries have **no `pickcenter`**,
  so every line comes from the core API (`odds-history --with-opening`), with opening and closing on
  the same games. The book changes by season: 2023-24 is mostly `DraftKings` (5,326 games) plus
  ESPN BET (368), accuscore (65), and a few others; 2024-25 is only `ESPN BET`; 2025-26 is
  `Draft Kings` (4,805) plus `ESPN BET` (944). Moneylines are missing on ~2-5% of closing rows.
- **Conference flags:** `header.competitions[0].conferenceCompetition` is set (true/false, never
  null) in every 2023-24 → 2025-26 summary, and each competitor's `team.groups` carries the
  conference id/slug (missing on only 2-4 competitor sides per season). Neither is stored in the
  warehouse yet.
- **No injury reports:** college summaries have no `injuries` key at all, so injury snapshots yield
  nothing (they're still taken for followed teams in case ESPN adds them).
- **Season shape:** ~124 game days (Nov → early April; `season_dates` uses Nov 1 → Apr 15).
  About **6,000-6,300 games** per season: 362 teams x ~31-34 games / 2, plus ~700-1,000 games against
  non-D1 schools and ~130 postseason games (NCAA, NIT, CBI). Conference tournaments are season type 2.

## Tried and not used
| Source | Result (2026-11-03) | Decision |
|---|---|---|
| `stats.nba.com` (what `nba_api` uses) | Connection timeout | Not used; it's known to block non-browser and cloud clients |
| `cdn.nba.com` static schedule JSON | HTTP 403 | Not used yet; could be reached with browser automation if needed (allowed since 2026-11-03) |

## Candidates for later
- **NHL:** ESPN `.../sports/hockey/nhl/...` (same shape) or the official `api-web.nhle.com`.
- **NFL:** ESPN `.../sports/football/nfl/...`.
- **Advanced NBA metrics** (pace, ratings): compute ourselves from box scores first. Add a
  licensed source only if needed.
