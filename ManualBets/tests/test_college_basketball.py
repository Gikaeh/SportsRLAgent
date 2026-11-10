"""College pipeline: leakage guards, train/predict parity, and betting rules (no network)."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from college_basketball.betting.betting_recommender import matchLines, normalizeName, parseOdds, recommend
from college_basketball.data_pipeline.prepare_data import (META_COLUMNS, buildMatchups, featureColumns,
                                                           trainingRows, upcomingRows)
from college_basketball.model.model_college import fitModels, predictGames
from shared.bankroll import bankrollFromLogs, kellyFraction, wholeDollarStake

TEAMS = [f"T{i}" for i in range(6)]


def syntheticData(seed=1):
    rng = np.random.default_rng(seed)
    games, team_rows, player_rows = [], [], []
    start = pd.Timestamp('2024-11-05 19:00')
    number = 0
    for season, offset in ((2025, 0), (2026, 365)):
        for day in range(40):
            order = rng.permutation(6)
            for i in (0, 2, 4):
                home, away = TEAMS[order[i]], TEAMS[order[i + 1]]
                number += 1
                game_id, hs, aps = str(number), int(rng.integers(55, 95)), int(rng.integers(55, 95))
                if hs == aps:
                    hs += 1
                games.append({'game_id': game_id, 'season_year': season, 'season_type': 2,
                              'start_time': start + pd.Timedelta(days=offset + day * 2), 'state': 'post',
                              'completed': True, 'neutral_site': False, 'home_team_id': home, 'away_team_id': away,
                              'home_score': hs, 'away_score': aps, 'home_abbr': home, 'away_abbr': away,
                              'home_name': f'{home} Tigers', 'away_name': f'{away} Bears',
                              'home_listed': True, 'away_listed': True})
                for team in (home, away):
                    team_rows.append({'game_id': game_id, 'team_id': team, 'fgm': 25, 'fga': 55, 'fg3m': 7, 'fg3a': 20,
                                      'ftm': 12, 'fta': 16, 'oreb': 8, 'dreb': 22, 'reb': 30, 'ast': 12, 'stl': 6,
                                      'blk': 3, 'tov': 12, 'pf': 16})
                    for p in range(8):
                        player_rows.append({'game_id': game_id, 'team_id': team, 'athlete_id': f'{team}-{p}',
                                            'minutes': float(35 - 3 * p), 'pts': float(20 - 2 * p), 'plus_minus': 1.0})
    return pd.DataFrame(games), pd.DataFrame(team_rows), pd.DataFrame(player_rows)


def features(matchups, game_ids):
    columns = featureColumns(matchups)
    return matchups[matchups['game_id'].isin(game_ids)].sort_values('game_id')[columns].reset_index(drop=True)


def test_future_games_cannot_change_earlier_features():
    games, team_stats, player_stats = syntheticData()
    cutoff = games['start_time'].sort_values().iloc[len(games) * 3 // 4]
    earlier = games[games['start_time'] <= cutoff]['game_id']
    later = games[games['start_time'] > cutoff]['game_id']
    baseline = features(buildMatchups(games, team_stats, player_stats), earlier)

    changed = games.copy()
    is_later = changed['game_id'].isin(later)
    changed.loc[is_later, ['home_score', 'away_score']] = [150, 20]
    ts = team_stats.copy()
    ts.loc[ts['game_id'].isin(later), 'fga'] = 99
    ps = player_stats.copy()
    ps.loc[ps['game_id'].isin(later), ['minutes', 'pts']] = [1.0, 99.0]
    pd.testing.assert_frame_equal(baseline, features(buildMatchups(changed, ts, ps), earlier))


def test_a_games_own_result_and_box_cannot_change_its_features():
    games, team_stats, player_stats = syntheticData()
    target = games.iloc[len(games) // 2]['game_id']
    baseline = features(buildMatchups(games, team_stats, player_stats), [target])

    changed = games.copy()
    changed.loc[changed['game_id'] == target, ['home_score', 'away_score']] = [150, 20]
    ts = team_stats.copy()
    ts.loc[ts['game_id'] == target, 'fga'] = 99
    ps = player_stats.copy()
    ps.loc[ps['game_id'] == target, ['minutes', 'pts']] = [40.0, 99.0]
    pd.testing.assert_frame_equal(baseline, features(buildMatchups(changed, ts, ps), [target]))


def test_scheduled_game_gets_the_same_features_as_when_it_is_completed():
    games, team_stats, player_stats = syntheticData()
    last_start = games['start_time'].max()
    last = games[games['start_time'] == last_start]['game_id']
    completed = features(buildMatchups(games, team_stats, player_stats), last)

    scheduled = games.copy()
    is_last = scheduled['game_id'].isin(last)
    scheduled.loc[is_last, ['home_score', 'away_score']] = np.nan
    scheduled.loc[is_last, 'completed'] = False
    scheduled.loc[is_last, 'state'] = 'pre'
    ts = team_stats[~team_stats['game_id'].isin(last)]
    ps = player_stats[~player_stats['game_id'].isin(last)]
    matchups = buildMatchups(scheduled, ts, ps)
    pd.testing.assert_frame_equal(completed, features(matchups, last))
    assert set(upcomingRows(matchups, last_start - pd.Timedelta(hours=1))['game_id']) == set(last)


def test_no_rank_market_or_target_columns_are_features():
    games, team_stats, player_stats = syntheticData()
    columns = featureColumns(buildMatchups(games, team_stats, player_stats))
    forbidden = ('rank', 'spread', 'moneyline', 'over_under', 'odds')
    assert not [c for c in columns if any(word in c for word in forbidden)]
    assert not {'home_won', 'point_diff', 'total_score', 'home_score', 'away_score'} & set(columns)
    assert not set(columns) & set(META_COLUMNS)


def test_non_d1_games_are_history_but_not_training_rows():
    games, team_stats, player_stats = syntheticData()
    games.loc[games.index[:5], 'away_listed'] = False
    rows = trainingRows(buildMatchups(games, team_stats, player_stats))
    assert len(rows) == len(games) - 5


def test_models_fit_and_predict_with_the_same_feature_order():
    games, team_stats, player_stats = syntheticData()
    rows = trainingRows(buildMatchups(games, team_stats, player_stats))
    models, columns, residual_std = fitModels(rows, {'learning_rate': 0.3, 'max_depth': 2})
    predictions = predictGames(models, columns, rows.tail(5))
    assert predictions['p_home_win'].between(0, 1).all()
    assert set(residual_std) == {'spread', 'total'}
    with pytest.raises(ValueError, match='missing training features'):
        predictGames(models, columns, rows.tail(5).drop(columns=[columns[0]]))


def oddsGame(home, away, home_spread=-5.5, total=150.5, home_ml=-200, away_ml=170):
    return {'commence_time': '2026-11-08T18:00:00Z', 'home_team': home, 'away_team': away, 'bookmakers': [{
        'key': 'betmgm', 'markets': [
            {'key': 'h2h', 'outcomes': [{'name': home, 'price': home_ml}, {'name': away, 'price': away_ml}]},
            {'key': 'spreads', 'outcomes': [{'name': home, 'point': home_spread, 'price': -110},
                                            {'name': away, 'point': -home_spread, 'price': -110}]},
            {'key': 'totals', 'outcomes': [{'name': 'Over', 'point': total, 'price': -105},
                                           {'name': 'Under', 'point': total, 'price': -115}]}]}]}


def prediction(margin=0.0, total=150.5, p_home=0.5, games_played=10.0):
    return pd.DataFrame([{'game_id': '1', 'start_time': pd.Timestamp('2026-11-08 18:00'), 'home_abbr': 'SIE',
                          'away_abbr': 'PRIN', 'home_name': 'Siena Saints', 'away_name': 'Princeton Tigers',
                          'p_home_win': p_home, 'pred_home_margin': margin, 'pred_total': total,
                          'min_games_played': games_played}])


def betsFor(pred, game):
    pairs, unmatched = matchLines(pred, parseOdds([game], ['betmgm']))
    assert not unmatched
    return recommend(pairs, 11.5, 16.5)


def test_spread_bet_takes_the_side_with_the_cushion():
    bets = betsFor(prediction(margin=0.0, p_home=0.45), oddsGame('Siena Saints', 'Princeton Tigers'))
    spreads = [b for b in bets if b['type'] == 'spread']
    assert [b['bet'] for b in spreads] == ['PRIN +5.5']
    assert spreads[0]['model_probability'] > 0.55


def test_neutral_site_line_listed_the_other_way_round_keeps_the_right_team():
    game = oddsGame('Princeton Tigers', 'Siena Saints', home_spread=5.5, home_ml=170, away_ml=-200)
    spreads = [b for b in betsFor(prediction(margin=0.0, p_home=0.45), game) if b['type'] == 'spread']
    assert [b['bet'] for b in spreads] == ['PRIN +5.5']


def test_total_needs_the_full_threshold_and_uses_the_right_price():
    game = oddsGame('Siena Saints', 'Princeton Tigers', home_spread=-0.5, home_ml=-110, away_ml=-110)
    assert not [b for b in betsFor(prediction(total=157.0), game) if b['type'] == 'total']
    under = [b for b in betsFor(prediction(total=140.0), game) if b['type'] == 'total'][0]
    assert under['bet'] == 'Under 150.5' and under['odds'] == -115


def test_odds_api_spellings_match_warehouse_names():
    assert normalizeName('SE Missouri St Redhawks') == normalizeName('Southeast Missouri State Redhawks')
    assert normalizeName('St. Thomas (MN) Tommies') == normalizeName('St. Thomas Tommies')
    assert normalizeName('CSU Bakersfield Roadrunners') == normalizeName('Cal State Bakersfield Roadrunners')
    assert normalizeName('North Dakota St Bison') == normalizeName('North Dakota State Bison')


def test_bets_are_withheld_until_both_teams_have_enough_games():
    game = oddsGame('Siena Saints', 'Princeton Tigers')
    assert not betsFor(prediction(margin=0.0, p_home=0.45, total=120.0, games_played=4.0), game)
    assert betsFor(prediction(margin=0.0, p_home=0.45, total=120.0, games_played=5.0), game)


def test_college_code_has_no_key_literal_and_no_bet_log_writer():
    for path in (ROOT / 'college_basketball').rglob('*.py'):
        text = path.read_text()
        assert 'logRecommendations' not in text and '_bets.csv' not in text
        assert not [line for line in text.splitlines() if 'api_key =' in line and "'" in line]


def test_stakes_use_capped_fractional_kelly_in_whole_dollars():
    assert kellyFraction(0.55, -110, 0.2, 0.05) == pytest.approx(0.0110, abs=0.0001)
    assert kellyFraction(0.90, -110, 0.2, 0.05) == 0.05
    assert kellyFraction(0.50, -110, 0.2, 0.05) == 0
    assert wholeDollarStake(0.05, 50, 1) == 2
    assert wholeDollarStake(0.011, 50, 1) == 1
    assert wholeDollarStake(0.005, 50, 1) == 0


def test_college_bets_carry_stakes_and_small_bankrolls_drop_them():
    game = oddsGame('Siena Saints', 'Princeton Tigers')
    pairs, _ = matchLines(prediction(margin=0.0, p_home=0.45), parseOdds([game], ['betmgm']))
    bets = recommend(pairs, 11.5, 16.5, bankroll=50)
    assert bets and all(b['stake'] == 2 for b in bets)
    assert not recommend(pairs, 11.5, 16.5, bankroll=5)


def test_new_bankroll_ignores_log_rows_before_its_start_date():
    logs = pd.DataFrame([
        {'result': 'L', 'bet_amount': 10, 'potential_profit': 9, 'timestamp': '2026-01-10 14:50:30'},
        {'result': 'W', 'bet_amount': 2, 'potential_profit': 1.82, 'timestamp': '2026-11-09 10:00:00'},
        {'result': 'L', 'bet_amount': 1, 'potential_profit': 0.91, 'timestamp': '2026-11-10 10:00:00'},
        {'result': None, 'bet_amount': 5, 'potential_profit': 4, 'timestamp': '2026-11-10 11:00:00'},
    ])
    assert bankrollFromLogs(50, [logs], '2026-11-08') == pytest.approx(50.82)
    assert bankrollFromLogs(50, [logs]) == pytest.approx(40.82)


def test_nba_config_and_real_logs_start_from_fifty_dollars():
    # Load by path: hockey has a module with the same name on sys.path.
    spec = importlib.util.spec_from_file_location('nba_betting_config', ROOT / 'basketball/betting/betting_config.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    NbaConfig = module.BettingConfig
    logs = [pd.read_csv(ROOT.parent / 'logs/basketball/betting' / f) for f in ('h2h_bets.csv', 'spread_bets.csv', 'total_bets.csv')]
    assert NbaConfig.STARTING_BANKROLL == 50
    # Rows from before the start date stay as history and must not move the $50. Real bets since then do count.
    start = pd.Timestamp(NbaConfig.BANKROLL_START_DATE)
    history = [log[pd.to_datetime(log['timestamp'], errors='coerce') < start] for log in logs]
    assert sum(log['result'].isin(['W', 'L']).sum() for log in history) > 0
    assert bankrollFromLogs(NbaConfig.STARTING_BANKROLL, history, NbaConfig.BANKROLL_START_DATE) == 50
