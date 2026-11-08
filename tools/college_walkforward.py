"""Walk-forward test of the college models: refit monthly on earlier games, predict the month.

Usage:
    .venv/bin/python tools/college_walkforward.py --start 2024-11-01 --end 2025-04-15 --out preds.csv
    (add --params '{"learning_rate": 0.3, "max_depth": 6}' to test settings; tuning uses 2024-25 only)
Set COLLEGE_WAREHOUSE_DB to read a warehouse copy. Writes only to --out.
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from college_basketball.data_pipeline.prepare_data import buildMatchups, trainingRows
from college_basketball.data_pipeline.warehouse_loader import loadCollegeData
from college_basketball.model.model_college import fitModels, predictGames


def walkForward(rows, start, end, params=None, log=print):
    results = []
    for month in pd.period_range(start, end - pd.Timedelta(days=1), freq='M'):
        lo, hi = max(month.start_time, start), min(month.end_time, end)
        test = rows[(rows['start_time'] >= lo) & (rows['start_time'] <= hi)]
        if test.empty:
            continue
        train = rows[rows['start_time'] < month.start_time]
        models, features, _ = fitModels(train, params)
        assert train['start_time'].max() < test['start_time'].min()
        preds = predictGames(models, features, test)
        trees = {k: m.best_iteration for k, m in models.items()}
        log(f"{month}: train {len(train)} test {len(test)} trees {trees}")
        results.append(preds[['game_id', 'start_time', 'season_year', 'home_abbr', 'away_abbr',
                              'min_games_played', 'neutral_site', 'home_score', 'away_score',
                              'p_home_win', 'pred_home_margin', 'pred_total']])
    return pd.concat(results, ignore_index=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--params', help='JSON xgboost settings; default is the frozen DEFAULT_PARAMS')
    args = ap.parse_args()
    rows = trainingRows(buildMatchups(*loadCollegeData()))
    preds = walkForward(rows, pd.Timestamp(args.start), pd.Timestamp(args.end),
                        json.loads(args.params) if args.params else None)
    preds.to_csv(args.out, index=False)
    print(f"{len(preds)} games -> {args.out}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
