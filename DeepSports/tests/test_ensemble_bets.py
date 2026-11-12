import json
import re
from datetime import UTC, datetime, timedelta

import pytest

from deepsports.analysis import ensemble_bets as eb

TIP = datetime(2026, 11, 8, 3, 0, tzinfo=UTC)


def _raw(game_id="g1", league="nba"):
    return {
        "game_id": game_id, "league": league, "season_year": 2027, "start_time_utc": TIP,
        "neutral_site": False, "venue": "Arena", "broadcasts": "ESPN",
        "home_team_id": "1", "away_team_id": "2", "home_abbr": "LAL", "home_name": "Lakers",
        "home_d1": True, "away_abbr": "BOS", "away_name": "Celtics", "away_d1": True,
    }  # fmt: skip


def _line(spread=-3.5, total=225.5, hp=-112, ap=-108, op=-110, up=-110, hml=-160, aml=135):
    return {
        "captured_at": TIP - timedelta(hours=5), "provider": "DraftKings", "spread_home": spread,
        "over_under": total, "home_moneyline": hml, "away_moneyline": aml,
        "spread_home_price": hp, "spread_away_price": ap, "over_price": op, "under_price": up,
    }  # fmt: skip


FORM = {"1": {"w": 3, "l": 1, "hw": 2, "hl": 0, "aw": 1, "al": 1, "l5w": 3, "l5l": 1,
              "avg_margin": 5.25, "l5_margin": 5.25, "avg_total": 224.0},
        "2": {}}  # fmt: skip
INJ = {("g1", "1"): [{"athlete_name": "Star", "status": "out", "detail": "knee", "mpg": 34.2,
                      "ppg": 25.1}]}  # fmt: skip
PRED = {"model_version": "v1.1", "p_home_win": 0.62, "pred_home_margin": 4.1, "pred_total": 228}


def _slate():
    g1 = eb.build_game(_raw(), {"last": _line(), "first": _line(spread=-2.5)}, PRED, FORM, {}, INJ)
    g2 = eb.build_game(_raw("g2"), {"last": _line(spread=None, hml=None)}, None, FORM, {}, {})
    return {"created_at": "2026-11-07T22:00:00+00:00", "days": 3, "leagues": ["nba"],
            "unlined_games": 4, "games": [g1, g2]}  # fmt: skip


def test_build_game_markets_and_no_line():
    g = _slate()["games"][0]
    assert g["markets"]["spread"] == {
        "home_line": -3.5, "home_price": -112, "away_line": 3.5, "away_price": -108,
    }  # fmt: skip
    assert g["markets"]["moneyline"]["market_home_win_prob"] == pytest.approx(0.591, abs=0.001)
    assert g["home"]["injuries"][0]["player"] == "Star"
    assert g["away"]["avg_margin"] is None
    # no pregame row at all, or a row with nothing sane, is not bettable
    assert eb.build_game(_raw(), {}, None, FORM, {}, {}) is None
    bad = _line(spread=99, total=5, hml=None)
    assert eb.build_game(_raw(), {"last": bad}, None, FORM, {}, {}) is None
    # NULL price falls back to -110
    g = eb.build_game(_raw(), {"last": _line(hp=None)}, None, FORM, {}, {})
    assert g["markets"]["spread"]["home_price"] == -110


def test_render_context_shuffles_but_keeps_facts():
    slate = _slate()
    a, b = eb.render_context(slate, seed=1), eb.render_context(slate, seed=2)
    assert set(a.splitlines()) == set(b.splitlines())
    assert "LAL -3.5 (-112)" in a and "spread LAL -2.5 → -3.5" in a
    assert "Star out (34.2 mpg, 25.1 ppg)" in a
    assert "no games this season yet" in a  # BOS has no form
    assert "4 more in the window have" in a.replace("\n", " ")


def test_parse_reply_tolerates_fences():
    obj = eb.parse_reply('```json\n{"picks": [], "notes": "pass"}\n```')
    assert obj["picks"] == []
    with pytest.raises(ValueError):
        eb.parse_reply("no json here")
    with pytest.raises(ValueError):
        eb.parse_reply('{"bets": []}')


def test_validate_picks_uses_slate_prices_and_rules():
    slate = _slate()
    reply = {"picks": [
        {"game_id": "g1", "market": "spread", "side": "away", "line": 10, "price": 500,
         "stake": 9, "confidence": 0.56},
        {"game_id": "g1", "market": "total", "side": "over"},          # second pick, same game
        {"game_id": "g2", "market": "spread", "side": "home"},         # not offered
        {"game_id": "g9", "market": "total", "side": "over"},          # not on slate
        {"game_id": "g2", "market": "total", "side": "sideways"},      # bad side
        {"game_id": "g2", "market": "total", "side": "UNDER", "stake": "x"},
    ]}  # fmt: skip
    picks, problems = eb.validate_picks(reply, slate)
    assert [(p["game_id"], p["market"], p["side"]) for p in picks] == [
        ("g1", "spread", "away"),
        ("g2", "total", "under"),
    ]
    assert picks[0]["line"] == 3.5 and picks[0]["price"] == -108 and picks[0]["stake"] == 3
    assert picks[1]["stake"] == 1 and picks[1]["line"] == 225.5
    assert len(problems) == 4
    # games that tipped before the tally are dropped
    late, probs = eb.validate_picks(reply, slate, now=TIP)
    assert late == [] and all("dropped" in p or "not" in p for p in probs)


def test_validate_picks_caps_count():
    games = [eb.build_game(_raw(f"g{i}"), {"last": _line()}, None, FORM, {}, {}) for i in range(12)]
    slate = {**_slate(), "games": games}
    reply = {"picks": [{"game_id": f"g{i}", "market": "total", "side": "over"} for i in range(12)]}
    picks, problems = eb.validate_picks(reply, slate)
    assert len(picks) == eb.MAX_PICKS and len(problems) == 12 - eb.MAX_PICKS


def test_tally_strict_majority_and_against():
    def pk(gid, m, s):
        return {"game_id": gid, "market": m, "side": s}

    picks = {
        "a01": [pk("g1", "spread", "home"), pk("g2", "total", "over")],
        "a02": [pk("g1", "spread", "home")],
        "a03": [pk("g1", "spread", "home"), pk("g2", "total", "under")],
        "a04": [pk("g1", "spread", "away"), pk("g2", "total", "over")],
    }
    r = eb.tally(picks, n_agents=5)  # a05 passed on everything
    assert [(c.game_id, c.side, c.votes, c.against) for c in r["majority"]] == [
        ("g1", "home", 3, 1)
    ]
    assert r["games_bet_by_anyone"] == 2
    # 2 of 4 is not a strict majority
    assert eb.tally({k: v for k, v in picks.items() if k != "a03"}, 4)["majority"] == []


def test_grade_pick():
    final = {"home_score": 110, "away_score": 105}  # margin +5, total 215
    home = {"market": "spread", "side": "home", "line": -3.5, "price": -110, "stake": 1}
    away = {"market": "spread", "side": "away", "line": 3.5, "price": -110, "stake": 2}
    assert eb.grade_pick(home, final)["grade"] == "win"
    assert eb.grade_pick(home, final)["profit"] == pytest.approx(0.909, abs=0.001)
    assert eb.grade_pick(away, final)["profit"] == -2
    push = {"market": "spread", "side": "away", "line": 5.0, "price": -110, "stake": 1}
    assert eb.grade_pick(push, final)["grade"] == "push"
    under = {"market": "total", "side": "under", "line": 225.5, "price": -105, "stake": 1}
    assert eb.grade_pick(under, final)["grade"] == "win"
    ml = {"market": "moneyline", "side": "away", "line": None, "price": 150, "stake": 1}
    assert eb.grade_pick(ml, final)["profit"] == -1
    s = eb.summarize_graded([eb.grade_pick(p, final) for p in (home, away, push, under)])
    assert s["record"] == "2-1-1" and s["units_staked"] == 5


def test_run_dir_round_trip(tmp_path):
    slate = _slate()
    run = eb.new_run_dir(datetime(2026, 11, 7, 22, tzinfo=UTC), root=tmp_path)
    paths = eb.write_context(run, slate, n_agents=3)
    assert [p.name for p in paths] == ["context-a01.md", "context-a02.md", "context-a03.md"]
    vote = {"picks": [{"game_id": "g1", "market": "spread", "side": "home", "reason": "r"}]}
    (run / "picks-a01.json").write_text(json.dumps(vote))
    (run / "picks-a02.json").write_text("Sure! " + json.dumps(vote))
    # a03 never replied: counts as a pass and a problem
    now = TIP - timedelta(hours=2)
    md, out = eb.tally_run(run, now=now)
    assert out["n_agents"] == 3
    assert [(m["label"], m["votes"], m["price"]) for m in out["majority"]] == [
        ("LAL -3.5", 2, -112)
    ]
    assert "a03" in out["problems"] and "2/3 agree" in md
    # tallied once: a later call returns the saved tally even after tip-off
    assert eb.tally_run(run, now=TIP + timedelta(hours=1))[1] == out
    table = eb.table_run(run)
    assert "```" in table and "LAL -3.5" in table and "-112" in table and "2/3" in table


def test_render_table_close_calls_and_empty():
    slate = _slate()
    g = slate["games"][0]
    pick = {
        "game_id": g["game_id"],
        "market": "total",
        "side": "over",
        "line": 225.5,
        "price": -110,
    }
    under = {**pick, "side": "under"}
    out = {"n_agents": 10, "majority": [],
           "picks": {"a01": [pick], "a02": [pick], "a03": [pick], "a04": [under]}}  # fmt: skip
    t = eb.render_table(out, slate)
    assert "No pick has a majority today." in t
    assert "Over 225.5 (-110)" in t and "3/10, 1 on the other side" in t


def test_grade_runs_by_context_version(tmp_path):
    import duckdb

    con = duckdb.connect()
    con.execute(
        "CREATE TABLE games (game_id VARCHAR, home_score INT, away_score INT, completed BOOLEAN,"
        " status VARCHAR)"
    )
    con.execute("INSERT INTO games VALUES ('g1', 110, 105, TRUE, 'STATUS_FINAL')")
    pick = {"game_id": "g1", "market": "spread", "side": "home", "line": -3.5, "price": -110,
            "stake": 1}  # fmt: skip
    for name, ver in (("r1", None), ("r2", "ctx-v2")):
        (tmp_path / name).mkdir()
        t = {"majority": [pick], "picks": {"a01": [pick]}}
        if ver:
            t["context_version"] = ver
        (tmp_path / name / "tally.json").write_text(json.dumps(t))
    g = eb.grade_runs(con, root=tmp_path)
    assert g["runs"] == 2 and g["majority"]["record"] == "2-0-0"
    assert set(g["by_context_version"]) == {"ctx-v1", "ctx-v2"}  # unversioned runs are ctx-v1
    assert g["by_context_version"]["ctx-v2"]["majority"]["bets"] == 1


# ---------- one-pick brief and historical (point-in-time) slates ----------


def test_render_context_one_pick_and_notes():
    slate = {**_slate(), "brief_notes": ["Lines are the final pre-tip lines.", "No injury data."]}
    one = eb.render_context(slate, seed=1, one_pick=True)
    assert "EXACTLY ONE pick" in one and "passing is not allowed" in one
    assert "At most" not in one and "Passing is allowed" not in one
    assert "- Lines are the final pre-tip lines.\n- No injury data.\n" in one
    live = eb.render_context(_slate(), seed=1)
    assert f"At most {eb.MAX_PICKS} picks" in live and "EXACTLY ONE" not in live
    # same game facts either way
    assert set(live.splitlines()) - set(one.splitlines()) <= set(
        eb.BRIEF.format(
            decide=eb.DECIDE,
            limits=eb.LIMITS.format(max_picks=eb.MAX_PICKS, max_stake=eb.MAX_STAKE),
            created_at=slate["created_at"], n_games=2, unlined=4,
        ).splitlines()
    )  # fmt: skip


def test_validate_picks_one_pick_slate():
    slate = {**_slate(), "max_picks": 1, "max_stake": 1}
    reply = {"picks": [
        {"game_id": "g1", "market": "spread", "side": "home", "stake": 3},
        {"game_id": "g2", "market": "total", "side": "over"},
    ]}  # fmt: skip
    picks, problems = eb.validate_picks(reply, slate)
    assert [(p["game_id"], p["stake"]) for p in picks] == [("g1", 1)]
    assert problems == ["pick 1: over the 1-pick limit, dropped"]


NOW = datetime(2026, 11, 7, 23, 0, tzinfo=UTC)  # decision time; the target game tips at 00:00


@pytest.fixture
def hist_db():
    from deepsports.store import Store

    store = Store(":memory:")
    con = store.con
    ts = NOW - timedelta(days=30)
    for tid, ab, name in (("1", "LAL", "Lakers"), ("2", "BOS", "Celtics"), ("3", "NY", "Knicks")):
        con.execute(
            "INSERT INTO teams (team_id, league, abbreviation, display_name, listed, updated_at)"
            " VALUES (?, 'nba', ?, ?, TRUE, ?)",
            [tid, ab, name, ts],
        )

    def game(gid, start, home, away, hs, as_, state="post"):
        con.execute(
            "INSERT INTO games (game_id, league, season_year, season_type, start_time_utc, status,"
            " state, completed, home_team_id, away_team_id, home_score, away_score, venue,"
            " venue_city, neutral_site, broadcasts, updated_at)"
            " VALUES (?, 'nba', 2027, 2, ?, 'STATUS_FINAL', ?, TRUE, ?, ?, ?, ?, 'Arena',"
            " 'Los Angeles', FALSE, 'TV', ?)",
            [gid, start, state, home, away, hs, as_, ts],
        )

    game("g0", NOW - timedelta(days=2), "1", "3", 101, 99)  # finished: counts toward form
    game("gr", NOW - timedelta(hours=2), "3", "1", 157, 58)  # not finished by NOW: excluded
    game("g1", NOW + timedelta(hours=1), "1", "2", 187, 43)  # the target game (already final)
    game("g9", NOW + timedelta(days=1, hours=2), "2", "1", 111, 109)  # outside the window
    cols = (
        "game_id, source, captured_at, provider, spread_home, over_under, home_moneyline,"
        " away_moneyline, spread_home_price, spread_away_price, over_price, under_price"
    )
    for src, at, sp, tot in (
        ("opening", NOW - timedelta(days=1), -2.5, 221.5),
        ("closing", NOW + timedelta(days=2), -4.5, 220.5),  # stored by a later backfill
    ):
        con.execute(
            f"INSERT INTO odds_snapshots ({cols}) VALUES ('g1', ?, ?, 'DK', ?, ?, -180, 150,"
            " -112, -108, -110, -110)",
            [src, at, sp, tot],
        )
    for at, before, who in (
        (NOW - timedelta(hours=3), True, "Early Guy"),  # usable
        (NOW + timedelta(minutes=30), True, "Late Guy"),  # captured after the decision time
    ):
        con.execute("INSERT INTO injury_captures VALUES ('g1', '1', ?, ?, 1, 'nba')", [at, before])
        con.execute(
            "INSERT INTO injury_reports (game_id, team_id, athlete_id, athlete_name, status,"
            " captured_at, captured_before_tip, league) VALUES ('g1', '1', ?, ?, 'Out', ?, ?,"
            " 'nba')",
            [who.split()[0], who, at, before],
        )
    for gid, mins, pts in (("g0", 30, 20), ("g1", 48, 77)):  # g1's box must not feed ppg
        con.execute(
            "INSERT INTO player_game_stats (game_id, team_id, athlete_id, athlete_name,"
            " did_not_play, minutes, pts, updated_at, league) VALUES (?, '1', 'Early',"
            " 'Early Guy', FALSE, ?, ?, ?, 'nba')",
            [gid, mins, pts, ts],
        )
    yield con
    store.close()


def test_historical_slate_is_point_in_time(hist_db):
    pred = {"g1": {"model_version": "v1.1", "p_home_win": 0.6, "pred_home_margin": 3.0,
                   "pred_total": 224.0}}  # fmt: skip
    slate = eb.load_historical_slate(
        hist_db, NOW, NOW + timedelta(hours=12), predictions=pred, model_source="test"
    )
    assert [g["game_id"] for g in slate["games"]] == ["g1"]
    assert slate["context_version"] == eb.SIM_CONTEXT_VERSION
    assert (slate["max_picks"], slate["max_stake"]) == (1, 1)
    g = slate["games"][0]
    # closing line, opening as first seen; the later capture time is not carried
    assert g["markets"]["spread"]["home_line"] == -4.5 and g["first_seen"]["spread_home"] == -2.5
    assert g["line_captured_at"] is None and g["line_source"] == "closing"
    # form: only g0 (gr tipped 2h before NOW, not finished)
    assert g["home"]["record"] == "1-0" and g["home"]["avg_margin"] == 2.0
    assert g["away"]["record"] == "0-0"
    # injuries: the capture before NOW only; season averages exclude g1's own box
    assert [(i["player"], i["mpg"], i["ppg"]) for i in g["home"]["injuries"]] == [
        ("Early Guy", 30.0, 20.0)
    ]
    text = eb.render_context(slate, seed=0, one_pick=True)
    assert "Late Guy" not in text and "Lines are the final pre-tip lines" in text
    # leakage: the target game's final score and result never appear
    blob = text + json.dumps(slate, default=str)
    for leak in ("187", "43", "230", "144", "77", "48", "157", "58"):
        assert not re.search(rf"(?<![\d.:-]){leak}(?![\d:])", blob), leak
    assert "score" not in blob and "STATUS" not in blob


def test_historical_slate_without_injury_capture(hist_db):
    slate = eb.load_historical_slate(hist_db, NOW - timedelta(hours=4), NOW + timedelta(hours=12))
    assert slate["injuries_captured_at"] is None
    assert "No injury data for this date." in slate["brief_notes"]
    g = next(g for g in slate["games"] if g["game_id"] == "g1")
    assert g["home"]["injuries"] == [] and g["model"] is None
