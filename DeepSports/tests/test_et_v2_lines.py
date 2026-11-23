import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from deepsports.analysis import et_v2_lines as L

FIX = Path(__file__).parent / "fixtures"
# Real Odds API historical snapshot (requested 2025-01-15T05:00Z = 21:00 PST on Jan 14), trimmed to
# one in-play event and two pregame events. Lines only.
SNAP = FIX / "oddsapi_historical_ncaab_20250115T050000Z_trim.json"


def team(tid, abbr, display, loc, name):
    return {"team_id": tid, "abbr": abbr, "display_name": display, "location": loc, "name": name}


LUC = team("2350", "LUC", "Loyola Chicago Ramblers", "Loyola Chicago", "Ramblers")
LMU = team("2351", "LMU", "Loyola Marymount Lions", "Loyola Marymount", "Lions")
URI = team("227", "URI", "Rhode Island Rams", "Rhode Island", "Rams")
VAN = team("238", "VAN", "Vanderbilt Commodores", "Vanderbilt", "Commodores")
SC = team("2579", "SC", "South Carolina Gamecocks", "South Carolina", "Gamecocks")
SJSU = team("23", "SJSU", "San José State Spartans", "San José State", "Spartans")


def snap():
    return json.loads(SNAP.read_text())


def test_requested_times_are_dst_aware():
    # 21:00 PST the night before Jan 15 = 05:00Z; 21:00 PDT the night before Nov 1 = 04:00Z
    assert L.log_time(date(2025, 1, 15)) == datetime(2025, 1, 15, 5, tzinfo=UTC)
    assert L.log_time(date(2024, 11, 1)) == datetime(2024, 11, 1, 4, tzinfo=UTC)
    assert L.requested_ts(date(2025, 1, 15), "0@09:00") == datetime(2025, 1, 15, 17, tzinfo=UTC)
    p = L.snapshot_path(Path("/x"), date(2025, 1, 15), "-1@21:00")
    assert p.name == "20250115T050000Z.json.gz"


def test_game_day_is_eastern():
    # 02:00Z on Jan 16 is 21:00 ET Jan 15
    assert L.game_day(datetime(2025, 1, 16, 2, tzinfo=UTC)) == date(2025, 1, 15)


def test_timestamp_ok():
    req = datetime(2025, 1, 15, 5, tzinfo=UTC)
    assert L.timestamp_ok(req, req - timedelta(minutes=4, seconds=22))
    assert L.timestamp_ok(req, req)
    assert not L.timestamp_ok(req, req + timedelta(seconds=1))
    assert not L.timestamp_ok(req, req - timedelta(minutes=31))
    assert not L.timestamp_ok(req, None)


def test_book_totals_drops_inplay_and_reads_both_sides():
    resp = snap()
    rows = L.book_totals(resp)
    all_rows = L.book_totals(resp, pregame_only=False)
    snap_ts = L.ts(resp["timestamp"])
    assert len(all_rows) > len(rows)
    assert all(r["commence_time"] > snap_ts for r in rows)
    assert {r["home_team"] for r in rows} == {"Loyola (Chi) Ramblers", "Vanderbilt Commodores"}
    wh = [r for r in rows if r["book"] == "williamhill_us"]
    assert len(wh) == 2
    for r in rows:
        assert r["consistent"] and L.sane_total(r["point"]) == r["point"]
        assert r["last_update"] <= snap_ts
        assert r["over_price"] is not None and r["under_price"] is not None
    assert len(L.events(resp)) == 2


def test_book_totals_flags_point_mismatch():
    resp = {
        "timestamp": "2025-01-15T04:55:00Z",
        "data": [
            {
                "id": "e",
                "commence_time": "2025-01-16T00:00:00Z",
                "home_team": "A",
                "away_team": "B",
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "markets": [
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "price": -110, "point": 140.5},
                                    {"name": "Under", "price": -110, "point": 141.5},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    (row,) = L.book_totals(resp)
    assert not row["consistent"] and row["point"] is None


def test_match_event_vendor_names_and_orientation():
    start = datetime(2025, 1, 16, 2, tzinfo=UTC)
    games = [
        {"game_id": "g1", "start_time_utc": start, "home": LUC, "away": URI},
        {"game_id": "g2", "start_time_utc": start, "home": LMU, "away": URI},
        {"game_id": "g3", "start_time_utc": start - timedelta(hours=3), "home": VAN, "away": SC},
    ]
    ev = {
        "commence_time": start,
        "home_team": "Loyola (Chi) Ramblers",
        "away_team": "Rhode Island Rams",
    }
    assert L.match_event(ev, games) == ("g1", False)
    flipped = {**ev, "home_team": "Rhode Island Rams", "away_team": "Loyola (Chi) Ramblers"}
    assert L.match_event(flipped, games) == ("g1", True)
    van = {
        "commence_time": start - timedelta(hours=3),
        "home_team": "Vanderbilt Commodores",
        "away_team": "South Carolina Gamecocks",
    }
    assert L.match_event(van, games) == ("g3", False)
    late = {**van, "commence_time": start + timedelta(hours=1)}  # 4 h off: no match
    assert L.match_event(late, games) == (None, False)


def test_match_event_accent_fold():
    start = datetime(2025, 1, 16, 4, tzinfo=UTC)
    games = [{"game_id": "s", "start_time_utc": start, "home": SJSU, "away": URI}]
    ev = {
        "commence_time": start,
        "home_team": "San José St Spartans",
        "away_team": "Rhode Island Rams",
    }
    assert L.match_event(ev, games) == ("s", False)
    ev2 = {**ev, "home_team": "San Jose St Spartans"}
    assert L.match_event(ev2, games) == ("s", False)


def test_aliases_override(monkeypatch):
    start = datetime(2025, 1, 16, 4, tzinfo=UTC)
    games = [{"game_id": "s", "start_time_utc": start, "home": SJSU, "away": URI}]
    monkeypatch.setitem(L.ALIASES, "SJ Spartans", "San José State Spartans")
    ev = {"commence_time": start, "home_team": "SJ Spartans", "away_team": "Rhode Island Rams"}
    assert L.match_event(ev, games) == ("s", False)


def test_agreement_and_grading_book():
    a = L.agreement([(140.5, 140.5), (141.0, 140.0), (137.0, 140.0), (None, 1.0)])
    assert a["n"] == 3
    assert abs(a["mean"] - (-2 / 3)) < 1e-9
    assert abs(a["mean_abs"] - 4 / 3) < 1e-9
    assert abs(a["identical"] - 1 / 3) < 1e-9
    assert abs(a["gt2"] - 1 / 3) < 1e-9
    assert L.agreement([])["n"] == 0
    assert L.grading_book(0.8, 0.9) == "williamhill_us"
    assert L.grading_book(0.5, 0.9) == "draftkings"
    assert L.grading_book(None, 0.6) == "draftkings"
    assert L.grading_book(0.5, 0.59) is None


def test_rename_aliases_from_the_pull():
    start = datetime(2022, 1, 10, 1, tzinfo=UTC)
    kc = team("140", "KC", "Kansas City Roos", "Kansas City", "Roos")
    pfw = team("2870", "PFW", "Purdue Fort Wayne Mastodons", "Purdue Fort Wayne", "Mastodons")
    games = [{"game_id": "k", "start_time_utc": start, "home": kc, "away": pfw}]
    ev = {
        "commence_time": start,
        "home_team": "UMKC Kangaroos",
        "away_team": "Fort Wayne Mastodons",
    }
    assert L.match_event(ev, games) == ("k", False)
