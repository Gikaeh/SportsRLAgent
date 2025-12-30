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
        from basketball.data_pipeline.injury_data import InjuryData
        from basketball.data_pipeline.prepare_data import NBATrainingDataPreparer
        
        updater = LiveDataUpdater()
        injury_data = InjuryData()
        preparer = NBATrainingDataPreparer()
        
        # Get latest player stats for injury summary
        try:
            latest_player_stats = preparer.precomputePlayerRollingAverages(preparer.getCurrentSeason())
            latest_player_stats = latest_player_stats.sort_values('GAME_DATE').groupby('PLAYER_ID').last().reset_index()
        except:
            latest_player_stats = None
        
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
                        # Add injury summary
                        if latest_player_stats is not None:
                            matchup_parts = rec['matchup'].split(' @ ')
                            if len(matchup_parts) == 2:
                                away_team, home_team = matchup_parts
                                rec['injury_summary'] = injury_data.getInjurySummaryForGame(home_team, away_team, latest_player_stats)
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
                        # Add injury summary
                        if latest_player_stats is not None:
                            matchup_parts = rec['matchup'].split(' @ ')
                            if len(matchup_parts) == 2:
                                away_team, home_team = matchup_parts
                                rec['injury_summary'] = injury_data.getInjurySummaryForGame(home_team, away_team, latest_player_stats)
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
        from hockey.data_pipeline.injury_data import HockeyInjuryData
        from hockey.data_pipeline.prepare_data import NHLTrainingDataPreparer
        
        updater = HockeyLiveDataUpdater()
        injury_data = HockeyInjuryData()
        preparer = NHLTrainingDataPreparer()
        
        # Get latest skater stats for injury summary
        try:
            skater_df, _ = preparer.precomputePlayerRollingAverages(preparer.getCurrentSeason())
            latest_skater_stats = skater_df.sort_values('GAME_DATE').groupby('PLAYER_ID').last().reset_index()
        except:
            latest_skater_stats = None
        
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
                        # Add injury summary
                        if latest_skater_stats is not None:
                            matchup_parts = rec['matchup'].split(' @ ')
                            if len(matchup_parts) == 2:
                                away_team, home_team = matchup_parts
                                rec['injury_summary'] = injury_data.getInjurySummaryForGame(home_team, away_team, latest_skater_stats)
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
                        # Add injury summary
                        if latest_skater_stats is not None:
                            matchup_parts = rec['matchup'].split(' @ ')
                            if len(matchup_parts) == 2:
                                away_team, home_team = matchup_parts
                                rec['injury_summary'] = injury_data.getInjurySummaryForGame(home_team, away_team, latest_skater_stats)
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
                        # Add injury summary
                        if latest_skater_stats is not None:
                            matchup_parts = rec['matchup'].split(' @ ')
                            if len(matchup_parts) == 2:
                                away_team, home_team = matchup_parts
                                rec['injury_summary'] = injury_data.getInjurySummaryForGame(home_team, away_team, latest_skater_stats)
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
