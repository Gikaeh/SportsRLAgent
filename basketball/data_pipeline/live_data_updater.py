from data_pipeline.basketball_data import BasketballData
from data_pipeline.prepare_data import NBATrainingDataPreparer
import pandas as pd
from pathlib import Path

class LiveDataUpdater:
    def __init__(self, data_dir='././data/basketball'):
        self.basketball_data = BasketballData()
        self.preparer = NBATrainingDataPreparer(data_dir=data_dir)
        self.data_dir = Path(data_dir)
        self.current_season = self.preparer.getCurrentSeason()
    
    def fetchTodaysGames(self):
        print(f"\n{'='*60}")
        print(f"Fetching upcoming games")
        print(f"{'='*60}")
        
        games_df = self.basketball_data.getUpcomingGames()
        games_df['GAME_DATE'] = pd.to_datetime(games_df['GAME_DATE'])
        
        if games_df.empty:
            print("No games scheduled for today.")
            return pd.DataFrame()
        
        return games_df
    
    def prepareGameFeatures(self):
        print(f"\n{'='*60}")
        print("Preparing features for prediction")
        print(f"{'='*60}")
        
        try:
            matchup_data = self.preparer.createUpcomingMatchupData()
            
            if matchup_data.empty:
                print("No feature data available for upcoming games.")
                return pd.DataFrame()
            
            print(f"\nPrepared features for {len(matchup_data)} games")
            return matchup_data
            
        except Exception as e:
            print(f"Error preparing features: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()
    
    def getPredictionReadyData(self, model_type):
        self.basketball_data.getAllSeasonData(season=self.current_season)
        todays_games = self.fetchTodaysGames()
        
        if todays_games.empty:
            return pd.DataFrame(), pd.DataFrame()
        
        game_features = self.prepareGameFeatures()
        
        if game_features.empty:
            print("No features available for upcoming games.")
            return pd.DataFrame(), pd.DataFrame()
        
        game_info = game_features[['game_id', 'date', 'home_team', 'away_team']].copy()
        
        if model_type == 'h2h':
            leakage_cols = [
                'game_id', 'date', 'season', 'home_team', 'away_team', 
                'home_ppg_l10', 'away_ppg_l10', 'home_blk_l10', 'away_blk_l10', 
                'home_stl_l10', 'away_stl_l10', 'home_fg_pct_l10', 'away_fg_pct_l10', 
                'home_fg3_pct_l10', 'away_fg3_pct_l10', 'ppg_diff', 'opp_ppg_diff'
            ]
        elif model_type == 'spread':
            leakage_cols =  [
                'game_id', 'date', 'season', 'home_team', 'away_team',
                'home_blk_l10', 'away_blk_l10', 'home_stl_l10', 'away_stl_l10', 
                'home_fg_pct_l10', 'away_fg_pct_l10', 'home_fg3_pct_l10', 'away_fg3_pct_l10'
            ]
        elif model_type == 'all':
            leakage_cols_h2h = [
                'game_id', 'date', 'season', 'home_team', 'away_team', 
                'home_ppg_l10', 'away_ppg_l10', 'home_blk_l10', 'away_blk_l10', 
                'home_stl_l10', 'away_stl_l10', 'home_fg_pct_l10', 'away_fg_pct_l10', 
                'home_fg3_pct_l10', 'away_fg3_pct_l10', 'ppg_diff', 'opp_ppg_diff'
            ]
            leakage_cols_spread = [
                'game_id', 'date', 'season', 'home_team', 'away_team',
                'home_blk_l10', 'away_blk_l10', 'home_stl_l10', 'away_stl_l10', 
                'home_fg_pct_l10', 'away_fg_pct_l10', 'home_fg3_pct_l10', 'away_fg3_pct_l10'
            ]
            prediction_data_h2h = game_features.drop(columns=[col for col in leakage_cols_h2h if col in game_features.columns])
            prediction_data_spread = game_features.drop(columns=[col for col in leakage_cols_spread if col in game_features.columns])

            return prediction_data_h2h, prediction_data_spread, game_info
        
        prediction_data = game_features.drop(columns=[col for col in leakage_cols if col in game_features.columns])
        return prediction_data, game_info