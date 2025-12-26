from hockey.data_pipeline.hockey_data import HockeyData
from hockey.data_pipeline.injury_data import HockeyInjuryData
import pandas as pd
from pathlib import Path

class HockeyLiveDataUpdater:
    def __init__(self, data_dir='././data/hockey'):
        self.hockey_data = HockeyData(data_dir=data_dir)
        self.injury_data = HockeyInjuryData(data_dir=data_dir)
        self.data_dir = Path(data_dir)
        self.current_season = self.hockey_data.getCurrentSeason()
    
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
    
    def updateInjuryData(self):
        """Update injury data from ESPN"""
        print(f"\n{'='*60}")
        print("Updating injury data from ESPN")
        print(f"{'='*60}")
        
        success = self.injury_data.fetchInjuriesFromESPN()
        
        if success:
            # Try to match player IDs
            print("\nMatching player IDs...")
            self.injury_data.matchPlayerIDs()
        
        return success
    
    def getInjuryReport(self):
        """Get formatted injury report"""
        return self.injury_data.getInjuryReport()
    
    def getFullUpdate(self):
        """Perform a full data update: injuries, season data, and today's games"""
        print(f"\n{'='*80}")
        print("STARTING FULL HOCKEY DATA UPDATE")
        print(f"{'='*80}")
        
        # Update injuries
        self.updateInjuryData()
        
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
        print(self.getInjuryReport())
        
        return todays_games
    
    def getPredictionReadyData(self):
        """Get data ready for predictions (similar to basketball pipeline)"""
        print(f"\n{'='*60}")
        print("Preparing prediction-ready data")
        print(f"{'='*60}")
        
        # Update injuries
        self.updateInjuryData()
        
        # Update current season data
        season_year = int(self.current_season[:4])
        self.hockey_data.scrape_season_games(season_year)
        self.hockey_data.scrape_season_player_data(season_year)
        self.hockey_data.scrape_season_team_data(season_year)
        
        # Get today's games
        todays_games = self.fetchTodaysGames()
        
        if todays_games.empty:
            print("No games scheduled for today.")
            return pd.DataFrame(), pd.DataFrame()
        
        # For now, return the games info
        # In the future, this would prepare features for ML models
        game_info = todays_games[['GAME_ID', 'GAME_DATE', 'HOME_TEAM', 'AWAY_TEAM']].copy()
        
        print(f"\nPrepared data for {len(game_info)} games")
        
        return todays_games, game_info
