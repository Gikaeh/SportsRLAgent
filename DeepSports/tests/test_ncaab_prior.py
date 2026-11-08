"""College cross-season prior (analysis/ncaab_prior.py): prior ratings, rows, rules."""

import json
import math
from datetime import datetime, timedelta

import numpy as np
import pytest
from test_ncaab import D1, _ridge_input, make_store, season_games

from deepsports.analysis import ncaab, ncaab_prior


def next_season(games, year=2027, gap_days=200):
    """The same schedule one season later (same strengths)."""
    shift = games[-1]["start_time_utc"] + timedelta(days=gap_days) - games[0]["start_time_utc"]
    return [
        {
            **g,
            "game_id": f"y{year}-{g['game_id']}",
            "season_year": year,
            "start_time_utc": g["start_time_utc"] + shift,
        }
        for g in games
    ]


def test_prior_ridge_without_prior_matches_base():
    a = ncaab.RidgeRatings(["A", "B", "C"], lam=1.0)
    b = ncaab_prior.PriorRidgeRatings(["A", "B", "C"], lam=1.0, prior=None)
    assert math.isnan(b.predict("A", "B", False)[0])
    for x in (a, b):
        x.add("A", "B", 80, 70, False)
        x.add("C", "A", 66, 71, True)
    assert b.predict("A", "C", False) == pytest.approx(a.predict("A", "C", False))


def test_prior_ridge_predicts_from_prior_before_games_and_fades():
    prior = ncaab_prior.SeasonRatings(
        mu=70.0, h=2.0, off={"A": 5.0, "B": -5.0}, dfn={"A": -3.0, "B": 3.0}
    )
    rr = ncaab_prior.PriorRidgeRatings(["A", "B"], lam=1.0, prior=prior, rho=0.5, lam_prior=4.0)
    m, t = rr.predict("A", "B", neutral=False)
    # home: 70 + 2 + 2.5 + 1.5 = 76; away: 70 - 2 - 2.5 - 1.5 = 64
    assert m == pytest.approx(12.0, abs=1e-4)
    assert t == pytest.approx(140.0, abs=1e-4)
    # a team without a prior starts level (v1's lam toward 0)
    rr2 = ncaab_prior.PriorRidgeRatings(["A", "Z"], lam=1.0, prior=prior, rho=1.0, lam_prior=4.0)
    assert rr2.predict("A", "Z", True)[0] == pytest.approx(5.0 + 3.0, abs=1e-4)
    # B is in fact better than A this season: many games pull the rating away from the prior
    for _ in range(200):
        rr.add("A", "B", 65, 75, neutral=True)
    assert rr.predict("A", "B", True)[0] == pytest.approx(-10.0, abs=0.5)


def test_final_ratings_recover_order():
    s = make_store()
    s.upsert_games(season_games(4))
    fr = ncaab_prior.final_ratings(ncaab._season_games(s.con, 2026), ncaab.listed_teams(s.con), 1.0)
    net = {t: fr.off[t] - fr.dfn[t] for t in D1}
    assert net["5"] > net["6"] > net["7"] > net["8"]
    assert "unlisted" in fr.off and fr.h > 0


def test_season_ridge_prior_from_previous_season_and_no_leakage():
    s = make_store()
    prev = season_games(4)
    cur = next_season(prev)
    s.upsert_games(prev + cur)
    d1 = ncaab.listed_teams(s.con)
    end = cur[-1]["start_time_utc"] + timedelta(days=1)
    plain = ncaab_prior.season_ridge(s.con, 2027, d1, 1.0, None, end)
    pri = ncaab_prior.season_ridge(s.con, 2027, d1, 1.0, {"rho": 0.7, "lam_prior": 8.0}, end)
    first = cur[0]["game_id"]  # 5 hosts 6
    assert math.isnan(plain[first]["rt_margin"])
    assert pri[first]["rt_margin"] > 5  # 5 was 10 points better than 6 last season
    assert pri[first]["rt_n"] == 0
    # later results in the current season never change earlier features
    changed = [dict(g) for g in cur]
    changed[-1]["home_score"] += 40
    s.upsert_games(changed)
    pri2 = ncaab_prior.season_ridge(s.con, 2027, d1, 1.0, {"rho": 0.7, "lam_prior": 8.0}, end)
    for g in cur[:-1]:
        assert pri2[g["game_id"]] == pri[g["game_id"]]
    # the cutoff drops games at or after it
    cut = cur[5]["start_time_utc"]
    assert set(ncaab_prior.season_ridge(s.con, 2027, d1, 1.0, None, cut)) == {
        g["game_id"] for g in cur[:5]
    }
    # first season has no prior: same as plain
    a = ncaab_prior.season_ridge(s.con, 2026, d1, 1.0, {"rho": 0.7, "lam_prior": 8.0}, end)
    b = ncaab.ridge_features(_ridge_input(prev), d1, 1.0)
    assert a == b


def test_bucket_edges():
    got = [ncaab_prior.bucket(n) for n in (0, 1, 2, 3, 4, 5, 9, 10, 30)]
    assert got == ["0", "1-2", "1-2", "3-4", "3-4", "5-9", "5-9", "10+", "10+"]


def test_train_ok_modes():
    early_prior = {"rt_n": 2, "has_prior": True}
    early_first = {"rt_n": 2, "has_prior": False}
    late = {"rt_n": 7, "has_prior": False}
    assert not ncaab_prior.train_ok(early_prior, 5, "v1")
    assert ncaab_prior.train_ok(early_prior, 5, "prior_rows")
    assert not ncaab_prior.train_ok(early_first, 5, "prior_rows")
    assert ncaab_prior.train_ok(late, 5, "v1")
    with pytest.raises(ValueError):
        ncaab_prior.train_ok(late, 5, "other")


def test_walk_forward_arms_end_to_end_respects_cutoff_and_time():
    s = make_store()
    prev = season_games(4)
    cur = next_season(prev)
    s.upsert_games(prev + cur)
    v1 = json.loads(ncaab_prior.V1_CONFIG.read_text())
    v1 = {
        **v1,
        "choice": {t: {"feature_set": "team", "min_games": 0} for t in ("win", "margin", "total")},
    }
    cutoff = cur[30]["start_time_utc"]
    prior = {"elo": {"k": 40.0, "carry": 0.5}, "ridge": {"rho": 0.7, "lam_prior": 8.0}}
    arms = ncaab_prior.build_arms(s.con, v1, prior, cutoff)
    assert all(r["start_time_utc"] < cutoff for a in arms.values() for r in a)
    first = {r["game_id"]: r for r in arms["prior"]}[cur[0]["game_id"]]
    first0 = {r["game_id"]: r for r in arms["noprior"]}[cur[0]["game_id"]]
    assert first["features"]["elo_diff"] > 0 == first0["features"]["elo_diff"]
    assert first["has_prior"] and not {r["game_id"]: r for r in arms["prior"]}["0-5-6"]["has_prior"]
    variants = {
        "noprior": ("noprior", ncaab_prior._choice(v1, "v1")),
        "prior": ("prior", ncaab_prior._choice(v1, "prior_rows")),
    }
    start = cur[0]["start_time_utc"]
    preds = ncaab_prior.walk_forward_arms(arms, variants, 60.0, start, cutoff)
    assert preds and all(
        start <= datetime.fromisoformat(p["start_time_utc"]) < cutoff for p in preds
    )
    for p in preds:
        for k in ("p_prior", "p_noprior", "m_prior", "t_noprior", "p_elo_prior", "m_rt_noprior"):
            assert np.isfinite(p[k])


def _rep(prior_ll, noprior_ll, ci_ll, ci_m, ece=0.03, elo_ll=0.7, top_lo=-0.01):
    def ci(lo, hi):
        return {"mean": (lo + hi) / 2, "lo": lo, "hi": hi}

    def bucket_entry():
        return {
            "metrics": {
                "Prior model": {"ece": ece, "log_loss": prior_ll, "margin_mae": 9.0},
                "Elo, carry-over": {"log_loss": elo_ll, "margin_mae": 10.0},
            },
            "diffs": {
                "Prior - No prior": {"log_loss": ci(top_lo, 0.01), "margin_mae": ci(-0.1, 0.1)}
            },
        }

    return {
        "diffs": {"Prior - No prior": {"log_loss": ci(*ci_ll), "margin_mae": ci(*ci_m)}},
        "buckets": {b: bucket_entry() for b in ncaab_prior.BUCKETS},
    }


def test_ship_decision_rule_and_gate():
    rep = _rep(0.6, 0.65, (-0.03, -0.01), (-0.5, -0.1))
    d = ncaab_prior.ship_decision(rep)
    assert d["ship"] and d["proposed_gate"] == 0
    # CI touching 0 on margin: no ship, no gate proposal
    d = ncaab_prior.ship_decision(_rep(0.6, 0.65, (-0.03, -0.01), (-0.5, 0.02)))
    assert not d["ship"] and d["proposed_gate"] is None
    # worse at 10+: no ship
    d = ncaab_prior.ship_decision(_rep(0.6, 0.65, (-0.03, -0.01), (-0.5, -0.1), top_lo=0.001))
    assert not d["ship"] and d["worse_at_10_plus"]
    # bucket 0 badly calibrated -> gate starts at the next qualifying bucket
    rep = _rep(0.6, 0.65, (-0.03, -0.01), (-0.5, -0.1))
    rep["buckets"]["0"]["metrics"]["Prior model"]["ece"] = 0.09
    assert ncaab_prior.ship_decision(rep)["proposed_gate"] == 1
    rep["buckets"]["3-4"]["metrics"]["Prior model"]["log_loss"] = 0.8  # loses to Elo
    assert ncaab_prior.ship_decision(rep)["proposed_gate"] == 5


def test_holdout_marker_refuses_second_run(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    cfg.with_suffix(".holdout-scored").write_text("x")
    assert ncaab_prior.main(["holdout", "--config", str(cfg), "--db", "x", "--preds", "y"]) == 2


# ---------- daily use: ncaab-v1p and ncaab-v1-early ----------


def test_live_rows_match_the_study_prior_arm():
    """The live path sees completed games exactly as the holdout's 'prior' arm did."""
    s = make_store()
    prev = season_games(4)
    cur = next_season(prev)
    s.upsert_games(prev + cur)
    v1 = ncaab.load_config()
    cfg = ncaab_prior.load_config()
    far = cur[-1]["start_time_utc"] + timedelta(days=1)
    arm = {r["game_id"]: r for r in ncaab_prior.build_arms(s.con, v1, cfg["prior"], far)["prior"]}
    live = {r["game_id"]: r for r in ncaab_prior.live_rows(s.con, cfg, v1)}
    assert set(arm) == set(live)
    for gid, a in arm.items():
        b = live[gid]
        assert (a["rt_n"], a["has_prior"], a["d1"]) == (b["rt_n"], b["has_prior"], b["d1"])
        assert a["elo_p_home"] == pytest.approx(b["elo_p_home"])
        for k in ("elo_diff", "rt_margin", "rt_total"):
            x, y = a["features"][k], b["features"][k]
            assert (math.isnan(x) and math.isnan(y)) or x == pytest.approx(y), (gid, k)


def test_prior_versions_share_one_fit_with_their_own_gates(monkeypatch):
    from datetime import UTC

    from test_ncaab import live_store

    from deepsports.analysis.record import pretip_predictions_versions

    calls = []
    real = ncaab_prior.live_rows
    monkeypatch.setattr(ncaab_prior, "live_rows", lambda *a: calls.append(1) or real(*a))
    now = datetime.now(UTC)
    s = live_store(now)
    gated: dict[str, dict[str, int]] = {}
    out = pretip_predictions_versions(
        s.con, ["ncaab-v1p", "ncaab-v1-early", "ncaab-v1"], now, 14, "ncaab", gated
    )
    assert len(calls) == 1  # one prior fit serves both versions
    rows = {v: {r["game_id"]: r for r in out[v][0]} for v in out}
    assert sorted(rows["ncaab-v1p"]) == sorted(rows["ncaab-v1"]) == ["u-ok"]
    assert sorted(rows["ncaab-v1-early"]) == ["u-few", "u-ok"]
    assert gated["ncaab-v1p"] == {"few_games": 1, "non_d1": 1}
    assert gated["ncaab-v1-early"] == {"non_d1": 1}
    p, e = rows["ncaab-v1p"]["u-ok"], rows["ncaab-v1-early"]["u-ok"]
    for k in ("p_home_win", "pred_home_margin", "pred_total", "features_json"):
        assert p[k] == e[k]  # same model, different gates
    assert p["model_version"] == "ncaab-v1p" and "skip_reason" not in p
    assert json.loads(p["features_json"])["rt_n"] == 6
    # the prior model starts the season from last season (team 5 > 6), unlike v1's restart
    v1 = rows["ncaab-v1"]["u-ok"]
    assert p["pred_home_margin"] > 0 and v1["pred_home_margin"] > 0
    assert p["pred_home_margin"] != v1["pred_home_margin"]
    with pytest.raises(ValueError, match="unknown college model"):
        ncaab.predict_upcoming_versions(s.con, ["ncaab-v2"])
    s.add_predictions(rows["ncaab-v1p"].values())
    s.close()
