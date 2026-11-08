"""Feature-injection harness (deepsports.analysis.feature_test): paired scoring, candidate
joins, and the bit-exact baseline reproduction on synthetic NBA and college rows. The scoring
and join tests are ported from the DeepSeek edge study's lab tests."""

import random
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from test_model import synth_store

from deepsports.analysis import ncaab
from deepsports.analysis.backtest import walk_forward
from deepsports.analysis.feature_test import (
    attach_columns,
    compare_predictions,
    game_values,
    home_minus_away,
    nba_feature_test,
    ncaab_feature_test,
    ncaab_walk_forward,
    paired_day_bootstrap,
    paired_gap_comparison,
    pearson,
    to_float,
)
from deepsports.analysis.features import build_features
from deepsports.analysis.model import make_model

# ---------- scoring ----------


def test_paired_day_bootstrap_mean_and_cluster_respect():
    # 3 days; day 3 has two games. The pooled mean is the plain mean of all diffs.
    days = ["d1", "d1", "d2", "d3", "d3"]
    diffs = [1.0, 3.0, -2.0, 0.0, 2.0]
    r = paired_day_bootstrap(days, diffs, reps=500, seed=42)
    assert r["mean"] == pytest.approx(4.0 / 5.0, rel=1e-12)
    assert r["n"] == 5 and r["n_days"] == 3
    # every resample draws whole days, so every resampled mean is a mean of day-means
    # (day means: 2, -2, 1) -> bounds within [-2, 2]
    assert -2.0 - 1e-9 <= r["lo"] <= r["hi"] <= 2.0 + 1e-9
    # same seed -> identical result
    r2 = paired_day_bootstrap(days, diffs, reps=500, seed=42)
    assert r2 == r


def test_paired_day_bootstrap_empty():
    r = paired_day_bootstrap([], [])
    assert r["n"] == 0 and np.isnan(r["mean"])


def test_paired_gap_comparison_close_cancels():
    # Two days. Baseline err = [1, 1], feature err = [0.5, 1.5] -> diffs = [-0.5, +0.5]
    rows = [
        {"day": "d1", "base_pred": 3.0, "pred": 2.5, "spread_home": -4.0, "home_margin": 2.0},
        {"day": "d2", "base_pred": 3.0, "pred": 3.5, "spread_home": -4.0, "home_margin": 2.0},
    ]
    r = paired_gap_comparison(
        rows, "pred", "base_pred", "spread_home", "home_margin", close_sign=-1
    )
    assert r["n"] == 2
    assert r["base_mae"] == pytest.approx(1.0, rel=1e-12)
    assert r["feat_mae"] == pytest.approx(1.0, rel=1e-12)
    assert r["delta_gap"] == pytest.approx(0.0, rel=1e-12)
    # the close (a constant -(-4) = 4 vs margin 2 -> err 2) must cancel exactly:
    assert r["base_gap"] == pytest.approx(1.0 - 2.0, rel=1e-12)
    assert r["feat_gap"] == pytest.approx(1.0 - 2.0, rel=1e-12)
    assert r["ci_lo"] <= r["delta_gap"] <= r["ci_hi"]


def test_paired_gap_comparison_sign():
    # feature strictly better on every row -> negative delta, bootstrap CI below 0
    rows = [
        {
            "day": f"d{i % 10}",
            "base_pred": float(5),
            "pred": float(4),
            "over_under": 200.0,
            "total": 3.0,
        }
        for i in range(50)
    ]
    r = paired_gap_comparison(rows, "pred", "base_pred", "over_under", "total", close_sign=1)
    assert r["delta_gap"] == pytest.approx(-1.0, rel=1e-12)
    assert r["ci_hi"] < 0


def test_pearson():
    assert pearson([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0, rel=1e-12)
    assert pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0, rel=1e-12)
    assert np.isnan(pearson([1, 1, 1], [1, 2, 3]))  # zero variance
    assert pearson([1, 2, np.nan, 4], [1, np.nan, 3, 4]) == pytest.approx(1.0, rel=1e-12)


# ---------- features ----------


def test_to_float():
    assert to_float("1.5") == 1.5
    assert to_float("") is None
    assert to_float("None") is None
    assert to_float("nan") is None


def test_game_values_drops_incomplete_games():
    rows = [
        {"game_id": "g1", "a": "1.0", "b": "2.0"},
        {"game_id": "g2", "a": "", "b": "3.0"},  # incomplete -> excluded
        {"game_id": "g3", "a": "4.0", "b": "None"},
    ]
    out = game_values(rows, ["a", "b"])
    assert out == {"a": {"g1": 1.0}, "b": {"g1": 2.0}}


def test_home_minus_away():
    rows = [
        {"game_id": "g1", "home_away": "home", "opp3_5": "0.4"},
        {"game_id": "g1", "home_away": "away", "opp3_5": "0.1"},
        {"game_id": "g2", "home_away": "home", "opp3_5": "0.2"},
        {"game_id": "g2", "home_away": "away", "opp3_5": ""},  # missing -> excluded
    ]
    out = home_minus_away(rows, "opp3_5")
    assert out == {"g1": pytest.approx(0.3, rel=1e-12)}


def test_attach_columns_nan_and_covered():
    rows = [
        {"game_id": "g1", "features": {"x": 1.0}},
        {"game_id": "g2", "features": {"x": 2.0}},
    ]
    maps = {"new": {"g1": 5.0}}
    covered = attach_columns(rows, maps)
    assert covered == {"new": {"g1"}}
    assert rows[0]["features"]["new"] == 5.0
    assert np.isnan(rows[1]["features"]["new"])


# ---------- bit-exact baseline reproduction ----------


@pytest.fixture(scope="module")
def nba_rows():
    s = synth_store(seasons=(2024, 2025, 2026), rounds=4)
    rows = build_features(s.con)
    s.close()
    return rows


def test_nba_baseline_reproduces_bit_exact_and_oracle_feature_helps(nba_rows):
    shipped = walk_forward(nba_rows, model_factory=lambda: make_model("v1.0"))["predictions"]
    done = [r for r in nba_rows if r["home_margin"] is not None]
    # A leaky "oracle" column (the true margin) on half the games: only to prove the plumbing
    # moves predictions toward the truth. Real candidates must be pre-tip.
    values = {"oracle": {r["game_id"]: float(r["home_margin"]) for r in done[::2]}}
    out = nba_feature_test(
        nba_rows,
        values,
        extra_win_margin=["oracle"],
        base_version="v1.0",
        reference=shipped,
        reps=200,
    )
    assert out["baseline_check"]["n_mismatch"] == 0  # NaN columns leave the baseline alone
    assert out["reference_check"]["n_mismatch"] == 0  # == the shipped walk-forward
    assert out["coverage"]["oracle"] == len(values["oracle"])
    m = out["margin"]
    assert m["n"] > 0 and m["delta_gap"] < 0 and m["ci_hi"] < 0
    assert "oracle" not in nba_rows[0]["features"]  # inputs untouched


def _college_rows(n_teams=8, days=90, seed=3):
    rng = random.Random(seed)
    win, total = ncaab.feature_lists("players")
    cols = sorted(set(win + total + ncaab.feature_lists("team")[0]))
    t0 = datetime(2025, 11, 3, 23, tzinfo=UTC)
    rows = []
    for i in range(days * 4):
        t = t0 + timedelta(hours=6 * i)
        feats = {c: rng.gauss(0, 1) for c in cols}
        margin = round(5 * feats["elo_diff"] + rng.gauss(0, 10)) or 1
        tot = 140 + round(3 * feats["rt_total"] + rng.gauss(0, 12))
        rows.append(
            {
                "game_id": str(i),
                "season": 2026,
                "season_type": 2,
                "start_time_utc": t,
                "day": t.date().isoformat(),
                "neutral_site": False,
                "conference": None,
                "d1": i % 7 != 0,
                "rt_n": min(i // n_teams, 20),
                "elo_p_home": 0.5,
                "home_win": int(margin > 0),
                "home_margin": margin,
                "total": tot,
                "market": {"p_home": 0.5, "spread_home": -margin / 2, "over_under": 141.5},
                "features": feats,
            }
        )
    return rows


def test_ncaab_walk_forward_reproduces_the_shipped_one():
    rows = _college_rows()
    choice = {
        "win": {"feature_set": "team", "min_games": 5},
        "margin": {"feature_set": "players", "min_games": 5},
        "total": {"feature_set": "players", "min_games": 5},
    }
    start = datetime(2025, 12, 1, 5, tzinfo=UTC)
    shipped = ncaab.walk_forward(rows, choice, home_adv=60.0, start=start)
    mine = ncaab_walk_forward(rows, choice, start)
    ref = [
        {
            "game_id": p["game_id"],
            "p_home_win": p["p_model"],
            "pred_home_margin": p["m_model"],
            "pred_total": p["t_model"],
        }
        for p in shipped
    ]
    assert len(mine) == len(ref) > 50
    assert compare_predictions(ref, mine, tol=0.0)["n_mismatch"] == 0
    noise = {"z": {r["game_id"]: random.Random(int(r["game_id"])).random() for r in rows}}
    out = ncaab_feature_test(rows, noise, choice, start, extra_total=["z"], reference=ref, reps=100)
    assert out["baseline_check"]["n_mismatch"] == 0
    assert out["reference_check"]["n_mismatch"] == 0
    assert out["total"]["n"] > 0 and "margin" not in out


def test_compare_predictions_reports_mismatches():
    a = [{"game_id": "1", "p_home_win": 0.5, "pred_home_margin": 1.0, "pred_total": None}]
    b = [{"game_id": "1", "p_home_win": 0.5 + 1e-6, "pred_home_margin": 1.0, "pred_total": None}]
    assert compare_predictions(a, a)["n_mismatch"] == 0
    r = compare_predictions(a, b + [{"game_id": "2"}])
    assert r["n_mismatch"] == 2  # p_home_win differs; game 2 missing from a
