"""Venue altitude features for college totals (research, 2026-11-22).

Candidate features, all known before tip-off (the venue and both teams' home arenas come from
the published schedule):
- ``venue_elev_km``: venue elevation in km.
- ``alt_b800`` / ``alt_b1200`` / ``alt_b1500``: venue band dummies (800-1200, 1200-1500,
  >= 1500 m; < 800 m is the reference).
- ``home_elev_h`` / ``home_elev_a``: each team's home-arena elevation in km.
- ``alt_gain_sum``: km climbed by the teams playing above their home (low team playing high).
- ``alt_drop_sum``: km dropped by the teams playing below their home (altitude school playing low).
- ``tz_cross_sum``: hours between the venue's UTC offset and each team's home offset, summed.

A team's home arena for a season is the venue of most of its non-neutral home games in that
season (the ``team_home_venues`` view on branch feature/college-venue-geo, recomputed here so a
warehouse without the view still works); a season without home games falls back to the nearest
season that has one. Results: docs/results/2026-11-22-altitude-feature.md.
"""

import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

ALTITUDE_FEATURES = [
    "venue_elev_km",
    "alt_b800",
    "alt_b1200",
    "alt_b1500",
    "home_elev_h",
    "home_elev_a",
    "alt_gain_sum",
    "alt_drop_sum",
    "tz_cross_sum",
]
BANDS = ((800, "alt_b800"), (1200, "alt_b1200"), (1500, "alt_b1500"))

HOME_VENUES_SQL = """
WITH h AS (
    SELECT home_team_id AS team_id, season_year, venue_id,
           count(*) AS home_games, max(start_time_utc) AS last_home_game
    FROM games
    WHERE league = ? AND NOT coalesce(neutral_site, false) AND venue_id IS NOT NULL
      AND status NOT IN ('STATUS_POSTPONED', 'STATUS_CANCELED')
    GROUP BY ALL
), r AS (
    SELECT *, row_number() OVER (PARTITION BY team_id, season_year
                                 ORDER BY home_games DESC, last_home_game DESC) AS rk
    FROM h
)
SELECT r.team_id, r.season_year, v.elevation_m, v.tz
FROM r JOIN venues v USING (venue_id) WHERE rk = 1
"""

GAMES_SQL = """
SELECT g.game_id, g.season_year, g.start_time_utc, g.home_team_id, g.away_team_id,
       v.elevation_m, v.tz
FROM games g LEFT JOIN venues v USING (venue_id)
WHERE g.league = ?
"""


def band(elev_m: float | None) -> str:
    """'<800', '800-1200', '1200-1500' or '1500+' ('na' if unknown)."""
    if elev_m is None or (isinstance(elev_m, float) and math.isnan(elev_m)):
        return "na"
    if elev_m < 800:
        return "<800"
    if elev_m < 1200:
        return "800-1200"
    if elev_m < 1500:
        return "1200-1500"
    return "1500+"


def utc_offset_h(tz: str | None, when: datetime) -> float | None:
    if not tz:
        return None
    off = when.astimezone(ZoneInfo(tz)).utcoffset()
    return off.total_seconds() / 3600 if off is not None else None


def game_features(
    venue_elev: float | None,
    venue_tz: str | None,
    home: tuple[float | None, str | None] | None,
    away: tuple[float | None, str | None] | None,
    when: datetime,
) -> dict[str, float]:
    """Altitude features of one game. `home`/`away` = (home-arena elevation m, tz) or None.
    Unknown inputs give NaN (the model's imputer fills them with the training mean)."""
    nan = math.nan
    ve = nan if venue_elev is None else float(venue_elev)
    out: dict[str, float] = {"venue_elev_km": ve / 1000}
    for lo, name in BANDS:
        hi = {800: 1200, 1200: 1500, 1500: math.inf}[lo]
        out[name] = nan if math.isnan(ve) else float(lo <= ve < hi)
    gain = drop = 0.0
    tz_sum = 0.0
    vo = utc_offset_h(venue_tz, when)
    for side, geo in (("h", home), ("a", away)):
        te = nan if geo is None or geo[0] is None else float(geo[0])
        out[f"home_elev_{side}"] = te / 1000
        gain += max(0.0, ve - te) / 1000 if not (math.isnan(ve) or math.isnan(te)) else nan
        drop += max(0.0, te - ve) / 1000 if not (math.isnan(ve) or math.isnan(te)) else nan
        to = utc_offset_h(geo[1], when) if geo else None
        tz_sum += abs(vo - to) if vo is not None and to is not None else nan
    out["alt_gain_sum"] = gain
    out["alt_drop_sum"] = drop
    out["tz_cross_sum"] = tz_sum
    return out


def nearest_season(
    homes: Mapping[tuple[str, int], tuple[float | None, str | None]], team: str, season: int
) -> tuple[float | None, str | None] | None:
    """The team's home arena in `season`, else the nearest season with one (earlier first)."""
    for d in range(0, 8):
        for s in (season - d, season + d):
            if (team, s) in homes:
                return homes[(team, s)]
    return None


def load_altitude_features(
    con: duckdb.DuckDBPyConnection, league: str = "ncaab"
) -> dict[str, dict[str, float]]:
    """game_id -> altitude features for every game of `league` (read-only queries)."""
    homes = {(t, s): (e, tz) for t, s, e, tz in con.execute(HOME_VENUES_SQL, [league]).fetchall()}
    out = {}
    for gid, season, start, h, a, ve, vtz in con.execute(GAMES_SQL, [league]).fetchall():
        out[gid] = game_features(
            ve, vtz, nearest_season(homes, h, season), nearest_season(homes, a, season), start
        )
    return out


def attach(rows: list[dict[str, Any]], feats: Mapping[str, Mapping[str, float]]) -> None:
    """Add the altitude features (in place) to feature rows; games without a venue get NaN."""
    blank = {k: math.nan for k in ALTITUDE_FEATURES}
    for r in rows:
        r["features"].update(feats.get(r["game_id"], blank))
