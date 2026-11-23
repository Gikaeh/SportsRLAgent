"""Venue geography: GeoNames parsing/matching, the scoreboard venue fields, the `venues` build,
team_home_venues and college travel_km. Real GeoNames rows (tests/fixtures/geonames_places_trim.txt,
cut from cities500.zip and US.zip) and real ESPN scoreboards."""

import gzip
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from deepsports.parse_espn import parse_scoreboard, parse_scoreboard_teams, parse_scoreboard_venues
from deepsports.sources import geonames
from deepsports.store import Store
from deepsports.venue_geo import (
    backfill_game_venues,
    cached_scoreboard_venues,
    coverage,
    missing_venue_days,
    replace_venues,
    venue_aggregates,
    venue_rows,
)

FIX = Path(__file__).parent / "fixtures"
UPCOMING = "espn_ncaab_scoreboard_20261108_upcoming.json"  # SMC vs NEV at Stateline, NV


@pytest.fixture(scope="module")
def places():
    return geonames.parse_places((FIX / "geonames_places_trim.txt").read_text().splitlines(True))


@pytest.fixture(scope="module")
def gaz(places):
    return geonames.Gazetteer(places)


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def test_parse_places(places):
    by_id = {p["geonameid"]: p for p in places}
    laramie = by_id[5830062]
    assert (laramie["name"], laramie["country"], laramie["admin1"]) == ("Laramie", "US", "WY")
    assert laramie["timezone"] == "America/Denver"
    assert geonames.elevation_m(laramie) == 2184
    paris = by_id[2988507]
    assert paris["elevation"] is None and geonames.elevation_m(paris) == 42  # DEM fallback
    assert "New York" in by_id[5128581]["alternatenames"]


def test_norm():
    assert geonames.norm("St. Bonaventure") == geonames.norm("Saint Bonaventure")
    assert geonames.norm("Ste. Genevieve") == "saintegenevieve"
    assert geonames.norm("Mt. Pleasant") == "mountpleasant"
    assert geonames.norm("Bayamón") == "bayamon"
    assert geonames.norm("Winston-Salem") == "winstonsalem"


def test_match_rules(gaz):
    p, how = gaz.match("Laramie", "WY")
    assert (p["geonameid"], how) == (5830062, "name")
    # two Statelines in NV: the more populous wins
    assert gaz.match("Stateline", "NV")[0]["geonameid"] == 5512994
    # ESPN "New York" is GeoNames' "New York City" by its alternate names
    p, how = gaz.match("New York", "NY")
    assert (p["name"], how) == ("New York City", "alternate")
    # Morehead KY: the populous western-KY place is wrong; the override picks Morehead State's
    p, how = gaz.match("Morehead", "KY")
    assert (p["geonameid"], p["timezone"], how) == (4301307, "America/New_York", "override")
    p, how = gaz.match("Maui", "HI")  # Lahaina Civic Center
    assert (p["name"], how) == ("Lahaina", "override")
    # Air Force: the venue override beats the city (Colorado Springs, 1,832 m)
    assert gaz.match("Colorado Springs", "CO")[0]["name"] == "Colorado Springs"
    p, how = gaz.match("Colorado Springs", "CO", "2014")
    assert (p["name"], geonames.elevation_m(p), how) == (
        "Air Force Academy",
        2069,
        "venue_override",
    )
    p, how = gaz.match("Nassau", "Bahamas")
    assert (p["country"], p["timezone"]) == ("BS", "America/Nassau")
    # no state (NBA games abroad): big cities only
    p, how = gaz.match("Paris", None)
    assert (p["country"], how) == ("FR", "big_city")
    assert gaz.match("Laramie", None) == (None, "no state")
    assert gaz.match(None, "WY") == (None, "no city")
    assert gaz.match("Melbourne", "Narnia") == (None, "unknown region")
    assert gaz.match("Nowhere", "WY") == (None, "no match")


def test_scoreboard_venue_fields():
    raw = load(UPCOMING)
    games, _ = parse_scoreboard(raw, league="ncaab")
    venues = {r["game_id"]: r for r in parse_scoreboard_venues(raw)}
    assert len(venues) == len(games) == len(raw["events"])
    for g in games:
        v = venues[g["game_id"]]
        assert (g["venue_id"], g["venue_state"]) == (v["venue_id"], v["venue_state"])
        assert g["venue_id"] and g["venue_state"]
    stateline = [g for g in games if g["venue_city"] == "Stateline"]
    assert stateline and stateline[0]["venue_state"] == "NV"


def _store_with_upcoming() -> Store:
    raw = load(UPCOMING)
    db = Store(":memory:")
    teams = parse_scoreboard_teams(raw, "ncaab")
    db.upsert_teams([{**t, "listed": True} for t in teams])
    games, _ = parse_scoreboard(raw, league="ncaab")
    db.upsert_games(games)
    return db


def test_build_backfills_and_geocodes(tmp_path, gaz):
    raw = load(UPCOMING)
    db = _store_with_upcoming()
    # rows stored before the columns existed have NULLs: rebuild them from the cached scoreboard
    db.con.execute("UPDATE games SET venue_id = NULL, venue_state = NULL")
    days = missing_venue_days(db.con)
    assert set(days) == {"ncaab"} and date(2026, 11, 8) in days["ncaab"]
    sb = tmp_path / "espn" / "ncaab" / "scoreboard"
    sb.mkdir(parents=True)
    with gzip.open(sb / "20261108.json.gz", "wt") as f:  # the cache layout: one file per day
        json.dump(raw, f)
    found = cached_scoreboard_venues(days, raw_dir=tmp_path)
    assert backfill_game_venues(db.con, found) == len(raw["events"])
    assert backfill_game_venues(db.con, found) == 0  # idempotent
    assert db.con.execute("SELECT count(*) FROM games WHERE venue_id IS NULL").fetchone()[0] == 0

    aggs = venue_aggregates(db.con)
    rows = venue_rows(aggs, gaz, now=datetime(2026, 11, 22, tzinfo=UTC))
    assert replace_venues(db, rows) == len(aggs)
    assert replace_venues(db, rows) == len(aggs)  # replaces, never duplicates
    v = db.con.execute(
        "SELECT city, state, country, elevation_m, tz, geo_match FROM venues"
        " WHERE city = 'Stateline'"
    ).fetchone()
    assert v == ("Stateline", "NV", "US", 1915, "America/Los_Angeles", "name")
    cov = coverage(db.con, "ncaab")
    assert cov["venues"] == len(aggs) == cov["venues_geocoded"] == cov["venues_with_elevation"]
    assert cov["incomplete"] == []
    ((season, games, with_id, geo, elev, tz),) = cov["per_season"]
    assert games == with_id == geo == elev == tz == len(raw["events"])

    # every non-neutral home team gets its venue for the season
    home = db.con.execute(
        "SELECT count(*), bool_and(share = 1) FROM team_home_venues WHERE league = 'ncaab'"
    ).fetchone()
    non_neutral = db.con.execute(
        "SELECT count(DISTINCT home_team_id) FROM games WHERE NOT neutral_site"
    ).fetchone()[0]
    assert home == (non_neutral, True)
    db.close()


def test_college_travel_km_uses_venue_ids(gaz):
    """A team's second game gets the great-circle km between the two venues' cities."""
    db = Store(":memory:")
    now = datetime(2026, 11, 1, tzinfo=UTC)
    db.upsert_teams(
        [
            {"team_id": t, "league": "ncaab", "abbreviation": t, "display_name": t, "listed": True}
            for t in ("A", "B", "C")
        ]
    )
    base = {
        "league": "ncaab",
        "season_year": 2027,
        "season_type": 2,
        "status": "STATUS_FINAL",
        "state": "post",
        "completed": True,
        "home_score": 70,
        "away_score": 60,
        "neutral_site": False,
        "attendance": None,
        "broadcasts": None,
    }
    db.upsert_games(
        [
            {**base, "game_id": "g1", "start_time_utc": datetime(2026, 11, 3, 2, tzinfo=UTC),
             "home_team_id": "A", "away_team_id": "B", "venue": "Arena-Auditorium",
             "venue_city": "Laramie", "venue_id": "100", "venue_state": "WY"},
            {**base, "game_id": "g2", "start_time_utc": datetime(2026, 11, 6, 2, tzinfo=UTC),
             "home_team_id": "C", "away_team_id": "B", "venue": "The Pit",
             "venue_city": "Albuquerque", "venue_id": "200", "venue_state": "NM"},
        ]
    )  # fmt: skip
    replace_venues(db, venue_rows(venue_aggregates(db.con), gaz, now=now))
    km = db.con.execute(
        "SELECT travel_km FROM team_game_context WHERE game_id = 'g2' AND team_id = 'B'"
    ).fetchone()[0]
    assert 690 < km < 720  # Laramie -> Albuquerque, ~705 km
    first = db.con.execute(
        "SELECT travel_km FROM team_game_context WHERE game_id = 'g1' AND team_id = 'B'"
    ).fetchone()[0]
    assert first is None
    db.close()


def test_fetch_downloads_once(tmp_path):
    """Two GET requests (one per dump), then cached on disk."""
    import io
    import zipfile

    import httpx

    from deepsports.http import PoliteClient

    def body(name: str) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(f"{name}.txt", (FIX / "geonames_places_trim.txt").read_text())
        return buf.getvalue()

    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200, content=body(req.url.path.rsplit("/", 1)[1][:-4]))

    client = PoliteClient(
        raw_dir=tmp_path,
        min_interval=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda s: None,
    )
    got = geonames.fetch(client, raw_dir=tmp_path)
    assert [f for _, f in got] == [True, True] and len(seen) == 2
    assert [f for _, f in geonames.fetch(client, raw_dir=tmp_path)] == [False, False]
    assert len(seen) == 2
    gaz = geonames.load_gazetteer(tmp_path)
    assert gaz.match("Laramie", "WY")[0]["timezone"] == "America/Denver"
