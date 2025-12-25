import requests
import pandas as pd
from pathlib import Path
from tqdm import tqdm
import time
from datetime import datetime, timedelta
import json

class HockeyData:
    def __init__(self, data_dir='././data/hockey'):
        self.data_dir = Path(data_dir)
        
        # Using NHL API (the old stats API is deprecated/down)
        self.base_api = "https://api-web.nhle.com/v1"
        
        # Track existing files (like basketball_data does)
        self.game_files = [f.stem.replace('_game_stats', '') for f in (self.data_dir / 'game_data').glob('*_game_stats.csv')]
        self.team_files = [f.stem.replace('_team_stats', '') for f in (self.data_dir / 'team_data').glob('*_team_stats.csv')]
        self.player_files = [f.stem.replace('_player_stats', '') for f in (self.data_dir / 'player_data').glob('*_player_stats.csv')]

        # NHL team IDs (for stats API)
        self.team_ids = {
            'ANA': 24, 'ARI': 53, 'BOS': 6, 'BUF': 7, 'CGY': 20, 'CAR': 12,
            'CHI': 16, 'COL': 21, 'CBJ': 29, 'DAL': 25, 'DET': 17, 'EDM': 22,
            'FLA': 13, 'LAK': 26, 'MIN': 30, 'MTL': 8, 'NSH': 18, 'NJD': 1,
            'NYI': 2, 'NYR': 3, 'OTT': 9, 'PHI': 4, 'PIT': 5, 'SJS': 28,
            'SEA': 55, 'STL': 19, 'TBL': 14, 'TOR': 10, 'VAN': 23, 'VGK': 54,
            'WSH': 15, 'WPG': 52
        }
        
        # Reverse mapping
        self.id_to_team = {v: k for k, v in self.team_ids.items()}
        
        self.end_year = datetime.now().year if datetime.now().month >= 10 else datetime.now().year - 1
    
    def _convert_season_to_id(self, season_year):
        """Convert season year (2023) to season ID (20232024)"""
        return f"{season_year}-{season_year + 1}"
    
    def _make_request(self, url, max_retries=3):
        """Make API request with retry logic"""
        for attempt in range(max_retries):
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 404:
                    return None
                time.sleep(1)
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"Error after {max_retries} attempts: {e}")
                    return None
                time.sleep(2 ** attempt)
        return None
    
    def get_season_schedule(self, season_year):
        """Get all games for a season using NHL API by iterating through dates"""
        season_id = self._convert_season_to_id(season_year)
        
        # NHL season typically runs from October to April
        start_date = datetime(season_year, 10, 1)
        end_date = datetime(season_year + 1, 6, 30)  # Include playoffs
        
        all_games = []
        seen_game_ids = set()  # Track unique game IDs to avoid duplicates
        current_date = start_date
        
        print(f"Fetching schedule from {start_date.date()} to {end_date.date()}...")
        
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            url = f"{self.base_api}/schedule/{date_str}"
            
            data = self._make_request(url)
            if data and 'gameWeek' in data:
                for game_week in data.get('gameWeek', []):
                    for game in game_week.get('games', []):
                        game_id = game.get('id')
                        # Only add if we haven't seen this game before
                        if game_id and game_id not in seen_game_ids:
                            all_games.append(game)
                            seen_game_ids.add(game_id)
            
            current_date += timedelta(days=1)
            
            # Progress indicator every 30 days
            if (current_date - start_date).days % 30 == 0:
                print(f"  Progress: {current_date.date()} ({len(all_games)} unique games found)")
        
        print(f"Total unique games found: {len(all_games)}")
        return all_games
    
    def scrape_season_games(self, season_year):
        """Scrape all games for a season"""
        season_str = self._convert_season_to_id(season_year)
        
        # Check if already scraped (like basketball_data does)
        if season_str in self.game_files:
            print(f"Game data for {season_str} already exists. Skipping...")
            output_file = self.data_dir / 'game_data' / f'{season_str}_game_stats.csv'
            return pd.read_csv(output_file)
        
        print(f"\nFetching game data for {season_str}...")
        games = self.get_season_schedule(season_year)
        
        if not games:
            print(f"No games found for season {season_str}")
            return pd.DataFrame()
        
        all_game_records = []
        
        for game in tqdm(games, desc=f"Processing games ({season_str})"):
            if game.get('gameType') != 2:  # Regular season only (gameType=2)
                continue
            
            game_id = game.get('id')
            game_date = game.get('startTimeUTC', '').split('T')[0] if 'startTimeUTC' in game else game.get('gameDate', '').split('T')[0]
            
            home_team = game.get('homeTeam', {})
            away_team = game.get('awayTeam', {})
            
            home_abbr = home_team.get('abbrev', 'UNK')
            away_abbr = away_team.get('abbrev', 'UNK')
            
            home_score = home_team.get('score', 0)
            away_score = away_team.get('score', 0)
            
            # Home team record
            all_game_records.append({
                'SEASON_ID': season_str,
                'GAME_ID': game_id,
                'GAME_DATE': game_date,
                'TEAM_ABBREVIATION': home_abbr,
                'MATCHUP': f"{home_abbr} vs. {away_abbr}",
                'HOME_AWAY': 'HOME',
                'WL': 'W' if home_score > away_score else 'L',
                'PTS': home_score,
                'PTS_AGAINST': away_score,
            })
            
            # Away team record
            all_game_records.append({
                'SEASON_ID': season_str,
                'GAME_ID': game_id,
                'GAME_DATE': game_date,
                'TEAM_ABBREVIATION': away_abbr,
                'MATCHUP': f"{away_abbr} @ {home_abbr}",
                'HOME_AWAY': 'AWAY',
                'WL': 'W' if away_score > home_score else 'L',
                'PTS': away_score,
                'PTS_AGAINST': home_score,
            })
        
        if all_game_records:
            df = pd.DataFrame(all_game_records)
            df.sort_values(by=['GAME_DATE', 'TEAM_ABBREVIATION'], inplace=True)
            
            # Save immediately (like basketball_data does)
            output_file = self.data_dir / 'game_data' / f'{season_str}_game_stats.csv'
            df.to_csv(output_file, index=False)
            print(f"✓ Saved {len(df)} game records to {output_file}")
            
            # Update tracking list
            self.game_files.append(season_str)
            
            time.sleep(1)  # Rate limiting like basketball
            return df
        else:
            print(f"No regular season games found for {season_str}")
            return pd.DataFrame()
    
    def scrape_season_player_data(self, season_year):
        season_str = self._convert_season_to_id(season_year)
        
        # Check if already scraped (like basketball_data does)
        if season_str in self.player_files:
            print(f"Player data for {season_str} already exists. Skipping...")
            output_file = self.data_dir / 'player_data' / f'{season_str}_player_stats.csv'
            return pd.read_csv(output_file)
        
        print(f"\nFetching player data for {season_str}...")
        games = self.get_season_schedule(season_year)
        
        if not games:
            print(f"No games found for season {season_str}")
            return pd.DataFrame()
        
        # Filter to regular season games only
        regular_season_games = [g for g in games if g.get('gameType') == 2]
        print(f"Found {len(regular_season_games)} regular season games to process")
        
        all_player_stats = []
        
        for game in tqdm(regular_season_games, desc="Fetching game boxscores"):
            game_id = game.get('id')
            game_date = game.get('startTimeUTC', '').split('T')[0] if 'startTimeUTC' in game else ''
            
            # Get detailed boxscore
            boxscore_url = f"{self.base_api}/gamecenter/{game_id}/boxscore"
            boxscore_data = self._make_request(boxscore_url)
            
            if not boxscore_data:
                continue
            
            # Extract player stats
            for side in ['homeTeam', 'awayTeam']:
                team_data = boxscore_data.get(side, {})
                team_abbr = team_data.get('abbrev', 'UNK')
                player_data = boxscore_data.get('playerByGameStats', {}).get(side, {})
                
                # Process forwards, defensemen, and goalies
                for position_group in ['forwards', 'defense', 'goalies']:
                    players = player_data.get(position_group, [])
                    
                    for player in players:
                        player_id = player.get('playerId')
                        player_name = player.get('name', {}).get('default', '')
                        position = player.get('position')
                        
                        player_record = {
                            'SEASON_YEAR': season_str,
                            'GAME_ID': game_id,
                            'GAME_DATE': game_date,
                            'PLAYER_ID': player_id,
                            'PLAYER_NAME': player_name,
                            'TEAM_ABBREVIATION': team_abbr,
                            'POSITION': position,
                            'HOME_AWAY': 'HOME' if side == 'homeTeam' else 'AWAY',
                            'GOALS': player.get('goals', 0),
                            'ASSISTS': player.get('assists', 0),
                            'POINTS': player.get('points', 0),
                            'PLUS_MINUS': player.get('plusMinus', 0),
                            'PIM': player.get('pim', 0),
                            'HITS': player.get('hits', 0),
                            'POWER_PLAY_GOALS': player.get('powerPlayGoals', 0),
                            'SHOTS': player.get('sog', 0),
                            'FACEOFF_WIN_PCTG': player.get('faceoffWinningPctg', 0),
                            'TOI': player.get('toi', '0:00'),
                            'BLOCK_SHOTS': player.get('blockedShots', 0),
                            'SHIFTS': player.get('shifts', 0),
                            'TAKEAWAY': player.get('takeaways', 0),
                            'GIVEAWAY': player.get('giveaways', 0),
                        }
                        
                        # Add goalie-specific stats
                        if position_group == 'goalies':
                            player_record.update({
                                'EVEN_STRENGTH_GOALS_AGAINST': player.get('evenStrengthGoalsAgainst', 0),
                                'POWER_PLAY_GOALS_AGAINST': player.get('powerPlayGoalsAgainst', 0),
                                'SHORT_HANDED_GOALS_AGAINST': player.get('shortHandedGoalsAgainst', 0),
                                'SAVES': player.get('saves', 0),
                                'SHOTS_AGAINST': player.get('shotsAgainst', 0),
                                'GOALS_AGAINST': player.get('goalsAgainst', 0),
                                'SAVE_PCT': player.get('savePctg', 0),
                            })
                        
                        all_player_stats.append(player_record)
            
            time.sleep(0.3)  # Rate limiting
        
        if all_player_stats:
            df = pd.DataFrame(all_player_stats)
            df.sort_values(by=['GAME_DATE', 'PLAYER_NAME'], inplace=True)
            
            # Save immediately (like basketball_data does)
            output_file = self.data_dir / 'player_data' / f'{season_str}_player_stats.csv'
            df.to_csv(output_file, index=False)
            print(f"✓ Saved {len(df)} player records to {output_file}")
            
            # Update tracking list
            self.player_files.append(season_str)
            
            return df
        else:
            print(f"No player stats found for {season_str}")
            return pd.DataFrame()
    
    def scrape_season_team_data(self, season_year):
        """Scrape team-level statistics by aggregating game data"""
        season_str = self._convert_season_to_id(season_year)
        
        # Check if already scraped (like basketball_data does)
        if season_str in self.team_files:
            print(f"Team stats for {season_str} already exist. Skipping...")
            output_file = self.data_dir / 'team_data' / f'{season_str}_team_stats.csv'
            return pd.read_csv(output_file)
        
        print(f"\nCalculating team stats from game data for {season_str}...")
        
        # Get game data first
        game_file = self.data_dir / 'game_data' / f'{season_str}_game_stats.csv'
        if not game_file.exists():
            print("Game data not found. Fetching games first...")
            self.scrape_season_games(season_year)
        
        if not game_file.exists():
            print("Could not generate team stats without game data")
            return pd.DataFrame()
        
        games_df = pd.read_csv(game_file)
        
        # Calculate team statistics from game data
        all_team_stats = []
        
        for team_abbr in games_df['TEAM_ABBREVIATION'].unique():
            team_games = games_df[games_df['TEAM_ABBREVIATION'] == team_abbr]
            
            wins = len(team_games[team_games['WL'] == 'W'])
            losses = len(team_games[team_games['WL'] == 'L'])
            games_played = len(team_games)
            
            team_record = {
                'SEASON_YEAR': season_str,
                'TEAM_ABBREVIATION': team_abbr,
                'GAMES_PLAYED': games_played,
                'WINS': wins,
                'LOSSES': losses,
                'WIN_PCT': wins / games_played if games_played > 0 else 0,
                'GOALS_FOR': team_games['PTS'].sum(),
                'GOALS_AGAINST': team_games['PTS_AGAINST'].sum(),
                'GOAL_DIFF': team_games['PTS'].sum() - team_games['PTS_AGAINST'].sum(),
                'GOALS_PER_GAME': team_games['PTS'].mean(),
                'GOALS_AGAINST_PER_GAME': team_games['PTS_AGAINST'].mean(),
            }
            
            all_team_stats.append(team_record)
        
        if all_team_stats:
            df = pd.DataFrame(all_team_stats)
            df.sort_values(by='WINS', ascending=False, inplace=True)
            
            # Save immediately (like basketball_data does)
            output_file = f'{self.data_dir}/team_data/{season_str}_team_stats.csv'
            df.to_csv(output_file, index=False)
            print(f"✓ Saved {len(df)} team records to {output_file}")
            
            # Update tracking list
            self.team_files.append(season_str)
            
            return df
        else:
            print(f"No team stats found for {season_str}")
            return pd.DataFrame()
    
    def scrape_all_seasons(self, start_year=2010, end_year=None, skip_player_data=False):
        """Scrape multiple seasons of data (like basketball_data.getAllSeasonData)"""
        if end_year is None:
            end_year = self.end_year
        
        print(f"\n{'='*80}")
        print(f"SCRAPING SEASONS {start_year}-{end_year}")
        if skip_player_data:
            print("(Skipping player data - use skip_player_data=False to include)")
        print(f"{'='*80}")
        
        seasons = range(start_year, end_year + 1)
        
        for year in tqdm(seasons, desc="Overall Progress"):
            season_str = self._convert_season_to_id(year)
            
            try:
                print(f"\n{'='*60}")
                print(f"SEASON {year}-{year+1} ({season_str})")
                print(f"{'='*60}")
                
                # Scrape games if not already done
                if season_str not in self.game_files:
                    self.scrape_season_games(year)
                else:
                    print(f"Game data for {season_str} already exists. Skipping...")
                
                # Scrape team stats if not already done
                if season_str not in self.team_files:
                    self.scrape_season_team_data(year)
                else:
                    print(f"Team stats for {season_str} already exist. Skipping...")
                
                # Scrape player stats if not already done (and not skipped)
                if not skip_player_data:
                    if season_str not in self.player_files:
                        self.scrape_season_player_data(year)
                    else:
                        print(f"Player data for {season_str} already exists. Skipping...")
                
                print(f"\n✅ Season {year}-{year+1} complete!")
                time.sleep(2)
                
            except Exception as e:
                print(f"\n❌ Error scraping season {year}: {e}")
                import traceback
                traceback.print_exc()
                continue
    
    def getUpcomingGames(self):
        """Get today's NHL games"""
        today = datetime.now().strftime('%Y-%m-%d')
        
        try:
            url = f"{self.base_api}/schedule/{today}"
            data = self._make_request(url)
            
            if not data:
                print("No schedule data available")
                return pd.DataFrame()
            
            games = []
            
            for game_week in data.get('gameWeek', []):
                for game in game_week.get('games', []):
                    if game.get('gameType') == 2:  # Regular season only
                        home_team = game.get('homeTeam', {})
                        away_team = game.get('awayTeam', {})
                        
                        games.append({
                            'GAME_ID': game.get('id'),
                            'GAME_DATE': game.get('startTimeUTC'),
                            'HOME_TEAM': home_team.get('placeName', {}).get('default', '') + ' ' + 
                                        home_team.get('commonName', {}).get('default', ''),
                            'AWAY_TEAM': away_team.get('placeName', {}).get('default', '') + ' ' + 
                                        away_team.get('commonName', {}).get('default', ''),
                            'TEAM_ABB_HOME': home_team.get('abbrev'),
                            'TEAM_ABB_AWAY': away_team.get('abbrev'),
                        })
            
            if games:
                df = pd.DataFrame(games)
                df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])
                df.to_csv(f'{self.data_dir}/upcoming_games.csv', index=False)
                print(f"Found {len(df)} games for today")
                return df
            else:
                print("No games scheduled for today")
                return pd.DataFrame()
                
        except Exception as e:
            print(f"Error fetching upcoming games: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()
    
    def getCurrentSeason(self):
        """Get the current NHL season string (e.g., '20232024')"""
        now = datetime.now()
        if now.month >= 10:  # Season starts in October
            return f"{now.year}-{now.year + 1}"
        else:
            return f"{now.year - 1}-{now.year}"
    
    def get_season_summary(self, season_year):
        """Get a summary of available data for a season"""
        season_str = self._convert_season_to_id(season_year)
        
        game_file = self.data_dir / 'game_data' / f'{season_str}_game_stats.csv'
        player_file = self.data_dir / 'player_data' / f'{season_str}_player_stats.csv'
        team_file = self.data_dir / 'team_data' / f'{season_str}_team_stats.csv'
        
        summary = {
            'season': season_str,
            'games': len(pd.read_csv(game_file)) if game_file.exists() else 0,
            'player_records': len(pd.read_csv(player_file)) if player_file.exists() else 0,
            'team_records': len(pd.read_csv(team_file)) if team_file.exists() else 0,
        }
        
        return summary

# Usage
if __name__ == "__main__":
    scraper = HockeyData()
    
    # Test with recent season
    # print("Testing with 2023-24 season...")
    scraper.scrape_season_player_data(2020)
    
    # Get today's games
    # print("\nFetching today's games...")
    # scraper.getUpcomingGames()
    
    # Scrape multiple seasons (uncomment to use)
    # scraper.scrape_all_seasons()