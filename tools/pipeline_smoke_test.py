"""Pipeline smoke test: train a fresh H2H model in memory (no Optuna, no
save) on data before the upcoming slate, then predict the games in
upcoming_games.csv.

Purpose: verify the fetch -> prepare -> train -> predict pipeline runs end to
end and that the prediction feature matrix lines up with the training matrix.
Nothing under models/ is written; the model exists only in this process.

This is a wiring check, NOT a performance backtest. The live prediction path
(`createUpcomingMatchupData`) builds team features from each team's MOST RECENT
stats, so for games whose date is already in the past the features are not
strictly point-in-time. For genuinely future games that is correct.

Usage:
    .venv\\Scripts\\python.exe tools\\pipeline_smoke_test.py
    .venv\\Scripts\\python.exe tools\\pipeline_smoke_test.py data\\basketball\\upcoming_games.csv
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'basketball'))

from data_pipeline.prepare_data import NBATrainingDataPreparer
from model.model_h2h import BasketballH2HModel
from shared.splitting import chronologicalSplit


def seasonForDate(date):
    """Same rule as NBATrainingDataPreparer.getCurrentSeason, but for an
    arbitrary date (the upcoming slate may not belong to today's season)."""
    if date.month < 7:
        return f"{date.year - 1}-{str(date.year)[-2:]}"
    return f"{date.year}-{str(date.year + 1)[-2:]}"


def trainFreshModel(training_data):
    train_data, val_data, _ = chronologicalSplit(training_data, date_col='date', test_frac=0.2, val_frac_of_test=0.5)

    model = BasketballH2HModel()
    leakage_cols = model.getLeakageColumns()

    def splitXY(df):
        df = df.drop(columns=[c for c in leakage_cols if c in df.columns])
        return df.drop('home_won', axis=1), df['home_won']

    X_train, y_train = splitXY(train_data)
    X_val, y_val = splitXY(val_data)
    print(f"Train: {len(X_train)} games ({train_data['date'].min().date()} -> {train_data['date'].max().date()})")
    print(f"Val:   {len(X_val)} games ({val_data['date'].min().date()} -> {val_data['date'].max().date()})")
    
    print("Training (no Optuna, no save)...")
    model.train(X_train, y_train, X_val, y_val, verbose=50)
    return model, X_train


def main():
    upcoming_file = (Path(sys.argv[1]).resolve() if len(sys.argv) > 1
                     else ROOT / 'data/basketball/upcoming_games.csv')
    if not upcoming_file.exists():
        print(f"Upcoming games file not found: {upcoming_file}")
        return 1

    upcoming = pd.read_csv(upcoming_file)
    upcoming['GAME_DATE'] = pd.to_datetime(upcoming['GAME_DATE'])
    cutoff = upcoming['GAME_DATE'].min()
    if cutoff.tz is not None:
        cutoff = cutoff.tz_localize(None)
    season = seasonForDate(cutoff)
    print("=" * 70)
    print(f"Upcoming slate: {len(upcoming)} games from {upcoming_file.name}")
    print(f"Earliest game: {cutoff.date()}  ->  season {season}")
    print("=" * 70)

    preparer = NBATrainingDataPreparer(data_dir=str(ROOT / 'data/basketball'))

    print("\nPreparing training data...")
    training_data = preparer.prepareAllSeasons(output_dir=str(ROOT / 'data/training_data/basketball'))
    if training_data is None or training_data.empty:
        print("No training data available")
        return 1
    training_data['date'] = pd.to_datetime(training_data['date'])
    if getattr(training_data['date'].dt, 'tz', None) is not None:
        training_data['date'] = training_data['date'].dt.tz_localize(None)

    # Point-in-time training: never train on games on/after the slate.
    training_data = training_data[training_data['date'] < cutoff]
    print(f"Games strictly before cutoff: {len(training_data)}")
    if len(training_data) < 50:
        print("Not enough training data before the cutoff")
        return 1

    model, X_train = trainFreshModel(training_data)

    print("\n" + "=" * 70)
    print("PREDICTING UPCOMING GAMES")
    print("=" * 70)
    # Pin the season so feature prep reads data matching the slate (today's
    # calendar season may have no fetched data yet).
    preparer.getCurrentSeason = lambda: season
    prediction_data = preparer.createUpcomingMatchupData(upcoming_games_file=upcoming_file)
    if prediction_data is None or prediction_data.empty:
        print("No prediction rows built from the upcoming games")
        return 1

    game_info = prediction_data[['game_id', 'date', 'home_team', 'away_team']].copy()
    leakage_cols = model.getLeakageColumns()
    X_pred = prediction_data.drop(columns=[c for c in leakage_cols if c in prediction_data.columns])

    missing = [c for c in X_train.columns if c not in X_pred.columns]
    extra = [c for c in X_pred.columns if c not in X_train.columns]
    if missing or extra:
        print("FEATURE MISMATCH between training and prediction:")
        print(f"  missing from prediction: {missing}")
        print(f"  extra in prediction:     {extra}")
        return 1
    X_pred = X_pred[X_train.columns]

    probs = model.predictProb(X_pred)[:, 1]
    if np.isnan(probs).any():
        print(f"Predicted probabilities contain NaN ({int(np.isnan(probs).sum())} rows)")
        return 1

    game_info['home_win_prob'] = probs
    game_info['away_win_prob'] = 1 - probs
    game_info['pick'] = np.where(probs > 0.5, game_info['home_team'], game_info['away_team'])
    game_info['confidence'] = np.abs(probs - 0.5) * 2

    pd.set_option('display.width', 200)
    pd.set_option('display.max_columns', 20)
    print(game_info.to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    print("\n" + "=" * 70)
    print(f"PIPELINE OK - trained on {len(X_train)} games, predicted {len(game_info)} games")
    print("Model was NOT saved; production models/ untouched.")
    print("=" * 70)
    return 0


if __name__ == '__main__':
    sys.exit(main())
