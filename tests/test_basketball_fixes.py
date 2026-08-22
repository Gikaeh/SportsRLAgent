"""Regression tests for NOTES.md Batch 1+2 fixes.

Basketball package names collide with hockey's (`data_pipeline`, `model`), so
basketball modules are imported in isolated interpreters via PYTHONPATH,
mirroring how `.venv/bin/python basketball/main.py` runs.
"""

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent


def run_in_basketball(code):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "basketball")
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=120,
        env=env,
    )


class TestChronologicalSplit:
    def test_orders_and_proportions(self):
        from shared.splitting import chronologicalSplit

        n = 1000
        df = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=n, freq="D"),
            "x": range(n),
        })
        train, val, test = chronologicalSplit(df, date_col="date", test_frac=0.2, val_frac_of_test=0.5)

        assert len(train) == 800 and len(val) == 100 and len(test) == 100
        assert train["date"].max() < val["date"].min()
        assert val["date"].max() < test["date"].min()

    def test_no_row_overlap_and_full_coverage(self):
        from shared.splitting import chronologicalSplit

        df = pd.DataFrame({"date": pd.date_range("2021-06-01", periods=97), "x": range(97)})
        train, val, test = chronologicalSplit(df)
        combined = pd.concat([train, val, test])
        assert len(combined) == len(df)
        assert combined["x"].nunique() == len(df)

    def test_empty_raises(self):
        from shared.splitting import chronologicalSplit

        with pytest.raises(ValueError):
            chronologicalSplit(pd.DataFrame())


PLAYER_SELECTION_CHECK = """
import pandas as pd
from datetime import datetime
from data_pipeline.prepare_data import NBATrainingDataPreparer

prep = NBATrainingDataPreparer(data_dir='/tmp/opencode/nonexistent')

d = pd.Timestamp('2026-03-10')
cols = ['PLAYER_ID','TEAM_ABBREVIATION','GAME_DATE','GAME_ID','MIN',
        'ppg_rolling','fg_pct_rolling','mpg_rolling','plus_minus_rolling',
        'apg_rolling','rpg_rolling','blk_rolling','stl_rolling','tov_rolling']

def row(pid, date, gid, min_played, mpg, ppg):
    return {'PLAYER_ID': pid, 'TEAM_ABBREVIATION': 'LAL', 'GAME_DATE': date,
            'GAME_ID': gid, 'MIN': min_played, 'ppg_rolling': ppg,
            'fg_pct_rolling': 0.45, 'mpg_rolling': mpg, 'plus_minus_rolling': 1.0,
            'apg_rolling': 2.0, 'rpg_rolling': 3.0, 'blk_rolling': 0.4,
            'stl_rolling': 0.5, 'tov_rolling': 1.1}

rows = [
    # star: high rolling mpg, played earlier games only
    row(1, d - pd.Timedelta(days=10), 100, 34, 34.0, 25.0),
    row(1, d - pd.Timedelta(days=5), 200, 36, 35.0, 26.0),
    # bench player: low rolling mpg but plays HUGE minutes in tonight's game
    row(2, d - pd.Timedelta(days=3), 300, 12, 11.0, 4.0),
    row(2, d, 400, 48, 11.0, 4.0),          # tonight's row (in-game info!)
    # rookie: FIRST appearance is tonight -> no pre-game history
    row(3, d, 400, 45, 0.0, 30.0),
]
player_df = pd.DataFrame(rows).sort_values(['PLAYER_ID','GAME_DATE']).reset_index(drop=True)

top = prep.getTopPlayersAsOf(player_df, d, 'LAL', top_n=6)
ids = top['PLAYER_ID'].tolist()
assert ids == [1, 2], f"expected pre-game ranking [1, 2], got {ids}"
assert abs(top.iloc[0]['mpg_rolling'] - 35.0) < 1e-9
assert abs(top.iloc[1]['mpg_rolling'] - 11.0) < 1e-9
print("ok")
"""


@pytest.mark.parametrize("sport", ["basketball"])
def test_player_selection_is_pregame_only(sport):
    result = run_in_basketball(PLAYER_SELECTION_CHECK)
    assert result.returncode == 0, f"A1 regression failed:\n{result.stderr}"


ODDS_WINDOW_CHECK = """
import sys
sys.path.insert(0, '.')
import pandas as pd
import pytz
from data_pipeline.odd_scraping import upcomingGamesWindow

pst = pytz.timezone('America/Los_Angeles')
now = pst.localize(pd.Timestamp('2026-03-10 18:00').to_pydatetime())

df = pd.DataFrame({
    'commence_time': [
        pst.localize(pd.Timestamp('2026-03-10 17:00').to_pydatetime()),  # already started
        pst.localize(pd.Timestamp('2026-03-10 19:30').to_pydatetime()),  # keep
        pst.localize(pd.Timestamp('2026-03-13 19:30').to_pydatetime()),  # beyond window
    ],
})
kept = upcomingGamesWindow(df, now)
assert len(kept) == 1, f"expected exactly the not-yet-started in-window game, got {len(kept)}"
print("ok")
"""


@pytest.mark.parametrize("sport", ["basketball"])
def test_odds_window_excludes_started_games(sport):
    result = run_in_basketball(ODDS_WINDOW_CHECK)
    assert result.returncode == 0, f"B1 regression failed:\n{result.stderr}"


COVER_PROB_CHECK = """
import json
from pathlib import Path
import tempfile
from betting.betting_recommender import BettingRecommender

rec = BettingRecommender.__new__(BettingRecommender)  # skip heavy __init__
rec.margin_residual_sigma = 11.8
rec.total_residual_sigma = 14.0

# C1: normal-approx cover probability
p_zero = rec.normalCoverProbability(0.0, 11.8)
p_pos = rec.normalCoverProbability(3.0, 11.8)
p_neg = rec.normalCoverProbability(-3.0, 11.8)
assert abs(p_zero - 0.5) < 1e-9
assert p_pos > 0.55, f"3-pt edge should clear 0.55 at sigma=11.8, got {p_pos}"
assert p_neg < 0.45
assert rec.normalCoverProbability(6.0, 11.8) > p_pos          # monotonic up
assert rec.normalCoverProbability(-6.0, 11.8) < p_neg         # monotonic down
assert abs(p_pos + p_neg - 1.0) < 1e-9                        # symmetric
assert rec.normalCoverProbability(500.0, 11.8) <= 0.99        # clamped high
assert rec.normalCoverProbability(-500.0, 11.8) >= 0.01       # clamped low
try:
    rec.normalCoverProbability(1.0, 0.0); assert False
except ValueError:
    pass

# wrappers use the right sigmas
assert rec.marginToProbability(3.0) == p_pos
assert rec.totalToProbability(3.0) < p_pos                    # bigger sigma -> smaller edge prob

# C2: devig
fair_h, fair_a = rec.devigTwoWay(rec.oddsToProbability(-110), rec.oddsToProbability(-110))
assert abs(fair_h - 0.5) < 1e-9 and abs(fair_a - 0.5) < 1e-9
implied_fav, implied_dog = rec.oddsToProbability(-120), rec.oddsToProbability(100)
fair2_h, fair2_a = rec.devigTwoWay(implied_fav, implied_dog)
assert abs((fair2_h + fair2_a) - 1.0) < 1e-9
assert abs(fair2_h - 12/23) < 1e-9   # (-120,+100): implied 6/11 overround 23/22 -> 12/23
edge = rec.calculateEdge(0.60, -120, 100)
assert abs(edge - (0.60 - fair2_h)) < 1e-9
raw_edge = rec.calculateEdge(0.60, -120)
assert abs(raw_edge - (0.60 - implied_fav)) < 1e-9            # no-opposite fallback intact
assert edge > raw_edge                                        # devigged edge is larger

# loadResidualSigma: measured file wins; missing dir falls back
with tempfile.TemporaryDirectory() as tmp:
    meta = Path(tmp) / 'retraining_spread_metadata.json'
    meta.write_text(json.dumps({'residual_std': 10.51}))
    got = rec.loadResidualSigma('spread', 11.8, metadata_dir=tmp)
    assert abs(got - 10.51) < 1e-9
    got_fb = rec.loadResidualSigma('total', 14.0, metadata_dir=tmp)  # only spread file exists
    assert got_fb == 14.0

print('ok')
"""


@pytest.mark.parametrize("sport", ["basketball"])
def test_cover_probability_and_devig_math(sport):
    result = run_in_basketball(COVER_PROB_CHECK)
    assert result.returncode == 0, f"C1/C2 regression failed:\n{result.stderr}"
