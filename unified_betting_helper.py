"""
Helper script to get betting recommendations from a specific sport.
This runs in isolation to avoid import conflicts.
"""
import sys
import json
from pathlib import Path

def get_sport_recommendations(sport, model_types=['h2h', 'spread', 'total']):
    """Get recommendations for a specific sport"""
    recommendations = []
    
    if sport == 'basketball':
        sys.path.insert(0, str(Path(__file__).parent / 'basketball'))
        from basketball.data_pipeline.live_data_updater import LiveDataUpdater
        from basketball.betting.betting_recommender import BettingRecommender
        
        updater = LiveDataUpdater()
        
        try:
            prediction_data_h2h, prediction_data_spread, prediction_data_total, game_info = updater.getPredictionReadyData(model_type='all')
            
            if prediction_data_h2h.empty:
                return []
            
            # H2H
            if 'h2h' in model_types:
                try:
                    recommender = BettingRecommender(model_path='./models/basketball_h2h_model.json')
                    predictions = recommender.predictGames(prediction_data_h2h, game_info)
                    recs = recommender.makeBettingRecommendations(predictions=predictions)
                    for rec in recs:
                        rec['sport'] = 'basketball'
                    recommendations.extend(recs)
                except Exception as e:
                    print(f"Error getting basketball H2H: {e}")
            
            # Spread
            if 'spread' in model_types:
                try:
                    recommender = BettingRecommender(model_path='./models/basketball_spread_model.json')
                    predictions = recommender.predictGames(prediction_data_spread, game_info)
                    recs = recommender.makeBettingRecommendations(predictions=predictions)
                    for rec in recs:
                        rec['sport'] = 'basketball'
                    recommendations.extend(recs)
                except Exception as e:
                    print(f"Error getting basketball spread: {e}")
                    
        except Exception as e:
            print(f"Error fetching basketball data: {e}")
            import traceback
            traceback.print_exc()
    
    elif sport == 'hockey':
        sys.path.insert(0, str(Path(__file__).parent / 'hockey'))
        from hockey.data_pipeline.live_data_updater import HockeyLiveDataUpdater
        from hockey.betting.betting_recommender import BettingRecommender
        
        updater = HockeyLiveDataUpdater()
        
        try:
            prediction_data_h2h, prediction_data_spread, prediction_data_total, game_info = updater.getPredictionReadyData(model_type='all')
            
            if prediction_data_h2h.empty:
                return []
            
            # H2H
            if 'h2h' in model_types:
                try:
                    recommender = BettingRecommender(model_path='./models/hockey_h2h_model.json')
                    predictions = recommender.predictGames(prediction_data_h2h, game_info)
                    recs = recommender.makeBettingRecommendations(predictions=predictions)
                    for rec in recs:
                        rec['sport'] = 'hockey'
                    recommendations.extend(recs)
                except Exception as e:
                    print(f"Error getting hockey H2H: {e}")
            
            # Spread
            if 'spread' in model_types:
                try:
                    recommender = BettingRecommender(model_path='./models/hockey_spread_model.json')
                    predictions = recommender.predictGames(prediction_data_spread, game_info)
                    recs = recommender.makeBettingRecommendations(predictions=predictions)
                    for rec in recs:
                        rec['sport'] = 'hockey'
                    recommendations.extend(recs)
                except Exception as e:
                    print(f"Error getting hockey spread: {e}")
            
            # Total
            if 'total' in model_types:
                try:
                    recommender = BettingRecommender(model_path='./models/hockey_total_model.json')
                    predictions = recommender.predictGames(prediction_data_total, game_info)
                    recs = recommender.makeBettingRecommendations(predictions=predictions)
                    for rec in recs:
                        rec['sport'] = 'hockey'
                    recommendations.extend(recs)
                except Exception as e:
                    print(f"Error getting hockey total: {e}")
                    
        except Exception as e:
            print(f"Error fetching hockey data: {e}")
            import traceback
            traceback.print_exc()
    
    return recommendations

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python unified_betting_helper.py <sport>")
        sys.exit(1)
    
    sport = sys.argv[1]
    recommendations = get_sport_recommendations(sport)
    
    # Convert datetime objects to strings for JSON serialization
    for rec in recommendations:
        if 'date' in rec:
            rec['date'] = str(rec['date'])
        if 'timestamp' in rec:
            rec['timestamp'] = str(rec['timestamp'])
    
    print(json.dumps(recommendations, default=str))
