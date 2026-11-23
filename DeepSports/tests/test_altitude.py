"""Altitude features (deepsports.analysis.altitude): bands, gain/drop, time zones, home-arena
lookup, and the warehouse loader on a tiny in-memory DuckDB."""

import math
from datetime import UTC, datetime

import duckdb

from deepsports.analysis.altitude import (
    ALTITUDE_FEATURES,
    attach,
    band,
    game_features,
    load_altitude_features,
    nearest_season,
)

WHEN = datetime(2026, 1, 10, 3, tzinfo=UTC)


def test_band_edges():
    assert band(799) == "<800"
    assert band(800) == "800-1200"
    assert band(1200) == "1200-1500"
    assert band(1500) == "1500+"
    assert band(None) == "na"


def test_low_team_at_altitude():
    # Laramie home game vs a sea-level visitor
    f = game_features(
        2184, "America/Denver", (2184, "America/Denver"), (10, "America/New_York"), WHEN
    )
    assert f["venue_elev_km"] == 2.184
    assert (f["alt_b800"], f["alt_b1200"], f["alt_b1500"]) == (0.0, 0.0, 1.0)
    assert math.isclose(f["alt_gain_sum"], 2.174)
    assert f["alt_drop_sum"] == 0.0
    assert f["tz_cross_sum"] == 2.0  # visitor from Eastern, home team at home


def test_altitude_school_on_the_road():
    f = game_features(
        100, "America/Chicago", (100, "America/Chicago"), (1609, "America/Denver"), WHEN
    )
    assert f["alt_gain_sum"] == 0.0
    assert math.isclose(f["alt_drop_sum"], 1.509)
    assert f["alt_b1200"] == 0.0
    assert f["tz_cross_sum"] == 1.0


def test_unknown_inputs_are_nan():
    f = game_features(None, None, None, (10, "America/New_York"), WHEN)
    assert math.isnan(f["venue_elev_km"]) and math.isnan(f["alt_b1500"])
    assert math.isnan(f["alt_gain_sum"]) and math.isnan(f["tz_cross_sum"])
    assert math.isnan(f["home_elev_h"]) and f["home_elev_a"] == 0.01


def test_nearest_season_prefers_same_then_earlier():
    homes = {("t", 2024): (1, "x"), ("t", 2026): (2, "y")}
    assert nearest_season(homes, "t", 2026) == (2, "y")
    assert nearest_season(homes, "t", 2025) == (1, "x")
    assert nearest_season(homes, "t", 2027) == (2, "y")
    assert nearest_season(homes, "u", 2026) is None


def test_loader_and_attach():
    con = duckdb.connect()
    con.execute(
        "create table venues(venue_id varchar, elevation_m integer, tz varchar);"
        "insert into venues values ('hi', 1600, 'America/Denver'), ('lo', 50, 'America/New_York');"
        "create table games(game_id varchar, league varchar, season_year integer,"
        " start_time_utc timestamptz, home_team_id varchar, away_team_id varchar,"
        " venue_id varchar, neutral_site boolean, status varchar);"
    )
    t = "2026-01-10 03:00:00+00"
    con.execute(
        "insert into games values"
        f" ('g1','ncaab',2026,'{t}','A','B','hi',false,'STATUS_FINAL'),"
        f" ('g2','ncaab',2026,'{t}','B','A','lo',false,'STATUS_FINAL'),"
        f" ('g3','ncaab',2026,'{t}','A','B','lo',true,'STATUS_FINAL')"
    )
    f = load_altitude_features(con)
    assert math.isclose(f["g1"]["alt_gain_sum"], 1.55)  # B (home 50 m) at A's 1600 m arena
    assert math.isclose(f["g2"]["alt_drop_sum"], 1.55)  # A down at B's arena
    assert f["g3"]["home_elev_h"] == 1.6  # neutral game doesn't define a home arena
    rows = [{"game_id": "g1", "features": {}}, {"game_id": "zz", "features": {}}]
    attach(rows, f)
    assert set(rows[0]["features"]) == set(ALTITUDE_FEATURES)
    assert all(math.isnan(v) for v in rows[1]["features"].values())
