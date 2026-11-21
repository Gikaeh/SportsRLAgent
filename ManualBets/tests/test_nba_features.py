"""Tests for the two-list availability design (core top 5 + current rotation)."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'basketball'))
sys.path.insert(0, str(ROOT))

from data_pipeline.prepare_data import NBATrainingDataPreparer  # noqa: E402


def playerRow(pid, name, team, day, game, minutes, pts):
    return {
        'PLAYER_ID': pid, 'PLAYER_NAME': name, 'TEAM_ABBREVIATION': team,
        'GAME_DATE': day, 'GAME_ID': game, 'MIN': minutes, 'PTS': pts,
        'REB': 5, 'AST': 3, 'BLK': 1, 'STL': 1, 'TOV': 2,
        # rolling columns used by getTopPlayersAsOf (values fixed per player)
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
        # Star: plays games 1-4 only (season-ending injury).
        if i < 4:
            rows.append(playerRow(1, 'Star', 'LAL', day, game, 35, 25))
        # Replacement: plays every game.
        rows.append(playerRow(2, 'Replacement', 'LAL', day, game, 20, 10))
        # Four rotation players: every game, 15 minutes.
        for pid in (3, 4, 5, 6):
            rows.append(playerRow(pid, f'Role{pid}', 'LAL', day, game, 15, 6))
        # Traded player: LAL games 1-4, BOS games 5-8.
        rows.append(playerRow(7, 'Traded', 'LAL' if i < 4 else 'BOS', day, game, 30, 15))
    return pd.DataFrame(rows), dates


def test_core_availability_and_current_rotation():
    prep = NBATrainingDataPreparer(data_dir='/tmp/opencode/nonexistent')
    player_df, dates = buildFrame()
    game8 = dates[7]

    core = prep.getTopPlayersAsOf(player_df, game8, 'LAL')
    assert 1 in core['PLAYER_ID'].tolist(), 'the injured star stays in the core list'
    core = prep.getCoreAvailability(player_df, game8, 'LAL', core).set_index('PLAYER_ID')
    assert core.loc[1, 'missed_last3'] == 3
    assert core.loc[1, 'days_since'] == 8
    assert core.loc[1, 'played_last'] == 0
    assert core.loc[2, 'missed_last3'] == 0
    assert 7 not in core.index, 'a traded-away player leaves the core list'

    rotation = prep.getRotationPlayers(player_df, game8, 'LAL')
    ids = rotation['PLAYER_ID'].tolist()
    assert 1 not in ids, 'a player out for the last 5 games leaves the rotation'
    assert 2 in ids
    assert rotation.set_index('PLAYER_ID').loc[2, 'rot_mpg'] == 20.0
    assert 7 not in ids, 'a traded-away player leaves the rotation'


def test_features_do_not_look_ahead():
    prep = NBATrainingDataPreparer(data_dir='/tmp/opencode/nonexistent')
    player_df, dates = buildFrame()
    game6 = dates[5]

    core = prep.getTopPlayersAsOf(player_df, game6, 'LAL')
    core = prep.getCoreAvailability(player_df, game6, 'LAL', core).set_index('PLAYER_ID')
    # Team games before game 6 are 1..5; last three are 3,4,5. The star played
    # 3 and 4 and missed 5, so exactly one missed game, not games 6-8.
    assert core.loc[1, 'missed_last3'] == 1
    assert core.loc[1, 'days_since'] == 4  # last played game 4 (Nov 7), game 6 Nov 11

    rotation = prep.getRotationPlayers(player_df, game6, 'LAL')
    # Last 5 team games are 1..5; the star played games 1-4 -> 4*35/5.
    assert rotation.set_index('PLAYER_ID').loc[1, 'rot_mpg'] == 28.0


def test_injury_status_mapping():
    from betting.injury_adjustment import adjustPredictionFrame

    prep = NBATrainingDataPreparer(data_dir='/tmp/opencode/nonexistent')
    player_df, dates = buildFrame()
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
    # Last two completed games were played; OUT makes the upcoming game a full miss.
    assert row['home_core_missed_last3'] == 1.0
    assert row['home_core_minutes_lost_last3'] == 35.0
    assert row['home_core_ppg_lost_last3'] == 25.0
    # Away team has no report.
    assert row['away_core_missed_last3'] == 0.0

    injuries.loc[0, 'status'] = 'QUESTIONABLE'
    adj = adjustPredictionFrame(frame, prep, '2025-26', injury_frame=injuries,
                                player_df=player_df, log=False)
    row = adj.iloc[0]
    assert row['home_core_missed_last3'] == 0.5
    assert row['home_core_minutes_lost_last3'] == 17.5
    assert row['home_core_ppg_lost_last3'] == 12.5
