import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deepsports.api import app as app_module
from deepsports.api import views
from deepsports.api.live import LiveService
from deepsports.parse_espn import parse_scoreboard, parse_summary, parse_teams
from deepsports.store import Store

FIX = Path(__file__).parent / "fixtures"
FOLLOWED = {"LAL", "LAC", "GS", "BOS"}


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


class FakeSrc:
    def __init__(self):
        self.calls = 0

    def scoreboard(self, day, refresh=False):
        self.calls += 1
        if day == date(2026, 11, 2):
            return load("espn_scoreboard_final.json")
        return load("espn_scoreboard_upcoming.json")

    def summary(self, game_id, refresh=False):
        self.calls += 1
        return load("espn_summary_final.json")


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "w.duckdb"
    store = Store(path)
    store.upsert_teams(parse_teams(load("espn_teams.json")))
    final, _ = parse_scoreboard(load("espn_scoreboard_final.json"))
    upcoming, _ = parse_scoreboard(load("espn_scoreboard_upcoming.json"))
    store.upsert_games(final + upcoming)
    store.close()
    return path


@pytest.fixture
def client(db_path, monkeypatch, tmp_path):
    monkeypatch.setattr(
        app_module, "followed_teams", lambda league="nba": FOLLOWED if league == "nba" else set()
    )
    live = LiveService(src=FakeSrc())
    app = app_module.create_app(live=live, db_path=db_path, web_dist=tmp_path / "nodist")
    return TestClient(app), live


# ---------- views ----------


def test_status_text_variants():
    from datetime import UTC, datetime

    start = datetime(2026, 11, 5, 3, 30, tzinfo=UTC)  # 7:30 PM Pacific
    pre = {"type": {"name": "STATUS_SCHEDULED", "state": "pre"}}
    assert views.status_text(pre, start) == "7:30 PM"
    live = {"type": {"name": "STATUS_IN_PROGRESS", "state": "in"}, "period": 3,
            "displayClock": "4:12"}  # fmt: skip
    assert views.status_text(live, start) == "Q3 4:12"
    ot = {**live, "period": 6, "displayClock": "1:05"}
    assert views.status_text(ot, start) == "2OT 1:05"
    half = {"type": {"name": "STATUS_HALFTIME", "state": "in"}, "period": 2}
    assert views.status_text(half, start) == "Halftime"
    final = {"type": {"name": "STATUS_FINAL", "state": "post", "shortDetail": "Final/OT"}}
    assert views.status_text(final, start) == "Final/OT"


def test_scoreboard_cards_put_followed_first():
    cards = views.scoreboard_cards(load("espn_scoreboard_upcoming.json"), FOLLOWED)
    followed = [c for c in cards if c["followed"]]
    assert followed and cards[: len(followed)] == followed
    lal = next(c for c in cards if c["away"]["abbr"] == "LAL")
    assert lal["home"]["score"] is None and lal["odds"].startswith("LAL -11.5, O/U")
    assert lal["start_time"].endswith("-08:00")


def test_glance_lines_are_short_and_followed_only():
    final = views.scoreboard_cards(load("espn_scoreboard_final.json"), {"OKC"})
    assert views.glance_lines(final) == ["OKC 117-112 CLE  Final"]
    assert views.glance_lines(final[:0]) == ["No followed games today"]
    upcoming = views.scoreboard_cards(load("espn_scoreboard_upcoming.json"), FOLLOWED)
    assert all(len(line) <= 30 for line in views.glance_lines(upcoming))


def test_game_detail_box_score():
    d = views.game_detail(load("espn_summary_final.json"), FOLLOWED)
    assert d["game"]["state"] == "post" and d["game"]["home"]["score"] == 112
    assert d["game"]["home"]["linescores"] == [30, 18, 36, 28]
    assert {t["abbr"] for t in d["teams"]} == {"CLE", "OKC"}
    for lines in d["players"].values():
        played = [p for p in lines if not p["did_not_play"]]
        assert lines[: len(played)] == played  # DNPs last
        assert played[0]["starter"]


# ---------- live cache ----------


def test_live_service_caches_until_ttl():
    now = [0.0]
    src = FakeSrc()
    live = LiveService(src=src, clock=lambda: now[0])
    live.scoreboard(date(2026, 11, 4))
    live.scoreboard(date(2026, 11, 4))
    assert src.calls == 1
    now[0] += 301  # idle TTL is 5 minutes (no live games in the fixture)
    live.scoreboard(date(2026, 11, 4))
    assert src.calls == 2


# ---------- endpoints ----------


def test_endpoints(client):
    c, _ = client
    assert c.get("/api/health").json()["warehouse"] == "ok"
    sb = c.get("/api/scoreboard", params={"date": "2026-11-02"}).json()
    assert sb["date"] == "2026-11-02" and len(sb["games"]) == 15 and sb["live"] is False
    assert c.get("/api/games/401909907").json()["game"]["away"]["abbr"] == "OKC"
    assert c.get("/api/games/abc").status_code == 404
    assert c.get("/api/glance").json()["lines"]


def test_standings_and_team_page(client):
    c, _ = client
    st = c.get("/api/standings").json()
    assert st["season"] == "2026-27"
    west = next(conf for conf in st["conferences"] if conf["name"] == "West")
    okc = next(t for t in west["teams"] if t["abbr"] == "OKC")
    assert (okc["wins"], okc["losses"], okc["streak"]) == (1, 0, "W1")
    assert west["teams"][0]["games_back"] == 0
    team = c.get("/api/teams/lal").json()
    assert team["team"]["followed"] and team["upcoming"][0]["opponent"] == "SAC"
    assert c.get("/api/teams/XXX").status_code == 404


def test_warehouse_busy_returns_503(client, monkeypatch):
    from deepsports.api import warehouse

    def busy(*a, **k):
        raise warehouse.WarehouseBusy("locked")

    monkeypatch.setattr(warehouse, "connect", busy)
    c, _ = client
    r = c.get("/api/standings")
    assert r.status_code == 503 and r.json() == {"error": "warehouse_busy"}
    assert c.get("/api/health").json()["warehouse"] == "busy"


def test_parse_summary_still_matches_card(client):
    teams, players, _ = parse_summary(load("espn_summary_final.json"))
    assert len(teams) == 2 and players


def test_cors_allows_glasses_webview(client):
    c, _ = client
    r = c.get("/api/glance", headers={"Origin": "https://evenhub.example"})
    assert r.headers["access-control-allow-origin"] == "*"


def test_missing_warehouse_and_glasses_mount(monkeypatch, tmp_path):
    monkeypatch.setattr(
        app_module, "followed_teams", lambda league="nba": FOLLOWED if league == "nba" else set()
    )
    glasses = tmp_path / "glasses"
    glasses.mkdir()
    (glasses / "index.html").write_text("<p>g2</p>")
    app = app_module.create_app(
        live=LiveService(src=FakeSrc()), db_path=tmp_path / "missing.duckdb",
        web_dist=tmp_path / "nodist", glasses_dist=glasses,
    )  # fmt: skip
    c = TestClient(app)
    r = c.get("/api/standings")
    assert r.status_code == 503 and r.json() == {"error": "warehouse_unavailable"}
    assert c.get("/api/health").json()["warehouse"] == "unavailable"
    assert c.get("/api/glance").status_code == 200  # live still works
    assert c.get("/glasses/").text == "<p>g2</p>"


def test_warehouse_open_timeout_becomes_unavailable(monkeypatch, tmp_path):
    import threading

    from deepsports.api import warehouse

    gate = threading.Event()
    monkeypatch.setattr(warehouse, "_open", lambda path: gate.wait(5))  # simulate a hung open
    with (
        pytest.raises(warehouse.WarehouseUnavailable, match="timed out"),
        warehouse.connect(tmp_path / "x.duckdb", timeout=0.2),
    ):
        pass
    gate.set()


def test_scoreboard_today_includes_next_followed_game(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(app_module, "league_today", lambda: date(2026, 11, 2))
    body = c.get("/api/scoreboard").json()  # 11/02 fixture is all finals -> looks ahead
    nxt = body["next_followed_game"]
    assert nxt["followed"] and nxt["state"] == "pre"
    assert (
        "next_followed_game" not in c.get("/api/scoreboard", params={"date": "2026-11-04"}).json()
    )


def test_nba_views_ignore_college_games_with_colliding_team_ids(client, db_path):
    """Team id 5 is CLE in the NBA and UAB in college; college games must stay off NBA pages."""
    c, _ = client
    before = c.get("/api/teams/CLE").json()
    store = Store(db_path)
    store.con.execute(
        """INSERT INTO games (game_id, league, season_year, season_type, start_time_utc, status,
           state, completed, home_team_id, away_team_id, home_score, away_score, updated_at)
           VALUES ('999000001', 'ncaab', 2027, 2, '2026-11-02 23:00:00+00', 'STATUS_FINAL', 'post',
                   true, '5', '25', 50, 90, now())"""
    )
    store.close()
    after = c.get("/api/teams/CLE").json()
    assert after["recent"] == before["recent"] and after["standing"] == before["standing"]
    st = c.get("/api/standings").json()
    cle = next(t for conf in st["conferences"] for t in conf["teams"] if t["abbr"] == "CLE")
    assert (cle["wins"], cle["losses"]) == (
        before["standing"]["wins"],
        before["standing"]["losses"],
    )


# ---------- v2: college + predictions ----------


class FakeCollege:
    def scoreboard(self, day, refresh=False):
        return load("espn_ncaab_scoreboard_20261108_upcoming.json")

    def summary(self, game_id, refresh=False):
        return load("espn_ncaab_summary_final_nev_unlv.json")


def test_college_status_uses_halves():
    from datetime import UTC, datetime

    start = datetime(2026, 11, 8, 21, 30, tzinfo=UTC)
    live = {
        "type": {"name": "STATUS_IN_PROGRESS", "state": "in"},
        "period": 2,
        "displayClock": "5:01",
    }
    assert views.status_text(live, start, "ncaab") == "2nd 5:01"
    assert views.status_text({**live, "period": 3}, start, "ncaab") == "OT 5:01"
    assert views.status_text({**live, "period": 3}, start, "nba") == "Q3 5:01"


@pytest.fixture
def v2_client(db_path, monkeypatch, tmp_path):
    follow = {"nba": FOLLOWED, "ncaab": {"NEV"}}
    monkeypatch.setattr(
        app_module, "followed_teams", lambda league="nba": follow.get(league, set())
    )
    live = LiveService(sources={"nba": FakeSrc(), "ncaab": FakeCollege()})
    app = app_module.create_app(live=live, db_path=db_path, web_dist=tmp_path / "nodist")
    return TestClient(app)


def test_college_scoreboard_followed_first_and_league_tagged(v2_client):
    body = v2_client.get("/api/scoreboard", params={"league": "ncaab", "date": "2026-11-08"}).json()
    assert body["league"] == "ncaab" and body["games"]
    assert all(g["league"] == "ncaab" and g["prediction"] is None for g in body["games"])
    first = body["games"][0]
    assert first["followed"] and "NEV" in (first["home"]["abbr"], first["away"]["abbr"])
    assert v2_client.get("/api/scoreboard", params={"league": "nfl"}).status_code == 400


def test_followed_by_league_and_glance_covers_both(v2_client, monkeypatch):
    f = v2_client.get("/api/followed").json()
    assert f["teams"] == sorted(FOLLOWED) and f["by_league"]["ncaab"] == ["NEV"]
    lines = v2_client.get("/api/glance").json()["lines"]
    assert any("NEV" in line for line in lines)
    assert any(" vs " in line for line in lines if "NEV" in line)  # neutral site


def test_predictions_attach_only_if_made_before_tip(v2_client, db_path):
    from datetime import UTC, datetime

    store = Store(db_path)
    store.add_predictions([
        {"game_id": "401909934", "model": "v1", "model_version": "v1.0",
         "created_at": datetime(2026, 11, 4, 12, 0, tzinfo=UTC), "p_home_win": 0.3,
         "pred_home_margin": -4.6, "pred_total": 236.1, "features_json": {}},
        # LAL @ SAC tips 2026-11-05 03:00 UTC; this one is AFTER tip and must be ignored
        {"game_id": "401909934", "model": "v1", "model_version": "v1.1",
         "created_at": datetime(2026, 11, 5, 4, 0, tzinfo=UTC), "p_home_win": 0.9,
         "pred_home_margin": 9.0, "pred_total": 200.0, "features_json": {}},
    ])  # fmt: skip
    store.close()
    games = v2_client.get("/api/scoreboard", params={"date": "2026-11-04"}).json()["games"]
    lal = next(g for g in games if g["away"]["abbr"] == "LAL")
    assert lal["prediction"]["model_version"] == "v1.0"
    assert lal["prediction"]["favorite_abbr"] == "LAL" and lal["prediction"]["favorite_prob"] == 0.7
    assert "result" not in lal["prediction"]  # not final yet


def test_prediction_graded_once_final():
    card = {"status": "STATUS_FINAL", "home": {"abbr": "CLE", "score": 112},
            "away": {"abbr": "OKC", "score": 117}}  # fmt: skip
    from datetime import UTC, datetime

    row = {"model": "v1", "model_version": "v1.0", "created_at": datetime(2026, 11, 2, tzinfo=UTC),
           "p_home_win": 0.45, "pred_home_margin": -2.0, "pred_total": 225.0}  # fmt: skip
    p = views.prediction_view(row, card)
    assert p["favorite_abbr"] == "OKC" and p["result"]["winner_correct"]
    assert p["result"] == {"winner_correct": True, "margin_error": 3.0, "total_error": 4.0}


def test_game_detail_before_tip_has_no_box_rows():
    raw = load("espn_ncaab_summary_pregame_nev_smc.json")
    d = views.game_detail(raw, {"NEV"}, "ncaab")
    assert d["game"]["state"] == "pre" and d["teams"] == [] and d["players"] == {}
    assert d["game"]["neutral_site"] is True


def test_api_prefers_display_model_version(v2_client, db_path):
    from datetime import UTC, datetime

    store = Store(db_path)
    store.add_predictions([
        {"game_id": "401909934", "model": "v1", "model_version": "v1.1",
         "created_at": datetime(2026, 11, 4, 10, 0, tzinfo=UTC), "p_home_win": 0.35,
         "pred_home_margin": -3.0, "pred_total": 230.0, "features_json": {}},
        {"game_id": "401909934", "model": "v1", "model_version": "v1.0",
         "created_at": datetime(2026, 11, 4, 11, 0, tzinfo=UTC), "p_home_win": 0.2,
         "pred_home_margin": -8.0, "pred_total": 236.0, "features_json": {}},
    ])  # fmt: skip
    store.close()
    games = v2_client.get("/api/scoreboard", params={"date": "2026-11-04"}).json()["games"]
    lal = next(g for g in games if g["away"]["abbr"] == "LAL")
    assert lal["prediction"]["model_version"] == "v1.1"  # preferred even though v1.0 is newer


class FakeCollegePregame(FakeCollege):
    def summary(self, game_id, refresh=False):
        return load("espn_ncaab_summary_pregame_nev_smc.json")


def test_college_cards_and_detail_get_predictions(db_path, monkeypatch, tmp_path):
    from datetime import UTC, datetime

    monkeypatch.setattr(
        app_module, "followed_teams", lambda league="nba": {"NEV"} if league == "ncaab" else set()
    )
    live = LiveService(sources={"nba": FakeSrc(), "ncaab": FakeCollegePregame()})
    c = TestClient(app_module.create_app(live=live, db_path=db_path, web_dist=tmp_path / "nd"))
    tip = datetime(2026, 11, 8, 21, 30, tzinfo=UTC)  # SMC @ NEV (401911453)
    store = Store(db_path)
    store.upsert_games(
        [
            {
                "game_id": "401911453",
                "league": "ncaab",
                "season_year": 2027,
                "season_type": 2,
                "start_time_utc": tip,
                "status": "STATUS_SCHEDULED",
                "state": "pre",
                "completed": False,
                "home_team_id": "2440",
                "away_team_id": "2608",
                "neutral_site": True,
            }
        ]
    )
    store.add_predictions([
        {"game_id": "401911453", "model": "v1", "model_version": "ncaab-v1",
         "created_at": datetime(2026, 11, 7, 12, 0, tzinfo=UTC), "p_home_win": 0.42,
         "pred_home_margin": -1.8, "pred_total": 141.3, "features_json": {}},
        {"game_id": "401911453", "model": "v1", "model_version": "ncaab-v1-test",
         "created_at": datetime(2026, 11, 7, 13, 0, tzinfo=UTC), "p_home_win": 0.9,
         "pred_home_margin": 12.0, "pred_total": 150.0, "features_json": {}},
    ])  # fmt: skip
    store.close()
    body = c.get("/api/scoreboard", params={"league": "ncaab", "date": "2026-11-08"}).json()
    nev = next(g for g in body["games"] if g["id"] == "401911453")
    p = nev["prediction"]
    assert p["model_version"] == "ncaab-v1"  # display version preferred over a newer one
    shape = {"model", "model_version", "created_at", "p_home_win", "pred_home_margin",
             "pred_total", "favorite_abbr", "favorite_prob", "early"}  # fmt: skip
    assert set(p) == shape  # same Prediction shape as NBA cards
    assert p["early"] is False
    assert (p["favorite_abbr"], p["favorite_prob"]) == ("SMC", 0.58)
    others = [g for g in body["games"] if g["id"] != "401911453"]
    assert others and all(g["prediction"] is None for g in others)
    detail = c.get("/api/games/401911453", params={"league": "ncaab"}).json()
    assert detail["game"]["prediction"] == p

    rec = c.get("/api/predictions/record", params={"league": "ncaab"}).json()
    assert rec["model_version"] == "ncaab-v1" and rec["games"] == 0
    assert c.get("/api/predictions/record", params={"league": "nfl"}).status_code == 400


def test_prediction_view_flags_early_season_college():
    from deepsports.api import views

    card = {"status": "STATUS_SCHEDULED", "home": {"abbr": "NEV", "score": None},
            "away": {"abbr": "SMC", "score": None}}  # fmt: skip
    row = {"model": "v1", "model_version": "ncaab-v1-early", "created_at": "2026-11-05",
           "p_home_win": 0.746, "pred_home_margin": 8.2, "pred_total": 150.9}  # fmt: skip
    assert views.prediction_view(row, card)["early"] is True
    assert views.prediction_view({**row, "model_version": "ncaab-v1"}, card)["early"] is False
    assert views.prediction_view({**row, "model_version": "v1.1"}, card)["early"] is False


def test_hidden_versions_never_reach_cards_but_have_a_record(db_path, monkeypatch, tmp_path):
    from datetime import UTC, datetime

    from deepsports.api import warehouse

    tip = datetime(2026, 11, 8, 21, 30, tzinfo=UTC)
    store = Store(db_path)
    store.upsert_games([
        {"game_id": g, "league": "ncaab", "season_year": 2027, "season_type": 2,
         "start_time_utc": tip, "status": "STATUS_SCHEDULED", "state": "pre",
         "completed": False, "home_team_id": "2440", "away_team_id": "2608"}
        for g in ("c1", "c2")
    ])  # fmt: skip
    made = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
    later = made.replace(hour=13)
    pred = {"model": "v1", "p_home_win": 0.6, "pred_home_margin": 3.0, "pred_total": 140.0,
            "features_json": {}}  # fmt: skip
    store.add_predictions([
        {**pred, "game_id": "c1", "model_version": "ncaab-v1", "created_at": made},
        {**pred, "game_id": "c1", "model_version": "ncaab-v1p", "created_at": later},
        {**pred, "game_id": "c2", "model_version": "ncaab-v1p", "created_at": made},
    ])  # fmt: skip
    store.close()
    with warehouse.connect(db_path) as con:
        got = warehouse.pre_tip_predictions(con, ["c1", "c2"])  # no preference: latest
    assert {g: r["model_version"] for g, r in got.items()} == {"c1": "ncaab-v1"}
    live = LiveService(sources={"nba": FakeSrc(), "ncaab": FakeCollegePregame()})
    c = TestClient(app_module.create_app(live=live, db_path=db_path, web_dist=tmp_path / "nd"))
    rec = c.get(
        "/api/predictions/record", params={"league": "ncaab", "model_version": "ncaab-v1p"}
    ).json()
    assert rec["model_version"] == "ncaab-v1p" and rec["games"] == 0


def test_scoreboard_tags_open_bets(client, monkeypatch):
    c, _ = client
    import deepsports.api.bets as bets_module

    first = c.get("/api/scoreboard").json()["games"]
    target = next(g for g in first if g["state"] != "post")
    final = next((g for g in first if g["state"] == "post"), None)
    open_map = {target["id"]: ["TOR -2.5"]}
    if final:
        open_map[final["id"]] = ["LAL -4.5"]
    monkeypatch.setattr(bets_module, "open_bets", lambda: open_map)
    games = {g["id"]: g for g in c.get("/api/scoreboard").json()["games"]}
    assert games[target["id"]]["bets"] == ["TOR -2.5"]
    if final:
        assert "bets" not in games[final["id"]]


def test_bets_endpoint_lists_only_games_with_open_bets(client, monkeypatch):
    c, _ = client
    import deepsports.api.bets as bets_module

    games = c.get("/api/scoreboard").json()["games"]
    pre = next(g for g in games if g["state"] == "pre")
    final = next((g for g in games if g["state"] == "post"), None)
    open_map = {pre["id"]: ["TOR -2.5"], "999": ["stale row"]}
    if final:
        open_map[final["id"]] = ["Over 200"]
    monkeypatch.setattr(bets_module, "open_bets", lambda: open_map)
    body = c.get("/api/bets").json()
    got = {g["id"]: g for g in body["games"]}
    assert got[pre["id"]]["bets"] == ["TOR -2.5"]
    assert "999" not in got
    if final:
        assert got[final["id"]]["bets"] == ["Over 200"]  # finals stay until graded
    states = [g["state"] for g in body["games"]]
    assert states == sorted(states, key={"in": 0, "pre": 1, "post": 2}.get)
    monkeypatch.setattr(bets_module, "open_bets", lambda: {})
    assert c.get("/api/bets").json()["games"] == []


def test_warehouse_access_error_is_unavailable_not_busy(monkeypatch, tmp_path):
    import duckdb

    from deepsports.api import warehouse

    def denied(path):
        raise duckdb.IOException('IO Error: Cannot open file "x": Operation not permitted')

    monkeypatch.setattr(warehouse, "_open", denied)
    with (
        pytest.raises(warehouse.WarehouseUnavailable, match="Operation not permitted"),
        warehouse.connect(tmp_path / "x.duckdb"),
    ):
        pass
