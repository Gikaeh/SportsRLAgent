"""Elo team ratings, FiveThirtyEight NBA style, with strictly pre-game ratings recorded.

Leakage rule: each game's row is written *before* its result updates the ratings, so a game's
own outcome can never influence its pre-game rating or probability.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import duckdb

from deepsports.analysis.market import DEFAULT_SEASON_TYPES, _in, final_sql

MEAN = 1500.0
POOL_KEY = "unlisted"  # rating key shared by every pooled (non-D1) team


def win_probability(home_elo: float, away_elo: float, home_adv: float = 100.0) -> float:
    """Probability the home team wins given pre-game ratings (home_adv=0 on a neutral court)."""
    return 1 / (1 + 10 ** (-(home_elo + home_adv - away_elo) / 400))


def mov_multiplier(margin: int, winner_elo_diff: float) -> float:
    """538 margin-of-victory multiplier: bigger wins move ratings more, but less so when the
    winner was already the stronger team (limits autocorrelation)."""
    return (abs(margin) + 3) ** 0.8 / max(7.5 + 0.006 * winner_elo_diff, 1.0)


@dataclass
class EloResult:
    games: list[dict[str, Any]] = field(default_factory=list)  # one row per rated game
    ratings: dict[str, float] = field(default_factory=dict)  # current rating per rating key
    alias: dict[str, str] = field(default_factory=dict)  # team_id -> POOL_KEY for pooled teams
    pool_rating: float = MEAN  # starting (and new-season regression) rating of POOL_KEY

    def key(self, team_id: str) -> str:
        return self.alias.get(team_id, team_id)

    def start(self, key: str) -> float:
        """Starting rating of a rating key (MEAN; `pool_rating` for the pooled team). A new
        season regresses toward it."""
        return self.pool_rating if key == POOL_KEY else MEAN

    def rating(self, team_id: str) -> float:
        return self.ratings.get(self.key(team_id), MEAN)


def elo_ratings(
    con: duckdb.DuckDBPyConnection,
    k: float = 20.0,
    home_adv: float = 100.0,
    carry_over: float = 0.75,
    season_types: tuple[int, ...] = DEFAULT_SEASON_TYPES,
    league: str = "nba",
    pool_unlisted: bool = False,
    pool_rating: float = MEAN,
    until: datetime | None = None,
) -> EloResult:
    """Walk completed games in start-time order; record pre-game Elo and home win probability.

    - New teams start at 1500. At a team's first game of a new season its rating is regressed:
      r = carry_over * r + (1 - carry_over) * start (1500; `pool_rating` for the pooled team).
      carry_over=0 restarts every season level (college v1: cross-season not validated).
    - Neutral-site games get no home advantage.
    - Preseason (season_type 1) is excluded by default.
    - `until` (point-in-time use): only games that tipped at or before it are rated, so
      `ratings` are the ratings as of then (callers pass `now - FINISH_LAG`).
    - `pool_unlisted` (college): every team with `listed = false` (non-D1 opponents, 1-3 D1
      games each) shares one rating under POOL_KEY, starting at `pool_rating`.
    """
    teams = con.execute(
        "SELECT team_id, coalesce(listed, true) FROM teams WHERE league = ?", [league]
    ).fetchall()
    alias = {t: POOL_KEY for t, listed in teams if pool_unlisted and not listed}
    ratings: dict[str, float] = {t: MEAN for t, _ in teams if t not in alias}
    if alias:
        ratings[POOL_KEY] = pool_rating
    last_season: dict[str, int] = {}
    rows = con.execute(
        f"""
        SELECT g.game_id, g.season_year, g.season_type, g.start_time_utc,
               g.home_team_id, g.away_team_id, g.home_score, g.away_score,
               coalesce(g.neutral_site, false)
        FROM games g
        WHERE {final_sql(league)} AND g.season_type IN ({_in(season_types)})
          {"" if until is None else "AND g.start_time_utc <= ?"}
        ORDER BY g.start_time_utc, g.game_id
        """,
        [] if until is None else [until],
    ).fetchall()
    out = EloResult(ratings=ratings, alias=alias, pool_rating=pool_rating)
    for gid, season, stype, start, home_id, away_id, hs, as_, neutral in rows:
        home, away = alias.get(home_id, home_id), alias.get(away_id, away_id)
        for t in (home, away):
            r = ratings.get(t, MEAN)
            if t in last_season and last_season[t] != season:
                r = carry_over * r + (1 - carry_over) * out.start(t)
            ratings[t] = r
            last_season[t] = season
        h_pre, a_pre = ratings[home], ratings[away]
        adv = 0.0 if neutral else home_adv
        p_home = win_probability(h_pre, a_pre, adv)
        margin = hs - as_
        out.games.append(
            {
                "game_id": gid,
                "season": season,
                "season_type": stype,
                "start_time_utc": start,
                "home_team_id": home_id,
                "away_team_id": away_id,
                "neutral_site": neutral,
                "home_elo_pre": h_pre,
                "away_elo_pre": a_pre,
                "p_home": p_home,
                "home_margin": margin,
                "home_win": int(margin > 0),
            }
        )
        # Update only after the pre-game row is recorded.
        if margin == 0:
            shift = 0.0
        else:
            diff = h_pre + adv - a_pre
            winner_diff = diff if margin > 0 else -diff
            outcome = 1.0 if margin > 0 else 0.0
            shift = k * mov_multiplier(margin, winner_diff) * (outcome - p_home)
        if not math.isfinite(shift):
            shift = 0.0
        ratings[home] = h_pre + shift
        ratings[away] = a_pre - shift
    return out
