"""Play-by-play and possession in /api/games/{id}: views.parse_plays, views.game_possession, and
the 10s live TTL. Hand-trimmed plays follow the real ESPN shape; real fixtures are at the bottom."""

import copy
import gzip
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from deepsports.api import app as app_module
from deepsports.api import views
from deepsports.api.live import GAME_LIVE_TTL, IDLE_TTL, LIVE_TTL, LiveService
from deepsports.http import PoliteClient
from deepsports.sources.espn import EspnBasketball

FIX = Path(__file__).parent / "fixtures"
SENTINEL = {"x": -214748340, "y": -214748365}
A, B = "3", "12"  # away, home


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def play(seq=1, type_text="Jump Shot", text="", team=A, **extra) -> dict:
    p = {
        "id": f"401909950{seq}",
        "sequenceNumber": str(seq),
        "type": {"id": "1", "text": type_text},
        "text": text,
        "awayScore": 0,
        "homeScore": 0,
        "period": {"number": 1},
        "clock": {"displayValue": "4:12"},
        "scoringPlay": False,
        "scoreValue": 0,
        "shootingPlay": False,
        "coordinate": SENTINEL,
        "pointsAttempted": 0,
    }
    if team is not None:
        p["team"] = {"id": team}
    return p | extra


def shot(seq=1, made=True, team=A, text="x", **extra) -> dict:
    return play(seq, "Jump Shot", text, team, shootingPlay=True, scoringPlay=made,
                scoreValue=2 if made else 0, **extra)  # fmt: skip


def raw_game(plays, state="in", name="STATUS_IN_PROGRESS", period=1, possession=None) -> dict:
    raw = copy.deepcopy(load("espn_summary_final.json"))
    comp = raw["header"]["competitions"][0]
    comp["status"] = {
        "period": period,
        "displayClock": "4:12",
        "type": {"name": name, "state": state, "completed": state == "post"},
    }
    for c, team_id, side in zip(comp["competitors"], (A, B), ("away", "home"), strict=True):
        c["id"] = team_id
        c["team"]["id"] = team_id
        c["homeAway"] = side
        c["possession"] = possession == team_id
    raw["plays"] = plays
    return raw


def inferred(*plays) -> str | None:
    pos = views.game_possession(raw_game(list(plays)), views.parse_plays({"plays": list(plays)}))
    assert pos is None or pos["source"] == "inferred"
    return pos["team_id"] if pos else None


# ---------- parse_plays ----------


def test_plays_sorted_by_sequence_number_not_list_order():
    plays = views.parse_plays({"plays": [play(10), play(9), play(145), play(2)]})
    assert [p["seq"] for p in plays] == [2, 9, 10, 145]


def test_play_shape_on_the_real_sample():
    raw_play = {
        "id": "401909950145", "sequenceNumber": "145",
        "type": {"id": "94", "text": "Tip Shot"}, "text": "Saddiq Bey misses tip shot",
        "awayScore": 24, "homeScore": 25,
        "period": {"number": 1, "displayValue": "1st Quarter"},
        "clock": {"displayValue": "1:05"}, "scoringPlay": False, "scoreValue": 0,
        "team": {"id": "3"}, "participants": [{"athlete": {"id": "4397136"}}],
        "wallclock": "2026-11-09T02:35:26Z", "shootingPlay": True,
        "coordinate": {"x": 25, "y": 0}, "pointsAttempted": 2, "shortDescription": "Missed FG",
    }  # fmt: skip
    assert views.parse_plays({"plays": [raw_play]}) == [
        {
            "id": "401909950145",
            "seq": 145,
            "period": 1,
            "clock": "1:05",
            "text": "Saddiq Bey misses tip shot",
            "team_id": "3",
            "away_score": 24,
            "home_score": 25,
            "scoring": False,
            "points": 0,
            "kind": "shot_missed",
            "coord": {"x": 25, "y": 0},
        }
    ]


def test_stale_scores_never_fall():
    scores = [(5, 7), (5, 9), (3, 7), (6, 7)]  # third play's annotation is stale
    plays = views.parse_plays(
        {"plays": [play(i, awayScore=a, homeScore=h) for i, (a, h) in enumerate(scores)]}
    )
    assert [(p["away_score"], p["home_score"]) for p in plays] == [
        (5, 7), (5, 9), (5, 9), (6, 9),
    ]  # fmt: skip


def test_missing_scores_carry_forward():
    plays = views.parse_plays(
        {"plays": [play(1, awayScore=4, homeScore=2), play(2, awayScore=None, homeScore=None)]}
    )
    assert (plays[1]["away_score"], plays[1]["home_score"]) == (4, 2)


def test_college_missed_free_throw_with_made_type_text():
    p = play(1, "MadeFreeThrow", "Montana Wheeler missed Free Throw.", shootingPlay=True,
             scoreValue=1, pointsAttempted=1, coordinate={"x": 25, "y": 0})  # fmt: skip
    got = views.parse_plays({"plays": [p]})[0]
    assert got["kind"] == "free_throw_missed"
    assert (got["scoring"], got["points"], got["coord"]) == (False, 0, None)


def test_coordinates():
    def coord(p):
        return views.parse_plays({"plays": [p]})[0]["coord"]

    assert coord(shot(coordinate={"x": 39, "y": 22})) == {"x": 39, "y": 22}
    assert coord(shot(coordinate={"x": 27, "y": 70})) == {"x": 27, "y": 70}  # heave
    assert coord(shot(coordinate=SENTINEL)) is None
    assert coord(shot(coordinate={"x": 25, "y": -214748365})) is None
    assert coord(shot(coordinate={"x": 60, "y": 5})) is None
    no_coord = shot()
    del no_coord["coordinate"]
    assert coord(no_coord) is None
    # college non-shots carry a placeholder (25, 0), real fouls carry a spot: neither is a shot
    assert coord(play(1, "PersonalFoul", coordinate={"x": 23, "y": 75})) is None
    made_ft = play(1, "Free Throw - 1 of 2", shootingPlay=True, scoringPlay=True, scoreValue=1,
                   coordinate={"x": 25, "y": 0})  # fmt: skip
    assert coord(made_ft) is None


@pytest.mark.parametrize(
    ("type_text", "text", "extra", "kind"),
    [
        ("Jump Shot", "makes", {"shootingPlay": True, "scoringPlay": True}, "shot_made"),
        ("Jump Shot", "misses", {"shootingPlay": True}, "shot_missed"),
        ("Free Throw - 2 of 2", "makes", {"shootingPlay": True, "scoringPlay": True},
         "free_throw_made"),
        ("Free Throw - 2 of 2", "misses", {"shootingPlay": True}, "free_throw_missed"),
        ("Defensive Rebound", "", {}, "rebound"),
        ("Dead Ball Rebound", "", {}, "rebound"),
        ("Bad Pass\nTurnover", "", {}, "turnover"),
        ("Traveling", "Derrick Jones Jr. traveling turnover", {}, "turnover"),
        ("Shooting Foul", "", {}, "foul"),
        ("Offensive Charge", "Josh Okogie offensive charge", {}, "foul"),
        ("Flopping Technical", "", {}, "foul"),
        ("Full Timeout", "", {}, "timeout"),
        ("OfficialTVTimeOut", "", {}, "timeout"),
        ("Substitution", "", {}, "substitution"),
        ("End Period", "", {}, "period_end"),
        ("End Game", "", {}, "period_end"),
        ("Jumpball", "", {}, "other"),
        ("Steal", "Cayden Charles Steal.", {}, "other"),
        ("Coach's Challenge (Stands)", "overturned turnover call", {}, "other"),
        ("Ref-Initiated Review (Stands)", "turnover review", {}, "other"),
        ("", "", {}, "other"),
    ],
)  # fmt: skip
def test_play_kinds(type_text, text, extra, kind):
    assert views.parse_plays({"plays": [play(1, type_text, text, **extra)]})[0]["kind"] == kind


def test_missing_team_and_sparse_play_do_not_crash():
    plays = views.parse_plays(
        {"plays": [play(1, "End Period", "End of the 1st Quarter", team=None), {"id": "7"}]}
    )
    assert plays[0]["team_id"] is None and plays[0]["kind"] == "period_end"
    assert plays[1]["clock"] is None and plays[1]["text"] == ""
    assert (plays[1]["period"], plays[1]["points"], plays[1]["coord"]) == (1, 0, None)


def test_points_only_on_scoring_plays():
    college_miss = shot(1, made=False)
    college_miss["scoreValue"] = 3  # college misses carry the shot's value
    plays = views.parse_plays({"plays": [college_miss, shot(2)]})
    assert [p["points"] for p in plays] == [0, 2]


# ---------- possession: inferred ----------


@pytest.mark.parametrize("type_text", ["Defensive Rebound", "Offensive Rebound"])
def test_rebound_goes_to_rebounder(type_text):
    assert inferred(shot(1, made=False), play(2, type_text, team=B)) == B


def test_made_shot_goes_to_other_team():
    assert inferred(shot(1, team=A)) == B
    assert inferred(shot(1, team=B)) == A


def test_and_one_foul_after_made_shot_is_unknown():
    assert inferred(shot(1), play(2, "Shooting Foul", "shooting foul", team=B)) is None


def test_turnover_goes_to_other_team():
    assert inferred(play(1, "Lost Ball Turnover", "x lost ball turnover", team=A)) == B
    assert inferred(play(1, "Traveling", "x traveling turnover", team=B)) == A


def test_college_steal_goes_to_stealer():
    assert inferred(play(1, "Steal", "Cayden Charles Steal.", team=B)) == B


@pytest.mark.parametrize(
    ("type_text", "text"),
    [("Offensive Foul", "Saddiq Bey offensive foul"),
     ("Offensive Charge", "Josh Okogie offensive charge")],
)  # fmt: skip
def test_offensive_foul_goes_to_other_team(type_text, text):
    assert inferred(play(1, type_text, text, team=A)) == B


def ft(text, made=True, type_text="Free Throw - 1 of 2", team=A) -> dict:
    return play(1, type_text, text, team, shootingPlay=True, scoringPlay=made,
                scoreValue=1 if made else 0)  # fmt: skip


def test_made_free_throw_flips_only_on_the_last_of_the_set():
    assert inferred(ft("Fears makes free throw 2 of 2")) == B
    assert inferred(ft("Fears makes free throw 3 of 3")) == B
    assert inferred(ft("Fears makes free throw 1 of 1")) == B
    assert inferred(ft("Fears makes free throw 1 of 2")) is None
    assert inferred(ft("Fears makes free throw 2 of 3")) is None


def test_missed_free_throw_is_unknown_until_the_rebound():
    assert inferred(ft("Fears misses free throw 2 of 2", made=False)) is None


@pytest.mark.parametrize(
    "text",
    ["Fears makes technical free throw",
     "Fears makes free throw flagrant 2 of 2",
     "Fears makes free throw clear path 2 of 2",
     "Cayden Charles made Free Throw."],  # older college text has no count
)  # fmt: skip
def test_free_throws_that_do_not_end_a_trip_are_unknown(text):
    assert inferred(ft(text)) is None


@pytest.mark.parametrize(
    "last",
    [
        play(2, "Full Timeout", "Clippers Full timeout"),
        play(2, "OfficialTVTimeOut", "Official TV Timeout", team=None),
        play(2, "End Period", "End of the 1st Quarter", team=None),
        play(2, "Jumpball", "Lopez vs. Matkovic (Jones gains possession)"),
        play(2, "Personal Foul", "x personal foul"),
        play(2, "Loose Ball Foul", "x loose ball foul"),
        play(2, "PersonalFoul", "Foul on Demarion Burch."),
        play(2, "Block Shot", "Andrew Osasuyi Block."),
        shot(2, made=False),
    ],
)
def test_unknowable_latest_play_is_null(last):
    assert inferred(shot(1), last) is None


def test_substitutions_are_skipped():
    sub = play(2, "Substitution", "x enters the game for y")
    assert inferred(shot(1, team=A), sub, {**sub, "sequenceNumber": "3"}) == B
    timeout = play(2, "Full Timeout", "timeout")
    assert inferred(shot(1), timeout, {**sub, "sequenceNumber": "3"}) is None


def test_no_plays_or_only_substitutions_is_null():
    assert inferred() is None
    assert inferred(play(1, "Substitution", "x enters the game for y")) is None


def test_play_without_a_known_team_is_null():
    assert inferred(play(1, "Defensive Rebound", "team rebound", team=None)) is None
    assert inferred(play(1, "Defensive Rebound", "rebound", team="999")) is None
    assert inferred(shot(1, team=None)) is None


def test_buzzer_play_and_stale_period_are_null():
    assert inferred(shot(1, clock={"displayValue": "0:00"})) is None
    assert inferred(shot(1, clock={"displayValue": "0.0"})) is None
    assert inferred(shot(1, clock={"displayValue": "0.4"})) == B
    plays = [shot(1)]
    raw = raw_game(plays, period=2)  # Q2 has started; the latest play is from Q1
    assert views.game_possession(raw, views.parse_plays(raw)) is None


@pytest.mark.parametrize("name", ["STATUS_HALFTIME", "STATUS_END_PERIOD"])
def test_breaks_are_null_even_if_the_end_of_period_play_has_not_posted(name):
    raw = raw_game([shot(1)], name=name)
    assert views.game_possession(raw, views.parse_plays(raw)) is None


# ---------- possession: ESPN ----------


def test_espn_competitor_possession_wins_over_inference():
    raw = raw_game([shot(1, team=A)], possession=A)  # a made shot alone would infer B
    assert views.game_possession(raw, views.parse_plays(raw)) == {"team_id": A, "source": "espn"}


@pytest.mark.parametrize(
    "situation", [{"possession": B}, {"possession": int(B)}, {"possession": {"id": B}}]
)
def test_espn_situation_block(situation):
    raw = raw_game([], possession=None)
    raw["situation"] = situation
    assert views.game_possession(raw, []) == {"team_id": B, "source": "espn"}
    del raw["situation"]
    raw["header"]["competitions"][0]["situation"] = situation
    assert views.game_possession(raw, []) == {"team_id": B, "source": "espn"}


def test_espn_flags_all_false_falls_back_to_inference():
    raw = raw_game([shot(1, team=A)])
    assert views.game_possession(raw, views.parse_plays(raw)) == {
        "team_id": B,
        "source": "inferred",
    }


def test_espn_situation_with_unknown_team_is_ignored():
    raw = raw_game([])
    raw["situation"] = {"possession": "999"}
    assert views.game_possession(raw, []) is None


@pytest.mark.parametrize(("state", "name"), [("pre", "STATUS_SCHEDULED"), ("post", "STATUS_FINAL")])
def test_possession_is_null_unless_in_progress(state, name):
    raw = raw_game([shot(1)], state=state, name=name, possession=A)
    assert views.game_possession(raw, views.parse_plays(raw)) is None


# ---------- game_detail ----------


def test_game_detail_adds_plays_and_possession():
    d = views.game_detail(raw_game([shot(2, team=A), shot(1, team=B)]), set())
    assert [p["seq"] for p in d["plays"]] == [1, 2]
    assert d["possession"] == {"team_id": B, "source": "inferred"}
    assert {d["game"]["away"]["id"], d["game"]["home"]["id"]} == {A, B}


def test_game_detail_before_tip_and_without_plays():
    pre = raw_game([shot(1)], state="pre", name="STATUS_SCHEDULED")
    assert views.game_detail(pre, set())["plays"] == []
    assert views.game_detail(pre, set())["possession"] is None
    pregame = views.game_detail(load("espn_ncaab_summary_pregame_nev_smc.json"), {"NEV"}, "ncaab")
    assert pregame["plays"] == [] and pregame["possession"] is None
    final = views.game_detail(load("espn_summary_final.json"), set())  # this fixture has no plays
    assert final["plays"] == [] and final["possession"] is None


# ---------- TTL and transport ----------


class FakeGames:
    def __init__(self, raw):
        self.raw = raw
        self.summaries = self.scoreboards = 0

    def summary(self, game_id, refresh=False):
        self.summaries += 1
        return self.raw

    def scoreboard(self, day, refresh=False):
        self.scoreboards += 1
        return {"events": [{"status": {"type": {"state": "in"}}}]}


@pytest.mark.parametrize(
    ("state", "name", "ttl"),
    [("in", "STATUS_IN_PROGRESS", GAME_LIVE_TTL), ("pre", "STATUS_SCHEDULED", IDLE_TTL),
     ("post", "STATUS_FINAL", IDLE_TTL)],
)  # fmt: skip
def test_summary_ttl_by_state(state, name, ttl):
    now = [0.0]
    src = FakeGames(raw_game([], state=state, name=name))
    live = LiveService(src=src, clock=lambda: now[0])
    live.summary("1")
    now[0] += ttl - 0.5
    live.summary("1")
    assert src.summaries == 1
    now[0] += 1
    live.summary("1")
    assert src.summaries == 2


def test_ttl_values_and_scoreboard_keeps_its_own():
    assert (GAME_LIVE_TTL, LIVE_TTL) == (10, 30)
    assert LiveService.refresh_seconds(True) == 30
    assert LiveService.game_refresh_seconds(True) == 10
    assert LiveService.game_refresh_seconds(False) == IDLE_TTL
    from datetime import date

    now = [0.0]
    src = FakeGames(raw_game([]))
    live = LiveService(src=src, clock=lambda: now[0])
    live.scoreboard(date(2026, 11, 8))
    now[0] += 29
    live.scoreboard(date(2026, 11, 8))
    assert src.scoreboards == 1
    now[0] += 2
    live.scoreboard(date(2026, 11, 8))
    assert src.scoreboards == 2


def test_in_progress_summary_is_not_served_from_the_disk_cache(tmp_path):
    """src.summary's cache rule: only a completed game is reused, so the TTL is the only delay."""
    calls = {"n": 0}
    state = {"raw": raw_game([], state="in")}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=state["raw"])

    client = PoliteClient(raw_dir=tmp_path, min_interval=0, sleep=lambda s: None,
                          client=httpx.Client(transport=httpx.MockTransport(handler)))  # fmt: skip
    src = EspnBasketball(client, "nba")
    src.summary("1")
    src.summary("1")
    assert calls["n"] == 2
    state["raw"] = raw_game([], state="post", name="STATUS_FINAL")
    src.summary("1")
    src.summary("1")
    assert calls["n"] == 3


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "followed_teams", lambda league="nba": set())
    # About a full game, with long enough text to be worth compressing
    plays = [shot(i, text=f"Player {i} makes a very long jump shot") for i in range(1, 500)]
    live = LiveService(src=FakeGames(raw_game(plays)))
    app = app_module.create_app(
        live=live, db_path=tmp_path / "missing.duckdb", web_dist=tmp_path / "nodist"
    )
    return TestClient(app)


def test_endpoint_returns_plays_at_the_live_refresh_rate(client):
    body = client.get("/api/games/401909950").json()
    assert body["refresh_seconds"] == 10
    assert len(body["plays"]) == 499 and body["possession"]["source"] == "inferred"
    assert body["game"]["state"] == "in"


def test_endpoint_is_gzipped_and_keeps_cors(client):
    r = client.get(
        "/api/games/401909950",
        headers={"Origin": "https://evenhub.example", "Accept-Encoding": "gzip"},
    )
    assert r.headers["content-encoding"] == "gzip"
    assert r.headers["access-control-allow-origin"] == "*"
    assert r.json()["plays"]


# ---------- real saved summaries ----------


@pytest.mark.parametrize(
    "name", ["espn_nba_summary_pbp_401358773", "espn_ncaab_summary_pbp_401804830"]
)
def test_real_summaries_parse_consistently(name):
    with gzip.open(FIX / f"{name}.json.gz", "rt", encoding="utf-8") as f:
        raw = json.load(f)
    plays = views.parse_plays(raw)
    assert len(plays) == len(raw["plays"]) > 400
    assert [p["seq"] for p in plays] == sorted(p["seq"] for p in plays)
    for before, after in zip(plays, plays[1:], strict=False):
        assert after["away_score"] >= before["away_score"]
        assert after["home_score"] >= before["home_score"]
    finals = {
        c["homeAway"]: int(c["score"]) for c in raw["header"]["competitions"][0]["competitors"]
    }
    assert sum(p["points"] for p in plays) == finals["home"] + finals["away"]
    for p in plays:
        if p["kind"] not in ("shot_made", "shot_missed"):
            assert p["coord"] is None
        assert p["scoring"] == (p["points"] > 0)
        assert p["scoring"] == (p["kind"] in ("shot_made", "free_throw_made"))
    assert any(p["coord"] for p in plays)
