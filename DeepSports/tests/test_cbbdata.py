"""cbbdata Barttorvik archive: parser on a trimmed real response, fetch caching and key hygiene,
team matching against ESPN's real team list."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from deepsports.http import PoliteClient
from deepsports.sources import cbbdata

FIX = Path(__file__).parent / "fixtures"
ARCHIVE = FIX / "cbbdata_torvik_archive_2022_trim.parquet"
KEY = "secret-key-123"


def test_parse_archive_real_rows():
    rows = cbbdata.parse_archive(ARCHIVE)
    assert len(rows) == 6
    assert set(rows[0]) == set(cbbdata.COLUMNS)
    nev = [r for r in rows if r["team"] == "Nevada"]
    assert [r["as_of_date"] for r in nev] == [date(2021, 11, d) for d in (8, 9, 10)]
    # Nevada beat Texas A&M-CC on 2021-11-09: the row dated the 9th already counts it
    assert [(r["wins"], r["losses"]) for r in nev] == [(0, 0), (1, 0), (1, 0)]
    first = nev[0]
    assert first["season"] == 2022 and first["conf"] == "MWC" and first["rank"] == 63
    assert first["adj_tempo"] == pytest.approx(71.734, abs=1e-3)
    assert first["adj_o"] == pytest.approx(106.110, abs=1e-3)
    assert first["adj_d"] == pytest.approx(96.050, abs=1e-3)
    assert 0 < first["barthag"] < 1
    assert rows == sorted(rows, key=lambda r: (r["as_of_date"], r["team"]))


def test_record_parsing():
    assert cbbdata._record("12-3") == (12, 3)
    assert cbbdata._record("NA") == (None, None)
    assert cbbdata._record(None) == (None, None)


def test_season_of():
    assert cbbdata.season_of(date(2026, 11, 19)) == 2027
    assert cbbdata.season_of(date(2027, 3, 1)) == 2027
    assert cbbdata.season_of(date(2026, 6, 30)) == 2026


def _client(handler, calls):
    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    return PoliteClient(
        client=httpx.Client(transport=httpx.MockTransport(wrapped)),
        sleep=lambda s: None,
        max_retries=1,
    )


def test_fetch_year_caches_past_seasons_and_refetches_current(tmp_path):
    body = ARCHIVE.read_bytes()
    calls: list[httpx.Request] = []
    client = _client(lambda r: httpx.Response(200, content=body), calls)
    today = date(2026, 11, 19)
    path, fetched = cbbdata.fetch_year(client, KEY, 2022, today=today, raw_dir=tmp_path)
    assert fetched and path == tmp_path / "cbbdata" / "torvik_archive" / "2022.parquet"
    assert KEY not in str(path) and path.read_bytes() == body
    assert calls[0].url.params["year"] == "2022" and calls[0].url.params["key"] == KEY
    _, fetched = cbbdata.fetch_year(client, KEY, 2022, today=today, raw_dir=tmp_path)
    assert not fetched and len(calls) == 1  # past season: cached forever
    _, fetched = cbbdata.fetch_year(client, KEY, 2027, today=today, raw_dir=tmp_path)
    _, fetched = cbbdata.fetch_year(client, KEY, 2027, today=today, raw_dir=tmp_path)
    assert fetched and len(calls) == 3  # current season: refetched each time


def test_fetch_year_rejects_non_parquet_without_leaking_key(tmp_path):
    calls: list[httpx.Request] = []
    msg = json.dumps({"error": f"bad key {KEY}"}).encode()
    client = _client(lambda r: httpx.Response(200, content=msg), calls)
    with pytest.raises(cbbdata.CbbdataError) as e:
        cbbdata.fetch_year(client, KEY, 2022, today=date(2026, 11, 19), raw_dir=tmp_path)
    assert KEY not in str(e.value) and "***" in str(e.value)
    assert not (tmp_path / "cbbdata" / "torvik_archive" / "2022.parquet").exists()


def test_fetch_error_never_quotes_key(tmp_path):
    calls: list[httpx.Request] = []
    client = _client(lambda r: httpx.Response(401, text="nope"), calls)
    with pytest.raises(cbbdata.CbbdataError) as e:
        cbbdata.fetch_year(client, KEY, 2022, raw_dir=tmp_path)
    assert KEY not in str(e.value) and "401" in str(e.value)


def test_read_key(tmp_path):
    p = tmp_path / "cbbdata.key"
    p.write_text(f"{KEY}\n")
    assert cbbdata.read_key(p) == KEY
    with pytest.raises(cbbdata.CbbdataError):
        cbbdata.read_key(tmp_path / "missing")


def test_normalize_name():
    assert cbbdata.normalize_name("Alabama St.") == cbbdata.normalize_name("Alabama State")
    assert cbbdata.normalize_name("Texas A&M") == "texas aandm"
    # applied to both sides, so "St." as "Saint" still matches ESPN's spelling
    assert cbbdata.normalize_name("Mount St. Mary's") == cbbdata.normalize_name("Mount St. Mary's")
    assert cbbdata.normalize_name("St. John's") == "state johns"


def _espn_teams() -> dict[str, dict]:
    d = json.loads((FIX / "espn_ncaab_teams.json").read_text())
    return {
        x["team"]["id"]: {k: x["team"].get(k) for k in ("location", "shortDisplayName")}
        | {"displayName": x["team"]["displayName"]}
        for x in d["sports"][0]["leagues"][0]["teams"]
    }


def test_match_teams_against_real_espn_list():
    seasons = {
        "Nevada": {2022},
        "Alabama St.": {2022},
        "Connecticut": {2015, 2025},
        "Miami OH": {2022},
        "Savannah St.": {2015},
        "Nowhere Tech": {2022},
    }
    rows = {r["torvik_team"]: r for r in cbbdata.match_teams(seasons, _espn_teams())}
    assert rows["Nevada"]["match"] == "auto" and rows["Nevada"]["espn_name"].startswith("Nevada")
    assert rows["Alabama St."]["espn_name"] == "Alabama State Hornets"
    assert rows["Connecticut"] == {
        "torvik_team": "Connecticut",
        "espn_team_id": "41",
        "espn_name": "UConn Huskies",
        "match": "manual",
        "first_season": 2015,
        "last_season": 2025,
    }
    assert rows["Miami OH"]["espn_team_id"] == "193"
    assert rows["Savannah St."]["espn_team_id"] is None and rows["Savannah St."]["match"] == "none"
    assert rows["Nowhere Tech"]["match"] == "none"


def test_map_collisions_only_for_overlapping_seasons():
    rows = [
        {"torvik_team": "IPFW", "espn_team_id": "2870", "first_season": 2015, "last_season": 2018},
        {"torvik_team": "FW", "espn_team_id": "2870", "first_season": 2019, "last_season": 2020},
        {"torvik_team": "Dup", "espn_team_id": "2870", "first_season": 2020, "last_season": 2021},
    ]  # fmt: skip
    assert cbbdata.map_collisions(rows) == [("2870", ["FW", "Dup"])]


def test_team_map_csv_is_complete_and_collision_free():
    from deepsports.torvik_cli import TEAM_MAP_PATH, load_team_map

    rows = load_team_map(TEAM_MAP_PATH)
    assert len(rows) >= 379
    assert cbbdata.map_collisions(rows) == []
    unmatched = {r["torvik_team"] for r in rows if not r["espn_team_id"]}
    assert unmatched <= {"Savannah St."}
