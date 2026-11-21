"""`deepsports torvik fetch|map|status`: Barttorvik T-Rank daily archive from cbbdata.

Files only, never DuckDB: Parquet per season under RAW_DIR/cbbdata/torvik_archive/, and the team
map in config/torvik_teams.csv (Barttorvik name -> ESPN team_id). `map` keeps the rows already
in the CSV (they are the reviewed ones) and appends new names only."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any

from deepsports import config
from deepsports.http import PoliteClient
from deepsports.sources import cbbdata

TEAM_MAP_PATH = config.ROOT / "config" / "torvik_teams.csv"
log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="deepsports torvik", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download season archives (past seasons cached forever)")
    g = f.add_mutually_exclusive_group()
    g.add_argument("--year", type=int, action="append", help="season end year, e.g. 2022")
    g.add_argument("--all", action="store_true", help=f"{cbbdata.FIRST_SEASON} to the current")
    f.add_argument("--refresh", action="store_true", help="refetch even cached past seasons")
    m = sub.add_parser("map", help="update config/torvik_teams.csv from the archive + ESPN cache")
    m.add_argument("--dry-run", action="store_true", help="report only, don't write the CSV")
    sub.add_parser("status", help="rows, teams and dates per cached season")
    return p


def _seasons(args: argparse.Namespace) -> list[int]:
    current = cbbdata.season_of(date.today())
    if args.all:
        return list(range(cbbdata.FIRST_SEASON, current + 1))
    return args.year or [current]


def _fetch(args: argparse.Namespace) -> int:
    key = cbbdata.read_key()
    client = PoliteClient()
    failed = 0
    for year in _seasons(args):
        try:
            path, fetched = cbbdata.fetch_year(client, key, year, refresh=args.refresh)
        except cbbdata.CbbdataError as e:
            print(f"{year}: error: {e}", file=sys.stderr)
            failed += 1
            continue
        n = cbbdata.row_count(path)
        how = "fetched" if fetched else "cached"
        print(f"{year}: {how:7s} {n:6d} rows  {path.stat().st_size:9d} bytes  {path}")
        if n == 0:
            print(
                f"{year}: warning: empty season (cbbdata has no data for it yet)", file=sys.stderr
            )
    print(f"network requests: {client.network_requests}")
    return 1 if failed else 0


def cached_seasons(raw_dir: Path | None = None) -> list[int]:
    d = (raw_dir or config.RAW_DIR) / cbbdata.RAW_SUBDIR
    return sorted(int(p.stem) for p in d.glob("*.parquet") if p.stem.isdigit())


def torvik_names(raw_dir: Path | None = None) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for year in cached_seasons(raw_dir):
        for r in cbbdata.parse_archive(cbbdata.archive_path(year, raw_dir)):
            out.setdefault(r["team"], set()).add(r["season"])
    return out


def espn_teams_from_cache(raw_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    """ESPN college teams: today's list (teams.json.gz) plus every team seen in the cached
    scoreboards, so programs that left D1 or were renamed still have their id."""
    base = (raw_dir or config.RAW_DIR) / "espn" / "ncaab"
    teams: dict[str, dict[str, Any]] = {}

    def add(t: dict[str, Any]) -> None:
        if t.get("id"):
            teams.setdefault(
                str(t["id"]),
                {k: t.get(k) for k in ("location", "shortDisplayName", "displayName")},
            )

    tf = base / "teams.json.gz"
    if tf.exists():
        with gzip.open(tf, "rt", encoding="utf-8") as fh:
            for x in json.load(fh)["sports"][0]["leagues"][0]["teams"]:
                add(x["team"])
    for sb in sorted((base / "scoreboard").glob("*.json.gz")):
        with gzip.open(sb, "rt", encoding="utf-8") as fh:
            for e in json.load(fh).get("events", []):
                for c in e["competitions"][0]["competitors"]:
                    add(c["team"])
    return teams


def load_team_map(path: Path = TEAM_MAP_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["espn_team_id"] = r["espn_team_id"] or None
        r["first_season"], r["last_season"] = int(r["first_season"]), int(r["last_season"])
    return rows


def _map(args: argparse.Namespace) -> int:
    names = torvik_names()
    if not names:
        print("no cached seasons; run `deepsports torvik fetch --all` first", file=sys.stderr)
        return 2
    fresh = {r["torvik_team"]: r for r in cbbdata.match_teams(names, espn_teams_from_cache())}
    kept = load_team_map()
    known = {r["torvik_team"] for r in kept}
    rows = kept + [r for n, r in fresh.items() if n not in known]
    for r in rows:  # season ranges follow the archive; the reviewed id/name stay as they are
        if r["torvik_team"] in names:
            seasons = names[r["torvik_team"]]
            r["first_season"], r["last_season"] = min(seasons), max(seasons)
    rows.sort(key=lambda r: r["torvik_team"])
    added = len(rows) - len(kept)
    unmatched = [r for r in rows if not r["espn_team_id"]]
    by_how: dict[str, int] = {}
    for r in rows:
        by_how[r["match"]] = by_how.get(r["match"], 0) + 1
    print(f"{len(rows)} names ({added} new): {by_how}")
    for year in sorted({y for s in names.values() for y in s}):
        in_year = [r for r in rows if r["torvik_team"] in names and year in names[r["torvik_team"]]]
        miss = sorted(r["torvik_team"] for r in in_year if not r["espn_team_id"])
        print(f"  {year}: {len(in_year) - len(miss)}/{len(in_year)} mapped; unmatched {miss}")
    for tid, pair in cbbdata.map_collisions(rows):
        print(f"  warning: ESPN id {tid} shared in overlapping seasons by {pair}")
    if unmatched:
        print(f"unmatched: {[r['torvik_team'] for r in unmatched]}")
    if args.dry_run:
        return 0
    TEAM_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TEAM_MAP_PATH, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cbbdata.MAP_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) or ("" if k != "first_season" else r[k]) for k in w.fieldnames})
    print(f"wrote {TEAM_MAP_PATH}")
    return 0


def _status() -> int:
    for year in cached_seasons():
        rows = cbbdata.parse_archive(cbbdata.archive_path(year))
        if not rows:
            print(f"{year}: empty")
            continue
        teams = len({r["team"] for r in rows})
        days = len({r["as_of_date"] for r in rows})
        print(
            f"{year}: {len(rows):6d} rows  {teams} teams  {days} days  "
            f"{rows[0]['as_of_date']} .. {rows[-1]['as_of_date']}"
        )
    return 0


def main(argv: list[str]) -> int:
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
    try:
        if args.cmd == "fetch":
            return _fetch(args)
        if args.cmd == "map":
            return _map(args)
        return _status()
    except cbbdata.CbbdataError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
