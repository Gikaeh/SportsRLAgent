from data_pipeline.hockey_data import HockeyData
from data_pipeline.prepare_data import NHLTrainingDataPreparer
# from data_pipeline.injury_data import HockeyInjuryData
from model.model_h2h import HockeyH2HModel
from model.model_spread import HockeySpreadModel
from model.model_total import HockeyTotalModel
import pandas as pd
from pathlib import Path

class HockeyLiveDataUpdater:
    def __init__(self, data_dir='././data/hockey'):
        self.hockey_data = HockeyData(data_dir=data_dir)
        self.preparer = NHLTrainingDataPreparer(data_dir=data_dir)
        # self.injury_data = HockeyInjuryData(data_dir=data_dir)
        self.data_dir = Path(data_dir)
        self.current_season = self.preparer.getCurrentSeason()
        self.total_model = HockeyTotalModel()
        self.h2h_model = HockeyH2HModel()
        self.spread_model = HockeySpreadModel()
    
    def fetchTodaysGames(self):
        """Fetch today's NHL games"""
        print(f"\n{'='*60}")
        print(f"Fetching upcoming NHL games")
        print(f"{'='*60}")
        
        games_df = self.hockey_data.getUpcomingGames()
        
        if games_df.empty:
            print("No games scheduled for today.")
            return pd.DataFrame()
        
        return games_df
    
    def updateCurrentSeasonData(self):
        """Update data for the current season"""
        print(f"\n{'='*60}")
        print(f"Updating data for season {self.current_season}")
        print(f"{'='*60}")
        
        try:
            season_year = int(self.current_season[:4])
            
            # Update game data
            self.hockey_data.scrape_season_games(season_year)
            
            # Update player data
            self.hockey_data.scrape_season_player_data(season_year)
            
            # Update team data
            self.hockey_data.scrape_season_team_data(season_year)
            
            print(f"\nSuccessfully updated season {self.current_season} data")
            return True
            
        except Exception as e:
            print(f"Error updating season data: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    # def updateInjuryData(self):
    #     """Update injury data from ESPN"""
    #     print(f"\n{'='*60}")
    #     print("Updating injury data from ESPN")
    #     print(f"{'='*60}")
        
    #     success = self.injury_data.fetchInjuriesFromESPN()
        
    #     if success:
    #         # Try to match player IDs
    #         print("\nMatching player IDs...")
    #         self.injury_data.matchPlayerIDs()
        
    #     return success
    
    # def getInjuryReport(self):
    #     """Get formatted injury report"""
    #     return self.injury_data.getInjuryReport()
    
    def getFullUpdate(self):
        """Perform a full data update: injuries, season data, and today's games"""
        print(f"\n{'='*80}")
        print("STARTING FULL HOCKEY DATA UPDATE")
        print(f"{'='*80}")
        
        # Update injuries
        # self.updateInjuryData()
        
        # Update current season data
        self.updateCurrentSeasonData()
        
        # Get today's games
        todays_games = self.fetchTodaysGames()
        
        print(f"\n{'='*80}")
        print("FULL UPDATE COMPLETE")
        print(f"{'='*80}")
        
        if not todays_games.empty:
            print(f"\nToday's games ({len(todays_games)}):")
            for _, game in todays_games.iterrows():
                print(f"  {game['AWAY_TEAM']} @ {game['HOME_TEAM']}")
        
        # Print injury report
        # print(self.getInjuryReport())
        
        return todays_games
    
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
        # print(f"\n{'='*60}")
        # print("Updating injury data from ESPN")
        # print(f"{'='*60}")
        # self.injury_data.fetchInjuriesFromESPN()
        # self.injury_data.matchPlayerIDs()
        
        season_year = int(self.current_season[:4])
        self.hockey_data.scrapeSeasonGames(season_year)
        self.hockey_data.scrapeSeasonData(season_year)
        
        todays_games = self.fetchTodaysGames()
        
        if todays_games.empty:
            print("No games scheduled for today.")
            return pd.DataFrame(), pd.DataFrame()
        
        game_features = self.prepareGameFeatures()
        
        if game_features.empty:
            print("No features available for upcoming games.")
            return pd.DataFrame(), pd.DataFrame()
        
        game_info = game_features[['game_id', 'date', 'home_team', 'away_team']].copy()
        
        # Injury features are for display/confidence adjustment only, not model input
        # (no historical injury data available for training)
        # injury_cols = [
        #     'home_points_lost', 'home_goals_lost', 'home_assists_lost', 'home_toi_lost',
        #     'home_num_injured', 'home_star_out', 'home_rotation_out', 'home_injury_severity',
        #     'away_points_lost', 'away_goals_lost', 'away_assists_lost', 'away_toi_lost',
        #     'away_num_injured', 'away_star_out', 'away_rotation_out', 'away_injury_severity',
        #     'injury_advantage'
        # ]
        leakage_cols = ['game_id', 'date', 'season', 'home_team', 'away_team']# + injury_cols
        
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
