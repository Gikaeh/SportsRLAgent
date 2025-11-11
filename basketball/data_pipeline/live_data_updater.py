from data_pipeline.basketball_data import BasketballData
from data_pipeline.prepare_data import NBATrainingDataPreparer
from model.model_h2h import BasketballH2HModel
from model.model_spread import BasketballSpreadModel
from model.model_total import BasketballTotalModel
import pandas as pd
from pathlib import Path

class LiveDataUpdater:
    def __init__(self, data_dir='././data/basketball'):
        self.basketball_data = BasketballData()
        self.preparer = NBATrainingDataPreparer(data_dir=data_dir)
        self.data_dir = Path(data_dir)
        self.current_season = self.preparer.getCurrentSeason()
        self.total_model = BasketballTotalModel()
        self.h2h_model = BasketballH2HModel()
        self.spread_model = BasketballSpreadModel()
    
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
        leakage_cols = ['game_id', 'date', 'season', 'home_team', 'away_team',]
        
        if model_type == 'h2h':
            leakage_cols = leakage_cols + self.h2h_model.getLeakageColumns()
        elif model_type == 'spread':
            leakage_cols =  leakage_cols + self.spread_model.getLeakageColumns()
        elif model_type == 'total':
            leakage_cols = leakage_cols + self.total_model.getLeakageColumns()
        elif model_type == 'all':
            leakage_cols_h2h = leakage_cols + self.h2h_model.getLeakageColumns()
            leakage_cols_spread = leakage_cols + self.spread_model.getLeakageColumns()
            leakage_cols_total = leakage_cols + self.total_model.getLeakageColumns()
            
            prediction_data_h2h = game_features.drop(columns=[col for col in leakage_cols_h2h if col in game_features.columns])
            prediction_data_spread = game_features.drop(columns=[col for col in leakage_cols_spread if col in game_features.columns])
            prediction_data_total = game_features.drop(columns=[col for col in leakage_cols_total if col in game_features.columns])

            return prediction_data_h2h, prediction_data_spread, prediction_data_total, game_info
        
        prediction_data = game_features.drop(columns=[col for col in leakage_cols if col in game_features.columns])        
        return prediction_data, game_info