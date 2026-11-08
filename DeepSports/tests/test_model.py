"""Model v1: features, walk-forward backtest, predict_upcoming. Synthetic data only."""

import json
import math
import random
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from deepsports.analysis import backtest, features
from deepsports.analysis.backtest import (
    BREAK_EVEN,
    ats,
    evaluate_backtest,
    over_under,
    run_backtest,
    walk_forward,
)
from deepsports.analysis.elo import elo_ratings
from deepsports.analysis.features import FEATURES, build_features, possessions
from deepsports.analysis.model import PREDICTION_KEYS, ModelV1, predict_upcoming
from deepsports.store import Store

TEAMS = [str(i) for i in range(1, 7)]
CONTEXT_DDL = """
CREATE TABLE IF NOT EXISTS team_game_context (
    game_id VARCHAR, team_id VARCHAR, opponent_id VARCHAR, is_home BOOLEAN,
    start_time_utc TIMESTAMPTZ, season_year INTEGER, rest_days INTEGER, back_to_back BOOLEAN,
    games_last_7_days INTEGER, road_trip_length INTEGER, travel_km DOUBLE
)"""
INJURY_DDL = """
CREATE TABLE IF NOT EXISTS injury_reports (
    game_id VARCHAR, team_id VARCHAR, athlete_id VARCHAR, athlete_name VARCHAR,
    status VARCHAR, injury_type VARCHAR, detail VARCHAR, captured_at TIMESTAMPTZ,
    captured_before_tip BOOLEAN
)"""


def _lit(x) -> str:
    """SQL literal for synthetic test data (avoids DuckDB's slow per-parameter binding)."""
    if x is None:
        return "NULL"
    if isinstance(x, bool):
        return "TRUE" if x else "FALSE"
    if isinstance(x, int | float):
        return repr(x)
    if isinstance(x, datetime):
        return f"TIMESTAMPTZ '{x.isoformat()}'"
    return "'" + str(x).replace("'", "''") + "'"


def _bulk_raw(con, table: str, cols: list[str], tuples: list[tuple]) -> None:
    if tuples:
        values = ",".join("(" + ",".join(_lit(v) for v in t) + ")" for t in tuples)
        con.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES {values}")


def _bulk(con, table: str, rows: list[dict]) -> None:
    """Fast multi-row INSERT of dict rows, adding updated_at where the table has one."""
    if not rows:
        return
    cols = list(rows[0])
    extra = () if table == "odds_snapshots" else (datetime.now(UTC),)
    _bulk_raw(
        con,
        table,
        cols + (["updated_at"] if extra else []),
        [(*r.values(), *extra) for r in rows],
    )


def _ml(p: float) -> int:
    """Fair probability -> American moneyline (no vig)."""
    p = min(max(p, 0.02), 0.98)
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


def synth_store(
    seasons=(2023, 2024, 2025, 2026),
    rounds=4,
    seed=7,
    context=True,
    n_pre=0,
    path=":memory:",
) -> Store:
    """Teams with known strengths; margins = strength gap + 3 home + noise.
    The 'market' knows the true expected margin, so it should be hard to beat."""
    rng = random.Random(seed)
    s = Store(path)
    s.upsert_teams(
        {"team_id": t, "league": "nba", "abbreviation": f"T{t}", "display_name": f"Team {t}"}
        for t in TEAMS
    )
    # Replace any real team_game_context view with a table we control (same columns), so these
    # tests don't depend on the view's logic. context="view" keeps the store's own view.
    if context != "view":
        s.con.execute("DROP VIEW IF EXISTS team_game_context")
    if context is True:
        s.con.execute(CONTEXT_DDL)
    strength = {t: rng.gauss(0, 5) for t in TEAMS}
    last_play: dict[str, datetime] = {}
    games, stats, odds, ctx = [], [], [], []
    for season in seasons:
        strength = {t: 0.7 * v + rng.gauss(0, 3) for t, v in strength.items()}
        t = datetime(season - 1, 10, 21, 23, 0, tzinfo=UTC)
        pairs = [(h, a) for h in TEAMS for a in TEAMS if h != a]
        for r in range(rounds):
            rng.shuffle(pairs)
            for h, a in pairs:
                t += timedelta(hours=rng.choice([12, 24, 36]))
                gid = f"{season}-{r}-{h}-{a}"
                rest = {
                    x: min((t - last_play[x]).days, 9) if x in last_play else None for x in (h, a)
                }
                exp_margin = strength[h] - strength[a] + 3.0
                margin = round(exp_margin + rng.gauss(0, 11))
                margin = margin or 1
                total = round(220 + rng.gauss(0, 16))
                hs = (total + margin) // 2
                as_ = total - hs
                games.append(
                    {
                        "game_id": gid,
                        "league": "nba",
                        "season_year": season,
                        "season_type": 2,
                        "start_time_utc": t,
                        "status": "STATUS_FINAL",
                        "state": "post",
                        "completed": True,
                        "home_team_id": h,
                        "away_team_id": a,
                        "home_score": hs,
                        "away_score": as_,
                        "neutral_site": False,
                    }
                )
                for team in (h, a):
                    stats.append(
                        {
                            "game_id": gid,
                            "team_id": team,
                            "home_away": "home" if team == h else "away",
                            "fga": rng.randint(80, 95),
                            "oreb": rng.randint(6, 14),
                            "tov": rng.randint(10, 18),
                            "fta": rng.randint(15, 30),
                        }
                    )
                    rd = rest[team]
                    ctx.append(
                        (
                            gid,
                            team,
                            a if team == h else h,
                            team == h,
                            t,
                            season,
                            rd,
                            None if rd is None else rd <= 1,
                            rng.randint(1, 4),
                            0 if team == h else rng.randint(1, 5),
                            rng.uniform(0, 3000),
                        )
                    )
                p = 1 - 0.5 * (1 + math.erf(-exp_margin / (11 * math.sqrt(2))))
                odds.append(
                    {
                        "game_id": gid,
                        "source": "closing",
                        "captured_at": t + timedelta(hours=3),
                        "provider": "test",
                        "details": None,
                        "spread_home": -round(exp_margin * 2) / 2,
                        "over_under": 220.5,
                        "home_moneyline": _ml(p),
                        "away_moneyline": _ml(1 - p),
                    }
                )
                last_play[h] = last_play[a] = t
    last_season = seasons[-1]
    for i in range(n_pre):
        h, a = TEAMS[i % 6], TEAMS[(i + 1) % 6]
        t += timedelta(days=1)
        games.append(
            {
                "game_id": f"pre-{i}",
                "league": "nba",
                "season_year": last_season,
                "season_type": 2,
                "start_time_utc": t,
                "status": "STATUS_SCHEDULED",
                "state": "pre",
                "completed": False,
                "home_team_id": h,
                "away_team_id": a,
                "home_score": None,
                "away_score": None,
                "neutral_site": False,
            }
        )
    _bulk(s.con, "games", games)
    _bulk(s.con, "team_game_stats", stats)
    _bulk(s.con, "odds_snapshots", odds)
    if context is True:
        names = "game_id team_id opponent_id is_home start_time_utc season_year rest_days "
        names += "back_to_back games_last_7_days road_trip_length travel_km"
        cols = names.split()
        _bulk_raw(s.con, "team_game_context", cols, ctx)
    return s


def test_uses_the_real_context_view_when_present():
    """Integration with the data-engineer's view (skipped if this Store doesn't define it)."""
    s = synth_store(seasons=(2025, 2026), rounds=2, context="view")
    if not features._table_exists(s.con, "team_game_context"):
        pytest.skip("team_game_context view not in this Store yet")
    rows = build_features(s.con)
    known = [r for r in rows if not math.isnan(r["features"]["rest_diff"])]
    assert len(known) > len(rows) / 2
    assert {r["features"]["b2b_home"] for r in rows} <= {0.0, 1.0}
    s.close()


@pytest.fixture(scope="module")
def store():
    s = synth_store()
    yield s
    s.close()


@pytest.fixture(scope="module")
def rows(store):
    return build_features(store.con)


# ---------- features ----------


def test_possessions():
    assert possessions(85, 10, 14, 25) == pytest.approx(85 - 10 + 14 + 11)
    assert possessions(None, 10, 14, 25) is None


def test_feature_rows_shape(rows):
    assert len(rows) == 4 * 4 * 30
    assert all(set(r["features"]) == set(FEATURES) for r in rows)
    assert all(r["state"] == "post" and r["home_win"] in (0, 1) for r in rows)
    starts = [r["start_time_utc"] for r in rows]
    assert starts == sorted(starts)
    first = rows[0]["features"]
    assert first["elo_diff"] == 0 and first["form_net_diff"] == 0  # nothing known yet
    assert math.isnan(first["rest_diff"])  # no previous game -> NULL rest -> NaN
    assert "market" in rows[0] and not set(rows[0]["market"]) & set(FEATURES)


def _tiny_store(results):
    """results: list of (home, away, home_score, away_score), one game per day."""
    s = Store(":memory:")
    s.upsert_teams(
        {"team_id": t, "league": "nba", "abbreviation": f"T{t}", "display_name": t} for t in TEAMS
    )
    t0 = datetime(2025, 10, 21, 23, 0, tzinfo=UTC)
    s.upsert_games(
        {
            "game_id": f"g{i}",
            "league": "nba",
            "season_year": 2026,
            "season_type": 2,
            "start_time_utc": t0 + timedelta(days=i),
            "status": "STATUS_FINAL",
            "state": "post",
            "completed": True,
            "home_team_id": h,
            "away_team_id": a,
            "home_score": hs,
            "away_score": as_,
            "neutral_site": False,
        }
        for i, (h, a, hs, as_) in enumerate(results)
    )
    return s


def test_form_uses_only_prior_games():
    """Team 1 wins game 0 by 10. Its own features know nothing of that; at game 1 (vs a fresh
    team) its form is that +10 shrunk toward 0 by SHRINK_GAMES prior games."""
    s = _tiny_store([("1", "2", 110, 100), ("1", "3", 100, 100 + 1)])
    g0, g1 = build_features(s.con)
    assert g0["features"]["form_net_diff"] == 0 and g0["features"]["elo_diff"] == 0
    assert g1["features"]["form_net_diff"] == pytest.approx(10 / (1 + features.SHRINK_GAMES))
    assert g1["features"]["elo_diff"] > 0  # team 1's Elo rose, team 3 untouched
    assert g1["form_games"] == 0  # team 3 has no history yet
    s.close()


def test_games_on_the_same_evening_do_not_see_each_other():
    """A game is only known FINISH_LAG after its tip, so two games 1h apart are independent."""
    s = _tiny_store([("1", "2", 130, 100)])
    s.con.execute(
        "INSERT INTO games SELECT 'g1', league, season_year, season_type, "
        "start_time_utc + INTERVAL 1 HOUR, status, state, completed, '3', '1', 100, 100 + 2, "
        "venue, venue_city, neutral_site, attendance, broadcasts, updated_at FROM games"
    )
    _, g1 = build_features(s.con)
    assert g1["features"]["form_net_diff"] == 0
    s.close()


def _same(a: dict, b: dict) -> bool:
    """Dict equality where NaN == NaN."""
    return a.keys() == b.keys() and all(
        (isinstance(a[k], float) and math.isnan(a[k]) and math.isnan(b[k])) or a[k] == b[k]
        for k in a
    )


def test_features_ignore_future_results():
    """Leakage test: changing every result and box score from a cutoff on leaves all earlier
    features (and the features of the first changed game itself) unchanged."""
    a, b = synth_store(), synth_store()
    cut = datetime(2025, 1, 1, tzinfo=UTC)
    later = "SELECT game_id FROM games WHERE start_time_utc >= ?"
    b.con.execute(
        "UPDATE games SET home_score = home_score - 20, away_score = away_score + 25 "
        "WHERE start_time_utc >= ?",
        [cut],
    )
    b.con.execute(f"UPDATE team_game_stats SET fga = fga + 25 WHERE game_id IN ({later})", [cut])
    ra, rb = build_features(a.con), build_features(b.con)
    first_after = next(i for i, r in enumerate(ra) if r["start_time_utc"] >= cut)
    for x, y in zip(ra[: first_after + 1], rb[: first_after + 1], strict=True):
        assert _same(x["features"], y["features"])
        assert x["elo_p_home"] == y["elo_p_home"]
    later_a = [r["features"]["form_net_diff"] for r in ra[first_after + 5 :]]
    later_b = [r["features"]["form_net_diff"] for r in rb[first_after + 5 :]]
    assert later_a != later_b  # sanity: the change did reach later features
    a.close()
    b.close()


def test_missing_context_view_is_ok():
    s = synth_store(seasons=(2025, 2026, 2027), rounds=2, context=False)
    rows = build_features(s.con)
    assert all(math.isnan(r["features"]["b2b_home"]) for r in rows)
    preds = walk_forward(rows)["predictions"]
    assert preds and all(0 < p["p_home_win"] < 1 for p in preds)
    s.close()


def test_injury_hook_off_by_default_and_ignores_post_tip_rows():
    s = synth_store(seasons=(2026,), rounds=1)
    s.con.execute(INJURY_DDL)
    gid, home, tip = s.con.execute(
        "SELECT game_id, home_team_id, start_time_utc FROM games ORDER BY start_time_utc LIMIT 1"
    ).fetchone()
    early, late = tip - timedelta(hours=5), tip - timedelta(hours=1)
    s.con.executemany(
        "INSERT INTO injury_reports (game_id, team_id, athlete_id, athlete_name, status, "
        "injury_type, captured_at, captured_before_tip) VALUES (?,?,?,?,?,?,?,?)",
        [
            (gid, home, "p0", "Z", "Out", "knee", early, True),  # superseded snapshot
            (gid, home, "p9", "Y", "Out", "knee", early, True),
            (gid, home, "p1", "A", "Out", "knee", late, True),  # latest pre-tip snapshot
            (gid, home, "p3", "C", "Day-To-Day", "rest", late, True),
            (gid, home, "p2", "B", "Out", "ankle", tip + timedelta(hours=1), False),  # ignored
        ],
    )
    assert "out_home" not in build_features(s.con)[0]["features"]
    rows = build_features(s.con, include_injuries=True)
    r = next(r for r in rows if r["game_id"] == gid)
    assert r["features"]["out_home"] == 1
    assert math.isnan(r["features"]["out_away"])
    s.close()


# ---------- model ----------


def test_logistic_recovers_elo_coefficient():
    """Outcomes drawn from the Elo logistic: P(home) = 1/(1+10^(-(d+100)/400)).
    The model should find log-odds slope ln(10)/400 on elo_diff and ~0 on pure noise."""
    rng = np.random.default_rng(0)
    n = 20000
    d = rng.normal(0, 150, n)
    noise = rng.normal(0, 1, n)
    p = 1 / (1 + 10 ** (-(d + 100) / 400))
    y = (rng.random(n) < p).astype(int)
    margin = (d + 100) / 28 + rng.normal(0, 12, n)
    rows = []
    for i in range(n):
        f = dict.fromkeys(FEATURES, 0.0)
        f.update(elo_diff=float(d[i]), home_court=1.0, form_net_diff=float(noise[i]))
        rows.append(
            {
                "features": f,
                "home_win": int(y[i]),
                "home_margin": float(margin[i]),
                "total": 220.0 + float(noise[i]),
            }
        )
    m = ModelV1().fit(rows)
    c = m.coefficients()
    slope = math.log(10) / 400
    assert c["win"]["elo_diff"] == pytest.approx(slope, rel=0.1)
    assert abs(c["win"]["form_net_diff"]) < 0.05
    assert c["win"]["intercept"] == pytest.approx(100 * slope, rel=0.25)
    assert c["margin"]["elo_diff"] == pytest.approx(1 / 28, rel=0.1)
    preds = m.predict(rows[:3])
    assert set(preds[0]) == {"p_home_win", "pred_home_margin", "pred_total"}


def test_fit_requires_both_outcomes():
    f = dict.fromkeys(FEATURES, 0.0)
    rows = [{"features": f, "home_win": 1, "home_margin": 5, "total": 200}] * 5
    with pytest.raises(ValueError):
        ModelV1().fit(rows)


# ---------- walk-forward ----------


@pytest.mark.parametrize("refit", ["monthly", "season"])
def test_walk_forward_never_sees_the_future(rows, refit):
    wf = walk_forward(rows, refit=refit)
    assert wf["folds"]
    for f in wf["folds"]:
        assert f["train_max_start"] < f["test_min_start"]
        season = f["block"][0]
        assert max(f["train_seasons"]) <= season
        if refit == "season":
            assert max(f["train_seasons"]) < season
        assert min(f["train_seasons"]) > 2023  # burn-in season never used
    # Burn-in (2023) and first training season (2024) are never predicted.
    assert {p["season"] for p in wf["predictions"]} == {2025, 2026}
    assert len({p["game_id"] for p in wf["predictions"]}) == len(wf["predictions"])


def test_shuffling_future_results_does_not_change_past_predictions():
    a, b = synth_store(), synth_store()
    cut = datetime(2025, 10, 1, tzinfo=UTC)  # between seasons 2025 and 2026
    future = b.con.execute(
        "SELECT game_id, home_score, away_score FROM games WHERE start_time_utc >= ?", [cut]
    ).fetchall()
    rng = random.Random(3)
    scores = [(h, a_) for _, h, a_ in future]
    rng.shuffle(scores)
    b.con.executemany(
        "UPDATE games SET home_score = ?, away_score = ? WHERE game_id = ?",
        [(h, a_, g) for (g, _, _), (h, a_) in zip(future, scores, strict=True)],
    )
    pa = walk_forward(build_features(a.con))["predictions"]
    pb = walk_forward(build_features(b.con))["predictions"]
    past_a = [p for p in pa if p["start_time_utc"] < cut]
    past_b = [p for p in pb if p["start_time_utc"] < cut]
    assert past_a
    keys = ("p_home_win", "pred_home_margin", "pred_total", "elo_p_home")
    for x, y in zip(past_a, past_b, strict=True):
        assert x["game_id"] == y["game_id"]
        assert all(x[k] == y[k] for k in keys)
    a.close()
    b.close()


def test_backtest_scores_on_known_truth(rows):
    ev = evaluate_backtest(walk_forward(rows)["predictions"])
    o = ev["overall"]
    assert o["n"] == 240 and o["win_market"]["n"] == 240
    # Real signal exists (team strength), so v1 beats always-pick-home ...
    assert o["win"]["model"]["brier"] < o["win"]["home_always"]["brier"]
    # ... but the market knows the true expected margin, so it should be at least as good.
    assert o["margin_market"]["market"] <= o["margin_market"]["model"] + 0.3
    assert o["win_market"]["market"]["brier"] <= o["win_market"]["model"]["brier"] + 0.005
    assert [b["threshold"] for b in o["ats"]] == list(backtest.ATS_THRESHOLDS)
    bets = [b["bets"] for b in o["ats"]]
    assert bets == sorted(bets, reverse=True)  # higher thresholds -> fewer bets
    assert len(ev["per_season"]) == 2


def _pred(pm, spread, margin, pt=None, ou=None, total=None):
    return {
        "pred_home_margin": pm,
        "spread_home": spread,
        "home_margin": margin,
        "pred_total": pt,
        "over_under": ou,
        "total": total,
    }


def test_ats_logic():
    ps = [
        _pred(8, -5, 10),  # we like home by 3 more than market; home covers (10-5>0): win
        _pred(2, -5, 10),  # we like away by 3; home covered: loss
        _pred(6, -5, 5),  # edge 1; margin 5 - 5 = 0: push
        _pred(-5, 5, -3),  # edge 0: no bet
    ]
    t0, t1, t2 = ats(ps, thresholds=(0, 1, 2))
    assert (t0["wins"], t0["losses"], t0["pushes"]) == (1, 1, 1)
    assert t0["hit_rate"] == 0.5 and t0["roi"] == pytest.approx((100 / 110 - 1) / 2)
    assert (t2["wins"], t2["losses"], t2["pushes"]) == (1, 1, 0)
    assert t1["bets"] == 2
    assert pytest.approx(0.5238, abs=1e-4) == BREAK_EVEN


def test_over_under_logic():
    ps = [
        _pred(0, 0, 0, pt=230, ou=220, total=225),  # over, hits
        _pred(0, 0, 0, pt=215, ou=220, total=225),  # under, misses
        _pred(0, 0, 0, pt=221, ou=220, total=220),  # push
    ]
    t0, t5 = over_under(ps, thresholds=(0, 5))
    assert (t0["wins"], t0["losses"], t0["pushes"]) == (1, 1, 1)
    assert (t5["wins"], t5["losses"]) == (1, 1)
    assert over_under(ps, thresholds=(6,))[0]["bets"] == 1


def test_wilson_interval():
    lo, hi = backtest.wilson(55, 100)
    assert lo < 0.55 < hi and hi - lo == pytest.approx(0.19, abs=0.01)
    assert backtest.wilson(0, 0) == (None, None)


# ---------- predict_upcoming + report ----------


def test_predict_upcoming_rows_match_predictions_schema():
    s = synth_store(n_pre=3)
    rows = predict_upcoming(s.con, "v1.0-test")
    assert [r["game_id"] for r in rows] == ["pre-0", "pre-1", "pre-2"]
    for r in rows:
        assert tuple(r) == PREDICTION_KEYS
        assert r["model"] == "v1" and r["model_version"] == "v1.0-test"
        assert 0 < r["p_home_win"] < 1 and 150 < r["pred_total"] < 300
        feats = json.loads(r["features_json"])
        assert set(feats) == set(FEATURES) and feats["elo_diff"] is not None
    # The engineer's Store.add_predictions may not exist yet; only round-trip if it does.
    if hasattr(Store, "add_predictions"):
        s.add_predictions(rows)
        n = s.con.execute("SELECT count(*) FROM predictions WHERE model = 'v1'").fetchone()[0]
        assert n == 3
    s.close()


def test_predict_upcoming_elo_regresses_for_new_season():
    s = synth_store(seasons=(2025, 2026), n_pre=1)
    s.con.execute("UPDATE games SET season_year = 2027 WHERE state = 'pre'")
    (row,) = [r for r in build_features(s.con) if r["state"] == "pre"]
    ratings = elo_ratings(s.con).ratings
    h, a = row["home_team_id"], row["away_team_id"]
    assert row["features"]["elo_diff"] == pytest.approx(0.75 * (ratings[h] - ratings[a]))
    s.close()


def test_backtest_report_and_cli(tmp_path):
    db = tmp_path / "w.duckdb"
    synth_store(seasons=(2024, 2025, 2026), rounds=3, path=db).close()
    out = tmp_path / "bt.md"
    assert backtest.main(["--db", str(db), "--out", str(out)]) == 0
    md = out.read_text()
    assert md.startswith("# DeepSports model v1 backtest")
    for section in ("Win probability", "Home margin", "Total points", "Against the spread"):
        assert section in md
    assert "Fold check: every training game tipped off before its test block (OK)" in md
    assert "52.4%" in md
    ro = Store(db, read_only=True)
    assert "== Win probability" in backtest.backtest_report(ro.con, md=False)
    ro.close()


def test_backtest_report_too_little_data():
    s = synth_store(seasons=(2026,), rounds=1)
    res = run_backtest(s.con)
    assert res["predictions"] == []
    assert "Not enough seasons" in backtest.backtest_report(result=res)
    s.close()
