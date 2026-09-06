"""Verification for opp_avg_win_pct_l10 (strength of schedule).

Run with `-s` to see the printed per-opponent breakdown:
    .venv\\Scripts\\python.exe -m pytest tests/test_opp_avg_win_pct.py -v -s

High -> team played hard opponents; low -> easy opponents. The "W-L" column shows
each opponent's win-loss record entering that matchup (i.e. over their games before
the one they played the sample team).
"""

import numpy as np
import pandas as pd
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from basketball.data_pipeline.prepare_data import NBATrainingDataPreparer

SEASON = "2024-25"
SAMPLE_TEAM = "BOS"
SAMPLE_GAME_INDEX = 40  # well past the ~game-21 full-window mark


def _load():
    preparer = NBATrainingDataPreparer()
    df = pd.read_csv(preparer.team_data_dir / f"{SEASON}_team_stats.csv")
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])
    return preparer, df


def test_opp_avg_win_pct_invariants():
    preparer, df = _load()
    out = preparer.calculateOpponentStrengthL10(df, keep_breakdown=True)

    assert "opp_avg_win_pct_l10" in out.columns
    assert out["opp_avg_win_pct_l10"].between(0, 1).all()

    # No leakage: the value equals the mean of the previous up-to-10 opponents'
    # adjusted win pct (shifted by one game).
    expected = out.groupby("TEAM_ABBREVIATION")["opponent_win_pct_adj"].transform(
        lambda x: x.rolling(window=10, min_periods=1).mean().shift(1)
    ).fillna(0.50)
    assert np.allclose(out["opp_avg_win_pct_l10"], expected), "oops, feature leaks or window shifted wrong"

    # Full-window rows (prior_games >= 10): fade fully off -> weight==1 and the
    # pct equals a pure multiple of 0.1 (k/10).
    full = out[out["prior_games"] >= 10]
    assert (full["weight"] == 1.0).all(), "weight should be 1 once an opponent has 10 games"
    assert np.allclose(full["win_pct_adj"], full["raw_pct"]), "full-window pct should be unshrunken"
    tenths = (full["raw_pct"] * 10).round(8)
    assert np.allclose(tenths, tenths.round()), "full-window pct should be a multiple of 0.1 (k/10)"


def test_preview_opponent_breakdown():
    preparer, df = _load()
    out = preparer.calculateOpponentStrengthL10(df, keep_breakdown=True)
    team = out[out["TEAM_ABBREVIATION"] == SAMPLE_TEAM].reset_index(drop=True)
    row = team.loc[SAMPLE_GAME_INDEX]

    # The saved avg uses the 10 opponents in the games immediately before this one.
    window = team.iloc[SAMPLE_GAME_INDEX - 10 : SAMPLE_GAME_INDEX]

    print(f"\n=== {SAMPLE_TEAM}: last 10 opponents entering game {SAMPLE_GAME_INDEX} "
          f"(played {row['GAME_DATE'].date()}) ===")
    print(f"{'opp':>5}  {'rec':>7}  {'weight':>6}  {'contrib':>7}")
    contribs = []
    for _, r in window.iterrows():
        n_games = int(r["opponent_prior_games"])
        wins = int(r["opponent_prior_wins"])
        rec = f"{wins}-{n_games - wins}"
        contribs.append(r["opponent_win_pct_adj"])
        print(f"{r['opponent_abbr']:>5}  {rec:>7}  {r['opponent_prior_games'] / 10.0:>6.2f}  {r['opponent_win_pct_adj']:>7.3f}")

    print(f"\nmanual mean of 10 contributions = {np.mean(contribs):.4f}")
    print(f"stored opp_avg_win_pct_l10      = {row['opp_avg_win_pct_l10']:.4f}")
    print(f"opponents with full 10-game rec = {int((window['opponent_prior_games'] >= 10).sum())}/10")

    assert np.isclose(np.mean(contribs), row["opp_avg_win_pct_l10"]), "breakdown mean != stored value"
