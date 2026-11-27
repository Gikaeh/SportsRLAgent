from datetime import UTC, datetime, timedelta

from test_api import client, db_path  # noqa: F401  (fixtures)

from deepsports.api import parlays
from deepsports.moon import ledger


def card(state, home=None, away=None, start="2026-11-24T15:00:00-08:00"):
    return {
        "state": state,
        "start_time": start,
        "status_text": "x",
        "home": {"name": "Home U", "abbr": "HU", "score": home},
        "away": {"name": "Away St", "abbr": "AS", "score": away},
    }


def leg(side, line, market="total", gid="1"):
    return {"game_id": gid, "market": market, "side": side, "line": line}


def test_leg_status_totals_pre_live_and_final():
    assert parlays.leg_status(leg("over", 140), None)["status"] == "pending"
    assert parlays.leg_status(leg("over", 140), card("pre"))["status"] == "pending"
    s = parlays.leg_status(leg("over", 140.5), card("in", 60, 70))
    assert s == {"status": "pending", "note": "130 pts, needs 11 more"}
    assert parlays.leg_status(leg("over", 140.5), card("in", 70, 71))["status"] == "won"
    assert parlays.leg_status(leg("under", 140.5), card("in", 70, 71))["status"] == "lost"
    assert parlays.leg_status(leg("under", 140.5), card("in", 60, 70))["status"] == "pending"
    assert parlays.leg_status(leg("under", 140.5), card("post", 60, 70))["status"] == "won"
    assert parlays.leg_status(leg("over", 130), card("post", 60, 70))["status"] == "push"
    spread = leg("home", -3.5, market="spread")
    assert parlays.leg_status(spread, card("post", 80, 70))["status"] == "won"


def test_overall():
    assert parlays.overall(["won", "pending"]) == "alive"
    assert parlays.overall(["won", "lost", "pending"]) == "lost"
    assert parlays.overall(["won", "push"]) == "won"
    assert parlays.overall(["push", "push"]) == "push"


def _rows(tmp_path):
    p = tmp_path / "moon.csv"
    legs = [
        {"game_id": "1", "league": "ncaab", "market": "total", "side": "over", "line": 140},
        {"game_id": "2", "league": "ncaab", "market": "total", "side": "under", "line": 150},
    ]
    old = datetime.now(UTC) - timedelta(days=5)
    a = ledger.add_bet(stake=1, price=264, market="parlay", legs=legs, path=p)
    b = ledger.add_bet(stake=1, price=264, market="parlay", legs=legs, path=p, now=old)
    ledger.add_result(b["id"], "loss", path=p)  # old and graded: hidden
    c = ledger.add_bet(stake=1, price=264, market="parlay", legs=legs, path=p)
    ledger.add_void(c["id"], "typo", path=p)  # voided: hidden
    ledger.add_bet(stake=1, price=-110, market="total", game_id="1", side="over", line=140, path=p)
    return ledger.read_rows(p), a["id"]


def test_recent_parlays_drops_voids_old_graded_and_singles(tmp_path):
    rows, keep = _rows(tmp_path)
    got = parlays.recent_parlays(rows, datetime.now(UTC))
    assert [p["id"] for p in got] == [keep]
    assert got[0]["price"] == 264 and len(got[0]["legs"]) == 2


def test_view_orders_legs_and_never_exposes_stakes(tmp_path):
    rows, _ = _rows(tmp_path)
    (p,) = parlays.recent_parlays(rows, datetime.now(UTC))
    cards = {"1": card("post", 80, 70, "2026-11-24T18:00:00-08:00"),
             "2": card("in", 40, 30, "2026-11-24T12:00:00-08:00")}  # fmt: skip
    v = parlays.view(p, cards)
    assert [x["game_id"] for x in v["legs"]] == ["2", "1"]  # tip order
    assert v["legs"][1]["status"] == "won" and v["legs"][0]["status"] == "pending"
    assert v["status"] == "alive" and v["won"] == 1 and v["pending"] == 1
    assert v["legs"][0]["matchup"] == "Away St @ Home U" and v["legs"][0]["label"] == "Under 150"
    assert (v["legs"][0]["away_abbr"], v["legs"][0]["home_abbr"]) == ("AS", "HU")
    text = str(v)
    assert "stake" not in text and "payout" not in text and "amount" not in text


def test_parlays_endpoint(client, monkeypatch, tmp_path):  # noqa: F811
    c, _ = client
    from deepsports.api import app as app_module

    rows, keep = _rows(tmp_path)
    monkeypatch.setattr(app_module.moon_ledger, "read_rows", lambda: rows)
    body = c.get("/api/parlays").json()
    assert [p["id"] for p in body["parlays"]] == [keep]
    assert {"live", "refresh_seconds"} <= body.keys()
    assert body["parlays"][0]["legs"][0]["status"] == "pending"  # games not on the scoreboard
    monkeypatch.setattr(app_module.moon_ledger, "read_rows", lambda: [])
    assert c.get("/api/parlays").json()["parlays"] == []


def test_graded_parlay_drops_off_after_its_placement_day(tmp_path):
    p = tmp_path / "moon.csv"
    legs = [
        {"game_id": "1", "league": "ncaab", "market": "total", "side": "over", "line": 140},
        {"game_id": "2", "league": "ncaab", "market": "total", "side": "under", "line": 150},
    ]
    placed = datetime(2026, 11, 24, 0, 26, tzinfo=UTC)  # 4:26 PM PT on Nov 23
    b = ledger.add_bet(stake=1, price=264, market="parlay", legs=legs, path=p, now=placed)
    o = ledger.add_bet(stake=1, price=264, market="parlay", legs=legs, path=p, now=placed)
    ledger.add_result(b["id"], "loss", path=p)
    rows = ledger.read_rows(p)
    same_night = datetime(2026, 11, 24, 7, 0, tzinfo=UTC)  # 11 PM PT Nov 23
    assert {x["id"] for x in parlays.recent_parlays(rows, same_night)} == {b["id"], o["id"]}
    next_morning = datetime(2026, 11, 24, 17, 0, tzinfo=UTC)  # 9 AM PT Nov 24
    assert [x["id"] for x in parlays.recent_parlays(rows, next_morning)] == [o["id"]]
