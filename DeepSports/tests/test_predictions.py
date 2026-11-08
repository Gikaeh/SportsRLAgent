"""Model v1 in daily use: pre-tip predictions, the prediction_results view, the record, and
the `predict` / `upcoming --json` CLI. Temp/in-memory DBs only."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from test_model import synth_store

from deepsports import cli
from deepsports.analysis.record import prediction_card, prediction_record, pretip_predictions
from deepsports.store import Store

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=UTC)
RECORD_KEYS = {
    "model",
    "model_version",
    "window_days",
    "games",
    "winner_accuracy",
    "margin_mae",
    "total_mae",
    "market",
    "recent",
}
GRADED_KEYS = {
    "game_id",
    "date",
    "matchup",
    "favorite_abbr",
    "favorite_prob",
    "pred_home_margin",
    "actual_home_margin",
    "winner_correct",
}


def _shift_pre_games(con, offsets: dict[str, timedelta], now: datetime) -> None:
    for gid, off in offsets.items():
        con.execute("UPDATE games SET start_time_utc = ? WHERE game_id = ?", [now + off, gid])


# ---------- predictions are made before tip only ----------


def test_pretip_predictions_skip_started_and_far_games():
    s = synth_store(n_pre=4)
    _shift_pre_games(
        s.con,
        {
            "pre-0": timedelta(hours=-1),  # still 'pre' in the DB, but tip time has passed
            "pre-1": timedelta(hours=2),
            "pre-2": timedelta(days=3),
            "pre-3": timedelta(days=20),  # beyond the 14-day horizon
        },
        NOW,
    )
    rows, skipped = pretip_predictions(s.con, now=NOW, days=14)
    assert [r["game_id"] for r in rows] == ["pre-1", "pre-2"]
    assert skipped == 1
    starts = dict(s.con.execute("SELECT game_id, start_time_utc FROM games").fetchall())
    for r in rows:
        assert r["created_at"] == NOW < starts[r["game_id"]]
        assert r["model"] == "v1" and r["model_version"] == "v1.0"
    s.close()


# ---------- grading view ----------


def _game(gid, home, away, start, hs=None, as_=None, status="STATUS_FINAL"):
    final = status == "STATUS_FINAL"
    return {
        "game_id": gid,
        "league": "nba",
        "season_year": 2027,
        "season_type": 2,
        "start_time_utc": start,
        "status": status,
        "state": "post" if final else "pre",
        "completed": final,
        "home_team_id": home,
        "away_team_id": away,
        "home_score": hs,
        "away_score": as_,
        "neutral_site": False,
    }


def _pred(gid, created, p, margin, total, version="v1.0"):
    return {
        "game_id": gid,
        "model": "v1",
        "model_version": version,
        "created_at": created,
        "p_home_win": p,
        "pred_home_margin": margin,
        "pred_total": total,
    }


@pytest.fixture
def graded_store():
    s = Store(":memory:")
    s.upsert_teams(
        [
            {
                "team_id": "1",
                "league": "nba",
                "abbreviation": "LAL",
                "display_name": "Lakers",
                "listed": True,
            },
            {
                "team_id": "2",
                "league": "nba",
                "abbreviation": "SAC",
                "display_name": "Kings",
                "listed": True,
            },
            {
                "team_id": "3",
                "league": "nba",
                "abbreviation": "BOS",
                "display_name": "Celtics",
                "listed": True,
            },
            {
                "team_id": "99",
                "league": "nba",
                "abbreviation": "AS",
                "display_name": "All-Stars",
                "listed": False,
            },
        ]
    )
    t1 = NOW - timedelta(days=2)
    t2 = NOW - timedelta(days=1)
    s.upsert_games(
        [
            _game("g1", "2", "1", t1, 110, 100),  # graded, with closing line
            _game("g2", "1", "3", t1, 100, 90),  # prediction made exactly at tip: never graded
            _game("g3", "3", "2", t1, status="STATUS_POSTPONED"),
            _game("g4", "99", "1", t1, 150, 140),  # non-NBA team
            _game("g5", "3", "1", t2, 120, 100),  # graded, no closing line, model wrong
            _game("g6", "1", "2", NOW - timedelta(days=60), 100, 101),  # outside 30-day window
        ]
    )
    s.add_predictions(
        [
            _pred("g1", t1 - timedelta(hours=1), 0.6, 4.0, 205.0),
            _pred("g1", t1 + timedelta(minutes=5), 0.9, 9.0, 210.0, version="v1.1"),
            _pred("g2", t1, 0.7, 5.0, 200.0),
            _pred("g3", t1 - timedelta(hours=3), 0.5, 0.0, 210.0),
            _pred("g4", t1 - timedelta(hours=3), 0.5, 0.0, 280.0),
            _pred("g5", t2 - timedelta(hours=2), 0.3, -3.0, 215.0),
            _pred("g6", NOW - timedelta(days=60, hours=1), 0.55, 2.0, 220.0),
        ]
    )
    s.add_odds(
        [
            {
                "game_id": "g1",
                "source": "closing",
                "captured_at": t1,
                "provider": "test",
                "spread_home": -3.5,
                "over_under": 212.5,
                "home_moneyline": -150,
                "away_moneyline": 130,
            }
        ]
    )
    yield s
    s.close()


def test_prediction_results_view(graded_store):
    cur = graded_store.con.execute("SELECT * FROM prediction_results ORDER BY game_id")
    cols = [d[0] for d in cur.description]
    assert cols == [
        "game_id",
        "league",
        "model",
        "model_version",
        "created_at",
        "start_time_utc",
        "home_abbr",
        "away_abbr",
        "p_home_win",
        "pred_home_margin",
        "pred_total",
        "home_score",
        "away_score",
        "actual_home_margin",
        "actual_total",
        "winner_correct",
        "margin_error",
        "total_error",
        "market_spread_home",
        "market_total",
        "market_p_home",
    ]
    rows = {(r[0], r[3]): dict(zip(cols, r, strict=True)) for r in cur.fetchall()}
    # g1 v1.1 (made after tip), g2 (at tip), g3 (postponed), g4 (non-NBA team) are excluded
    assert set(rows) == {("g1", "v1.0"), ("g5", "v1.0"), ("g6", "v1.0")}
    g1 = rows[("g1", "v1.0")]
    assert (g1["home_abbr"], g1["away_abbr"]) == ("SAC", "LAL")
    assert g1["actual_home_margin"] == 10 and g1["actual_total"] == 210
    assert g1["winner_correct"] is True
    assert g1["margin_error"] == pytest.approx(6.0)
    assert g1["total_error"] == pytest.approx(5.0)
    assert (g1["market_spread_home"], g1["market_total"]) == (-3.5, 212.5)
    ih, ia = 1 / (1 + 100 / 150), 1 / 2.3
    assert g1["market_p_home"] == pytest.approx(ih / (ih + ia))
    g5 = rows[("g5", "v1.0")]
    assert g5["winner_correct"] is False
    assert g5["market_spread_home"] is None and g5["market_p_home"] is None


def test_grading_never_uses_a_post_tip_prediction(graded_store):
    con = graded_store.con
    # Overwrite g5's pre-tip row with one made after tip: g5 is no longer graded at all.
    start = con.execute("SELECT start_time_utc FROM games WHERE game_id = 'g5'").fetchone()[0]
    graded_store.add_predictions([_pred("g5", start + timedelta(hours=1), 0.99, 20.0, 220.0)])
    n = con.execute("SELECT count(*) FROM prediction_results WHERE game_id = 'g5'").fetchone()[0]
    assert n == 0
    assert all(
        c < s
        for c, s in con.execute(
            "SELECT created_at, start_time_utc FROM prediction_results"
        ).fetchall()
    )


# ---------- record ----------


def test_prediction_record_shape_and_numbers(graded_store):
    rec = prediction_record(graded_store.con, days=30, now=NOW)
    assert set(rec) == RECORD_KEYS
    assert (rec["model"], rec["model_version"], rec["window_days"]) == ("v1", "v1.0", 30)
    assert rec["games"] == 2  # g1 + g5 (g6 is outside the window)
    assert rec["winner_accuracy"] == 0.5
    assert rec["margin_mae"] == pytest.approx((6 + 23) / 2)
    assert rec["total_mae"] == pytest.approx((5 + 5) / 2)
    assert rec["market"] == {
        "games": 1,
        "winner_accuracy": 1.0,
        "margin_mae": 6.5,
        "total_mae": 2.5,
    }
    assert [g["game_id"] for g in rec["recent"]] == ["g5", "g1"]  # newest first
    g5 = rec["recent"][0]
    assert set(g5) == GRADED_KEYS
    assert g5["matchup"] == "LAL @ BOS"
    assert (g5["favorite_abbr"], g5["favorite_prob"]) == ("LAL", 0.7)
    assert g5["actual_home_margin"] == 20 and g5["winner_correct"] is False
    json.dumps(rec)  # JSON-serializable as is


def test_prediction_record_without_view_and_empty(graded_store):
    with_view = prediction_record(graded_store.con, now=NOW)
    graded_store.con.execute("DROP VIEW prediction_results")
    assert prediction_record(graded_store.con, now=NOW) == with_view  # inline SQL fallback
    empty = prediction_record(graded_store.con, now=NOW + timedelta(days=365))
    assert set(empty) == RECORD_KEYS
    assert empty["games"] == 0 and empty["market"] is None and empty["recent"] == []
    assert empty["winner_accuracy"] is None
    bare = Store(":memory:")
    assert prediction_record(bare.con)["games"] == 0
    bare.close()


def test_prediction_card():
    pred = _pred("g", NOW, 0.32, -4.26, 221.04)
    card = prediction_card(pred, "SAC", "LAL")
    assert card["favorite_abbr"] == "LAL" and card["favorite_prob"] == 0.68
    assert card["pred_home_margin"] == -4.3 and card["model_version"] == "v1.0"
    assert card["created_at"] == NOW.isoformat()


# ---------- CLI ----------


def test_cli_predict_and_upcoming_json(tmp_path, monkeypatch, capsys):
    path = tmp_path / "w.duckdb"
    s = synth_store(seasons=(2025, 2026), rounds=3, n_pre=3, path=path, context="view")
    now = datetime.now(UTC)
    _shift_pre_games(
        s.con,
        {"pre-0": timedelta(hours=-1), "pre-1": timedelta(hours=3), "pre-2": timedelta(days=1)},
        now,
    )
    s.close()
    monkeypatch.setattr(cli.config, "require_data_dir", lambda: None)
    monkeypatch.setattr(cli, "Store", lambda read_only=False: Store(path, read_only))
    monkeypatch.setattr(cli, "load_calendar_config", lambda: {})

    assert cli.main(["predict"]) == 0
    assert "predictions=2 skipped_started=1" in capsys.readouterr().out
    db = Store(path, read_only=True)
    first = dict(db.con.execute("SELECT game_id, created_at FROM predictions").fetchall())
    assert set(first) == {"pre-1", "pre-2"}
    run = db.con.execute(
        "SELECT games_upserted, errors, notes FROM ingest_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    assert run[0] == 2 and run[1] == 0 and "skipped_started=1" in run[2]
    db.close()

    # Re-running updates the same (game, model, version) row with a newer created_at.
    assert cli.main(["predict"]) == 0
    capsys.readouterr()
    db = Store(path, read_only=True)
    again = dict(db.con.execute("SELECT game_id, created_at FROM predictions").fetchall())
    assert set(again) == set(first) and all(again[g] > first[g] for g in first)
    db.close()

    assert cli.main(["upcoming", "--json", "--all", "--days", "3"]) == 0
    games = {g["game_id"]: g for g in json.loads(capsys.readouterr().out)}
    assert set(games) == {"pre-1", "pre-2"}
    for g in games.values():
        p = g["prediction"]
        assert p["model_version"] == "v1.0" and 0 < p["p_home_win"] < 1
        assert p["favorite_abbr"] in (g["home_abbr"], g["away_abbr"])
        assert p["favorite_prob"] >= 0.5


def test_cli_predict_league_choices():
    assert cli.build_parser().parse_args(["predict", "--league", "ncaab"]).model_version is None
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["predict", "--league", "nfl"])


def test_grading_line_limits_per_league(graded_store):
    """College closing totals (~120-195) survive grading; the NBA filter would blank them."""
    s = graded_store
    s.upsert_teams(
        [
            {"team_id": t, "league": "ncaab", "abbreviation": a, "display_name": a}
            for t, a in (("2440", "NEV"), ("2608", "SMC"))
        ]
    )
    t = NOW - timedelta(days=1)
    college = [
        {**_game("c1", "2440", "2608", t, 70, 64), "league": "ncaab"},
        {**_game("c2", "2608", "2440", t, 60, 50), "league": "ncaab"},
    ]
    s.upsert_games(college)
    s.add_predictions(
        [
            _pred("c1", t - timedelta(hours=2), 0.6, 3.0, 140.0, version="ncaab-v1"),
            _pred("c2", t - timedelta(hours=2), 0.4, -2.0, 130.0, version="ncaab-v1"),
            _pred("g5", NOW - timedelta(days=1, hours=2), 0.3, -3.0, 215.0, version="v1.1"),
        ]
    )
    line = {"source": "closing", "captured_at": t, "provider": "test"}
    s.add_odds(
        [
            {**line, "game_id": "c1", "spread_home": -45.5, "over_under": 138.5},  # real college
            {**line, "game_id": "c2", "spread_home": -61.0, "over_under": 230.0},  # insane
            {**line, "game_id": "g5", "spread_home": -45.5, "over_under": 138.5},  # insane in NBA
        ]
    )
    got = {
        r[0]: r[1:]
        for r in s.con.execute(
            "SELECT game_id, market_spread_home, market_total FROM prediction_results "
            "WHERE game_id IN ('c1', 'c2', 'g5')"
        ).fetchall()
    }
    assert got["c1"] == (-45.5, 138.5)
    assert got["c2"] == (None, None)
    assert got["g5"] == (None, None)
    # the record is per league: college games never appear in the NBA record and vice versa
    rec = prediction_record(s.con, league="ncaab", now=NOW)
    assert rec["model_version"] == "ncaab-v1" and rec["games"] == 2
    assert rec["market"] == {"games": 1, "winner_accuracy": 1.0, "margin_mae": 39.5,
                             "total_mae": 4.5}  # fmt: skip
    assert {g["game_id"] for g in rec["recent"]} == {"c1", "c2"}
    nba = prediction_record(s.con, league="nba", model_version="v1.1", now=NOW)
    assert {g["game_id"] for g in nba["recent"]} == {"g5"}
