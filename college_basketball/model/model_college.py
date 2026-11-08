"""XGBoost models for college h2h, spread (home margin) and total."""
import json
from pathlib import Path

import numpy as np
import xgboost as xgb

from college_basketball.data_pipeline.prepare_data import featureColumns

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / 'models'
METADATA_DIR = MODEL_DIR / 'metadata' / 'college_basketball'
TARGETS = {'h2h': 'home_won', 'spread': 'point_diff', 'total': 'total_score'}

# Chosen on 2024-25 only, before the 2025-26 holdout was scored (docs/DECISIONS.md).
DEFAULT_PARAMS = {'learning_rate': 0.03, 'max_depth': 3, 'subsample': 0.7,
                  'colsample_bytree': 0.5, 'min_child_weight': 10}


def makeModel(bet_type, params=None):
    settings = {'tree_method': 'hist', 'n_estimators': 2000, 'early_stopping_rounds': 50,
                'random_state': 42, 'n_jobs': -1, **(params or DEFAULT_PARAMS)}
    if bet_type == 'h2h':
        return xgb.XGBClassifier(objective='binary:logistic', eval_metric='logloss', **settings)
    return xgb.XGBRegressor(objective='reg:absoluteerror', eval_metric='mae', **settings)


def fitModels(training_rows, params=None, validation_frac=0.1):
    """Fit all three on the given rows; the latest validation_frac is the early-stopping
    set. Returns (models, feature list, validation residual std per bet type)."""
    features = featureColumns(training_rows)
    ordered = training_rows.sort_values('start_time')
    cut = int(len(ordered) * (1 - validation_frac))
    train, val = ordered.iloc[:cut], ordered.iloc[cut:]
    models, residual_std = {}, {}
    for bet_type, target in TARGETS.items():
        model = makeModel(bet_type, params)
        model.fit(train[features], train[target], eval_set=[(val[features], val[target])], verbose=False)
        models[bet_type] = model
        if bet_type != 'h2h':
            residual_std[bet_type] = float(np.std(val[target] - model.predict(val[features])))
    return models, features, residual_std


def predictGames(models, features, rows):
    """Adds p_home_win, pred_home_margin and pred_total; a missing column is an error."""
    missing = [c for c in features if c not in rows.columns]
    if missing:
        raise ValueError(f"Prediction rows are missing training features: {missing[:10]}")
    X = rows[features]
    out = rows.copy()
    out['p_home_win'] = models['h2h'].predict_proba(X)[:, 1]
    out['pred_home_margin'] = models['spread'].predict(X)
    out['pred_total'] = models['total'].predict(X)
    return out


def saveModels(models, features, residual_std, training_rows, model_dir=MODEL_DIR, metadata_dir=METADATA_DIR):
    model_dir, metadata_dir = Path(model_dir), Path(metadata_dir)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    for bet_type, model in models.items():
        model.save_model(model_dir / f'college_basketball_{bet_type}_model.json')
    (metadata_dir / 'training_metadata.json').write_text(json.dumps({
        'features': features,
        'residual_std': residual_std,
        'games_trained': len(training_rows),
        'trained_through': str(training_rows['start_time'].max()),
    }, indent=2))


def loadModels(model_dir=MODEL_DIR, metadata_dir=METADATA_DIR):
    model_dir, metadata_dir = Path(model_dir), Path(metadata_dir)
    metadata = json.loads((metadata_dir / 'training_metadata.json').read_text())
    models = {}
    for bet_type in TARGETS:
        model = makeModel(bet_type)
        model.load_model(model_dir / f'college_basketball_{bet_type}_model.json')
        models[bet_type] = model
    return models, metadata
