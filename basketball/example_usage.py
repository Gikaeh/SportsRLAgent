"""
Example Usage - Demonstrates how to use the betting system
"""
from data_pipeline.live_data_updater import LiveDataUpdater
from betting_recommender import BettingRecommender
from model_retrainer import ModelRetrainer
from betting_config import BettingConfig
import pandas as pd

def example_1_get_todays_predictions():
    """
    Example 1: Get predictions for today's games
    """
    print("\n" + "="*80)
    print("EXAMPLE 1: Get Today's Predictions")
    print("="*80)
    
    # Initialize
    updater = LiveDataUpdater()
    recommender = BettingRecommender()
    
    # Get today's games with features
    prediction_data, game_info = updater.getPredictionReadyData()
    print(prediction_data)
    print(game_info)
    
    if prediction_data.empty:
        print("No games today")
        return
    
    # Generate predictions
    predictions = recommender.predict_games(prediction_data, game_info)
    
    # Display
    print("\nToday's Games:")
    for _, game in predictions.iterrows():
        print(f"\n{game['away_team']} @ {game['home_team']}")
        print(f"  Predicted Winner: {game['predicted_winner']}")
        print(f"  Home Win Probability: {game['home_win_prob']:.1%}")
        print(f"  Away Win Probability: {game['away_win_prob']:.1%}")
        print(f"  Confidence: {game['confidence']:.1%}")


def example_2_betting_recommendations():
    """
    Example 2: Get betting recommendations with default odds
    """
    print("\n" + "="*80)
    print("EXAMPLE 2: Betting Recommendations")
    print("="*80)
    
    # Initialize
    updater = LiveDataUpdater()
    recommender = BettingRecommender()
    
    # Get data and predictions
    prediction_data, game_info = updater.getPredictionReadyData()
    
    if prediction_data.empty:
        print("No games today")
        return
    
    predictions = recommender.predict_games(prediction_data, game_info)
    
    # Make recommendations (using default -110 odds)
    recommendations = recommender.make_betting_recommendations(predictions)
    
    # Display
    recommender.display_recommendations(recommendations)

def example_5_model_retraining():
    """
    Example 5: Check and retrain model
    """
    print("\n" + "="*80)
    print("EXAMPLE 5: Model Retraining")
    print("="*80)
    
    retrainer = ModelRetrainer()
    
    # Check current status
    retrainer.getRetrainingStatus()
    
    # Check if retrain needed
    should_retrain, reason = retrainer.checkIfRetrainNeeded()
    print(f"\nShould retrain: {should_retrain}")
    print(f"Reason: {reason}")
    
    if should_retrain:
        result = retrainer.retrainModel()
        
        if result['success']:
            print(f"\nRetraining successful!")
            print(f"   Model Version: {result['model_version']}")
            print(f"   Validation Accuracy: {result['val_accuracy']:.4f}")
            print(f"   Test Accuracy: {result['test_accuracy']:.4f}")
            print(f"   Games Trained: {result['games_trained']}")


def main():
    print("\n" + "="*80)
    print("NBA BETTING SYSTEM - USAGE EXAMPLES")
    print("="*80)
    print("\nThis script demonstrates various ways to use the betting system.")
    print("Choose an example to run:\n")
    
    examples = [
        ("Get Today's Predictions", example_1_get_todays_predictions),
        ("Betting Recommendations (Default Odds)", example_2_betting_recommendations),
        ("Model Retraining", example_5_model_retraining),
    ]
    
    for i, (name, _) in enumerate(examples, 1):
        print(f"{i}. {name}")
    
    print(f"{len(examples) + 1}. Run All Examples")
    print("0. Exit")
    
    choice = input("\nEnter your choice: ")
    
    try:
        choice = int(choice)
        if choice == 0:
            print("Exiting...")
            return
        elif choice == len(examples) + 1:
            # Run all examples
            for name, func in examples:
                print("\n" + "="*80)
                input(f"Press Enter to run: {name}")
                func()
        elif 1 <= choice <= len(examples):
            examples[choice - 1][1]()
        else:
            print("Invalid choice")
    except ValueError:
        print("Invalid input")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
