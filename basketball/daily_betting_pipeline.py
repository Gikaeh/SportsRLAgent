"""
Daily Betting Pipeline - Orchestrates the complete daily workflow
Run this script daily to get betting recommendations
"""
import sys
from datetime import datetime
from pathlib import Path
import argparse

from data_pipeline.live_data_updater import LiveDataUpdater
from betting_recommender import BettingRecommender
from model_retrainer import ModelRetrainer
from betting_config import BettingConfig

class DailyBettingPipeline:
    def __init__(self, config=None):
        self.config = config or BettingConfig()
        self.updater = LiveDataUpdater()
        self.recommender = BettingRecommender(config=self.config)
        self.retrainer = ModelRetrainer()
        
        # Create necessary directories
        Path(self.config.LOG_DIR).mkdir(parents=True, exist_ok=True)
    
    def run_morning_update(self):
        """
        Morning workflow (10:00 AM):
        - Check for model retraining needs
        - Fetch today's games
        - Generate preliminary predictions
        """
        print("\n" + "="*80)
        print(f"🌅 MORNING UPDATE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        
        # Step 1: Check if model needs retraining
        print("\n📊 Step 1: Checking model status...")
        retrain_result = self.retrainer.auto_retrain_if_needed()
        
        if retrain_result.get('success'):
            print(f"✅ Model retrained successfully (v{retrain_result['model_version']})")
            # Reload model in recommender
            self.recommender = BettingRecommender(config=self.config)
        elif retrain_result.get('skipped'):
            print(f"⏭️  Model retrain skipped: {retrain_result['reason']}")
        
        # Step 2: Fetch today's games
        print("\n🏀 Step 2: Fetching today's games...")
        prediction_data, game_info = self.updater.get_prediction_ready_data()
        
        if prediction_data.empty:
            print("ℹ️  No games scheduled for today")
            return None
        
        # Step 3: Generate predictions
        print("\n🎯 Step 3: Generating predictions...")
        predictions = self.recommender.predict_games(prediction_data, game_info)
        
        print("\n" + "="*80)
        print("PRELIMINARY PREDICTIONS")
        print("="*80)
        for _, game in predictions.iterrows():
            print(f"\n{game['away_team']} @ {game['home_team']}")
            print(f"  Predicted Winner: {game['predicted_winner']}")
            print(f"  Home Win Prob: {game['home_win_prob']:.1%}")
            print(f"  Away Win Prob: {game['away_win_prob']:.1%}")
            print(f"  Confidence: {game['confidence']:.1%}")
        
        # Log predictions
        self.recommender.log_predictions(predictions)
        
        return predictions
    
    def run_afternoon_update(self, odds_data=None):
        """
        Afternoon workflow (2:00 PM):
        - Update with latest injury news (future enhancement)
        - Collect updated odds
        - Generate betting recommendations
        """
        print("\n" + "="*80)
        print(f"☀️ AFTERNOON UPDATE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        
        # Step 1: Fetch today's games with latest data
        print("\n🏀 Step 1: Fetching latest game data...")
        prediction_data, game_info = self.updater.get_prediction_ready_data()
        
        if prediction_data.empty:
            print("ℹ️  No games scheduled for today")
            return None
        
        # Step 2: Generate predictions
        print("\n🎯 Step 2: Generating predictions...")
        predictions = self.recommender.predict_games(prediction_data, game_info)
        
        # Step 3: Make betting recommendations
        print("\n💰 Step 3: Analyzing betting opportunities...")
        recommendations = self.recommender.make_betting_recommendations(predictions, odds_data)
        
        # Display recommendations
        self.recommender.display_recommendations(recommendations)
        
        # Log everything
        self.recommender.log_predictions(predictions)
        self.recommender.log_recommendations(recommendations)
        
        return recommendations
    
    def run_pregame_update(self, odds_data=None):
        """
        Pre-game workflow (5:00 PM):
        - Final injury/lineup check (future enhancement)
        - Get closing odds
        - Final betting recommendations
        """
        print("\n" + "="*80)
        print(f"🌆 PRE-GAME UPDATE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        
        # Step 1: Fetch today's games
        print("\n🏀 Step 1: Fetching final game data...")
        prediction_data, game_info = self.updater.get_prediction_ready_data()
        
        if prediction_data.empty:
            print("ℹ️  No games scheduled for today")
            return None
        
        # Step 2: Generate final predictions
        print("\n🎯 Step 2: Generating final predictions...")
        predictions = self.recommender.predict_games(prediction_data, game_info)
        
        # Step 3: Make final betting recommendations
        print("\n💰 Step 3: Final betting recommendations...")
        recommendations = self.recommender.make_betting_recommendations(predictions, odds_data)
        
        # Display recommendations
        self.recommender.display_recommendations(recommendations)
        
        # Log everything
        self.recommender.log_predictions(predictions)
        self.recommender.log_recommendations(recommendations)
        
        return recommendations
    
    def run_postgame_update(self):
        """
        Post-game workflow (11:00 PM):
        - Collect game results
        - Update performance tracking
        - Prepare for next day
        """
        print("\n" + "="*80)
        print(f"🌙 POST-GAME UPDATE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        
        # Step 1: Update results
        print("\n📈 Step 1: Updating game results...")
        self.updater.update_results()
        
        # Step 2: Reset daily limits
        print("\n🔄 Step 2: Resetting daily limits...")
        self.recommender.reset_daily_limits()
        
        print("\n✅ Post-game update complete")
    
    def run_full_day_pipeline(self, odds_data=None):
        """
        Run complete daily pipeline (for testing or manual execution)
        """
        print("\n" + "="*80)
        print(f"🚀 FULL DAY PIPELINE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        
        # Morning
        morning_predictions = self.run_morning_update()
        
        if morning_predictions is not None:
            # Afternoon
            print("\n" + "="*80)
            input("Press Enter to continue to afternoon update...")
            afternoon_recs = self.run_afternoon_update(odds_data)
            
            # Pre-game
            print("\n" + "="*80)
            input("Press Enter to continue to pre-game update...")
            pregame_recs = self.run_pregame_update(odds_data)
            
            return {
                'morning_predictions': morning_predictions,
                'afternoon_recommendations': afternoon_recs,
                'pregame_recommendations': pregame_recs
            }
        else:
            print("\nNo games today - pipeline complete")
            return None


def main():
    parser = argparse.ArgumentParser(description='Daily NBA Betting Pipeline')
    parser.add_argument(
        '--mode',
        choices=['morning', 'afternoon', 'pregame', 'postgame', 'full'],
        default='full',
        help='Pipeline mode to run'
    )
    parser.add_argument(
        '--force-retrain',
        action='store_true',
        help='Force model retraining'
    )
    
    args = parser.parse_args()
    
    # Initialize pipeline
    pipeline = DailyBettingPipeline()
    
    # Force retrain if requested
    if args.force_retrain:
        print("\n🔄 FORCING MODEL RETRAIN")
        pipeline.retrainer.auto_retrain_if_needed(force=True)
        pipeline.recommender = BettingRecommender()
    
    # Run appropriate mode
    if args.mode == 'morning':
        pipeline.run_morning_update()
    elif args.mode == 'afternoon':
        pipeline.run_afternoon_update()
    elif args.mode == 'pregame':
        pipeline.run_pregame_update()
    elif args.mode == 'postgame':
        pipeline.run_postgame_update()
    elif args.mode == 'full':
        pipeline.run_full_day_pipeline()


if __name__ == "__main__":
    main()
