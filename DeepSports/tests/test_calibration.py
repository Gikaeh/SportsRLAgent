"""Calibration study helpers (analysis/calibration.py) and the v1.1c / ncaab-v1c versions."""

import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from test_ncaab import live_store
from test_players import pstore  # noqa: F401  (fixture)

from deepsports.analysis import calibration as cal
from deepsports.analysis import ncaab
from deepsports.analysis.features import build_features
from deepsports.analysis.model import (
    PREDICTION_KEYS,
    V11_WIN_FEATURES,
    VERSION_WIN_C,
    make_model,
    predict_upcoming,
    resolve_version,
    training_rows,
)


def _sim(n=20000, a=0.0, b=1.0, seed=0):
    """Probabilities p and outcomes drawn from sigmoid(a + b * logit p)."""
    rng = np.random.default_rng(seed)
    p = cal.sigmoid(rng.normal(0, 1.2, n))
    y = (rng.random(n) < cal.sigmoid(a + b * cal.logit(p))).astype(int)
    return p, y


def test_calibration_slope_recovers_truth():
    p, y = _sim()
    s = cal.calibration_slope(p, y)
    assert s["slope"] == pytest.approx(1.0, abs=0.05)
    assert s["intercept"] == pytest.approx(0.0, abs=0.05)
    # outcomes follow a flatter curve than p: p is overconfident, slope < 1
    p, y = _sim(a=0.3, b=0.6)
    s = cal.calibration_slope(p, y)
    assert s["slope"] == pytest.approx(0.6, abs=0.05)
    assert s["intercept"] == pytest.approx(0.3, abs=0.05)


def test_calibrator_modes():
    p, y = _sim(a=0.3, b=0.6, seed=1)
    platt = cal.Calibrator("platt").fit(p, y)
    temp = cal.Calibrator("temperature").fit(p, y)
    assert (platt.a, platt.b) == pytest.approx((0.3, 0.6), abs=0.05)
    assert temp.a == 0.0 and temp.b < 1
    assert np.allclose(cal.Calibrator("identity").apply(p), p)
    # fixing the overconfidence lowers log loss on fresh data from the same curve
    p2, y2 = _sim(a=0.3, b=0.6, seed=2)
    assert cal.log_loss_vec(platt.apply(p2), y2).mean() < cal.log_loss_vec(p2, y2).mean()
    with pytest.raises(ValueError):
        cal.Calibrator("nope").fit(p, y)


def _preds(n_blocks=6, per=200, seed=0):
    rng = np.random.default_rng(seed)
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    out = []
    for b in range(n_blocks):
        for i in range(per):
            p = float(cal.sigmoid(rng.normal(0, 1)))
            out.append(
                {
                    "game_id": f"g{b}-{i}",
                    "block": f"b{b}",
                    "start_time_utc": t0 + timedelta(days=30 * b, minutes=i),
                    "day": (t0 + timedelta(days=30 * b)).date().isoformat(),
                    "p_c1": p,
                    "home_win": int(rng.random() < p),
                    "market_p_home": p,
                }
            )
    return out


def test_walk_forward_calibration_uses_only_earlier_games():
    a = _preds()
    fits = cal.walk_forward_calibrate(a, "p_c1", "platt", "p_platt", min_n=300)
    # blocks 0 and 1 have < 300 earlier games: identity
    assert [f["mode"] for f in fits[:2]] == ["identity", "identity"]
    assert all(x["p_platt"] == x["p_c1"] for x in a if x["block"] in ("b0", "b1"))
    assert fits[2]["n"] == 400 and fits[-1]["n"] == 1000
    # rewriting the outcomes of the last block leaves every calibrated probability unchanged
    b = _preds()
    for x in b:
        if x["block"] == "b5":
            x["home_win"] = 1 - x["home_win"]
    cal.walk_forward_calibrate(b, "p_c1", "platt", "p_platt", min_n=300)
    assert [x["p_platt"] for x in a] == [x["p_platt"] for x in b]


def test_by_confidence_folds_to_reference_favorite():
    p = np.array([0.55, 0.45, 0.85, 0.1])
    y = np.array([1, 1, 1, 0])
    rows = cal.by_confidence(p, y)
    assert [r["n"] for r in rows] == [2, 0, 0, 2]
    assert rows[0]["pred"] == pytest.approx(0.55) and rows[0]["obs"] == pytest.approx(0.5)
    assert rows[3]["pred"] == pytest.approx((0.85 + 0.9) / 2) and rows[3]["obs"] == 1.0
    # another model's p is bucketed and oriented by the reference model
    q = np.array([0.6, 0.3, 0.8, 0.2])
    r2 = cal.by_confidence(q, y, ref=p)
    assert [r["n"] for r in r2] == [2, 0, 0, 2]
    assert r2[0]["pred"] == pytest.approx((0.6 + 0.7) / 2)


def test_picks_and_encompassing():
    rows = [
        {"p": 0.6, "market_p_home": 0.5, "home_win": 0},  # model likes home
        {"p": 0.3, "market_p_home": 0.4, "home_win": 0},  # model likes away
        {"p": 0.5, "market_p_home": 0.5, "home_win": 1},  # no disagreement: no pick
    ]
    (t0,) = cal.picks(rows, "p", thresholds=(0.0,))
    assert t0["n"] == 2
    assert t0["model_p"] == pytest.approx((0.6 + 0.7) / 2)
    assert t0["market_p"] == pytest.approx((0.5 + 0.6) / 2)
    assert t0["actual"] == pytest.approx(0.5)
    # a model that is the market plus noise gets no weight next to the market
    rng = np.random.default_rng(3)
    zk = rng.normal(0, 1, 8000)
    sim = [
        {
            "p": float(cal.sigmoid(z + rng.normal(0, 0.5))),
            "market_p_home": float(cal.sigmoid(z)),
            "home_win": int(rng.random() < cal.sigmoid(z)),
        }
        for z in zk
    ]
    e = cal.encompassing(sim, "p")
    assert abs(e["b_model"]) < 3 * e["se_model"]
    assert e["b_market"] == pytest.approx(1.0, abs=0.15)


def test_ship_decision_rule():
    def rep(hi, e_new, e_cur=0.03):
        return {
            "diffs": {"x": {"log_loss": {"mean": hi - 0.001, "lo": hi - 0.002, "hi": hi}}},
            "models": {"x": {"ece": e_new}, "current": {"ece": e_cur}},
        }

    assert cal.ship_decision(rep(-0.0001, 0.05), "x") == {
        "ship": True,
        "by_log_loss": True,
        "by_ece": False,
    }
    assert cal.ship_decision(rep(0.0009, 0.02), "x")["ship"]  # ECE better, LL not worse
    assert not cal.ship_decision(rep(0.0011, 0.02), "x")["ship"]  # LL CI too high
    assert not cal.ship_decision(rep(0.0005, 0.031), "x")["ship"]  # ECE not better


def test_holdout_split_never_mixes():
    preds = [
        {"season": s, "start_time_utc": datetime(2000 + s - 1, 12, 1, tzinfo=UTC)}
        for s in (2024, 2025, 2026, 2027)
    ]
    pre, tune, hold = cal.split("nba", preds)
    assert [x["season"] for x in pre] == [2024, 2025]
    assert [x["season"] for x in tune] == [2025]
    assert [x["season"] for x in hold] == [2026]
    c = [{"start_time_utc": cal.NCAAB_HOLDOUT_START + timedelta(seconds=s)} for s in (-1, 0)]
    pre, _, hold = cal.split("ncaab", c)
    assert len(pre) == 1 and len(hold) == 1 and pre[0] is c[0]


# ---------- versions ----------


def test_v11c_resolves_and_only_changes_win_c():
    assert resolve_version("v1.1c") == "v1.1c" == resolve_version("v1.1c-test")
    assert resolve_version("v1.1") == "v1.1"
    m, base = make_model("v1.1c"), make_model("v1.1")
    assert m.win_c == VERSION_WIN_C["v1.1c"] == 0.03 and base.win_c == 1.0
    assert m.win_features == base.win_features == V11_WIN_FEATURES
    assert m.total_features == base.total_features


def test_v11c_parity_and_round_trip(pstore):  # noqa: F811
    """v1.1c trains and predicts on the same column set as v1.1, its stored rows are exactly
    the predictions table's columns, margins and totals equal v1.1's, only p differs."""
    rows = build_features(pstore.con, include_players=True)
    train = training_rows(rows)
    built = {frozenset(r["features"]) for r in rows}
    assert len(built) == 1
    assert set(make_model("v1.1c").fit(train).columns()) <= next(iter(built))
    c = predict_upcoming(pstore.con, "v1.1c")
    b = predict_upcoming(pstore.con, "v1.1")
    assert c and [r["game_id"] for r in c] == [r["game_id"] for r in b]
    for rc, rb in zip(c, b, strict=True):
        assert set(rc) == set(PREDICTION_KEYS) and rc["model_version"] == "v1.1c"
        assert rc["features_json"] == rb["features_json"]
        assert rc["pred_home_margin"] == pytest.approx(rb["pred_home_margin"])
        assert rc["pred_total"] == pytest.approx(rb["pred_total"])
        assert 0 < rc["p_home_win"] < 1
        # stronger L2 pulls the probability toward the base rate, never past it
        assert abs(rc["p_home_win"] - 0.5) <= abs(rb["p_home_win"] - 0.5) + 0.05
    pstore.add_predictions(c)
    back = dict(
        pstore.con.execute(
            "SELECT game_id, p_home_win FROM predictions WHERE model_version = 'v1.1c'"
        ).fetchall()
    )
    assert back == pytest.approx({r["game_id"]: r["p_home_win"] for r in c})


def test_ncaab_v1c_round_trip():
    now = datetime.now(UTC)
    s = live_store(now)
    c = ncaab.predict_upcoming_calibrated(s.con)
    b = ncaab.predict_upcoming(s.con)
    assert ncaab.CALIBRATED_VERSION not in ncaab.VERSIONS  # `--model-version all` unchanged
    assert [r["game_id"] for r in c] == [r["game_id"] for r in b]
    assert [r["skip_reason"] for r in c] == [r["skip_reason"] for r in b]
    ok = [(rc, rb) for rc, rb in zip(c, b, strict=True) if rc["skip_reason"] is None]
    assert ok
    for rc, rb in ok:
        assert rc["model_version"] == "ncaab-v1c"
        assert set(rc) == set(PREDICTION_KEYS) | {"skip_reason"}
        assert rc["pred_home_margin"] == pytest.approx(rb["pred_home_margin"])
        assert rc["pred_total"] == pytest.approx(rb["pred_total"])
        assert json.loads(rc["features_json"]) == json.loads(rb["features_json"])
        assert 0 < rc["p_home_win"] < 1
    s.add_predictions([{k: v for k, v in r.items() if k != "skip_reason"} for r, _ in ok])
    s.close()
