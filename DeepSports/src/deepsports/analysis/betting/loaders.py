"""Read-only loaders that shape warehouse rows for `grading.grade` and `audit.audit`.

Every function takes an open DuckDB connection (read-only is fine) and returns plain lists of
dicts. Data notes (verified on the 2026-11-04 warehouse copy):
- `odds_snapshots` opening rows carry the tip time as `captured_at`: there is one per game and
  it says nothing about when the line was posted. Closing rows are mostly stamped after tip by
  the backfill, but the lines are genuine closes.
- `load_lines` nulls spread/total lines outside the per-league sanity limits
  (`store.SANE_LIMITS`); moneylines are left alone.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb

from deepsports import config
from deepsports.store import SANE_LIMITS

ET = "'America/New_York'"


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: Sequence[Any] = ()) -> list[dict]:
    cur = con.execute(sql, list(params))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def _where(
    params: list[Any],
    league: str | None,
    seasons: Sequence[int] | None,
    season_types: Sequence[int] | None,
    game_ids: Sequence[str] | None = None,
    alias: str = "g",
) -> list[str]:
    parts = []
    if league is not None:
        params.append(league)
        parts.append(f"{alias}.league = ?")
    if seasons:
        params.extend(int(s) for s in seasons)
        parts.append(f"{alias}.season_year IN ({', '.join('?' * len(seasons))})")
    if season_types:
        params.extend(int(s) for s in season_types)
        parts.append(f"{alias}.season_type IN ({', '.join('?' * len(season_types))})")
    if game_ids:
        params.extend(str(x) for x in game_ids)
        parts.append(f"{alias}.game_id IN ({', '.join('?' * len(game_ids))})")
    return parts


FINAL = (
    "g.completed AND g.status = 'STATUS_FINAL' "
    "AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL"
)


def load_games(
    con: duckdb.DuckDBPyConnection,
    league: str | None = None,
    seasons: Sequence[int] | None = None,
    season_types: Sequence[int] = (2, 3, 5),
    listed_only: bool = False,
    game_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Final games with both teams in `teams` (drops All-Star/exhibition teams): scores,
    margin, total, team abbreviations and `tip_date` (US/Eastern 'YYYY-MM-DD').
    `listed_only` also drops college games against non-D1 opponents."""
    params: list[Any] = []
    parts = [FINAL, *_where(params, league, seasons, season_types, game_ids)]
    if listed_only:
        parts.append("h.listed AND a.listed")
    sql = f"""
        SELECT g.game_id, g.league, g.season_year, g.season_type,
               strftime(g.start_time_utc AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%SZ')
                   AS start_time_utc,
               g.home_team_id, g.away_team_id,
               h.abbreviation AS home_abbr, a.abbreviation AS away_abbr,
               g.home_score, g.away_score,
               g.home_score - g.away_score AS margin, g.home_score + g.away_score AS total,
               g.neutral_site,
               CAST(g.start_time_utc AT TIME ZONE {ET} AS DATE)::VARCHAR AS tip_date
        FROM games g
        JOIN teams h ON h.league = g.league AND h.team_id = g.home_team_id
        JOIN teams a ON a.league = g.league AND a.team_id = g.away_team_id
        WHERE {" AND ".join(parts)}
        ORDER BY g.start_time_utc, g.game_id
    """
    return _rows(con, sql, params)


def load_odds(
    con: duckdb.DuckDBPyConnection,
    source: str,
    league: str | None = None,
    seasons: Sequence[int] | None = None,
    season_types: Sequence[int] = (2, 3, 5),
    game_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """One odds row per game for `source` ('opening': the earliest row; 'closing' and
    'pregame': the latest). spread_home negative = home favored."""
    if source not in ("opening", "closing", "pregame"):
        raise ValueError(f"unknown odds source {source!r}")
    order = "ASC" if source == "opening" else "DESC"
    params: list[Any] = [source]
    parts = _where(params, league, seasons, season_types, game_ids)
    sql = f"""
        WITH pick AS (
            SELECT * FROM odds_snapshots WHERE source = ?
            QUALIFY row_number() OVER (PARTITION BY game_id ORDER BY captured_at {order}) = 1
        )
        SELECT p.game_id, g.league, g.season_year, g.season_type,
               strftime(p.captured_at AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%SZ') AS captured_at,
               p.provider, p.details, p.spread_home, p.over_under,
               p.home_moneyline, p.away_moneyline
        FROM pick p JOIN games g USING (game_id)
        {("WHERE " + " AND ".join(parts)) if parts else ""}
        ORDER BY g.start_time_utc, p.game_id
    """
    return _rows(con, sql, params)


def sane_lines(row: dict[str, Any]) -> dict[str, Any]:
    """Null the spread/total columns of a `load_lines`-shaped row that fall outside the
    league's sanity limits (in place; returns the row)."""
    lim = SANE_LIMITS.get(row.get("league"))
    if lim is None:
        return row
    max_spread, lo, hi = lim
    for key in ("open_spread_home", "close_spread_home"):
        v = row.get(key)
        row[key] = v if v is not None and abs(v) <= max_spread else None
    for key in ("open_total", "close_total"):
        v = row.get(key)
        row[key] = v if v is not None and lo <= v <= hi else None
    return row


def load_lines(
    con: duckdb.DuckDBPyConnection,
    league: str | None = None,
    seasons: Sequence[int] | None = None,
    season_types: Sequence[int] = (2, 3, 5),
    apply_sane: bool = True,
) -> list[dict[str, Any]]:
    """Per final game with any opening/closing row: open_* and close_* spread_home, total,
    home_ml, away_ml. The `lines=` input of `grading.grade` and `audit.audit`."""
    params: list[Any] = []
    parts = [FINAL, *_where(params, league, seasons, season_types)]
    sql = f"""
        WITH closing AS (
            SELECT * FROM odds_snapshots WHERE source = 'closing'
            QUALIFY row_number() OVER (PARTITION BY game_id ORDER BY captured_at DESC) = 1
        ),
        opening AS (
            SELECT * FROM odds_snapshots WHERE source = 'opening'
            QUALIFY row_number() OVER (PARTITION BY game_id ORDER BY captured_at ASC) = 1
        ),
        gm AS (
            SELECT g.game_id, g.league, g.season_year, g.season_type,
                   CAST(g.start_time_utc AT TIME ZONE {ET} AS DATE)::VARCHAR AS tip_date
            FROM games g WHERE {" AND ".join(parts)}
        )
        SELECT gm.*,
               o.spread_home AS open_spread_home, c.spread_home AS close_spread_home,
               o.over_under AS open_total, c.over_under AS close_total,
               o.home_moneyline AS open_home_ml, c.home_moneyline AS close_home_ml,
               o.away_moneyline AS open_away_ml, c.away_moneyline AS close_away_ml
        FROM gm LEFT JOIN closing c USING (game_id) LEFT JOIN opening o USING (game_id)
        WHERE c.game_id IS NOT NULL OR o.game_id IS NOT NULL
        ORDER BY gm.tip_date, gm.game_id
    """
    rows = _rows(con, sql, params)
    return [sane_lines(r) for r in rows] if apply_sane else rows


def load_odds_raw(
    con: duckdb.DuckDBPyConnection,
    game_ids: Sequence[str] | None = None,
    sources: Sequence[str] = ("opening", "closing"),
    league: str | None = None,
) -> list[dict[str, Any]]:
    """Every raw odds_snapshots row (no per-game dedup) for the given sources; the audit
    attaches these to its biggest-edge winners."""
    params: list[Any] = [str(s) for s in sources]
    where = f"o.source IN ({', '.join('?' * len(sources))})"
    if league is not None:
        params.append(league)
        where += " AND g.league = ?"
    if game_ids:
        params.extend(str(x) for x in game_ids)
        where += f" AND o.game_id IN ({', '.join('?' * len(game_ids))})"
    sql = f"""
        SELECT o.game_id, o.source,
               strftime(o.captured_at AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%SZ') AS captured_at,
               o.provider, o.details, o.spread_home, o.over_under,
               o.home_moneyline, o.away_moneyline, g.league, g.season_year
        FROM odds_snapshots o JOIN games g USING (game_id)
        WHERE {where}
        ORDER BY o.game_id, o.source, o.captured_at
    """
    return _rows(con, sql, params)


def read_raw_summary(
    league: str, game_id: str | int, raw_dir: str | Path | None = None
) -> dict[str, Any]:
    """The cached raw ESPN summary JSON of one game ({raw_dir}/espn/{league}/summary/{id}.json.gz,
    raw_dir defaulting to config.RAW_DIR). Input for `deepsports.parse_pbp.parse_summary`."""
    root = Path(raw_dir) if raw_dir is not None else config.RAW_DIR
    path = root / "espn" / league / "summary" / f"{game_id}.json.gz"
    if not path.is_file():
        raise FileNotFoundError(f"no raw summary at {path}")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)
