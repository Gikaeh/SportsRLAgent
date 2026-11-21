"""The Odds API historical pull: pure parser (a real live response + a SYNTHETIC historical one
shaped like the documented response, since the free plan has no history access), planner,
cost, key hygiene, and the resumable pull loop against a mocked API."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime, time
from pathlib import Path

import httpx
import pytest

from deepsports import config, oddsapi_cli
from deepsports.http import PoliteClient
from deepsports.sources import oddsapi_history as oah

FIX = Path(__file__).parent / "fixtures"
LIVE = FIX / "oddsapi_live_ncaab_totals_us_20261119.json"  # real, trimmed to 2 events
HIST = FIX / "oddsapi_historical_ncaab_synthetic.json"  # SYNTHETIC: documented shape, made up
KEY = "k3y-0123456789abcdef"


def test_parse_live_real_response():
    data = json.loads(LIVE.read_text())
    now = datetime(2026, 11, 19, 21, 24, 39, tzinfo=UTC)
    rows = oah.parse_snapshot(data, now)
    assert rows and set(rows[0]) == set(oah.ROW_COLUMNS)
    assert all(r["snapshot_ts"] == now and r["market"] == "totals" for r in rows)
    nd = [r for r in rows if r["home_team"] == "Notre Dame Fighting Irish"]
    assert {r["away_team"] for r in nd} == {"Auburn Tigers"}
    fd = [r for r in nd if r["book"] == "fanduel"]
    assert {(r["outcome"], r["point"], r["price"]) for r in fd} == {
        ("Over", 151.5, -110),
        ("Under", 151.5, -110),
    }
    assert fd[0]["market_last_update"] == datetime(2026, 11, 19, 21, 24, 15, tzinfo=UTC)
    assert fd[0]["commence_time"] == datetime(2026, 11, 19, 22, 0, tzinfo=UTC)
    # every totals outcome carries a point and an integer American price
    assert all(isinstance(r["point"], float) and isinstance(r["price"], int) for r in rows)


def test_parse_historical_synthetic():
    rows = oah.parse_snapshot(json.loads(HIST.read_text()))
    snap = datetime(2022, 1, 15, 4, 55, tzinfo=UTC)
    assert {r["snapshot_ts"] for r in rows} == {snap}
    assert len(rows) == 8  # DK totals+spreads, Pinnacle totals, FD totals; UNLV has no books
    spread = [r for r in rows if r["market"] == "spreads"]
    assert {(r["outcome"], r["point"], r["price"]) for r in spread} == {
        ("Nevada Wolf Pack", 4.5, -108),
        ("San Diego St Aztecs", -4.5, -112),
    }
    pin = [r for r in rows if r["book"] == "pinnacle"]
    assert {r["point"] for r in pin} == {131.0}
    assert {r["event_id"] for r in rows} == {
        "0a1b2c3d4e5f60718293a4b5c6d7e8f9",
        "f9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4",
    }


def test_coverage_uses_eastern_game_day():
    data = json.loads(HIST.read_text())
    cov = oah.coverage(data, date(2022, 1, 15), "totals")
    assert cov["events"] == 3 and cov["with_market"] == 2  # 01:00Z/02:00Z are Jan 15 ET
    assert cov["per_book"] == {"draftkings": 1, "pinnacle": 1, "fanduel": 1}
    assert oah.coverage(data, date(2022, 1, 15), "spreads")["with_market"] == 1
    assert oah.coverage(data, date(2022, 1, 16))["events"] == 0


def test_snapshot_times_pacific_and_dst():
    days = [date(2022, 1, 15), date(2025, 11, 3), date(2022, 3, 14)]
    got = oah.snapshot_times(days)
    assert datetime(2022, 1, 15, 5, 0, tzinfo=UTC) in got  # 21:00 PST Jan 14
    assert datetime(2022, 1, 15, 17, 0, tzinfo=UTC) in got  # 09:00 PST Jan 15
    assert datetime(2025, 11, 3, 5, 0, tzinfo=UTC) in got  # Nov 2 is PST already
    assert datetime(2022, 3, 14, 4, 0, tzinfo=UTC) in got  # Mar 13 21:00 is PDT
    assert got == sorted(set(got)) and len(got) == 6
    # consecutive days: night-before of day 2 is not the morning of day 1
    assert len(oah.snapshot_times([date(2022, 1, 15), date(2022, 1, 16)])) == 4


def test_parse_times_and_cost():
    assert oah.parse_times("-1@21:00, 0@9") == ((-1, time(21, 0)), (0, time(9, 0)))
    assert oah.cost(100, ["totals"], ["us"]) == 1000
    assert oah.cost(100, ["totals", "spreads"], ["us", "eu"]) == 4000
    ten = [f"b{i}" for i in range(10)]
    assert oah.cost(1, ["totals"], ["us", "eu"], ten) == 10  # 10 books = one region
    assert oah.cost(1, ["totals"], ["us"], [*ten, "x"]) == 20
    assert oah.scope_label(["us", "eu"]) == "us,eu"
    assert oah.scope_label(["us"], ["pinnacle", "draftkings"]) == "books=draftkings,pinnacle"


def _scoreboard(dirpath: Path, ymd: str, types: list[int]) -> None:
    dirpath.mkdir(parents=True, exist_ok=True)
    body = {"events": [{"season": {"year": 2022, "type": t}} for t in types]}
    with gzip.open(dirpath / f"{ymd}.json.gz", "wt") as fh:
        json.dump(body, fh)


def test_game_days_from_cache_and_window(tmp_path):
    sb = tmp_path / "scoreboard"
    for d in range(1, 31):
        _scoreboard(sb, f"202111{d:02d}", [2] if d % 2 else [])
    _scoreboard(sb, "20211015", [1, 1])  # preseason-only day (outside the window anyway)
    cached = oah.scoreboard_game_days(sb)
    assert cached[date(2021, 11, 2)] == 0 and cached[date(2021, 10, 15)] == 0
    out = oah.game_days("ncaab", [2022, 2023], cached)
    days, src = out[2022]
    assert src == "espn" and len(days) == 15 and days[0] == date(2021, 11, 1)
    days, src = out[2023]
    assert src == "window" and days[0] == date(2022, 11, 1) and days[-1] == date(2023, 4, 10)


def test_read_key_env_then_file(tmp_path):
    f = tmp_path / "oddsapi.key"
    assert oah.read_key(f, {"ODDS_API_KEY": " abc "}) == "abc"
    with pytest.raises(oah.OddsApiError, match="ODDS_API_KEY"):
        oah.read_key(f, {})
    f.write_text(KEY + "\n")
    f.chmod(0o600)
    assert oah.read_key(f, {}) == KEY


def _client(handler) -> PoliteClient:
    return PoliteClient(
        raw_dir=Path("/nonexistent"),
        min_interval=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda s: None,
    )


def test_fetch_historical_headers_and_key_hygiene():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(dict(req.url.params))
        if req.url.params.get("date") == "2022-01-15T05:00:00Z":
            return httpx.Response(
                200,
                json=json.loads(HIST.read_text()),
                headers={
                    "x-requests-remaining": "99960",
                    "x-requests-used": "40",
                    "x-requests-last": "20",
                },
            )
        return httpx.Response(401, json={"message": f"bad key {KEY}"})

    c = _client(handler)
    ts = datetime(2022, 1, 15, 5, 0, tzinfo=UTC)
    data, cr = oah.fetch_historical(c, KEY, "basketball_ncaab", ts, ["totals"], ["us", "eu"])
    assert data["timestamp"] == "2022-01-15T04:55:00Z"
    assert cr == oah.Credits(99960, 40, 20)
    assert seen[0]["regions"] == "us,eu" and seen[0]["oddsFormat"] == "american"
    with pytest.raises(oah.OddsApiError) as e:
        oah.fetch_historical(
            c, KEY, "basketball_ncaab", datetime(2022, 1, 1, tzinfo=UTC), ["totals"], ["us"]
        )
    assert "401" in str(e.value) and KEY not in str(e.value)


def test_bookmakers_param_replaces_regions():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(dict(req.url.params))
        return httpx.Response(200, json=[], headers={"x-requests-last": "0"})

    oah.fetch_live(_client(handler), KEY, "basketball_nba", ["totals"], ["us"], ["pinnacle"])
    assert seen[0]["bookmakers"] == "pinnacle" and "regions" not in seen[0]


def test_pull_resumes_and_respects_reserve(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "RAW_DIR", tmp_path)
    sb = tmp_path / "espn" / "ncaab" / "scoreboard"
    for d in range(1, 31):
        _scoreboard(sb, f"202111{d:02d}", [2] if d in (10, 11, 12) else [])
    state = {"remaining": 1000, "calls": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        hdr = {"x-requests-used": "0"}
        if req.url.path == "/v4/sports":
            hdr |= {"x-requests-remaining": str(state["remaining"]), "x-requests-last": "0"}
            return httpx.Response(200, json=[], headers=hdr)
        state["calls"] += 1
        state["remaining"] -= 10
        hdr |= {"x-requests-remaining": str(state["remaining"]), "x-requests-last": "10"}
        body = {
            "timestamp": req.url.params["date"],
            "previous_timestamp": None,
            "next_timestamp": None,
            "data": [],
        }
        return httpx.Response(200, json=body, headers=hdr)

    monkeypatch.setattr(oddsapi_cli, "PoliteClient", lambda: _client(handler))
    monkeypatch.setattr(oah, "read_key", lambda: KEY)
    base = [
        "pull",
        "--league",
        "ncaab",
        "--season",
        "2022",
        "--markets",
        "totals",
        "--regions",
        "us",
    ]

    assert oddsapi_cli.main([*base, "--reserve", "975"]) == 0
    assert state["calls"] == 2  # 1000 -> 990 -> 980; a third would leave 970 < 975
    files = sorted((tmp_path / "oddsapi/historical/basketball_ncaab/totals/us").glob("*.json.gz"))
    # night-before snapshots go first: 21:00 PST Nov 9 and Nov 10
    assert [f.name for f in files] == ["20211110T050000Z.json.gz", "20211111T050000Z.json.gz"]

    assert oddsapi_cli.main([*base, "--reserve", "0"]) == 0
    assert state["calls"] == 6  # resumed: only the 4 missing (3 days x 2 times = 6 total)
    ledger = oah.read_ledger()
    assert len(ledger) == 6 and ledger[-1]["remaining"] == 940
    assert all(KEY not in json.dumps(e) for e in ledger)
    out = capsys.readouterr().out
    assert KEY not in out and "remaining=940" in out

    assert oddsapi_cli.main(["status"]) == 0
    assert "6 snapshots" in capsys.readouterr().out
