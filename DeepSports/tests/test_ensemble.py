"""Ensemble v2 (ensemble.py): holdout isolation, walk-forward order, blends, bootstrap."""

import numpy as np
import pytest
from test_model import synth_store
from test_players import add_players

from deepsports.analysis import ensemble
from deepsports.analysis.ensemble import (
    Blend,
    TreeModel,
    TreeParams,
    cluster_bootstrap,
    oof_predictions,
    reliability,
)
from deepsports.analysis.features import build_features

FAST = TreeParams(learning_rate=0.1, max_iter=20, max_leaf_nodes=7, min_samples_leaf=10)


@pytest.fixture(scope="module")
def rows():
    s = synth_store(seasons=(2022, 2023, 2024, 2025, 2026), rounds=2)
    add_players(s)
    r = [x for x in build_features(s.con, include_players=True) if x["state"] == "post"]
    s.close()
    return r


def test_oof_never_sees_seasons_beyond_max(rows):
    oof = oof_predictions(rows, (2025,), max_season=2025, tree_params=FAST)
    assert oof and {r["season"] for r in oof} == {2025}
    # Changing every holdout-season result must not change a single validation prediction.
    scrambled = [
        {**r, "home_margin": -r["home_margin"], "home_win": 1 - r["home_win"]}
        if r["season"] == 2026
        else r
        for r in rows
    ]
    oof2 = oof_predictions(scrambled, (2025,), max_season=2025, tree_params=FAST)
    for a, b in zip(oof, oof2, strict=True):
        assert a["p_tree"] == b["p_tree"] and a["m_v11"] == b["m_v11"]
    with pytest.raises(ValueError):
        oof_predictions(rows, (2026,), max_season=2025)


def test_oof_has_every_base_and_the_market(rows):
    oof = oof_predictions(rows, (2024, 2025), max_season=2025, tree_params=FAST)
    for k in ("p_elo", "p_v10", "p_v11", "p_tree", "m_tree", "t_tree", "market_p_home"):
        assert k in oof[0]
    assert all(0 < r["p_tree"] < 1 for r in oof)


def test_validate_drops_the_holdout(rows, monkeypatch):
    monkeypatch.setattr(ensemble, "TREE_GRID", [FAST])
    seen = []
    real = ensemble.oof_predictions

    def spy(rs, *a, **k):
        seen.append(max(r["season"] for r in rs))
        return real(rs, *a, **k)

    monkeypatch.setattr(ensemble, "oof_predictions", spy)
    cfg = ensemble.validate(rows, log=lambda *a, **k: None)
    assert cfg["max_season_seen"] < ensemble.HOLDOUT_SEASON
    assert seen and max(seen) < ensemble.HOLDOUT_SEASON
    for kind in ("prob", "margin", "total"):
        assert cfg["blends"]["chosen"][kind]["inputs"]


def test_tree_model_shapes(rows):
    train = [r for r in rows if r["season"] in (2024, 2025)]
    p = TreeModel(FAST).fit(train).predict(rows[:5])
    assert len(p) == 5 and set(p[0]) == {"p_home_win", "pred_home_margin", "pred_total"}


def _fake(n=400, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        q = rng.uniform(0.2, 0.8)
        y = int(rng.uniform() < q)
        m = rng.normal(10 * (q - 0.5), 12)
        out.append(
            {
                "home_win": y,
                "home_margin": m,
                "total": 220.0,
                "day": f"d{i // 8}",
                "p_good": q,
                "p_bad": 0.5,
                "m_good": 10 * (q - 0.5),
                "m_bad": 0.0,
            }
        )
    return out


def test_convex_blend_prefers_the_informative_input():
    rs = _fake()
    b = Blend("prob", "convex", ["p_good", "p_bad"]).fit(rs)
    assert b.weights[0] > 0.8 and abs(sum(b.weights) - 1) < 1e-9
    m = Blend("point", "convex", ["m_good", "m_bad"]).fit(rs)
    assert m.weights[0] > 0.6
    s = Blend("prob", "stack", ["p_good", "p_bad"]).fit(rs)
    assert 0 < s.predict(rs[:3]).min() < 1
    assert Blend("point", "mean", ["m_good", "m_bad"]).fit(rs).predict(rs[:1])[0] == pytest.approx(
        rs[0]["m_good"] / 2
    )


def test_bootstrap_and_reliability():
    rs = _fake()
    d = np.full(len(rs), -0.01)
    ci = cluster_bootstrap(rs, d, reps=200)
    assert ci["lo"] == pytest.approx(-0.01) and ci["hi"] == pytest.approx(-0.01)
    rel = reliability([0.05, 0.15, 0.95, 1.0], [0, 0, 1, 1])
    assert sum(b["n"] for b in rel["bins"]) == 4 and rel["ece"] == pytest.approx(0.0625)
