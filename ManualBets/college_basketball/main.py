"""College basketball menu. Recommendations are printed only; a human places every bet."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from college_basketball.betting.betting_config import BettingConfig
from college_basketball.betting.betting_recommender import matchLines, parseOdds, recommend
from college_basketball.data_pipeline.odd_scraping import fetchCollegeOdds
from college_basketball.data_pipeline.prepare_data import buildMatchups, trainingRows, upcomingRows
from college_basketball.data_pipeline.warehouse_loader import loadCollegeData
from college_basketball.model.model_college import fitModels, loadModels, predictGames, saveModels

PREDICTION_DAYS = 2


def loadMatchups():
    print("Reading the DeepSports warehouse (read-only)...")
    return buildMatchups(*loadCollegeData())


def trainModels():
    rows = trainingRows(loadMatchups())
    models, features, residual_std = fitModels(rows)
    saveModels(models, features, residual_std, rows)
    print(f"Trained on {len(rows)} D1 games through {rows['start_time'].max()}; residual std {residual_std}")


def upcomingPredictions():
    models, metadata = loadModels()
    now = pd.Timestamp.now('UTC').tz_localize(None)
    rows = upcomingRows(loadMatchups(), now)
    rows = rows[rows['start_time'] < now + pd.Timedelta(days=PREDICTION_DAYS)]
    return predictGames(models, metadata['features'], rows), metadata


def showPredictions():
    predictions, _ = upcomingPredictions()
    for game in predictions.itertuples():
        print(f"{game.start_time:%m-%d %H:%M} UTC {game.away_abbr} @ {game.home_abbr}: "
              f"home win {game.p_home_win:.1%}, margin {game.pred_home_margin:+.1f}, total {game.pred_total:.1f}, "
              f"fewest games played {game.min_games_played:.0f}")


def askBankroll():
    """College bets aren't logged, so the owner supplies the current balance."""
    try:
        answer = input(f"Current bankroll [${BettingConfig.STARTING_BANKROLL}]: ").strip().lstrip('$')
    except EOFError:
        answer = ''
    return float(answer) if answer else float(BettingConfig.STARTING_BANKROLL)


def showRecommendations():
    bankroll = askBankroll()
    predictions, metadata = upcomingPredictions()
    games, remaining = fetchCollegeOdds(BettingConfig.BOOKS)
    pairs, unmatched = matchLines(predictions, parseOdds(games, BettingConfig.BOOKS))
    sigma = metadata.get('residual_std', {})
    bets = recommend(pairs, sigma.get('spread', BettingConfig.SPREAD_RESIDUAL_SIGMA_FALLBACK),
                     sigma.get('total', BettingConfig.TOTAL_RESIDUAL_SIGMA_FALLBACK), bankroll)
    withheld = sum(pred.min_games_played < BettingConfig.MIN_GAMES_PLAYED for pred, _ in pairs)
    print(f"Lines matched for {len(pairs)} (unmatched {len(unmatched)}); {withheld} withheld, under "
          f"{BettingConfig.MIN_GAMES_PLAYED} games played; Odds API requests remaining: {remaining}")
    if not bets:
        print("No bets clear the rules.")
    for bet in bets:
        print(f"{bet['start_time']:%m-%d %H:%M} UTC {bet['matchup']}: ${bet['stake']} on {bet['bet']} ({bet['odds']:+d}, {bet['book']}) "
              f"model {bet['model_probability']:.1%}; {bet['detail']}")
    print("These are suggestions from a model with no proven edge. Nothing was logged or placed.")


TASKS = [('Retrain models', trainModels), ('Show predictions', showPredictions),
         ('Show recommendations (costs 3 Odds API credits)', showRecommendations)]


def main():
    print("0. Exit")
    for number, (label, _) in enumerate(TASKS, 1):
        print(f"{number}. {label}")
    print(f"{len(TASKS) + 1}. Run all")
    choice = int(input("Choice: "))
    if 1 <= choice <= len(TASKS):
        TASKS[choice - 1][1]()
    elif choice == len(TASKS) + 1:
        for _, task in TASKS:
            task()


if __name__ == '__main__':
    main()
