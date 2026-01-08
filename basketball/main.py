from operator import is_
from data_pipeline.live_data_updater import LiveDataUpdater
from betting.betting_recommender import BettingRecommender
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
    print("1. H2H")
    print("2. Spread")
    # print("3. Total")
    print("3. All")
    
    choice = input("\nEnter your choice: ")
    
    if choice == '1':
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

        if prediction_data_h2h.empty:
            print("No games today")
            return

        recommender = BettingRecommender(model_path = './models/basketball_h2h_model.json')
        predictions = recommender.predictGames(prediction_data_h2h, game_info)
        recommendations_h2h = recommender.makeBettingRecommendations(predictions=predictions)
        
        recommender = BettingRecommender(model_path = './models/basketball_spread_model.json')
        predictions = recommender.predictGames(prediction_data_spread, game_info)
        recommendations_spread = recommender.makeBettingRecommendations(predictions=predictions)
        
        # recommender = BettingRecommender(model_path = './models/basketball_total_model.json')
        # predictions = recommender.predictGames(prediction_data_total, game_info)
        # recommendations_total = recommender.makeBettingRecommendations(predictions=predictions)
        
        recommendations = recommendations_h2h + recommendations_spread #+ recommendations_total
    else:
        print("Invalid choice")
        return
    
    recommender.displayRecommendations(recommendations)

def modelRetraining():
    print("\n" + "="*80)
    print("Model Retraining")
    print("="*80)
    
    for model_path in Path('./models').glob('*.json'):
        retrainer = ModelRetrainer(model_path=model_path)
        
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
    BasketballData().getSeasonGames(season='2025-26')
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
