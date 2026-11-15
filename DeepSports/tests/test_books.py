"""OddsPapi book lines: parser on saved real responses, game matching, grab, moon merge, picks."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from deepsports.analysis import model_picks as mp
from deepsports.books import grab, oddspapi
from deepsports.http import FetchError
from deepsports.moon import circa as moon_circa

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text())


MARKETS = _load("oddspapi_markets_basketball_subset.json")
CIRCA = _load("oddspapi_odds_circasports_20261115.json")
CAESARS = _load("oddspapi_odds_caesars_20261115.json")
INDEX = oddspapi.market_index(MARKETS)


def _team(abbr, display, location, name):
    return {"abbr": abbr, "display_name": display, "location": location, "name": name}


# Warehouse-shaped candidates. PHI hosts IND; LAL host PHX (OddsPapi lists PHX first).
CANDS = [
    {
        "game_id": "401",
        "league": "nba",
        "start_time_utc": datetime(2026, 11, 15, 18, tzinfo=UTC),
        "home": _team("PHI", "Philadelphia 76ers", "Philadelphia", "76ers"),
        "away": _team("IND", "Indiana Pacers", "Indiana", "Pacers"),
    },
    {
        "game_id": "402",
        "league": "nba",
        "start_time_utc": datetime(2026, 11, 15, 21, tzinfo=UTC),
        "home": _team("LAL", "Los Angeles Lakers", "Los Angeles", "Lakers"),
        "away": _team("PHX", "Phoenix Suns", "Phoenix", "Suns"),
    },
    {
        "game_id": "403",
        "league": "ncaab",
        "start_time_utc": datetime(2026, 11, 15, 17, tzinfo=UTC),
        "home": _team("QUIN", "Quinnipiac Bobcats", "Quinnipiac", "Bobcats"),
        "away": _team(
            "CCSU", "Central Connecticut Blue Devils", "Central Connecticut", "Blue Devils"
        ),
    },
]


def _by(lines, gid, market, side):
    return next(
        q for q in lines if q["game_id"] == gid and q["market"] == market and q["side"] == side
    )


def test_parse_circa_main_lines():
    rows = oddspapi.parse_fixtures(CIRCA, "circasports", INDEX)
    phi = [r for r in rows if r["p1"] == "Philadelphia 76ers"]
    got = {(r["market"], r["who"]): (r["line"], r["price"]) for r in phi}
    assert got[("spread", "1")] == (-7.5, -110)
    assert got[("spread", "2")] == (7.5, -110)  # participant 2 gets the mirrored line
    assert got[("total", "over")] == (224.5, -110)
    assert got[("moneyline", "1")] == (None, -280)
    assert got[("moneyline", "2")] == (None, 235)
    assert {r["league"] for r in rows} == {"nba"}  # women's college (21384) is skipped


def test_parse_skips_pulled_prices_and_alt_lines():
    rows = oddspapi.parse_fixtures(CAESARS, "caesars", INDEX)
    ccsu = [r for r in rows if r["p1"].startswith("Central Connecticut")]
    # The saved Caesars board had its moneyline pulled (active false) and an inactive 135 total.
    assert not [r for r in ccsu if r["market"] == "moneyline"]
    assert {r["line"] for r in ccsu if r["market"] == "total"} == {133.5}
    assert {(r["who"], r["line"]) for r in ccsu if r["market"] == "spread"} == {
        ("1", 4.5),
        ("2", -4.5),
    }
    assert len({(r["fixture_id"], r["market"], r["who"]) for r in rows}) == len(rows)


def test_parse_skips_started_and_suspended():
    started = json.loads(json.dumps(CIRCA[:1]))
    started[0]["statusId"] = 1
    assert oddspapi.parse_fixtures(started, "circasports", INDEX) == []
    sus = json.loads(json.dumps(CIRCA[:1]))
    sus[0]["bookmakerOdds"]["circasports"]["suspended"] = True
    assert oddspapi.parse_fixtures(sus, "circasports", INDEX) == []


def test_to_lines_orients_to_warehouse_game():
    rows = oddspapi.parse_fixtures(CIRCA, "circasports", INDEX)
    lines, unmatched = grab.to_lines(rows, CANDS)
    assert unmatched == 0
    assert _by(lines, "401", "spread", "home")["line"] == -7.5  # PHI is participant 1 and home
    assert _by(lines, "401", "moneyline", "away")["price"] == 235
    # PHX is participant 1 but the away team: the matcher flips the sides.
    assert _by(lines, "402", "spread", "away")["line"] == 2.5
    assert _by(lines, "402", "spread", "home")["line"] == -2.5
    assert _by(lines, "402", "moneyline", "home")["price"] == -145
    assert _by(lines, "402", "total", "over")["line"] == 226
    assert set(lines[0]) == {
        "game_id",
        "league",
        "away",
        "home",
        "market",
        "side",
        "line",
        "price",
        "rotation",
    }


def test_to_lines_drops_unmatched_and_far_starts():
    rows = oddspapi.parse_fixtures(CIRCA, "circasports", INDEX)
    lines, unmatched = grab.to_lines(rows, CANDS[2:])  # no NBA candidates
    assert lines == [] and unmatched == 2
    late = [dict(CANDS[0], start_time_utc=datetime(2026, 11, 16, 18, tzinfo=UTC))]
    lines, unmatched = grab.to_lines(rows, late)  # same teams, a day later: not this game
    assert not [q for q in lines if q["game_id"] == "401"]


class FakeClient:
    """Stands in for PoliteClient: answers by path, counts calls, can fail like FetchError."""

    def __init__(self, fail_slug=None):
        self.network_requests = 0
        self.calls = []
        self.fail_slug = fail_slug

    def get_json(self, url, params=None, *, cache_key, cache_ok=None):
        self.network_requests += 1
        self.calls.append((url, dict(params)))
        if url.endswith("/markets"):
            return MARKETS
        if params.get("bookmaker") == self.fail_slug:
            raise FetchError(f"{url} params={params}: HTTP 429")
        return CIRCA if params["bookmaker"] == "circasports" else CAESARS


def test_grab_day_writes_both_books(tmp_path, monkeypatch):
    monkeypatch.setattr("deepsports.config.BOOKS_DIR", tmp_path)
    fake = FakeClient()
    res = grab.grab_day(
        date(2026, 11, 15), client=fake, key="SECRETKEY", candidates=lambda d: CANDS
    )
    assert res.ok, res.message
    circa = grab.load("circa", date(2026, 11, 15))
    wh = grab.load("williamhill", date(2026, 11, 15))
    assert circa["source_book"] == "circasports" and wh["source_book"] == "caesars"
    assert _by(circa["lines"], "401", "spread", "home")["line"] == -7.5
    assert _by(wh["lines"], "403", "spread", "away")["line"] == 4.5  # CCSU is participant 1, away
    assert fake.network_requests == 3  # markets + one call per book
    assert all(p["apiKey"] == "SECRETKEY" for _, p in fake.calls)
    assert "SECRETKEY" not in (tmp_path / "circa" / "2026-11-15.json").read_text()


def test_grab_day_hides_the_key_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("deepsports.config.BOOKS_DIR", tmp_path)
    res = grab.grab_day(
        date(2026, 11, 15),
        client=FakeClient(fail_slug="caesars"),
        key="SECRETKEY",
        candidates=lambda d: CANDS,
    )
    assert not res.ok
    assert "SECRETKEY" not in res.message + " ".join(res.problems)
    assert "***" in " ".join(res.problems)
    assert grab.load("circa", date(2026, 11, 15)) is not None  # the other book still landed
    assert grab.load("williamhill", date(2026, 11, 15)) is None


def test_grab_day_without_key_or_games(tmp_path, monkeypatch):
    monkeypatch.setattr("deepsports.config.ODDSPAPI_KEY_FILE", tmp_path / "missing")
    res = grab.grab_day(date(2026, 11, 15), client=FakeClient(), candidates=lambda d: CANDS)
    assert not res.ok and "no OddsPapi key" in res.message

    def busy(d):
        raise RuntimeError("lock")

    res = grab.grab_day(date(2026, 11, 15), client=FakeClient(), key="K", candidates=busy)
    assert not res.ok and "no games to match" in res.message


def test_unknown_markets_counts_only_ids_missing_from_catalogue():
    assert oddspapi.unknown_markets(CIRCA, "circasports", MARKETS) == 0
    odd = json.loads(json.dumps(CIRCA[:1]))
    odd[0]["bookmakerOdds"]["circasports"]["markets"]["99999999"] = {"outcomes": {}}
    assert oddspapi.unknown_markets(odd, "circasports", MARKETS) == 1


# ---------- moon merge ----------


def _q(gid, market, side, line, price):
    return {
        "game_id": gid,
        "league": "nba",
        "away": "A",
        "home": "H",
        "market": market,
        "side": side,
        "line": line,
        "price": price,
        "rotation": None,
    }


def test_merge_screenshots_win_per_side():
    screens = {"read_at": "t1", "lines": [_q("401", "spread", "home", -7, -110)]}
    feed = {
        "grabbed_at": "t2",
        "lines": [_q("401", "spread", "home", -7.5, -110), _q("401", "spread", "away", 7.5, -110)],
    }
    m = moon_circa.merge(screens, feed)
    assert _by(m["lines"], "401", "spread", "home")["line"] == -7
    assert _by(m["lines"], "401", "spread", "away")["line"] == 7.5
    assert m["sources"] == {"screenshots": 1, "feed": 1}
    assert moon_circa.merge(None, None) is None
    assert len(moon_circa.merge(None, feed)["lines"]) == 2


def test_moon_auto_reads_the_feed_file(tmp_path, monkeypatch):
    from deepsports.moon import cli as moon_cli

    monkeypatch.setenv("DEEPSPORTS_CIRCA_LINES", str(tmp_path / "screens"))
    monkeypatch.setenv("DEEPSPORTS_BOOKS_DIR", str(tmp_path / "books"))
    (tmp_path / "books" / "circa").mkdir(parents=True)
    (tmp_path / "books" / "circa" / "2026-11-15.json").write_text(
        json.dumps({"grabbed_at": "t", "lines": [_q("401", "total", "over", 224.5, -110)]})
    )
    data, note = moon_cli._circa_payload("auto", date(2026, 11, 15))
    assert note is None and data["sources"] == {"screenshots": 0, "feed": 1}
    monkeypatch.setenv("DEEPSPORTS_BOOKS_DIR", str(tmp_path / "nothing"))
    data, note = moon_cli._circa_payload("auto", date(2026, 11, 15))
    assert data is None and "check Circa by hand" in note


# ---------- model picks message ----------


def test_attach_books_and_quote():
    top = [
        {"game_id": "401", "market": "spread", "side": "home", "line": -7.5, "price": -110},
        {"game_id": "999", "market": "total", "side": "over", "line": 200, "price": -110},
    ]
    books = {
        "circa": {"lines": [_q("401", "spread", "home", -7.5, -110)]},
        "williamhill": {"lines": [_q("401", "spread", "home", -7, -115)]},
        "x": None,
    }
    mp.attach_books(top, books)
    assert top[0]["books"] == {
        "circa": {"line": -7.5, "price": -110},
        "williamhill": {"line": -7, "price": -115},
    }
    assert "books" not in top[1]
    assert mp._book_quote(top[0]) == " | Circa -7.5 -110, WH -7 -115"
    assert mp._book_quote(top[1]) == ""


@pytest.mark.parametrize("line,expected", [(224.5, "Circa 224.5 -110"), (None, "Circa -110")])
def test_book_quote_total_and_no_line(line, expected):
    p = {"market": "total", "books": {"circa": {"line": line, "price": -110}}}
    assert mp._book_quote(p) == " | " + expected
