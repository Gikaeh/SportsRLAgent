"""`deepsports venues fetch|build|status`: venue coordinates, elevation and time zone.

- fetch: download the GeoNames dumps (2 requests, kept under RAW_DIR/geonames/; `--refresh`).
- build: backfill games.venue_id from cached scoreboards, geocode every venue, replace the
  `venues` table. No network; loads the gazetteer before taking the writer lock, then one
  short write (lock wait 120 s).
- status: coverage per season (read-only).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from deepsports import config
from deepsports.http import PoliteClient
from deepsports.sources import geonames
from deepsports.store import Store, is_lock_conflict
from deepsports.venue_geo import (
    backfill_game_venues,
    cached_scoreboard_venues,
    coverage,
    missing_venue_days,
    replace_venues,
    venue_aggregates,
    venue_rows,
)

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="deepsports venues", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download the GeoNames gazetteer dumps (2 requests)")
    f.add_argument("--refresh", action="store_true", help="download again even if present")
    sub.add_parser("build", help="backfill games.venue_id and rebuild the venues table (writer)")
    s = sub.add_parser("status", help="venue geography coverage per season (read-only)")
    s.add_argument("--league", choices=("ncaab", "nba"), default="ncaab")
    return p


def _fetch(args: argparse.Namespace) -> int:
    client = PoliteClient()
    for path, fetched in geonames.fetch(client, refresh=args.refresh):
        state = "downloaded" if fetched else "cached"
        print(f"{path.name}: {state} ({path.stat().st_size / 1e6:.1f} MB)")
    return 0


def _build(args: argparse.Namespace) -> int:
    t0 = time.monotonic()
    try:
        gaz = geonames.load_gazetteer()
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    # Read what needs backfilling and parse the cache with no lock held.
    try:
        ro = Store(config.DB_PATH, read_only=True, lock_wait=120.0)
    except Exception as e:
        if is_lock_conflict(e):
            print("skipped, warehouse busy")
            return 3
        raise
    try:
        has_col = ro.con.execute(
            "SELECT count(*) FROM duckdb_columns() WHERE table_name = 'games' "
            "AND column_name = 'venue_id'"
        ).fetchone()[0]
        found = cached_scoreboard_venues(missing_venue_days(ro.con)) if has_col else {}
    finally:
        ro.close()
    try:
        db = Store(config.DB_PATH, lock_wait=120.0)
    except Exception as e:
        if is_lock_conflict(e):
            print("skipped, warehouse busy")
            return 3
        raise
    try:
        if not has_col:  # the writer open just migrated games; find the days again
            found = cached_scoreboard_venues(missing_venue_days(db.con))
        filled = backfill_game_venues(db.con, found)
        rows = venue_rows(venue_aggregates(db.con), gaz)
        n = replace_venues(db, rows)
        missing = db.con.execute("SELECT count(*) FROM games WHERE venue_id IS NULL").fetchone()[0]
    finally:
        db.close()
    unmatched = [r for r in rows if r["lat"] is None]
    print(
        f"games backfilled={filled} games_without_venue_id={missing} venues={n} "
        f"geocoded={n - len(unmatched)} no_elevation={sum(r['elevation_m'] is None for r in rows)}"
        f" ({time.monotonic() - t0:.0f}s)"
    )
    for r in unmatched:
        print(
            f"  unmatched: {r['venue_id']} {r['name']} | {r['city']}, {r['state']}"
            f" ({r['geo_match']})"
        )
    return 0


def _status(args: argparse.Namespace) -> int:
    db = Store(config.DB_PATH, read_only=True, lock_wait=30.0)
    try:
        if not db.has_table("venues"):
            print("no venues table yet: run `deepsports venues build`")
            return 1
        c = coverage(db.con, args.league)
    finally:
        db.close()
    print(
        f"{c['league']}: venues={c['venues']} geocoded={c['venues_geocoded']} "
        f"with_elevation={c['venues_with_elevation']} with_tz={c['venues_with_tz']}"
    )
    print("season  games  venue_id  geocoded  elevation  tz")
    for season, games, vid, geo, elev, tz in c["per_season"]:
        print(
            f"{season}  {games:5d}  {vid / games:7.1%}  {geo / games:7.1%}  {elev / games:8.1%}"
            f"  {tz / games:6.1%}"
        )
    for vid, name, city, state, how, games in c["incomplete"]:
        print(f"  incomplete: {vid} {name} | {city}, {state} ({how}; {games} games)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        config.require_data_dir()
    except config.DataDirUnavailable as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return {"fetch": _fetch, "build": _build, "status": _status}[args.cmd](args)
