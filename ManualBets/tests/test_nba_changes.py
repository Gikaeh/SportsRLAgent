"""Regression tests for the 2026-11-20 NBA changes (A7, CLV)."""
import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def loadModule(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_latest_window_stats_uses_the_most_recent_games(tmp_path):
    """NOTES.md A7: live features must cover the same window as training rows.

    Training row for the next game uses games N-9..N (the last played game
    included). The old live path used N-10..N-1, one game behind.
    """
    sys.path.insert(0, str(ROOT))
    module = loadModule('basketball/data_pipeline/prepare_data.py', 'nba_prepare_data_a7')
    preparer = module.NBATrainingDataPreparer(data_dir=str(tmp_path))
    preparer.getCurrentSeason = lambda: '2025-26'
    team_dir = tmp_path / 'team_data'
    team_dir.mkdir(parents=True)

    rows = []
    # LAL scores 100, 110, 120, 130: the last three must average 120, not 110.
    scores = {'LAL': [100, 110, 120, 130], 'BOS': [95, 105, 115, 125]}
    for i, date in enumerate(pd.date_range('2025-11-01', periods=4, freq='2D')):
        for team, opp in (('LAL', 'BOS'), ('BOS', 'LAL')):
            pts = scores[team][i]
            rows.append({
                'GAME_ID': f'00{i}', 'GAME_DATE': date,
                'TEAM_ABBREVIATION': team, 'MATCHUP': f'{team} @ {opp}',
                'WL': 'W' if pts > scores[opp][i] else 'L',
                'MIN': 240, 'PTS': pts, 'PLUS_MINUS': pts - scores[opp][i],
                'FGM': 40, 'FGA': 85, 'FG3M': 10, 'FG3_PCT': 0.35,
                'FTA': 20, 'OREB': 10, 'DREB': 30, 'REB': 40, 'AST': 22,
                'TOV': 12, 'STL': 7, 'BLK': 5,
            })
    pd.DataFrame(rows).to_csv(team_dir / '2025-26_team_stats.csv', index=False)

    latest = preparer.latestWindowStats('2025-26', window=3).set_index('TEAM_ABBREVIATION')
    assert latest.loc['LAL', 'ppg_l3'] == 120.0, latest.loc['LAL'].to_dict()
    assert latest.loc['LAL', 'wins_l3'] == 3
    assert latest.loc['BOS', 'ppg_l3'] == (105 + 115 + 125) / 3
    assert pd.Timestamp(latest.loc['LAL', 'GAME_DATE']) == pd.Timestamp('2025-11-07')


def test_clv_points_reward_beating_the_close():
    """A home -3.5 bet that closes -5.5 has +2 points of CLV."""
    clv = loadModule('tools/clv.py', 'nba_clv')
    snapshot = pd.DataFrame([
        {'home_team': 'BOS', 'away_team': 'LAL', 'name': 'BOS', 'price': -110, 'point': -5.5,
         'bookmakers_key': 'betmgm', 'commence_time': '2025-11-08T02:00:00Z'},
        {'home_team': 'BOS', 'away_team': 'LAL', 'name': 'LAL', 'price': -110, 'point': 5.5,
         'bookmakers_key': 'betmgm', 'commence_time': '2025-11-08T02:00:00Z'},
    ])
    snapshot['commence_time'] = pd.to_datetime(snapshot['commence_time'], utc=True)
    bet = pd.Series({
        'market': 'spread', 'matchup': 'LAL @ BOS', 'bet_team': 'BOS', 'bet_side': 'home',
        'home_spread': -3.5, 'away_spread': 3.5, 'home_odds': -110, 'away_odds': -110,
        'book': 'betmgm', 'game_id': 1, 'timestamp': '2025-11-07 10:00:00',
        'bet_ts': pd.Timestamp('2025-11-07 10:00'),
    })
    row = clv.clvRow(bet, [(pd.Timestamp('2025-11-07 17:00', tz=clv.PT), 'spread_fake.csv', snapshot)])
    assert row is not None
    assert row['clv_points'] == 2.0
    assert row['close_line'] == -5.5
    assert row['clv_prob'] is not None
