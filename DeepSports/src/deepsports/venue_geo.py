"""Venue geography: ESPN venue ids on `games`, and the `venues` table (city coordinates,
elevation, IANA time zone) built offline from the GeoNames gazetteer (sources/geonames.py).

`deepsports venues build` (venues_cli.py):
1. backfill `games.venue_id`/`venue_state` for rows stored before those columns existed, from
   the cached ESPN scoreboards (the scoreboard parser fills them for every new row);
2. aggregate every venue in `games` (both leagues) and geocode it by (city, state);
3. replace the `venues` rows. Idempotent; no network.
"""

from __future__ import annotations

import gzip
import json
import logging
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from deepsports import config
from deepsports.parse_espn import parse_scoreboard_venues
from deepsports.sources.geonames import Gazetteer, elevation_m

log = logging.getLogger(__name__)

VENUE_COLS = (
    "venue_id",
    "name",
    "city",
    "state",
    "country",
    "lat",
    "lon",
    "elevation_m",
    "tz",
    "geonameid",
    "geo_place",
    "geo_match",
    "games",
    "neutral_games",
    "first_game_utc",
    "last_game_utc",
    "updated_at",
)


def missing_venue_days(con) -> dict[str, set[date]]:
    """{league: US/Eastern game days (+-1) of games without a venue_id} (scoreboard file days)."""
    rows = con.execute(
        """SELECT DISTINCT league, CAST(timezone('America/New_York', start_time_utc) AS DATE)
           FROM games WHERE venue_id IS NULL"""
    ).fetchall()
    out: dict[str, set[date]] = {}
    for league, d in rows:
        out.setdefault(league, set()).update(d + timedelta(days=k) for k in (-1, 0, 1))
    return out


def cached_scoreboard_venues(
    days: dict[str, set[date]], raw_dir: Path | None = None
) -> dict[str, dict[str, Any]]:
    """{game_id: venue fields} from the cached scoreboards of those days (missing files skipped)."""
    base = (raw_dir or config.RAW_DIR) / "espn"
    out: dict[str, dict[str, Any]] = {}
    for league, ds in days.items():
        for d in sorted(ds):
            path = base / league / "scoreboard" / f"{d:%Y%m%d}.json.gz"
            if not path.exists():
                continue
            with gzip.open(path, "rt", encoding="utf-8") as f:
                for r in parse_scoreboard_venues(json.load(f)):
                    if r["venue_id"]:
                        out[r["game_id"]] = r
    return out


def backfill_game_venues(con, found: dict[str, dict[str, Any]]) -> int:
    """Fill games.venue_id/venue_state where NULL. Returns rows updated."""
    if not found:
        return 0
    payload = json.dumps(
        [
            {"game_id": g, "venue_id": r["venue_id"], "st": r["venue_state"]}
            for g, r in found.items()
        ]
    )
    before = con.execute("SELECT count(*) FROM games WHERE venue_id IS NULL").fetchone()[0]
    con.execute(
        """UPDATE games SET venue_id = v.venue_id, venue_state = v.st
           FROM (SELECT unnest(from_json(?::JSON,
                 '[{"game_id":"VARCHAR","venue_id":"VARCHAR","st":"VARCHAR"}]'), recursive := true)
                ) v
           WHERE games.game_id = v.game_id AND games.venue_id IS NULL""",
        [payload],
    )
    after = con.execute("SELECT count(*) FROM games WHERE venue_id IS NULL").fetchone()[0]
    return before - after


def venue_aggregates(con) -> list[dict[str, Any]]:
    """One row per venue_id in games: the latest name/city/state and game counts."""
    cur = con.execute(
        """SELECT venue_id,
                  arg_max(venue, start_time_utc) AS name,
                  arg_max(venue_city, start_time_utc) AS city,
                  arg_max(venue_state, start_time_utc) AS state,
                  count(*) AS games,
                  count(*) FILTER (WHERE neutral_site) AS neutral_games,
                  min(start_time_utc) AS first_game_utc,
                  max(start_time_utc) AS last_game_utc
           FROM games WHERE venue_id IS NOT NULL GROUP BY venue_id ORDER BY venue_id"""
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def venue_rows(
    aggregates: Iterable[dict[str, Any]], gazetteer: Gazetteer, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Pure: geocode each venue aggregate. Unmatched venues keep a row with NULL geography and
    the reason in `geo_match`."""
    now = now or datetime.now(UTC)
    rows = []
    for a in aggregates:
        place, how = gazetteer.match(a["city"], a["state"], a["venue_id"])
        geo = {
            "country": place["country"] if place else None,
            "lat": place["lat"] if place else None,
            "lon": place["lon"] if place else None,
            "elevation_m": elevation_m(place) if place else None,
            "tz": place["timezone"] if place else None,
            "geonameid": place["geonameid"] if place else None,
            "geo_place": place["name"] if place else None,
        }
        rows.append({**a, **geo, "geo_match": how, "updated_at": now})
    return [{c: r[c] for c in VENUE_COLS} for r in rows]


def replace_venues(db, rows: list[dict[str, Any]]) -> int:
    """Swap the whole venues table in one transaction."""
    db.con.execute("BEGIN TRANSACTION")
    try:
        db.con.execute("DELETE FROM venues")
        n = db._write("venues", rows)
        db.con.execute("COMMIT")
    except Exception:
        db.con.execute("ROLLBACK")
        raise
    return n


def coverage(con, league: str = "ncaab") -> dict[str, Any]:
    """Coverage of a league's games by venue geography, per season and overall (read-only)."""
    per_season = con.execute(
        """SELECT g.season_year,
                  count(*) AS games,
                  count(g.venue_id) AS with_venue_id,
                  count(v.lat) AS geocoded,
                  count(v.elevation_m) AS with_elevation,
                  count(v.tz) AS with_tz
           FROM games g LEFT JOIN venues v USING (venue_id)
           WHERE g.league = ? GROUP BY 1 ORDER BY 1""",
        [league],
    ).fetchall()
    venues = con.execute(
        """SELECT count(*), count(lat), count(elevation_m), count(tz)
           FROM venues WHERE venue_id IN (SELECT venue_id FROM games WHERE league = ?)""",
        [league],
    ).fetchone()
    unmatched = con.execute(
        """SELECT venue_id, name, city, state, geo_match, games FROM venues
           WHERE (lat IS NULL OR elevation_m IS NULL OR tz IS NULL)
             AND venue_id IN (SELECT venue_id FROM games WHERE league = ?)
           ORDER BY games DESC""",
        [league],
    ).fetchall()
    return {
        "league": league,
        "per_season": per_season,
        "venues": venues[0],
        "venues_geocoded": venues[1],
        "venues_with_elevation": venues[2],
        "venues_with_tz": venues[3],
        "incomplete": unmatched,
    }
