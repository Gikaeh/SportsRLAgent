from data_pipeline.live_data_updater import LiveDataUpdater
from betting.betting_recommender import BettingRecommender
from betting.betting_config import BettingConfig
from model.model_retrainer import ModelRetrainer
from data_pipeline.basketball_data import BasketballData
from pathlib import Path

def main():
    print("\n" + "="*80)
    print("NBA BETTING SYSTEM")
    print("="*80)
    print("Choose an option to run:\n")
    
    options = [
        ("Betting Recommendations", bettingRecommendations),
        ("Betting Update", bettingUpdate),
        ("Active Bets", activeBets),
        ("Model Retraining", modelRetraining),
    ]
    
    for i, (name, _) in enumerate(options, 1):
        print(f"{i}. {name}")
    
    print("0. Exit")
    
    choice = input("\nEnter your choice: ")
    
    try:
        choice = int(choice)
        if choice == 0:
            print("Exiting...")
            return
        elif choice == len(options) + 1:
            for name, func in options:
                print("\n" + "="*80)
                input(f"Press Enter to run: {name}")
                func()
        elif 1 <= choice <= len(options):
            options[choice - 1][1]()
        else:
            print("Invalid choice")
    except ValueError:
        print("Invalid input")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

def bettingRecommendations():
    print("\n" + "="*80)
    print("Betting Recommendations")
    print("="*80)

    updater = LiveDataUpdater()

    print("\nChoose an option to run: ")
    print("1. H2H (paused: negative live record, see docs/DECISIONS.md 2026-11-20)")
    print("2. Spread")
    # print("3. Total")
    print("3. All enabled markets")

    choice = input("\nEnter your choice: ")

    enabled = set(BettingConfig.ENABLED_MARKETS)

    if choice == '1':
        print("\nWARNING: h2h is paused from the daily run (23 graded bets, 11-12, -$15.47).")
        prediction_data, game_info = updater.getPredictionReadyData(model_type='h2h')

        if prediction_data.empty:
            print("No games today")
            return

        recommender = BettingRecommender(model_path = './models/basketball_h2h_model.json')

        predictions = recommender.predictGames(prediction_data, game_info)

        recommendations = recommender.makeBettingRecommendations(predictions=predictions)
    elif choice == '2':
        prediction_data, game_info = updater.getPredictionReadyData(model_type='spread')

        if prediction_data.empty:
            print("No games today")
            return

        recommender = BettingRecommender(model_path = './models/basketball_spread_model.json')

        predictions = recommender.predictGames(prediction_data, game_info)

        recommendations = recommender.makeBettingRecommendations(predictions=predictions)
    # elif choice == '3':
    #     prediction_data, game_info = updater.getPredictionReadyData(model_type='total')

    #     if prediction_data.empty:
    #         print("No games today")
    #         return

    #     recommender = BettingRecommender(model_path = './models/basketball_total_model.json')

    #     predictions = recommender.predictGames(prediction_data, game_info)

    #     recommendations = recommender.makeBettingRecommendations(predictions=predictions)
    elif choice == '3':
        prediction_data_h2h, prediction_data_spread, prediction_data_total, game_info = updater.getPredictionReadyData(model_type='all')

        if prediction_data_spread.empty:
            print("No games today")
            return

        recommendations = []

        if 'h2h' in enabled:
            recommender = BettingRecommender(model_path = './models/basketball_h2h_model.json')
            predictions = recommender.predictGames(prediction_data_h2h, game_info)
            recommendations += recommender.makeBettingRecommendations(predictions=predictions)
        else:
            print("h2h skipped (paused in BettingConfig.ENABLED_MARKETS)")

        if 'spread' in enabled:
            recommender = BettingRecommender(model_path = './models/basketball_spread_model.json')
            predictions = recommender.predictGames(prediction_data_spread, game_info)
            recommendations += recommender.makeBettingRecommendations(predictions=predictions)
        else:
            print("spread skipped (not in BettingConfig.ENABLED_MARKETS)")

        # recommender = BettingRecommender(model_path = './models/basketball_total_model.json')
        # predictions = recommender.predictGames(prediction_data_total, game_info)
        # recommendations_total = recommender.makeBettingRecommendations(predictions=predictions)

        if not recommendations:
            print("\nNo recommendations from the enabled markets.")
            return
    else:
        print("Invalid choice")
        return

    recommender.displayRecommendations(recommendations)

def modelRetraining():
    print("\n" + "="*80)
    print("Model Retraining")
    print("="*80)
    
    for model_path in Path('./models').glob('basketball_*.json'):
        model_type = model_path.stem.split('_')[1]
        retrainer = ModelRetrainer(model_type=model_type, model_path=model_path, metadata_path=model_path.parent / f'metadata/basketball/retraining_{model_type}_metadata.json')
        
        retrainer.getRetrainingStatus()
        
        should_retrain, reason = retrainer.checkIfRetrainNeeded()
        print(f"\nShould retrain: {should_retrain}")
        print(f"Reason: {reason}")
        
        if should_retrain:
            is_success, result = retrainer.retrainModel()
            
            if is_success:
                print(f"\nRetraining successful!")
                print(f"   Model Version: {result['model_version']}")
                print(f"   Games Trained: {result['total_games_trained']}")
            else:
                print(f"\nRetraining failed!")
                print(f"   Reason: {result['reason']}")


def bettingUpdate():
    print("\n" + "="*80)
    print("Betting Update")
    print("="*80)
    basketball_data = BasketballData()
    current_season = basketball_data.getCurrentSeason()
    basketball_data.getSeasonGames(season=current_season)
    recommender = BettingRecommender(model_path = './models/basketball_h2h_model.json')

    archive = input("Archive? (y/n): ")
    if archive == 'y':
        current = recommender.setBankroll(archive=True)
        print(f"Current Bankroll: ${current:,.2f}")
        recommender.displayModelWinRate(archive=True)
    else:
        print(f"Current Bankroll: ${recommender.getCurrentBankroll():,.2f}")
        recommender.displayModelWinRate()

def activeBets():
    print("\n" + "="*80)
    print("Active Bets")
    print("="*80)    
    
    recommender = BettingRecommender(model_path = './models/basketball_h2h_model.json')
    activeBets = recommender.getActiveBets()
    print(activeBets)
    recommender.displayRecommendations(activeBets)
    
    print(f"Current Bankroll: ${recommender.getCurrentBankroll():,.2f}")    

if __name__ == "__main__":
    main()
