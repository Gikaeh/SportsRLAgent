import gzip
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from deepsports import pipeline
from deepsports.http import FetchError, PoliteClient
from deepsports.parse_espn import parse_moneyline, parse_scoreboard, parse_summary, parse_teams
from deepsports.sources.espn_nba import EspnNba
from deepsports.store import Store

FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


# ---------- parsers ----------


def test_parse_teams():
    rows = parse_teams(load("espn_teams.json"))
    assert len(rows) == 30
    assert {"team_id", "abbreviation", "display_name"} <= rows[0].keys()


def test_parse_scoreboard_final_day():
    games, odds = parse_scoreboard(load("espn_scoreboard_final.json"))
    assert len(games) == 15
    g = next(g for g in games if g["game_id"] == "401909907")
    assert (g["home_team_id"], g["away_team_id"]) == ("5", "25")  # OKC @ CLE
    assert (g["home_score"], g["away_score"]) == (112, 117)
    assert g["completed"] and g["state"] == "post"
    assert g["start_time_utc"].tzinfo is not None
    assert odds == []  # no pregame odds for finished games


def test_parse_scoreboard_upcoming_odds_home_perspective():
    games, odds = parse_scoreboard(load("espn_scoreboard_upcoming.json"))
    assert all(g["state"] == "pre" and g["home_score"] is None for g in games)
    by_game = {o["game_id"]: o for o in odds}
    # PHI @ DET: DET (home) -2.5, DET -130 / PHI +110
    det = by_game["401909922"]
    assert det["spread_home"] == -2.5 and det["over_under"] == 217.5
    assert (det["home_moneyline"], det["away_moneyline"]) == (-130, 110)
    # ATL @ WSH: ATL (away) favored, so the home spread is positive
    assert by_game["401909923"]["spread_home"] == 1.5


def test_parse_summary_boxscore_and_closing_odds():
    teams, players, odds = parse_summary(load("espn_summary_final.json"))
    assert len(teams) == 2
    for t in teams:
        assert t["fga"] >= t["fgm"] > 0 and t["reb"] == t["oreb"] + t["dreb"]
    played = [p for p in players if not p["did_not_play"]]
    assert played and all(p["minutes"] is not None for p in played)
    # team points from box score sum to the final score (112 CLE, 117 OKC)
    pts = {}
    for p in played:
        pts[p["team_id"]] = pts.get(p["team_id"], 0) + (p["pts"] or 0)
    assert pts == {"5": 112, "25": 117}
    assert len(odds) == 1 and odds[0]["source"] == "closing"
    assert odds[0]["spread_home"] == -4.5 and odds[0]["home_moneyline"] == -173


@pytest.mark.parametrize(
    "raw,expected", [("-130", -130), ("+110", 110), ("EVEN", 100), (146, 146), ("-", None)]
)
def test_parse_moneyline(raw, expected):
    assert parse_moneyline(raw) == expected


# ---------- store ----------


@pytest.fixture
def db():
    store = Store(":memory:")
    store.upsert_teams(parse_teams(load("espn_teams.json")))
    yield store
    store.close()


def test_upserts_are_idempotent(db):
    games, _ = parse_scoreboard(load("espn_scoreboard_final.json"))
    db.upsert_games(games)
    db.upsert_games(games)
    assert db.counts()["games"] == 15
    assert len(db.games_missing_boxscores()) == 15
    teams, players, odds = parse_summary(load("espn_summary_final.json"))
    for _ in range(2):
        db.upsert_team_stats(teams)
        db.upsert_player_stats(players)
        db.add_odds(odds)
    assert "401909907" not in db.games_missing_boxscores()
    assert db.counts()["odds_snapshots"] == 1


def test_pregame_odds_only_stored_when_line_moves(db):
    _, odds = parse_scoreboard(load("espn_scoreboard_upcoming.json"))
    first = db.add_odds(odds)
    later = [{**o, "captured_at": o["captured_at"] + timedelta(hours=1)} for o in odds]
    assert db.add_odds(later) == 0
    moved = [
        {
            **later[0],
            "spread_home": -3.5,
            "captured_at": later[0]["captured_at"] + timedelta(hours=1),
        }
    ]
    assert db.add_odds(moved) == 1
    assert db.counts()["odds_snapshots"] == first + 1


def test_upcoming_filters_by_team(db):
    games, odds = parse_scoreboard(load("espn_scoreboard_upcoming.json"))
    db.upsert_games(games)
    db.add_odds(odds)
    start = datetime(2026, 11, 4, tzinfo=UTC)
    end = start + timedelta(days=2)
    assert len(db.upcoming_games(start, end)) == len(games)
    lal = db.upcoming_games(start, end, ["LAL"])
    assert [(r["away_abbr"], r["home_abbr"]) for r in lal] == [("LAL", "SAC")]
    assert lal[0]["spread_home"] == 11.5


# ---------- http client + caching ----------


def make_client(tmp_path, handler):
    transport = httpx.MockTransport(handler)
    return PoliteClient(
        raw_dir=tmp_path,
        min_interval=0,
        client=httpx.Client(transport=transport),
        sleep=lambda s: None,
    )


def test_settled_scoreboard_is_served_from_cache(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, json=load("espn_scoreboard_final.json"))

    src = EspnNba(make_client(tmp_path, handler))
    src.scoreboard(date(2026, 11, 2))
    src.scoreboard(date(2026, 11, 2))
    assert len(calls) == 1
    assert (tmp_path / "espn/nba/scoreboard/20261102.json.gz").exists()
    src.scoreboard(date(2026, 11, 2), refresh=True)
    assert len(calls) == 2


def test_unsettled_scoreboard_is_refetched(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=load("espn_scoreboard_upcoming.json"))

    src = EspnNba(make_client(tmp_path, handler))
    src.scoreboard(date(2026, 11, 4))
    src.scoreboard(date(2026, 11, 4))
    assert len(calls) == 2


def test_retries_then_succeeds(tmp_path):
    responses = [httpx.Response(503), httpx.Response(429), httpx.Response(200, json={"ok": 1})]
    client = make_client(tmp_path, lambda r: responses.pop(0))
    assert client.get_json("https://x.test/a", cache_key="t/a") == {"ok": 1}
    assert client.network_requests == 3
    with gzip.open(tmp_path / "t/a.json.gz", "rt") as f:
        assert json.load(f) == {"ok": 1}


def test_client_error_is_not_retried(tmp_path):
    client = make_client(tmp_path, lambda r: httpx.Response(404))
    with pytest.raises(FetchError):
        client.get_json("https://x.test/b", cache_key="t/b")
    assert client.network_requests == 1


def test_season_dates():
    assert pipeline.season_dates("2025-26") == (date(2025, 10, 1), date(2026, 6, 30))


# ---------- historical odds (core API) ----------

from deepsports.parse_espn import choose_book, parse_core_odds  # noqa: E402

START = datetime(2025, 3, 1, tzinfo=UTC)


def test_core_odds_open_and_close_from_explicit_sides():
    rows = parse_core_odds(load("espn_core_odds_401705426.json"), "401705426", START)
    by = {r["source"]: r for r in rows}
    assert by["closing"]["spread_home"] == -3.5 and by["closing"]["over_under"] == 226.5
    assert (by["closing"]["home_moneyline"], by["closing"]["away_moneyline"]) == (-175, 145)
    assert by["opening"]["spread_home"] == -4.5
    assert all(r["captured_at"] == START for r in rows)


def test_core_odds_prefers_draftkings_and_skips_live_books():
    raw = load("espn_core_odds_401585485.json")
    assert choose_book(raw["items"])["provider"]["name"] == "DraftKings"
    by = {r["source"]: r for r in parse_core_odds(raw, "401585485", START)}
    # away team (CLE) favored by 7, so the home spread is +7
    assert by["closing"]["spread_home"] == 7 and by["closing"]["details"] == "CLE -7"
    assert by["closing"]["home_moneyline"] > 0 > by["closing"]["away_moneyline"]
    live = {"items": [o for o in raw["items"] if "Live" in o["provider"]["name"]]}
    assert parse_core_odds(live, "x", START) == []


def test_core_odds_flat_legacy_format_is_closing_only():
    rows = parse_core_odds(load("espn_core_odds_401360500.json"), "401360500", START)
    assert [r["source"] for r in rows] == ["closing"]
    assert rows[0]["spread_home"] == -3.5 and rows[0]["over_under"] == 210.5


def test_collect_core_odds_fills_gaps_but_keeps_summary_closing(tmp_path, db):
    games, _ = parse_scoreboard(load("espn_scoreboard_final.json"))
    db.upsert_games(games[:2])
    g_with, g_without = games[0]["game_id"], games[1]["game_id"]
    db.add_odds(
        [
            {
                "game_id": g_with,
                "source": "closing",
                "captured_at": START,
                "provider": "DraftKings",
                "details": "keep me",
                "spread_home": -1.0,
                "over_under": 200.0,
                "home_moneyline": -110,
                "away_moneyline": -110,
            }
        ]
    )
    fixture = load("espn_core_odds_401705426.json")
    src = EspnNba(make_client(tmp_path, lambda r: httpx.Response(200, json=fixture)))
    pipeline.collect_core_odds(src, db)  # only the game without a closing line
    rows = db.con.execute(
        "SELECT game_id, source, details FROM odds_snapshots ORDER BY game_id, source"
    ).fetchall()
    assert (g_with, "closing", "keep me") in rows
    assert {(g, s) for g, s, _ in rows if g == g_without} == {
        (g_without, "closing"),
        (g_without, "opening"),
    }
    pipeline.collect_core_odds(src, db, include_opening=True)  # adds opening, keeps closing
    assert (
        db.con.execute(
            "SELECT details FROM odds_snapshots WHERE game_id = ? AND source = 'closing'", [g_with]
        ).fetchone()[0]
        == "keep me"
    )
    assert db.games_needing_core_odds(include_opening=True) == []


def test_quality_checks_pass_on_consistent_data(db):
    from deepsports.quality import run_checks

    games, _ = parse_scoreboard(load("espn_scoreboard_final.json"))
    db.upsert_games([g for g in games if g["game_id"] == "401909907"])
    teams, players, odds = parse_summary(load("espn_summary_final.json"))
    db.upsert_team_stats(teams)
    db.upsert_player_stats(players)
    db.add_odds(odds)
    results = {c.name: c for c in run_checks(db)}
    assert all(c.failures == 0 for c in results.values()), results
    db.con.execute("UPDATE games SET home_score = home_score + 1")
    after = {c.name: c for c in run_checks(db)}
    assert after["player points sum to team score"].failures == 1  # points no longer add up


def test_summary_player_without_espn_id_gets_placeholder():
    raw = load("espn_summary_final.json")
    team = raw["boxscore"]["players"][0]
    team["statistics"][0]["athletes"].append(
        {"active": False, "athlete": {"links": [], "shortName": "Olbrich"}, "starter": False,
         "didNotPlay": True, "reason": "COACH'S DECISION", "ejected": False, "stats": []}
    )  # fmt: skip
    _, players, _ = parse_summary(raw)
    p = next(p for p in players if p["athlete_name"] == "Olbrich")
    assert p["athlete_id"] == f"noid:{team['team']['id']}:Olbrich" and p["did_not_play"]


def test_require_data_dir_fails_clearly_when_volume_missing(tmp_path, monkeypatch):
    from deepsports import config

    link = tmp_path / "data"
    link.symlink_to(tmp_path / "unmounted-volume" / "data")
    monkeypatch.setattr(config, "DATA_DIR", link)
    with pytest.raises(config.DataDirUnavailable, match="mounted"):
        config.require_data_dir()


def test_quality_separates_known_espn_gaps(db):
    from deepsports.quality import KNOWN_NO_BOXSCORE, run_checks

    games, _ = parse_scoreboard(load("espn_scoreboard_final.json"))
    g = dict(games[0], game_id=sorted(KNOWN_NO_BOXSCORE)[0])
    db.upsert_games([g])
    by = {c.name: c for c in run_checks(db)}
    assert by["final games with 2 team box scores"].failures == 0
    assert by["known ESPN gaps: no box score (summary 404)"].failures == 1
    assert not by["known ESPN gaps: no box score (summary 404)"].hard


def test_quality_known_points_mismatches_are_listed_team_games(db, monkeypatch):
    from deepsports import quality

    games, _ = parse_scoreboard(load("espn_scoreboard_final.json"))
    g = next(g for g in games if g["game_id"] == "401909907")
    db.upsert_games([g])
    teams, players, _ = parse_summary(load("espn_summary_final.json"))
    db.upsert_team_stats(teams)
    db.upsert_player_stats(players)
    db.con.execute("UPDATE games SET home_score = home_score + 9, away_score = away_score + 9")
    name, gap = "player points sum to team score", "known ESPN gaps: points don't add up"
    by = {c.name: c for c in quality.run_checks(db)}
    assert (by[name].failures, by[gap].failures) == (2, 0)
    # listing one team-game turns only that one into a known gap; its opponent still fails
    monkeypatch.setattr(quality, "KNOWN_POINTS_MISMATCH", {("401909907", g["home_team_id"])})
    by = {c.name: c for c in quality.run_checks(db)}
    assert (by[name].failures, by[gap].failures) == (1, 1)
    assert by[name].hard and not by[gap].hard


def test_quality_known_points_mismatch_list():
    from deepsports.quality import KNOWN_POINTS_MISMATCH

    ids = {"401597895", "401597922", "401608976", "401720664", "401722030", "401722338",
           "401727325"}  # fmt: skip
    assert {g for g, _ in KNOWN_POINTS_MISMATCH} == ids and len(KNOWN_POINTS_MISMATCH) == 7
