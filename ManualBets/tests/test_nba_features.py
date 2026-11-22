"""Tests for the core/rotation player features and injury mapping.

Basketball package names collide with hockey's (`data_pipeline`, `model`), so
the checks run in an isolated interpreter via PYTHONPATH, matching the repo's
other basketball tests.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


CHECK = r'''
import pandas as pd
from data_pipeline.prepare_data import NBATrainingDataPreparer
from betting.injury_adjustment import adjustPredictionFrame


def playerRow(pid, name, team, day, game, minutes, pts):
    return {
        'PLAYER_ID': pid, 'PLAYER_NAME': name, 'TEAM_ABBREVIATION': team,
        'GAME_DATE': day, 'GAME_ID': game, 'MIN': minutes, 'PTS': pts,
        'REB': 5, 'AST': 3, 'BLK': 1, 'STL': 1, 'TOV': 2,
        'ppg_rolling': pts / max(minutes, 1) * 35,
        'fg_pct_rolling': 0.45, 'mpg_rolling': minutes,
        'plus_minus_rolling': 1.0, 'apg_rolling': 3.0, 'rpg_rolling': 5.0,
        'blk_rolling': 1.0, 'stl_rolling': 1.0, 'tov_rolling': 2.0,
    }


def buildFrame():
    dates = [pd.Timestamp('2025-11-01') + pd.Timedelta(days=2 * i) for i in range(8)]
    rows = []
    for i, day in enumerate(dates):
        game = f'G{i + 1}'
        if i < 4:
            rows.append(playerRow(1, 'Star', 'LAL', day, game, 35, 25))
        rows.append(playerRow(2, 'Replacement', 'LAL', day, game, 20, 10))
        for pid in (3, 4, 5, 6):
            rows.append(playerRow(pid, f'Role{pid}', 'LAL', day, game, 15, 6))
        rows.append(playerRow(7, 'Traded', 'LAL' if i < 4 else 'BOS', day, game, 30, 15))
    return pd.DataFrame(rows), dates


prep = NBATrainingDataPreparer(data_dir='/tmp/opencode/nonexistent')
player_df, dates = buildFrame()

# --- core availability: injured star stays in the core list ---
game8 = dates[7]
core = prep.getTopPlayersAsOf(player_df, game8, 'LAL')
assert 1 in core['PLAYER_ID'].tolist(), 'injured star should stay in the core list'
core = prep.getCoreAvailability(player_df, game8, 'LAL', core).set_index('PLAYER_ID')
assert core.loc[1, 'missed_last3'] == 3
assert core.loc[1, 'days_since'] == 8
assert core.loc[1, 'played_last'] == 0
assert core.loc[2, 'missed_last3'] == 0
assert 7 not in core.index, 'traded-away player should leave the core list'

# --- current rotation: replacement passes the injured starter ---
rotation = prep.getRotationPlayers(player_df, game8, 'LAL')
ids = rotation['PLAYER_ID'].tolist()
assert 1 not in ids, 'player out for the last 5 games should leave the rotation'
assert 2 in ids
assert rotation.set_index('PLAYER_ID').loc[2, 'rot_mpg'] == 20.0
assert 7 not in ids, 'traded-away player should leave the rotation'

# --- no look-ahead at game 6 ---
game6 = dates[5]
core6 = prep.getTopPlayersAsOf(player_df, game6, 'LAL')
core6 = prep.getCoreAvailability(player_df, game6, 'LAL', core6).set_index('PLAYER_ID')
assert core6.loc[1, 'missed_last3'] == 1      # games 3,4 played, 5 missed
assert core6.loc[1, 'days_since'] == 4
rot6 = prep.getRotationPlayers(player_df, game6, 'LAL')
assert rot6.set_index('PLAYER_ID').loc[1, 'rot_mpg'] == 28.0  # 4*35/5

# --- injury status mapping ---
game5 = dates[4]
columns = ['home_core_missed_last3', 'home_core_missed_last5',
           'home_core_minutes_lost_last3', 'home_core_ppg_lost_last3',
           'away_core_missed_last3', 'away_core_missed_last5',
           'away_core_minutes_lost_last3', 'away_core_ppg_lost_last3']
frame = pd.DataFrame([{
    'game_id': 'G5', 'date': game5, 'home_team': 'LAL', 'away_team': 'BOS',
    **{c: 0.0 for c in columns},
}])
injuries = pd.DataFrame([{
    'player_id': 1, 'player_name': 'Star', 'team_abbreviation': 'LAL', 'status': 'OUT',
}])

adj = adjustPredictionFrame(frame, prep, '2025-26', injury_frame=injuries,
                            player_df=player_df, log=False)
row = adj.iloc[0]
assert row['home_core_missed_last3'] == 1.0
assert row['home_core_minutes_lost_last3'] == 35.0
assert row['home_core_ppg_lost_last3'] == 25.0
assert row['away_core_missed_last3'] == 0.0

injuries.loc[0, 'status'] = 'QUESTIONABLE'
adj = adjustPredictionFrame(frame, prep, '2025-26', injury_frame=injuries,
                            player_df=player_df, log=False)
row = adj.iloc[0]
assert row['home_core_missed_last3'] == 0.5
assert row['home_core_minutes_lost_last3'] == 17.5
assert row['home_core_ppg_lost_last3'] == 12.5

# binary mode treats only OUT as a miss
injuries.loc[0, 'status'] = 'QUESTIONABLE'
adj = adjustPredictionFrame(frame, prep, '2025-26', injury_frame=injuries,
                            player_df=player_df, mode='binary', log=False)
assert adj.iloc[0]['home_core_missed_last3'] == 0.0

# ESPN often returns QUESTIONABLE/DAY-TO-DAY with "probable" in the comment.
from data_pipeline.injury_data import InjuryData
idata = InjuryData(data_dir='/tmp/opencode/nonexistent')
assert idata._mapInjuryStatus('Questionable', 'is probable to play') == 'PROBABLE'
assert idata._mapInjuryStatus('Day-To-Day', 'probable for Sunday') == 'PROBABLE'
assert idata._mapInjuryStatus('Out', 'probable but listed out') == 'OUT'

print('ok')
'''


def test_availability_and_injury_features():
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT / 'basketball')
    result = subprocess.run(
        [sys.executable, '-c', CHECK], capture_output=True, text=True,
        cwd=ROOT, timeout=180, env=env)
    assert result.returncode == 0, f"feature check failed:\n{result.stdout}\n{result.stderr}"
