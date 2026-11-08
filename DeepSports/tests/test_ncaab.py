"""College (NCAAB) model v1: ratings, leakage, pooling, folds, holdout guard, market filters."""

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from deepsports.analysis import ncaab
from deepsports.analysis.elo import POOL_KEY, elo_ratings
from deepsports.analysis.features import build_features, closing_lines
from deepsports.analysis.market import final_sql, sane_spread, sane_total
from deepsports.store import Store

FIX = Path(__file__).parent / "fixtures"
T0 = datetime(2025, 11, 3, 23, 0, tzinfo=UTC)
D1 = ["5", "6", "7", "8"]
NON_D1 = ["901", "902"]


def make_store(path=":memory:") -> Store:
    s = Store(path)
    s.upsert_teams(
        {"team_id": t, "league": "ncaab", "abbreviation": f"C{t}", "display_name": f"C {t}"}
        for t in D1
    )
    s.add_discovered_teams(
        {
            "team_id": t,
            "league": "ncaab",
            "abbreviation": f"N{t}",
            "display_name": f"N {t}",
            "listed": False,
        }
        for t in NON_D1
    )
    # An NBA team with a colliding id must never leak into college queries.
    s.upsert_teams(
        [{"team_id": "5", "league": "nba", "abbreviation": "CLE", "display_name": "Cavs"}]
    )
    return s


def cgame(gid, day, home, away, hs, as_, neutral=False, hours=0.0):
    return {
        "game_id": gid,
        "league": "ncaab",
        "season_year": 2026,
        "season_type": 2,
        "start_time_utc": T0 + timedelta(days=day, hours=hours),
        "status": "STATUS_FINAL",
        "state": "post",
        "completed": True,
        "home_team_id": home,
        "away_team_id": away,
        "home_score": hs,
        "away_score": as_,
        "neutral_site": neutral,
    }


def season_games(n_rounds=4):
    """Team strength 5 > 6 > 7 > 8 (10 points apart), home edge 3, plus non-D1 games."""
    strength = {"5": 30, "6": 20, "7": 10, "8": 0}
    games, day = [], 0
    for r in range(n_rounds):
        for h in D1:
            for a in D1:
                if h != a:
                    m = strength[h] - strength[a] + 3
                    games.append(cgame(f"{r}-{h}-{a}", day, h, a, 70 + m // 2, 70 - (m - m // 2)))
                    day += 1
        games.append(cgame(f"{r}-nd", day, D1[r % 4], NON_D1[r % 2], 95, 55))
        day += 1
    return games


def test_ridge_ratings_recover_strengths():
    rr = ncaab.RidgeRatings(["A", "B", "C"], lam=0.01)
    rng = np.random.default_rng(0)
    true = {"A": 6.0, "B": 0.0, "C": -6.0}
    for _ in range(300):
        h, a = rng.choice(list(true), 2, replace=False)
        neutral = bool(rng.integers(0, 2))
        loc = 0 if neutral else 1
        m = true[h] - true[a] + 4 * loc
        rr.add(h, a, 70 + m / 2, 70 - m / 2, neutral)
    margin, total = rr.predict("A", "C", neutral=False)
    assert margin == pytest.approx(12 + 4, abs=1e-3)
    assert total == pytest.approx(140, abs=1e-3)
    assert rr.predict("A", "C", neutral=True)[0] == pytest.approx(12, abs=1e-3)


def test_ridge_ratings_shrink_and_nan_before_games():
    rr = ncaab.RidgeRatings(["A", "B"], lam=4.0)
    assert math.isnan(rr.predict("A", "B", False)[0])
    rr.add("A", "B", 90, 60, neutral=True)  # one 30-point win
    m, _ = rr.predict("A", "B", True)
    assert 0 < m < 30  # pulled toward 0 by the prior


def _ridge_input(games):
    return [
        (
            g["game_id"],
            g["start_time_utc"],
            g["home_team_id"],
            g["away_team_id"],
            g["home_score"],
            g["away_score"],
            g["neutral_site"],
        )
        for g in games
    ]


def test_ridge_features_no_leakage():
    games = season_games()
    base = ncaab.ridge_features(_ridge_input(games), set(D1), lam=2.0)
    cut = 20
    changed = [
        {**g, "home_score": g["away_score"] + 40} if i >= cut else g for i, g in enumerate(games)
    ]
    alt = ncaab.ridge_features(_ridge_input(changed), set(D1), lam=2.0)
    for g in games[: cut + 1]:  # the game at `cut` itself: its own result can't matter
        a, b = base[g["game_id"]], alt[g["game_id"]]
        assert a == b or all((math.isnan(a[k]) and math.isnan(b[k])) or a[k] == b[k] for k in a)
    assert base[games[-1]["game_id"]] != alt[games[-1]["game_id"]]


def test_ridge_features_finish_lag():
    g1 = cgame("a", 0, "5", "6", 80, 60)
    g2 = cgame("b", 0, "7", "8", 70, 60, hours=1.0)  # tips 1h later: g1 not finished
    g3 = cgame("c", 1, "5", "7", 70, 60)
    rt = ncaab.ridge_features(_ridge_input([g1, g2, g3]), set(D1), lam=2.0)
    assert math.isnan(rt["b"]["rt_margin"])
    assert rt["c"]["rt_n"] == 1.0  # both 5 and 7 have one game visible


def test_ridge_features_pool_non_d1():
    games = [cgame("a", 0, "5", "901", 90, 50), cgame("b", 1, "6", "902", 90, 50)]
    games.append(cgame("c", 2, "7", "901", 80, 60))
    rt = ncaab.ridge_features(_ridge_input(games), set(D1), lam=2.0)
    assert rt["c"]["rt_n"] == 0.0  # team 7 has no games yet
    assert rt["c"]["rt_margin"] > 0  # but the pooled non-D1 team has two losses


def test_elo_pools_unlisted_and_scopes_league():
    s = make_store()
    s.upsert_games(season_games())
    res = elo_ratings(s.con, league="ncaab", pool_unlisted=True, pool_rating=1200)
    assert POOL_KEY in res.ratings and "901" not in res.ratings and "902" not in res.ratings
    assert res.key("901") == res.key("902") == POOL_KEY
    nd = [g for g in res.games if g["away_team_id"] in NON_D1]
    assert nd[0]["away_elo_pre"] == 1200
    assert nd[1]["away_elo_pre"] < 1200  # the shared rating carried the first loss
    assert nd[0]["away_team_id"] == "901"  # rows keep the real team ids
    nba = elo_ratings(s.con)  # NBA default: no college games
    assert nba.games == []


def test_build_features_league_scoped():
    s = make_store()
    s.upsert_games(season_games(2))
    rows = build_features(
        s.con, league="ncaab", season_types=(2, 3), elo_params={"pool_unlisted": True}
    )
    assert len(rows) == len(season_games(2))
    assert build_features(s.con) == []  # NBA rows unaffected by college games


def test_market_filters_per_league():
    assert sane_spread("nba") == "abs({col}) <= 40"
    assert sane_total("nba") == "{col} BETWEEN 150 AND 320"
    assert "60" in sane_spread("ncaab") and "100 AND 220" in sane_total("ncaab")
    assert "g.league = 'ncaab'" in final_sql("ncaab")
    with pytest.raises(ValueError):
        final_sql("nhl")


def test_closing_lines_college_keeps_big_spreads():
    s = make_store()
    s.upsert_games([cgame("a", 0, "5", "8", 100, 50)])
    s.add_odds(
        [
            {
                "game_id": "a",
                "source": "closing",
                "captured_at": T0,
                "provider": "t",
                "details": None,
                "spread_home": -44.5,
                "over_under": 150.5,
                "home_moneyline": None,
                "away_moneyline": None,
            }
        ]
    )
    assert closing_lines(s.con, "ncaab")["a"]["spread_home"] == -44.5
    assert closing_lines(s.con, "ncaab")["a"]["over_under"] == 150.5
    assert "a" not in closing_lines(s.con)  # NBA lookup doesn't see college games


def test_conference_flag_from_real_summary():
    d = json.loads((FIX / "espn_ncaab_summary_final_nev_unlv.json").read_text())
    assert ncaab.conference_flag(d) is True
    assert ncaab.conference_flag({}) is None


def _rows(n_days=60):
    out = []
    for i in range(n_days * 3):
        t = datetime(2025, 11, 3, 23, tzinfo=UTC) + timedelta(hours=8 * i)
        out.append({"start_time_utc": t, "d1": i % 5 != 0, "game_id": str(i)})
    return out


def test_weekly_folds_train_before_test_d1_only():
    rows = _rows()
    start = datetime(2025, 11, 20, 5, tzinfo=UTC)
    end = datetime(2025, 12, 20, 5, tzinfo=UTC)
    seen = []
    for b, train, test in ncaab.weekly_folds(rows, start, end):
        assert max(r["start_time_utc"] for r in train) < b <= min(r["start_time_utc"] for r in test)
        assert all(r["d1"] for r in train + test)
        assert all(r["start_time_utc"] < end for r in test)
        seen += [r["game_id"] for r in test]
    assert len(seen) == len(set(seen))  # each game predicted once


def test_market_blend_ignores_noise_model():
    rng = np.random.default_rng(1)
    preds = []
    for _ in range(2000):
        m = rng.normal(0, 10)
        y = m + rng.normal(0, 10)
        p = 1 / (1 + math.exp(-m / 6))
        preds.append(
            {
                "market_p_home": p,
                "spread_home": -m,
                "over_under": 140.0,
                "home_win": int(y > 0),
                "home_margin": y,
                "total": 140 + rng.normal(0, 15),
                "p_model": float(rng.uniform(0.05, 0.95)),
                "m_model": float(rng.normal(0, 10)),
                "t_model": float(140 + rng.normal(0, 15)),
            }
        )
    w = ncaab.fit_market_blend(preds)
    assert w["win"] <= 0.1 and w["margin"] <= 0.1 and w["total"] <= 0.1


def test_holdout_marker_refuses_second_run(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    cfg.with_suffix(".holdout-scored").write_text("x")
    rc = ncaab.main(["holdout", "--config", str(cfg), "--preds", str(tmp_path / "p.json")])
    assert rc == 2


def test_validate_never_sees_holdout(monkeypatch):
    """validate() must drop rows at or after HOLDOUT_START before any walk-forward."""
    seen = {}

    def fake_rows(con, elo_params, lam, include_players=True, conf=None):
        base = datetime(2025, 11, 3, 23, tzinfo=UTC)
        return [
            {"start_time_utc": base + timedelta(days=i), "d1": True, "game_id": str(i)}
            for i in range(150)
        ]

    def fake_wf(rows, choice, home_adv, start, end=None, extra=()):
        seen["max"] = max(r["start_time_utc"] for r in rows)
        seen["end"] = end
        raise StopIteration  # stop here: only the inputs matter

    monkeypatch.setattr(
        ncaab, "elo_validation", lambda con: [{"k": 20, "home_adv": 90, "log_loss": 0.6}]
    )
    monkeypatch.setattr(ncaab, "ridge_validation", lambda con: [{"lam": 2.0, "margin_mae": 9.0}])
    monkeypatch.setattr(ncaab, "college_rows", fake_rows)
    monkeypatch.setattr(ncaab, "walk_forward", fake_wf)
    with pytest.raises(StopIteration):
        ncaab.validate(None, log=lambda *_: None)
    assert seen["max"] < ncaab.HOLDOUT_START
    assert seen["end"] == ncaab.HOLDOUT_START


# ---------- daily use: predictions for scheduled games ----------


def sched(gid, start, home, away, season=2027):
    return {
        "game_id": gid,
        "league": "ncaab",
        "season_year": season,
        "season_type": 2,
        "start_time_utc": start,
        "status": "STATUS_SCHEDULED",
        "state": "pre",
        "completed": False,
        "home_team_id": home,
        "away_team_id": away,
        "home_score": None,
        "away_score": None,
        "neutral_site": False,
    }


def test_ridge_features_scheduled_games_use_only_prior_finals():
    games = season_games(2)
    mid = len(games) // 2
    up = (
        "up",
        games[mid]["start_time_utc"] + timedelta(minutes=30),
        "5",
        "8",
        None,
        None,
        False,
    )
    rows = _ridge_input(games)
    with_up = rows[: mid + 1] + [up] + rows[mid + 1 :]
    rt = ncaab.ridge_features(with_up, set(D1), lam=1.0)
    # rated exactly like a final at that tip time would be, from the finals before it
    probe = (*up[:4], 0, 0, False)
    want = ncaab.ridge_features(rows[: mid + 1] + [probe], set(D1), lam=1.0)["up"]
    assert rt["up"] == want
    # later finals can't change it (tip-off order) ...
    changed = [(*g[:4], g[5] + 40, g[5], g[6]) for g in rows[mid + 1 :]]
    alt = ncaab.ridge_features(rows[: mid + 1] + [up] + changed, set(D1), lam=1.0)
    assert alt["up"] == rt["up"]
    # ... and the scheduled game never enters the fit (other games are unchanged)
    base = ncaab.ridge_features(rows, set(D1), lam=1.0)
    assert all(rt[g] == base[g] for g in base)


def test_season_games_include_scheduled():
    s = make_store()
    now = datetime.now(UTC)
    s.upsert_games([cgame("f", 0, "5", "6", 70, 60), sched("u", now + timedelta(days=1), "5", "6")])
    s.upsert_games([sched("x", now + timedelta(days=1), "5", "777")])  # unknown team: out
    done = ncaab._season_games(s.con, 2026)
    assert [g[0] for g in done] == ["f"]
    up = ncaab._season_games(s.con, 2027, include_scheduled=True)
    assert [(g[0], g[4], g[5]) for g in up] == [("u", None, None)]


def test_elo_carry_over_zero_restarts_level_including_pool():
    s = make_store()
    games = season_games(2)
    t = games[-1]["start_time_utc"] + timedelta(days=200)
    nxt = [
        {**cgame("n1", 0, "5", "901", 80, 60), "season_year": 2027, "start_time_utc": t},
        {
            **cgame("n2", 0, "6", "7", 80, 60),
            "season_year": 2027,
            "start_time_utc": t + timedelta(days=1),
        },
    ]
    s.upsert_games(games + nxt)
    res = elo_ratings(s.con, league="ncaab", pool_unlisted=True, pool_rating=1200, carry_over=0.0)
    first = {g["game_id"]: g for g in res.games}
    assert first["n1"]["home_elo_pre"] == 1500 and first["n1"]["away_elo_pre"] == 1200
    assert first["n2"]["home_elo_pre"] == first["n2"]["away_elo_pre"] == 1500
    # default carry-over regresses the pool toward its own start, not 1500
    res = elo_ratings(s.con, league="ncaab", pool_unlisted=True, pool_rating=1200)
    assert {g["game_id"]: g for g in res.games}["n1"]["away_elo_pre"] < 1200


def live_store(now: datetime, path=":memory:") -> Store:
    """Season 2026 for training; season 2027 with teams 5 and 6 at six games each and teams
    7 and 8 at three or fewer, then scheduled games around `now`."""
    s = make_store(path)
    base = now - timedelta(days=10)

    def fin(gid, day, home, away, hs, as_):
        g = cgame(gid, 0, home, away, hs, as_)
        return {**g, "season_year": 2027, "start_time_utc": base + timedelta(days=day)}

    cur = [fin(f"a{i}", i, *(("5", "6") if i % 2 else ("6", "5")), 0, 0) for i in range(6)]
    for g in cur:  # team 5 wins every game by 10
        g["home_score"], g["away_score"] = (75, 65) if g["home_team_id"] == "5" else (65, 75)
    cur += [fin("b0", 0, "7", "8", 70, 66), fin("b1", 1, "8", "7", 64, 70)]
    cur += [fin("b2", 2, "7", "901", 90, 50)]
    up = [
        sched("u-ok", now + timedelta(days=1), "5", "6"),  # 6 games each: predicted
        sched("u-few", now + timedelta(days=1, hours=1), "5", "7"),  # 7 has 3 games
        sched("u-nd1", now + timedelta(days=2), "6", "902"),  # non-D1 opponent
        sched("u-far", now + timedelta(days=20), "5", "6"),  # beyond the horizon
        sched("u-late", now - timedelta(hours=1), "5", "6"),  # tip time has passed
    ]
    s.upsert_games(season_games(4) + cur + up)
    return s


def test_pretip_predictions_college_gate():
    from deepsports.analysis.record import pretip_predictions

    now = datetime.now(UTC)
    s = live_store(now)
    gated: dict[str, int] = {}
    rows, started = pretip_predictions(s.con, now=now, days=14, league="ncaab", gated=gated)
    assert [r["game_id"] for r in rows] == ["u-ok"]
    assert started == 1 and gated == {"few_games": 1, "non_d1": 1}
    r = rows[0]
    assert (r["model"], r["model_version"], r["created_at"]) == ("v1", "ncaab-v1", now)
    assert "skip_reason" not in r
    assert 0.5 < r["p_home_win"] < 1 and r["pred_home_margin"] > 0
    assert 100 < r["pred_total"] < 180
    feats = json.loads(r["features_json"])
    assert feats["rt_n"] == 6 and feats["rt_margin"] > 0
    s.add_predictions(rows)  # rows are exactly the predictions table's columns
    s.close()


def test_pretip_predictions_college_early_version():
    from deepsports.analysis.record import pretip_predictions

    now = datetime.now(UTC)
    s = live_store(now)
    gated: dict[str, int] = {}
    rows, _ = pretip_predictions(
        s.con, now=now, days=14, league="ncaab", model_version=ncaab.EARLY_VERSION, gated=gated
    )
    # the early version also covers teams with 1-4 games; non-D1 games are still skipped
    assert sorted(r["game_id"] for r in rows) == ["u-few", "u-ok"]
    assert gated == {"non_d1": 1}
    assert {r["model_version"] for r in rows} == {"ncaab-v1-early"}
    s.close()


def test_skip_reason_gate_threshold():
    row = {"d1": True, "rt_n": 4.0}
    assert ncaab.skip_reason(row) == ncaab.SKIP_FEW_GAMES
    assert ncaab.skip_reason({**row, "rt_n": 5.0}) is None
    assert ncaab.skip_reason({**row, "d1": False, "rt_n": 9.0}) == ncaab.SKIP_NON_D1
    assert ncaab.MIN_GAMES_TO_PREDICT == 5
    assert ncaab.skip_reason({**row, "rt_n": 1.0}, ncaab.EARLY_MIN_GAMES) is None
    assert ncaab.skip_reason({**row, "rt_n": 0.0}, ncaab.EARLY_MIN_GAMES) == ncaab.SKIP_FEW_GAMES


def test_cli_predict_college(tmp_path, monkeypatch, capsys):
    from deepsports import cli

    path = tmp_path / "w.duckdb"
    live_store(datetime.now(UTC), path).close()
    monkeypatch.setattr(cli.config, "require_data_dir", lambda: None)
    monkeypatch.setattr(cli, "Store", lambda read_only=False: Store(path, read_only))
    monkeypatch.setattr(cli, "load_calendar_config", lambda: {"ncaab": {"teams": ["C5"]}})

    assert cli.main(["predict", "--league", "ncaab"]) == 0
    out = capsys.readouterr().out
    assert "league=ncaab model_version=ncaab-v1 predictions=1 skipped_started=1" in out
    assert "skipped_few_games=1 skipped_non_d1=1" in out
    assert cli.main(["predict", "--league", "ncaab", "--model-version", "v1.1"]) == 2
    capsys.readouterr()

    assert cli.main(["upcoming", "--league", "ncaab", "--json", "--days", "3"]) == 0
    games = {g["game_id"]: g for g in json.loads(capsys.readouterr().out)}
    assert games["u-ok"]["prediction"]["model_version"] == "ncaab-v1"
    assert games["u-ok"]["prediction"]["favorite_abbr"] == "C5"
    assert games["u-few"]["prediction"] is None

    # early-season and side-by-side (v1p) predictions are stored, written after ncaab-v1, but
    # never reach `upcoming` (the calendar)
    argv = ["predict", "--league", "ncaab", "--model-version", "ncaab-v1p,ncaab-v1-early"]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "model_version=ncaab-v1p predictions=1 skipped_started=1" in out
    assert "model_version=ncaab-v1-early predictions=2" in out
    assert cli.main(["upcoming", "--league", "ncaab", "--json", "--days", "3"]) == 0
    games = {g["game_id"]: g for g in json.loads(capsys.readouterr().out)}
    assert games["u-ok"]["prediction"]["model_version"] == "ncaab-v1"
    assert games["u-few"]["prediction"] is None

    assert cli.main(["predict", "--league", "ncaab", "--model-version", "all"]) == 0
    out = capsys.readouterr().out
    assert [ln.split()[2] for ln in out.splitlines()] == [
        "model_version=ncaab-v1",
        "model_version=ncaab-v1p",
        "model_version=ncaab-v1-early",
    ]
    assert cli.main(["predict", "--league", "ncaab", "--model-version", "ncaab-v1,nope"]) == 2
    s = Store(path, read_only=True)
    n = dict(s.con.execute("SELECT model_version, count(*) FROM predictions GROUP BY 1").fetchall())
    s.close()
    assert n == {"ncaab-v1": 1, "ncaab-v1p": 1, "ncaab-v1-early": 2}
