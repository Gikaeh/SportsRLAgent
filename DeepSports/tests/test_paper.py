"""Forward paper-trade log (analysis/paper.py, paper_bets, paper_results): frozen first logs,
pre-tip only, lines captured before logging, the -early college version excluded, rule
thresholds, the load rule, grading/CLV, and the CLI. Synthetic temp warehouses only."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from deepsports.analysis import paper
from deepsports.analysis.fatigue import top8_load
from deepsports.store import Store

NOW = datetime(2026, 11, 10, 17, 0, tzinfo=UTC)  # 12:00 US/Eastern, Tuesday
TIP = datetime(2026, 11, 11, 0, 0, tzinfo=UTC)  # 19:00 ET the same game day


def game(gid, start, home, away, league="nba", final=False, hs=None, as_=None, stype=2):
    return {
        "game_id": gid,
        "league": league,
        "season_year": 2027,
        "season_type": stype,
        "start_time_utc": start,
        "status": "STATUS_FINAL" if final else "STATUS_SCHEDULED",
        "state": "post" if final else "pre",
        "completed": final,
        "home_team_id": home,
        "away_team_id": away,
        "home_score": hs,
        "away_score": as_,
    }


def box(gid, team, prefix, minutes=30, n=8, league="nba"):
    return [
        {
            "game_id": gid,
            "team_id": team,
            "athlete_id": f"{prefix}{i}",
            "minutes": minutes,
            "league": league,
        }
        for i in range(n)
    ]


def odds(gid, at, total, source="pregame", spread=-3.5):
    return {
        "game_id": gid,
        "source": source,
        "captured_at": at,
        "provider": "ESPN BET",
        "details": "X -3.5",
        "spread_home": spread,
        "over_under": total,
        "home_moneyline": -150,
        "away_moneyline": 130,
    }


def pred(gid, version, total, created=NOW - timedelta(hours=2)):
    return {
        "game_id": gid,
        "model": "v1",
        "model_version": version,
        "created_at": created,
        "p_home_win": 0.6,
        "pred_home_margin": 3.0,
        "pred_total": total,
        "features_json": None,
    }


def make_store(path=":memory:") -> Store:
    s = Store(path)
    teams = [("nba", t, f"N{t}") for t in "1234"] + [("ncaab", t, f"C{t}") for t in "5678"]
    s.upsert_teams(
        {"team_id": t, "league": lg, "abbreviation": ab, "display_name": ab} for lg, t, ab in teams
    )
    h1 = datetime(2026, 11, 8, 0, 30, tzinfo=UTC)  # in T1's 27-72 h window
    h2 = datetime(2026, 11, 9, 0, 30, tzinfo=UTC)  # in T1's window
    h3 = TIP + timedelta(hours=1) - timedelta(hours=27)  # exactly 27 h before T2: excluded
    s.upsert_games(
        [
            game("H1", h1, "1", "3", final=True, hs=100, as_=90),
            game("H2", h2, "1", "2", final=True, hs=100, as_=90),
            game("H3", h3, "3", "4", final=True, hs=100, as_=90),
            game("T1", TIP, "1", "2"),  # load 480 + 240 = 720 -> under; v1.1 edge +4.0 -> over
            game("T2", TIP + timedelta(hours=1), "3", "4"),  # load 0; v1.1 edge -3.9 -> no bet
            game("LATE", NOW - timedelta(hours=1), "1", "4"),  # tip passed, still 'pre'
            game("TMRW", TIP + timedelta(days=1), "2", "3"),  # tomorrow's game day
            game("PO", TIP + timedelta(hours=2), "2", "4", stype=3),  # postseason
            game("C1", TIP, "5", "6", league="ncaab"),  # only an -early prediction
            game("C2", TIP, "7", "8", league="ncaab"),  # gated ncaab-v1: edge -7.0 -> under
        ]
    )
    s.upsert_player_stats(
        box("H1", "1", "a") + box("H1", "3", "c") + box("H2", "1", "a") + box("H2", "2", "b")
        + box("H3", "3", "c") + box("H3", "4", "d")
    )  # fmt: skip
    before, after = NOW - timedelta(hours=1), NOW + timedelta(hours=1)
    s.add_odds(
        [
            odds("T1", before, 220.5),
            odds("T1", after, 230.5),  # captured after `now`: never used for this log
            odds("T2", before, 215.5),
            odds("LATE", before - timedelta(hours=2), 200.5),
            odds("TMRW", before, 210.5),
            odds("PO", before, 210.5),
            odds("C1", before, 140.5),
            odds("C2", before, 150.5),
        ]
    )
    s.add_predictions(
        [
            pred("T1", "v1.1", 224.5),
            pred("T1", "v1.0", 200.0),  # other NBA version: ignored
            pred("T2", "v1.1", 211.6),
            pred("T2", "v1.0", 240.0),
            pred("LATE", "v1.1", 240.0),
            pred("TMRW", "v1.1", 230.5),
            pred("PO", "v1.1", 240.0),
            pred("C1", "ncaab-v1-early", 160.0),
            pred("C2", "ncaab-v1", 143.5),
            pred("C2", "ncaab-v1-early", 170.0),
        ]
    )
    return s


def by_rule(bets):
    return {(b["rule"], b["game_id"]): b for b in bets}


def test_rules_are_frozen():
    assert [(r.name, r.version, r.threshold, r.model_version) for r in paper.RULES] == [
        ("ncaab-total-t7", "1", 7.0, "ncaab-v1"),
        ("nba-total-t4", "1", 4.0, "v1.1"),
        ("nba-load-under", "1", 470.0, None),
    ]
    load = paper.RULES_BY_NAME["nba-load-under"]
    assert (load.window_hours, load.exclude_hours, load.market) == (72.0, 27.0, "total")


def test_select_bets_rules_thresholds_and_pregame_only():
    s = make_store()
    bets, skipped = paper.select_bets(s.con, NOW)
    got = by_rule(bets)
    assert set(got) == {
        ("nba-total-t4", "T1"),
        ("nba-load-under", "T1"),
        ("ncaab-total-t7", "C2"),
    }
    t4 = got[("nba-total-t4", "T1")]
    assert (t4["side"], t4["line"], t4["model_value"]) == ("over", 220.5, 224.5)  # edge == 4
    assert t4["line_captured_at"] <= NOW and t4["logged_at"] == NOW
    assert (t4["price"], t4["stake"], t4["line_source"]) == (-110, 1.0, "pregame")
    assert t4["inputs_json"]["model_version"] == "v1.1"
    load = got[("nba-load-under", "T1")]
    assert (load["side"], load["model_value"]) == ("under", 720.0)
    assert load["inputs_json"]["home_load"] == 480.0 and load["inputs_json"]["away_load"] == 240.0
    c2 = got[("ncaab-total-t7", "C2")]
    assert (c2["side"], c2["line"]) == ("under", 150.5)
    assert c2["inputs_json"]["model_version"] == "ncaab-v1"  # never the -early one
    assert skipped["ncaab-total-t7"] == {"no_prediction": 1}  # C1 has only -early
    assert skipped["nba-total-t4"] == {"below_threshold": 1}  # T2: |-3.9| < 4
    assert skipped["nba-load-under"] == {"below_threshold": 1}  # T2: 0 minutes
    # LATE (tip passed), TMRW (tomorrow) and PO (postseason) are never candidates
    assert not {b["game_id"] for b in bets} & {"LATE", "TMRW", "PO"}
    two_days = {b["game_id"] for b in paper.select_bets(s.con, NOW, days=2)[0]}
    assert "TMRW" in two_days and "PO" not in two_days
    s.close()


def test_no_line_before_logging_means_no_bet():
    s = make_store()
    early = NOW - timedelta(hours=4)  # before every pregame snapshot; LATE hasn't tipped yet
    bets, skipped = paper.select_bets(s.con, early)
    assert bets == []
    assert skipped["nba-total-t4"] == {"no_line": 3}
    s.close()


def test_missing_recent_box_score_skips_the_load_rule():
    s = make_store()
    s.con.execute("DELETE FROM player_game_stats WHERE game_id = 'H2'")
    bets, skipped = paper.select_bets(s.con, NOW)
    assert ("nba-load-under", "T1") not in by_rule(bets)
    assert skipped["nba-load-under"]["incomplete_history"] == 1
    s.close()


def test_top8_load_window_and_top8():
    t0 = 1_000_000.0
    h = 3600.0
    games = [
        {"game_id": g, "league": "nba", "season_year": 2027, "start_epoch": t0 + dt * h,
         "home_team_id": "1", "away_team_id": "2"}
        for g, dt in (("a", 0), ("b", 30), ("c", 50), ("t", 80))
    ]  # fmt: skip
    stats = [
        {"game_id": "a", "team_id": "1", "athlete_id": f"p{i}", "minutes": 10 + i}
        for i in range(10)
    ]
    stats += [
        {"game_id": "b", "team_id": "1", "athlete_id": f"p{i}", "minutes": 1} for i in range(10)
    ]
    stats += [{"game_id": "c", "team_id": "1", "athlete_id": "p9", "minutes": 40}]
    load = top8_load(games, stats)
    assert load["a"] == {"home": None, "away": None}  # season opener: no top-8 yet
    # target t at +80 h: window [8 h, 53 h) holds b (+30 h) and c (+50 h) but not a (0 h).
    # top-8 by season minutes before t: p9 (19+1+40), p8..p2 -> b gives 8 x 1, c gives 40.
    assert load["t"]["home"] == 48.0
    assert load["t"]["away"] is None  # team 2 never logged minutes
    with pytest.raises(ValueError):
        top8_load(games, stats, window_hours=10, exclude_hours=20)


def test_log_is_insert_only_and_first_bet_frozen():
    s = make_store()
    first = paper.log_bets(s, NOW)
    assert first["nba-total-t4"] == {"qualifying": 1, "new": 1, "skipped": {"below_threshold": 1}}
    # Later: the line and the prediction move; a re-run must not touch the frozen bet.
    later = NOW + timedelta(hours=2)
    s.add_predictions([pred("T1", "v1.1", 240.0, created=later)])
    again = paper.log_bets(s, later)
    assert again["nba-total-t4"]["qualifying"] == 1 and again["nba-total-t4"]["new"] == 0
    row = s.con.execute(
        "SELECT line, model_value, logged_at FROM paper_bets WHERE rule = 'nba-total-t4'"
    ).fetchone()
    assert row[0] == 220.5 and row[1] == 224.5 and row[2] == NOW
    assert s.con.execute("SELECT count(*) FROM paper_bets").fetchone()[0] == 3
    # duplicate keys inside one batch: the first row wins
    dup = dict(paper.select_bets(s.con, NOW)[0][0], game_id="X")
    assert s.add_paper_bets([dup, {**dup, "line": 999.0}]) == 1
    assert s.con.execute("SELECT line FROM paper_bets WHERE game_id = 'X'").fetchone()[0] != 999.0
    with pytest.raises(ValueError, match="unknown paper_bets columns"):
        s.add_paper_bets([{**dup, "oops": 1}])
    s.close()


def finish(s: Store, gid: str, hs: int, as_: int, close_total: float) -> None:
    s.con.execute(
        "UPDATE games SET status = 'STATUS_FINAL', state = 'post', completed = true, "
        "home_score = ?, away_score = ? WHERE game_id = ?",
        [hs, as_, gid],
    )
    s.add_odds([odds(gid, TIP + timedelta(hours=3), close_total, source="closing")])


def test_grading_view_report_and_clv():
    s = make_store()
    paper.log_bets(s, NOW)
    # a bet "logged" after tip is never graded
    late = dict(paper.select_bets(s.con, NOW)[0][0], rule="nba-total-t4", game_id="T2")
    late["logged_at"] = TIP + timedelta(hours=2)
    s.add_paper_bets([late])
    finish(s, "T1", 100, 110, 218.5)  # total 210: under wins, over loses; closed 218.5
    finish(s, "T2", 100, 100, 215.5)
    rows = {(r["rule"], r["game_id"]): r for r in paper.graded_rows(s.con)}
    assert set(rows) == {("nba-total-t4", "T1"), ("nba-load-under", "T1")}
    over, under = rows[("nba-total-t4", "T1")], rows[("nba-load-under", "T1")]
    assert (over["result"], over["profit"], over["clv"]) == ("loss", -1.0, -2.0)
    assert under["result"] == "win" and under["profit"] == pytest.approx(10 / 11)
    assert under["clv"] == pytest.approx(2.0)
    # the betting library agrees with the view, bet by bet
    graded = paper.grade_rule([under]).bets[0]
    assert graded["grade"] == "win" and graded["profit"] == pytest.approx(under["profit"])
    assert graded["clv"] == pytest.approx(under["clv"])

    report = {e["rule"]: e for e in paper.paper_report(s.con)}
    load = report["nba-load-under"]
    assert (load["logged"], load["graded"], load["pending"]) == (1, 1, 0)
    assert load["summary"]["record"] == "1-0-0"
    assert load["summary"]["roi"] == pytest.approx(10 / 11)
    assert load["summary"]["clv_mean"] == pytest.approx(2.0)
    t4 = report["nba-total-t4"]
    assert (t4["logged"], t4["graded"], t4["pending"]) == (2, 1, 1)  # T2 bet: never graded
    assert t4["summary"]["record"] == "0-1-0"
    assert report["ncaab-total-t7"]["summary"] is None  # C2 not final yet
    text = paper.render_report(list(report.values()))
    assert "nba-load-under" in text and "1-0-0" in text
    s.close()


def test_report_on_a_warehouse_without_the_table():
    import duckdb

    con = duckdb.connect()
    report = paper.paper_report(con)
    assert [e["logged"] for e in report] == [0, 0, 0]
    assert all(e["summary"] is None for e in report)


def test_cli_paper_log_and_report(tmp_path, monkeypatch, capsys):
    from deepsports import cli

    path = tmp_path / "w.duckdb"
    make_store(path).close()
    monkeypatch.setattr(cli.config, "require_data_dir", lambda: None)
    monkeypatch.setattr(cli, "Store", lambda read_only=False: Store(path, read_only))
    monkeypatch.setattr(paper, "datetime", _FrozenDatetime)
    monkeypatch.setattr(cli, "datetime", _FrozenDatetime)

    assert cli.main(["paper", "log"]) == 0
    out = capsys.readouterr().out
    assert "paper log: nba-total-t4 new=1 qualifying=1 below_threshold=1" in out
    assert "paper log: ncaab-total-t7 new=1 qualifying=1 no_prediction=1" in out
    assert cli.main(["paper", "log"]) == 0
    assert "nba-total-t4 new=0 qualifying=1" in capsys.readouterr().out

    assert cli.main(["paper", "report", "--json"]) == 0
    report = {e["rule"]: e for e in json.loads(capsys.readouterr().out)}
    assert report["nba-load-under"]["logged"] == 1 and report["nba-load-under"]["graded"] == 0
    assert cli.main(["paper", "report"]) == 0
    assert "break-even 52.4%" in capsys.readouterr().out
    s = Store(path, read_only=True)
    notes = s.con.execute(
        "SELECT notes FROM ingest_runs WHERE command LIKE '%paper%' OR notes LIKE '%new=%'"
    ).fetchall()
    s.close()
    assert notes and "nba-total-t4: new=1/1" in notes[0][0]


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is not None else NOW.replace(tzinfo=None)
