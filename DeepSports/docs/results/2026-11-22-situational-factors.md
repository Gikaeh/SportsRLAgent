# Situational factors and et-v1 college totals (2026-11-22)

**Question.** Do situational factors (tip time, body clock, travel, time zones, rest, altitude,
neutral site) explain which et-v1 picks win, or where the models or the market miss college totals?

**Answer. No factor explains et-v1 wins.** Across 27 factor buckets, none moved et-v1's (or the
wider edge >= 2 set's) win % at the opener in a way that held out of sample. Two things did hold, and
both are about the totals themselves, not about et-v1:
1. **Altitude.** At venues >= 1200 m, games score more than both models (+1.7 pts vs other games in
   discovery, +1.6 in holdout) and more than the closing total (+1.4 / +1.7). The effect grows with
   elevation (1200-1500 m: +1.6 vs close; 1500 m+: +3.0, over hits 58.1% vs the close, n = 576) and survives
   dropping any one city. It's the only candidate for a new model feature.
2. **Openers run high in neutral-site, short-rest and tournament games.** The total drops from open to close
   by 0.5-1.6 pts more than in other games (neutral site, 2nd/3rd game of a neutral event, min rest <= 1,
   3+ games in 7 days, Feast Week, destination events). This held in both holdout seasons. The close
   only partly corrects it, and it doesn't change et-v1's win % on either side.

Time of day, early or late body clock, travel distance, time zones crossed (east or west), weekend and
rest mismatch: nothing held.

## Data and coverage
- Games: 26,743 college games 2021-22 → 2025-26 that have walk-forward DS and MB totals and a closing total
  (the same inputs as `2026-11-20-college-walkforward-older-seasons.md`). Openers are in 2023-24 → 2025-26 only (16,867 games).
- Splits by season only: **discovery** = 2021-22 → 2023-24 (openers: 2023-24 only), **holdout** = 2024-25 and 2025-26.
- Venue city and state come from the cached ESPN scoreboard responses already on disk
  (`data/raw/espn/ncaab/scoreboard`, 33,512 events, all games matched). No network.
- `team_game_context.travel_km` covers only ~7% of college rows (`venue_cities` holds 36 NBA
  cities), so it isn't used. Team home = the team's most common non-neutral home venue (368 teams).
  Time zone comes from state, with city overrides where a state spans two zones. Distance uses state
  centroids plus about 40 city coordinates, so it's coarse (good for 1000/2000 km buckets). Elevation is a
  hand list of about 25 venue cities >= 800 m. These are static, hand-entered tables kept in the research
  folder, not a new source. The ROADMAP item "College arena coordinates" would replace them.
- Scripts and outputs: `/Volumes/ExFATStorag/DeepSports/work/factors-2026-11-22/situational/`
  (`extract_venues.py`, `geo.py`, `build.py`, `analyze.py`/`.out`, `followup.py`/`.out`, `altitude.py`/`.out`, `live.py`/`.out`).

## Method
- Every factor uses the schedule, venue and earlier games only (known before tip). Each bucket is compared with
  the rest of the games. Differences come with day-clustered (CR1) standard errors.
- Outcomes: model miss (actual - average of DS and MB), market miss (actual - close), open→close move,
  et-v1 win % at the opener (both edges > 0, average >= 4), edge >= 2 win % at the opener.
- Multiple comparisons: 134 discovery tests (27 buckets x 5 outcomes, minus one with n < 15), Benjamini-Hochberg
  at q = 0.10 (Bonferroni cut p < 0.00037). "Held" = BH survivor in discovery, then the same sign with p < 0.05 in holdout.
  The follow-ups (by side, by city, by elevation band) add about 15 more looks and are descriptive.

## Results: difference vs the rest of the games (95% CI); discovery | holdout
Win % rows are et-v1 at the opener (discovery = 2023-24 only). Points elsewhere. Full tables are in `analyze.out`.

| factor (n disc / hold, all games) | model miss | market miss (vs close) | open→close move | et-v1 win % (n disc / hold) | held? |
|---|---|---|---|---|---|
| tip local < 13:00 (868 / 711) | +0.5 (-0.6,+1.6) \| -0.3 (-1.6,+0.9) | +0.3 \| -0.5 | -0.2 \| -0.1 | +1.9 (79) \| -1.3 (196) | no |
| tip local >= 20:00 (1574 / 1054) | +0.3 (-0.6,+1.2) \| +0.0 (-1.2,+1.3) | +0.2 \| -0.4 | -0.2 \| +0.1 | +7.3 (113) \| +1.9 (257) | no |
| a team's body clock < 12:00 (403 / 307) | +0.4 (-1.3,+2.2) \| +0.3 (-1.3,+2.0) | +0.4 \| +0.5 | -0.2 \| -0.4 | -4.0 (39) \| +1.2 (92) | no |
| a team's body clock >= 22:00 (125 / 129) | -0.2 (-3.3,+2.9) \| -0.1 (-2.7,+2.5) | 0.0 \| -0.8 | +0.2 \| +0.1 | n<15 \| -6.0 (31) | no |
| weekend (6513 / 4773) | +0.4 \| +0.1 | +0.4 \| +0.3 | 0.0 \| 0.0 | **-7.7 (-13.0,-2.4)** (561) \| +0.9 (1215) | no (BH in disc, flat in holdout) |
| Feast Week Nov 20-Dec 1 (1157 / 1079) | -0.9 \| -1.1 | -0.1 \| -1.1 | **-0.4 \| -0.5** | +5.1 (147) \| -2.3 (394) | move only |
| a team traveled >= 2000 km (1083 / 1090) | **-1.4 (-2.4,-0.4)** \| -0.4 (-1.4,+0.6) | -0.9 \| -0.5 | +0.1 \| 0.0 | +4.2 (142) \| +1.9 (327) | no |
| a team >= 2 zones from home (883 / 954) | -1.1 (-2.3,+0.2) \| +0.5 (-0.6,+1.6) | -1.0 \| +0.1 | -0.1 \| -0.1 | +1.2 (123) \| 0.0 (280) | no |
| a team 2+ zones east (351 / 376) | **-2.4 (-4.1,-0.6)** \| -0.8 (-2.5,+0.8) | -2.0 \| -0.9 | -0.5 \| -0.1 | -7.0 (48) \| -2.2 (92) | no |
| a team 2+ zones west (533 / 579) | -0.2 (-1.9,+1.5) \| +1.4 (0.0,+2.8) | -0.3 \| +0.7 | +0.1 \| 0.0 | +6.4 (75) \| +1.1 (188) | no |
| neutral event, 2nd+ game (935 / 682) | **-1.3 (-2.3,-0.4)** \| -0.4 (-1.8,+1.1) | -1.0 \| -0.4 | **-1.0 \| -0.6** | +1.5 (113) \| +1.2 (224) | move only |
| neutral event, 3rd+ game (246 / 165) | **-2.7 (-4.5,-0.8)** \| +0.8 (-2.0,+3.5) | -1.4 \| +1.2 | **-1.6 \| -0.8** | -2.7 (30) \| +5.8 (55) | move only |
| destination site: HI, Caribbean, Mexico, Europe (233 / 168) | -1.9 \| +1.8 | -1.3 \| +1.0 | **-0.8 \| -0.5** | -0.5 (23) \| -10.1 (63) | move only |
| min rest <= 1 day (891 / 710) | -1.0 (-2.0,+0.1) \| -1.3 (-2.5,-0.1) | -0.4 \| -0.9 | **-0.9 \| -0.7** | +2.6 (113) \| +1.5 (234) | move only |
| rest mismatch >= 3 days (2050 / 1548) | +0.1 \| +0.4 | +0.2 \| +0.3 | -0.1 \| 0.0 | +7.1 (183) \| +1.5 (393) | no |
| a team 3+ games in 7 days (1233 / 511) | -0.6 \| -1.3 | -0.6 \| -0.5 | **-0.6 \| -0.5** | -5.1 (92) \| +3.5 (151) | move only |
| **venue >= 1200 m** (693 / 504) | **+1.7 (+0.5,+3.0) \| +1.6 (+0.1,+3.2)** | +1.4 (+0.1,+2.7) \| +1.7 (+0.1,+3.2) | +0.1 \| +0.3 | -2.7 (50) \| +2.6 (125) | **yes (model miss)** |
| high venue, low-altitude visitor (450 / 348) | +0.6 \| +1.6 | +0.3 \| +1.6 | +0.3 \| +0.5 | -2.7 (32) \| +2.8 (93) | no |
| neutral site (1905 / 1414) | -1.0 (-1.8,-0.2) \| 0.0 (-1.1,+1.0) | **-1.1 (-1.8,-0.3)** \| -0.7 (-1.7,+0.3) | **-0.6 \| -0.5** | -2.6 (214) \| -0.9 (450) | move only |

Bold = BH survivor in discovery (or the holdout confirmation). Also checked, nothing held: tip 13-17 and 17-20,
holiday stretch Dec 18-Jan 2, November, March/postseason, travel >= 1000 km, >= 1500 km from home, min rest >= 5.

### Altitude in detail (`altitude.out`, `followup.out`)
| | n | actual - close | over % vs close (95% CI) | over % vs open |
|---|---|---|---|---|
| all other venues | 25,546 | +0.77 | 50.3% | - |
| venue >= 1200 m, all seasons | 1,197 | +2.28 | 55.8% (53.0-58.6) | 57.0% (53.5-60.5), n = 747 |
| by season 2021-22 / 22-23 / 23-24 / 24-25 / 25-26 | ~200-260 each | +0.6 / +2.9 / +3.2 / +1.5 / +2.9 | 52.3 / 56.6 / 56.2 / 54.7 / 58.4% | - / - / 56.4 / 56.7 / 58.0% |
| 800-1200 m / 1200-1500 m / 1500 m+ | 462 / 621 / 576 | +0.7 / +1.6 / +3.0 | 51.2 / 53.6 / 58.1% | |
| high-altitude schools' road games at < 800 m | 650 | -0.8 | 46.4% | |

- The effect holds after dropping any one city (+1.3 to +1.7 vs other venues). Denver, Greeley, Laramie,
  Flagstaff, Logan and Pocatello run highest; Boulder, Reno, Bozeman and Provo are flat or negative.
- It's at least partly a team home/road split: the same schools' road games go *under* the close. A
  rating built from all of a team's games averages the two, so a venue-elevation (or altitude-school
  home/road) term fits what the models are missing.
- et-v1 picks at altitude, 2023-26: overs 61.0% (n = 118), unders 42.1% (n = 57) at the opener. That fits,
  but it's a post-hoc cut with small n.

### Neutral / short-rest / tournament games ("drift-down") by side (`followup.out` 3, 3b)
- Unders at the opener in these games win 52.6% (n = 2,662) vs 49.0% elsewhere (2023-24 51.4%, 2024-25 50.8%,
  2025-26 55.7%). Unders at the close win 51.9% (50.0-53.8), below -110 break-even.
- et-v1 in these games: overs 52.7% (n = 389) vs 54.7% elsewhere; unders 52.8% (n = 436) vs 52.7%. The CLV
  on unders is larger (+1.64 vs +1.09 pts), but it doesn't turn into more wins.

### Live 2026-27 (describe only; `live.out`)
- et-v1 logged bets: 74 graded, 40 W (54.1%). Every split has n <= 16 except weekend (32: 46.9%) and
  neutral (16: 50.0%). Min rest <= 1: 0 of 4, all overs (fits the drift-down pattern, but n = 4).
  2+ time zones from home: 4 of 9.
- Owner's graded college totals (W/L only): 95 graded, 53 W. 2+ zones from home: 4 of 13; tip >= 20:00 local: 1 of 4.
  The backtest shows no time-zone effect on et-v1 (+1.2 / 0.0 pts), so read these as noise.

## Real vs noise
- **Real, in the totals:** altitude (model and close both too low; dose-response; four of five seasons clearly
  positive, 2024-25 weaker) and the downward open→close drift in neutral, short-rest and event games (holds in
  every season with openers, p < 0.001 in holdout).
- **Noise for et-v1 selection:** every et-v1 and edge >= 2 win % split. The one discovery survivor (weekend,
  -7.7 pts) reversed to +0.9 in holdout. 2+ zones east and long-travel model misses didn't hold.
- **Weather:** basketball is indoors. A free historical weather source would mostly flag rare storm/travel
  disruptions, which are already visible through rest and schedule fields. Not worth a new source.

## Recommendation
1. **Pre-register a DS model-feature test (new version, not a change to `ncaab-v1`):** venue elevation (bands
   < 1200 / 1200-1500 / 1500+ m, or log elevation) plus an "altitude school on the road" term. Evaluate
   walk-forward on 2021-22 → 2025-26 against total MAE and the closing total, fixing the elevation table first
   (ROADMAP "College arena coordinates"). Success = total MAE gain at altitude venues with no loss elsewhere,
   in each season.
2. **If (1) works, consider a pre-registered et-v2 candidate** that adds the altitude term to the DS number (or
   drops unders at venues >= 1200 m). Not before et-v1's 300-bet verdict, and et-v1 stays exactly as registered.
3. **Timing note, not a rule:** in neutral-site, 2nd/3rd-game, short-rest and 3+-in-7 games, totals tend to
   fall 0.5-1.6 pts from open to close. An under in these games is best bet early (et-v1 already does). An
   over may get a better number closer to tip. No win-rate gain was shown, so this changes nothing in et-v1.
