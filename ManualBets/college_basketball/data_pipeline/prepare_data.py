"""Pre-game features for college basketball.

One builder serves training and live prediction: a scheduled game is just a row
with no result yet, so the two paths cannot drift apart.

Every rolling value is taken from completed games strictly before the row. There
are no betting lines and no fetch-time rank columns (basketball/NOTES.md A6).

College-specific choices:
- Rolling form runs across seasons, and `games_this_season` and last season's
  ratings are features, so the model can learn how far to trust a 1-2 game sample.
- Non-D1 games feed team history, but only D1-vs-D1 games are trained on.
"""
from collections import deque

import numpy as np
import pandas as pd

ROLLING_STATS = ['pts', 'opp_pts', 'margin', 'game_total', 'off_eff', 'def_eff', 'poss',
                 'efg', 'tov_rate', 'oreb_rate', 'ft_rate', 'fg3a_rate', 'won', 'adj_margin',
                 'opp_strength']
WINDOWS = (5, 10)
PRIOR_SEASON_STATS = ['margin', 'off_eff', 'def_eff', 'poss', 'won']
MAX_REST_DAYS = 14
TOP_PLAYERS = 6
PLAYER_WINDOW = 10
ROSTER_LOOKBACK_GAMES = 15

META_COLUMNS = [
    'game_id', 'start_time', 'season_year', 'season_type', 'state', 'completed',
    'home_team_id', 'away_team_id', 'home_score', 'away_score', 'home_abbr', 'away_abbr',
    'home_name', 'away_name', 'home_listed', 'away_listed', 'point_diff', 'total_score',
    'home_won',
]


def _safeDivide(a, b):
    return a / b.where(b != 0)


def buildTeamGameFrame(games, team_stats):
    """One row per team per game, with box-score rates for completed games."""
    shared = ['game_id', 'season_year', 'start_time', 'completed']
    home = games[shared + ['home_team_id', 'away_team_id', 'home_score', 'away_score']].rename(
        columns={'home_team_id': 'team_id', 'away_team_id': 'opp_id',
                 'home_score': 'pts', 'away_score': 'opp_pts'})
    away = games[shared + ['home_team_id', 'away_team_id', 'home_score', 'away_score']].rename(
        columns={'away_team_id': 'team_id', 'home_team_id': 'opp_id',
                 'away_score': 'pts', 'home_score': 'opp_pts'})
    frame = pd.concat([home, away], ignore_index=True)
    frame[['pts', 'opp_pts']] = frame[['pts', 'opp_pts']].astype(float)

    own = team_stats.rename(columns={c: f'{c}_own' for c in team_stats.columns
                                     if c not in ('game_id', 'team_id')})
    opp = team_stats.rename(columns={c: f'{c}_opp' for c in team_stats.columns
                                     if c not in ('game_id', 'team_id')}).rename(
        columns={'team_id': 'opp_id'})
    frame = frame.merge(own, on=['game_id', 'team_id'], how='left')
    frame = frame.merge(opp, on=['game_id', 'opp_id'], how='left')

    frame['margin'] = frame['pts'] - frame['opp_pts']
    frame['game_total'] = frame['pts'] + frame['opp_pts']
    frame['won'] = np.where(frame['margin'].isna(), np.nan, (frame['margin'] > 0).astype(float))
    own_poss = frame['fga_own'] - frame['oreb_own'] + frame['tov_own'] + 0.475 * frame['fta_own']
    opp_poss = frame['fga_opp'] - frame['oreb_opp'] + frame['tov_opp'] + 0.475 * frame['fta_opp']
    frame['poss'] = (own_poss + opp_poss) / 2
    frame['off_eff'] = 100 * _safeDivide(frame['pts'], frame['poss'])
    frame['def_eff'] = 100 * _safeDivide(frame['opp_pts'], frame['poss'])
    frame['efg'] = _safeDivide(frame['fgm_own'] + 0.5 * frame['fg3m_own'], frame['fga_own'])
    frame['tov_rate'] = _safeDivide(frame['tov_own'], own_poss)
    frame['oreb_rate'] = _safeDivide(frame['oreb_own'], frame['oreb_own'] + frame['dreb_opp'])
    frame['ft_rate'] = _safeDivide(frame['fta_own'], frame['fga_own'])
    frame['fg3a_rate'] = _safeDivide(frame['fg3a_own'], frame['fga_own'])
    keep = shared + ['team_id', 'opp_id', 'pts', 'opp_pts', 'margin', 'game_total', 'won', 'poss',
                     'off_eff', 'def_eff', 'efg', 'tov_rate', 'oreb_rate', 'ft_rate', 'fg3a_rate']
    return frame[keep].sort_values(['team_id', 'start_time', 'game_id']).reset_index(drop=True)


def _pregame(values, completed, transform):
    """transform() over completed games only, then each row sees the latest value
    from before it. A scheduled row sees everything completed so far."""
    done = values[completed]
    return transform(done).reindex(values.index).ffill().shift(1)


def addOpponentStrength(frame):
    """Opponent's pre-game season margin, with last season's as the fallback.
    adj_margin rewards results against strong opponents."""
    frame = frame.copy()
    frame['completed'] = frame['completed'].astype(bool)
    season_margin = frame.groupby(['team_id', 'season_year'], group_keys=False).apply(
        lambda g: _pregame(g['margin'], g['completed'],
                           lambda s: s.expanding(min_periods=1).mean()), include_groups=False)
    prior = (frame[frame['completed']].groupby(['team_id', 'season_year'])['margin'].mean()
             .rename('prior_margin').reset_index())
    prior['season_year'] += 1
    strength = frame[['game_id', 'team_id', 'season_year']].assign(season_margin=season_margin)
    strength = strength.merge(prior, on=['team_id', 'season_year'], how='left')
    strength['strength'] = strength['season_margin'].fillna(strength['prior_margin'])
    lookup = strength[['game_id', 'team_id', 'strength']].rename(
        columns={'team_id': 'opp_id', 'strength': 'opp_strength'})
    frame = frame.merge(lookup, on=['game_id', 'opp_id'], how='left')
    frame['adj_margin'] = frame['margin'] + frame['opp_strength']
    return frame.sort_values(['team_id', 'start_time', 'game_id']).reset_index(drop=True)


def addRollingFeatures(frame):
    frame = frame.copy()
    new = {}
    by_team = frame.groupby('team_id', sort=False)
    by_season = frame.groupby(['team_id', 'season_year'], sort=False)
    for stat in ROLLING_STATS:
        for window in WINDOWS:
            new[f'{stat}_l{window}'] = pd.concat(
                [_pregame(g[stat], g['completed'],
                          lambda s, w=window: s.rolling(w, min_periods=1).mean())
                 for _, g in by_team]).reindex(frame.index)
        new[f'{stat}_season'] = pd.concat(
            [_pregame(g[stat], g['completed'], lambda s: s.expanding(min_periods=1).mean())
             for _, g in by_season]).reindex(frame.index)
    frame = pd.concat([frame, pd.DataFrame(new, index=frame.index)], axis=1)

    frame['games_this_season'] = (frame['completed'].astype(int)
                                  .groupby([frame['team_id'], frame['season_year']])
                                  .transform(lambda s: s.cumsum().shift(1).fillna(0)))
    previous = by_team['start_time'].shift(1)
    rest = (frame['start_time'] - previous).dt.total_seconds() / 86400
    frame['rest_days'] = rest.clip(upper=MAX_REST_DAYS).fillna(MAX_REST_DAYS)
    frame['back_to_back'] = (frame['rest_days'] < 1.5).astype(int)

    prior = (frame[frame['completed']].groupby(['team_id', 'season_year'])[PRIOR_SEASON_STATS].mean()
             .add_prefix('prior_').reset_index())
    prior['season_year'] += 1
    return frame.merge(prior, on=['team_id', 'season_year'], how='left')


def addPlayerFeatures(frame, player_stats):
    """Top players chosen by pre-game rolling minutes, never by minutes in this game."""
    columns = ['top6_mpg', 'top6_ppg', 'top3_ppg', 'top6_plus_minus', 'top6_missed_last']
    frame = frame.sort_values(['team_id', 'start_time', 'game_id']).reset_index(drop=True)
    boxes = {key: rows for key, rows in player_stats.groupby(['game_id', 'team_id'])}
    out = np.full((len(frame), len(columns)), np.nan)

    for _, group in frame.groupby(['team_id', 'season_year'], sort=False):
        history = {}
        last_seen = {}
        team_game = 0
        last_players = set()
        for row in group.itertuples():
            active = [p for p, seen in last_seen.items() if team_game - seen <= ROSTER_LOOKBACK_GAMES]
            if active:
                ranked = sorted(active, key=lambda p: (-np.mean(history[p]['min']), p))
                top = ranked[:TOP_PLAYERS]
                out[row.Index] = [
                    np.mean([np.mean(history[p]['min']) for p in top]),
                    np.mean([np.mean(history[p]['pts']) for p in top]),
                    np.mean([np.mean(history[p]['pts']) for p in top[:3]]),
                    np.nansum([np.nanmean(history[p]['pm']) if np.isfinite(history[p]['pm']).any() else 0
                               for p in top]),
                    sum(p not in last_players for p in top) / len(top),
                ]
            box = boxes.get((row.game_id, row.team_id))
            if row.completed and box is not None:
                team_game += 1
                last_players = set(box['athlete_id'])
                for player in box.itertuples():
                    h = history.setdefault(player.athlete_id, {
                        'min': deque(maxlen=PLAYER_WINDOW),
                        'pts': deque(maxlen=PLAYER_WINDOW),
                        'pm': deque(maxlen=PLAYER_WINDOW)})
                    h['min'].append(float(player.minutes))
                    h['pts'].append(float(player.pts) if pd.notna(player.pts) else 0.0)
                    h['pm'].append(float(player.plus_minus) if pd.notna(player.plus_minus) else np.nan)
                    last_seen[player.athlete_id] = team_game
    return pd.concat([frame, pd.DataFrame(out, columns=columns, index=frame.index)], axis=1)


def buildMatchups(games, team_stats, player_stats):
    """One row per game: META_COLUMNS, then home_*, away_* and diff_* pre-game features."""
    games = games.copy()
    games['start_time'] = pd.to_datetime(games['start_time'])
    frame = buildTeamGameFrame(games, team_stats)
    frame = addOpponentStrength(frame)
    frame = addRollingFeatures(frame)
    frame = addPlayerFeatures(frame, player_stats)

    outcomes = {'pts', 'opp_pts', 'margin', 'game_total', 'won', 'poss', 'off_eff', 'def_eff', 'efg',
                'tov_rate', 'oreb_rate', 'ft_rate', 'fg3a_rate', 'adj_margin', 'opp_strength',
                'season_year', 'start_time', 'completed', 'opp_id'}
    features = [c for c in frame.columns if c not in outcomes | {'game_id', 'team_id'}]
    side = frame[['game_id', 'team_id'] + features]

    base = games.merge(side.rename(columns={'team_id': 'home_team_id',
                                            **{c: f'home_{c}' for c in features}}),
                       on=['game_id', 'home_team_id'], how='left')
    base = base.merge(side.rename(columns={'team_id': 'away_team_id',
                                           **{c: f'away_{c}' for c in features}}),
                      on=['game_id', 'away_team_id'], how='left')
    diffs = {f'diff_{c}': base[f'home_{c}'] - base[f'away_{c}'] for c in features}
    base = pd.concat([base, pd.DataFrame(diffs, index=base.index)], axis=1)

    base['neutral_site'] = base['neutral_site'].fillna(False).astype(int)
    base['is_postseason'] = (base['season_type'] == 3).astype(int)
    base['min_games_played'] = base[['home_games_this_season', 'away_games_this_season']].min(axis=1)
    base['home_score'] = base['home_score'].astype(float)
    base['away_score'] = base['away_score'].astype(float)
    base['point_diff'] = base['home_score'] - base['away_score']
    base['total_score'] = base['home_score'] + base['away_score']
    base['home_won'] = np.where(base['point_diff'].isna(), np.nan, (base['point_diff'] > 0).astype(float))
    return base.sort_values(['start_time', 'game_id']).reset_index(drop=True)


def featureColumns(matchups):
    return [c for c in matchups.columns if c not in META_COLUMNS]


def trainingRows(matchups):
    """Completed D1-vs-D1 games with a real result (no ties in the data)."""
    keep = (matchups['completed'].astype(bool) & matchups['home_listed'].astype(bool)
            & matchups['away_listed'].astype(bool) & matchups['point_diff'].notna())
    return matchups[keep].reset_index(drop=True)


def upcomingRows(matchups, now):
    """Games that have not started, D1 vs D1, so the model never scores untrained matchups."""
    keep = ((matchups['state'] == 'pre') & (matchups['start_time'] > now)
            & matchups['home_listed'].astype(bool) & matchups['away_listed'].astype(bool))
    return matchups[keep].reset_index(drop=True)
