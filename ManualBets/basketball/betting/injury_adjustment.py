"""Prediction-time injury adjustment.

The spread model was trained on participation: core availability (`missed_last3/5`,
`days_since`) and lost production (`core_minutes_lost_last3`, `core_ppg_lost_last3`).
At prediction time we know the upcoming game's injury report, which the model never
saw for historical games. This module turns the status into an expected participation
probability and recomputes the 3/5-game window with the upcoming game included.

Mapping (NOTES.md: no hand-tuned point adjustment; this is a probability on a feature
the model already learned):

    OUT 0.0 | DOUBTFUL 0.25 | QUESTIONABLE 0.5 | PROBABLE 0.9 | otherwise 1.0

Training is untouched. The adjustment runs only on the live feature frame.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_pipeline.injury_data import InjuryData  # noqa: E402

STATUS_PLAY_PROB = {
    'OUT': 0.0,
    'DOUBTFUL': 0.25,
    'QUESTIONABLE': 0.5,
    'PROBABLE': 0.9,
    'ACTIVE': 1.0,
}

ADJUSTED = (
    'core_missed_last3', 'core_missed_last5',
    'core_minutes_lost_last3', 'core_ppg_lost_last3',
)


def playProbability(status, injuryData, mode='prior'):
    if not status:
        return 1.0
    normalized = injuryData._mapInjuryStatus(str(status))
    if mode == 'binary':
        return 0.0 if normalized == 'OUT' else 1.0
    return STATUS_PLAY_PROB.get(normalized, 1.0)


def loadInjuries(preparer, refresh=True):
    """Return (InjuryData, current injury frame); refresh once per prediction run."""
    data_dir = getattr(preparer, 'data_dir', None) or '././data/basketball'
    injuryData = InjuryData(data_dir=str(data_dir))
    if refresh:
        try:
            injuryData.refreshFromEspnFeed()
        except Exception as exc:
            print(f'Injury refresh failed ({type(exc).__name__}: {exc}); using the saved snapshot')
    return injuryData, injuryData._loadInjuries()


def injurySummary(injury_frame, team, injuryData, max_players=6):
    if injury_frame is None or injury_frame.empty:
        return ''
    rows = injury_frame[injury_frame['team_abbreviation'] == team]
    if rows.empty:
        return ''
    parts = []
    for _, row in rows.head(max_players).iterrows():
        parts.append(f"{row['player_name']} {injuryData._mapInjuryStatus(str(row['status']))}")
    return '; '.join(parts)


def logForwardPredictions(frame, predictions, injuryData, injuries, model_version, path):
    """Append one row per game per arm to the forward comparison log."""
    from datetime import datetime
    now = datetime.now().isoformat(timespec='seconds')
    rows = []
    work = frame.reset_index(drop=True)
    for i, row in work.iterrows():
        home = row.get('home_team')
        away = row.get('away_team')
        home_inj = injurySummary(injuries, home, injuryData)
        away_inj = injurySummary(injuries, away, injuryData)
        for arm, values in predictions.items():
            rows.append({
                'created_at': now,
                'game_id': row.get('game_id'),
                'date': str(row.get('date')),
                'home_team': home,
                'away_team': away,
                'arm': arm,
                'predicted_margin': round(float(values[i]), 3),
                'model_version': model_version,
                'home_injuries': home_inj,
                'away_injuries': away_inj,
            })
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, mode='a', header=not path.exists(), index=False)


def injuryLookup(injury_frame, injuryData, team):
    if injury_frame is None or injury_frame.empty:
        return {}, {}
    rows = injury_frame[injury_frame['team_abbreviation'] == team]
    by_id, by_name = {}, {}
    for _, row in rows.iterrows():
        status = row.get('status')
        try:
            pid = int(row.get('player_id') or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid:
            by_id[pid] = status
        name = row.get('player_name')
        if isinstance(name, str) and name.strip():
            by_name[injuryData._normalizePlayerName(name)] = status
    return by_id, by_name


def adjustPredictionFrame(frame, preparer, season, injury_frame=None,
                          player_df=None, top_n=5, log=True, refresh=True,
                          mode='prior'):
    """Recompute the core availability features with the upcoming game's report.

    The 3-game window becomes the last 2 completed games plus the upcoming game,
    whose participation is the status probability. The 5-game window uses the last
    4. A player already out for the last 3 games therefore keeps the same value;
    a newly ruled-out player gets a fractional expected miss.
    """
    if frame is None or frame.empty:
        return frame
    if mode == 'none':
        return frame
    data_dir = getattr(preparer, 'data_dir', None) or '././data/basketball'
    injuryData = InjuryData(data_dir=str(data_dir))
    if injury_frame is None:
        if refresh:
            try:
                injuryData.refreshFromEspnFeed()
            except Exception as exc:
                print(f'Injury refresh failed ({type(exc).__name__}: {exc}); using the saved snapshot')
        injury_frame = injuryData._loadInjuries()
    if injury_frame is None or injury_frame.empty:
        if log:
            print('Injury adjustment: no current_injuries.csv; features unchanged')
        return frame
    if player_df is None:
        player_df = preparer.precomputePlayerRollingAverages(season)
    if player_df is None or player_df.empty:
        return frame

    out = frame.copy()
    # Counts can arrive as int64; the adjustment is fractional.
    for side in ('home', 'away'):
        for name in ADJUSTED:
            column = f'{side}_{name}'
            if column in out.columns:
                out[column] = out[column].astype(float)
    adjusted = []
    for idx, row in out.iterrows():
        game_date = pd.to_datetime(row['date'])
        if getattr(game_date, 'tzinfo', None) is not None:
            game_date = game_date.tz_localize(None)
        for side in ('home', 'away'):
            team = row[f'{side}_team']
            by_id, by_name = injuryLookup(injury_frame, injuryData, team)
            if not by_id and not by_name:
                continue
            team_games = preparer.teamGameDates(player_df, game_date, team)
            last2, last4 = team_games[-2:], team_games[-4:]
            core = preparer.getTopPlayersAsOf(player_df, game_date, team, top_n=top_n)
            if core.empty:
                continue
            before = player_df[
                (player_df['TEAM_ABBREVIATION'] == team) & (player_df['GAME_DATE'] < game_date)
            ]

            missed3 = missed5 = minutes_lost = ppg_lost = 0.0
            for _, player in core.iterrows():
                pid = player['PLAYER_ID']
                name = player.get('PLAYER_NAME')
                status = by_id.get(pid) or by_name.get(
                    injuryData._normalizePlayerName(name) if isinstance(name, str) else '')
                p_play = playProbability(status, injuryData, mode)
                played = set(before[before['PLAYER_ID'] == pid]['GAME_DATE'])
                missed2 = sum(d not in played for d in last2)
                missed4 = sum(d not in played for d in last4)
                expected3 = missed2 + (1.0 - p_play)
                expected5 = missed4 + (1.0 - p_play)
                missed3 += expected3
                missed5 += expected5
                minutes_lost += float(player['mpg_rolling']) * expected3
                ppg_lost += float(player['ppg_rolling']) * expected3
                if p_play < 1.0:
                    adjusted.append(f"{team} {name} {status} ({p_play:.0%})")

            out.at[idx, f'{side}_core_missed_last3'] = round(missed3, 3)
            out.at[idx, f'{side}_core_missed_last5'] = round(missed5, 3)
            out.at[idx, f'{side}_core_minutes_lost_last3'] = round(minutes_lost, 3)
            out.at[idx, f'{side}_core_ppg_lost_last3'] = round(ppg_lost, 3)

    if log:
        if adjusted:
            print('Injury adjustment: ' + '; '.join(adjusted))
        else:
            print('Injury adjustment: no listed core players')
    return out
