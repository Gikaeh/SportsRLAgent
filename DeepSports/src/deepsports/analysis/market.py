"""Home-court advantage and closing-line accuracy, computed in SQL (read-only)."""

from collections.abc import Sequence
from typing import Any

import duckdb

from deepsports.store import SANE_LIMITS

LEAGUES = ("nba", "ncaab")


def _league(league: str) -> str:
    if league not in LEAGUES:
        raise ValueError(f"unknown league {league!r}")
    return league


def final_sql(league: str = "nba") -> str:
    """Games with a real final score in `league` (alias `g`). Postponed games are `post` but
    not completed. ESPN team ids are only unique within a league, so every query is scoped.
    Both sides must be in `teams` for that league: NBA All-Star / exhibition teams are absent
    (out); college non-D1 opponents are present with `listed = false` (in; callers decide)."""
    lg = _league(league)
    teams = f"(SELECT team_id FROM teams WHERE league = '{lg}')"
    return (
        f"g.league = '{lg}' AND g.completed AND g.status = 'STATUS_FINAL'"
        f" AND g.home_score IS NOT NULL AND g.home_team_id IN {teams} AND g.away_team_id IN {teams}"
    )


FINAL = final_sql("nba")
# Per-league line sanity limits (max |spread|, total lo, hi) live in store.py so the grading
# view (prediction_results) applies the same ones; re-exported here.


def sane_spread(league: str = "nba") -> str:
    return f"abs({{col}}) <= {SANE_LIMITS[_league(league)][0]}"


def sane_total(league: str = "nba") -> str:
    _, lo, hi = SANE_LIMITS[_league(league)]
    return f"{{col}} BETWEEN {lo} AND {hi}"


SANE_SPREAD = sane_spread("nba")
SANE_TOTAL = sane_total("nba")
DEFAULT_SEASON_TYPES = (2, 3, 5)  # regular season, postseason, play-in


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def _in(values: Sequence[int]) -> str:
    return ", ".join(str(int(v)) for v in values)


def home_court(
    con: duckdb.DuckDBPyConnection, seasons: Sequence[int] | None = None
) -> list[dict[str, Any]]:
    """Per season (regular season, final, non-neutral games): n, home win %, avg home margin."""
    where = f"{FINAL} AND g.season_type = 2 AND NOT coalesce(g.neutral_site, false)"
    if seasons:
        where += f" AND g.season_year IN ({_in(seasons)})"
    sql = f"""
        SELECT g.season_year AS season,
               count(*) AS n,
               avg((g.home_score > g.away_score)::int) AS home_win_pct,
               avg(g.home_score - g.away_score) AS avg_home_margin
        FROM games g WHERE {where}
        GROUP BY 1 ORDER BY 1
    """
    return _rows(con, sql, [])


def _closing_cte(season_types: Sequence[int]) -> str:
    return f"""
        WITH closing AS (
            SELECT * FROM odds_snapshots WHERE source = 'closing'
            QUALIFY row_number() OVER (PARTITION BY game_id ORDER BY captured_at DESC) = 1
        ),
        opening AS (
            SELECT * FROM odds_snapshots WHERE source = 'opening'
            QUALIFY row_number() OVER (PARTITION BY game_id ORDER BY captured_at ASC) = 1
        ),
        gm AS (
            SELECT g.game_id, g.season_year AS season,
                   g.home_score - g.away_score AS margin,
                   g.home_score + g.away_score AS total
            FROM games g
            WHERE {FINAL} AND g.season_type IN ({_in(season_types)})
        )
    """


def market_accuracy(
    con: duckdb.DuckDBPyConnection, season_types: Sequence[int] = DEFAULT_SEASON_TYPES
) -> dict[str, list[dict[str, Any]]]:
    """Closing-line accuracy per season, plus opening -> closing movement.

    Returns {"closing": [...], "movement": [...]}, one row per season in each.
    - favorite_win_pct: favorite (by closing spread) won outright; pick'ems (spread 0) excluded.
    - home_cover_pct: covers / (covers + non-covers); `pushes` counted separately.
    - spread_mae: mean |actual margin - (-spread_home)|; total_mae: mean |actual total - O/U|.
    """
    spread_ok = SANE_SPREAD.format(col="c.spread_home")
    total_ok = SANE_TOTAL.format(col="c.over_under")
    closing_sql = (
        _closing_cte(season_types)
        + f"""
        SELECT gm.season,
               count(*) FILTER (WHERE {spread_ok}) AS n_spread,
               count(*) FILTER (WHERE {spread_ok} AND c.spread_home <> 0) AS n_favorite,
               avg(CASE WHEN c.spread_home < 0 THEN (gm.margin > 0)::int
                        WHEN c.spread_home > 0 THEN (gm.margin < 0)::int END)
                   FILTER (WHERE {spread_ok}) AS favorite_win_pct,
               count(*) FILTER (WHERE {spread_ok} AND gm.margin + c.spread_home > 0) AS home_covers,
               count(*) FILTER (WHERE {spread_ok} AND gm.margin + c.spread_home < 0) AS away_covers,
               count(*) FILTER (WHERE {spread_ok} AND gm.margin + c.spread_home = 0) AS pushes,
               avg(abs(gm.margin + c.spread_home)) FILTER (WHERE {spread_ok}) AS spread_mae,
               count(*) FILTER (WHERE {total_ok}) AS n_total,
               avg(abs(gm.total - c.over_under)) FILTER (WHERE {total_ok}) AS total_mae,
               avg((gm.total > c.over_under)::int)
                   FILTER (WHERE {total_ok} AND gm.total <> c.over_under) AS over_pct,
               count(*) FILTER (WHERE NOT coalesce({spread_ok}, false)
                                  AND c.spread_home IS NOT NULL) AS n_spread_rejected,
               count(*) FILTER (WHERE NOT coalesce({total_ok}, false)
                                  AND c.over_under IS NOT NULL) AS n_total_rejected
        FROM gm JOIN closing c USING (game_id)
        GROUP BY 1 ORDER BY 1
    """
    )
    closing = _rows(con, closing_sql, [])
    for r in closing:
        decided = r["home_covers"] + r["away_covers"]
        r["home_cover_pct"] = r["home_covers"] / decided if decided else None

    o_spread = SANE_SPREAD.format(col="o.spread_home")
    o_total = SANE_TOTAL.format(col="o.over_under")
    move_sql = (
        _closing_cte(season_types)
        + f"""
        SELECT gm.season,
               count(*) FILTER (WHERE {spread_ok} AND {o_spread}) AS n_spread,
               avg(abs(c.spread_home - o.spread_home))
                   FILTER (WHERE {spread_ok} AND {o_spread}) AS spread_mean_abs_move,
               avg(abs(gm.margin + o.spread_home))
                   FILTER (WHERE {spread_ok} AND {o_spread}) AS open_spread_mae,
               avg(abs(gm.margin + c.spread_home))
                   FILTER (WHERE {spread_ok} AND {o_spread}) AS close_spread_mae,
               avg((abs(gm.margin + c.spread_home) < abs(gm.margin + o.spread_home))::int)
                   FILTER (WHERE {spread_ok} AND {o_spread}
                           AND c.spread_home <> o.spread_home) AS close_spread_better_pct,
               count(*) FILTER (WHERE {total_ok} AND {o_total}) AS n_total,
               avg(abs(c.over_under - o.over_under))
                   FILTER (WHERE {total_ok} AND {o_total}) AS total_mean_abs_move,
               avg(abs(gm.total - o.over_under))
                   FILTER (WHERE {total_ok} AND {o_total}) AS open_total_mae,
               avg(abs(gm.total - c.over_under))
                   FILTER (WHERE {total_ok} AND {o_total}) AS close_total_mae
        FROM gm JOIN closing c USING (game_id) JOIN opening o USING (game_id)
        GROUP BY 1 ORDER BY 1
    """
    )
    return {"closing": closing, "movement": _rows(con, move_sql, [])}
