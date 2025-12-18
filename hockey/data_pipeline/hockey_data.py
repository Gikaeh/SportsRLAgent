import requests
import pandas as pd
from pathlib import Path
from tqdm import tqdm
import time
from datetime import datetime

class HockeyData:
    def __init__(self, data_dir='./data/hockey'):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / 'game_data').mkdir(exist_ok=True)
        (self.data_dir / 'team_data').mkdir(exist_ok=True)
        (self.data_dir / 'player_data').mkdir(exist_ok=True)
        
        self.base_url = "https://api-web.nhle.com/v1"
        
        # NHL team abbreviations
        self.teams = [
            'ANA', 'ARI', 'BOS', 'BUF', 'CGY', 'CAR', 'CHI', 'COL', 'CBJ', 'DAL',
            'DET', 'EDM', 'FLA', 'LAK', 'MIN', 'MTL', 'NSH', 'NJD', 'NYI', 'NYR',
            'OTT', 'PHI', 'PIT', 'SJS', 'SEA', 'STL', 'TBL', 'TOR', 'VAN', 'VGK',
            'WSH', 'WPG', 'UTA'  # Utah Hockey Club
        ]
        
        self.end_year = datetime.now().year if datetime.now().month >= 10 else datetime.now().year - 1
    
    def get_team_roster(self, team_abbr, season):
        url = f"{self.base_url}/roster/{team_abbr}/{season}"
        
        try:
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                
                players = []
                for position in ['forwards', 'defensemen', 'goalies']:
                    if position in data:
                        for player in data[position]:
                            players.append({
                                'id': player.get('id'),
                                'name': player.get('firstName', {}).get('default', '') + ' ' + 
                                       player.get('lastName', {}).get('default', ''),
                                'position': player.get('positionCode'),
                                'team': team_abbr
                            })
                
                return players
            return []
        except Exception as e:
            print(f"Error fetching roster for {team_abbr}: {e}")
            return []
    
    def get_player_game_log(self, player_id, season, game_type=2):
        #game_type: 1=preseason, 2=regular season, 3=playoffs
        url = f"{self.base_url}/player/{player_id}/game-log/{season}/{game_type}"
        
        try:
            response = requests.get(url)
            if response.status_code == 200:
                data = response.json()
                print(data)
                return data.get('gameLog', [])
            return []
        except Exception as e:
            print(f"Error fetching game log for player {player_id}: {e}")
            return []
    
    def get_team_game_stats(self, team_abbr, season, game_type=2):
        url = f"{self.base_url}/club-stats/{team_abbr}/{season}/{game_type}"
        
        try:
            response = requests.get(url)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"Error fetching team stats for {team_abbr}: {e}")
            return None
    
    def scrape_season_player_data(self, season):
        season_str = f"{season}{season+1}"
        output_file = self.data_dir / 'player_data' / f'{season_str}_player_stats.csv'
        
        if output_file.exists():
            print(f"Season {season_str} already scraped.")
            return pd.read_csv(output_file)
        
        all_game_logs = []
        
        # Get rosters for all teams
        print("Fetching team rosters...")
        all_players = []
        for team in tqdm(self.teams, desc="Teams"):
            roster = self.get_team_roster(team, season_str)
            all_players.extend(roster)
            time.sleep(0.1)
        
        print(f"\nFound {len(all_players)} players")
        print(f"Fetching game logs...\n")
        
        # Get game logs for each player
        for player in tqdm(all_players, desc="Players"):
            game_log = self.get_player_game_log(player['id'], season_str, game_type=2)
            
            if game_log:
                for game in game_log:
                    game_data = {
                        'SEASON_YEAR': season_str,
                        'PLAYER_ID': player['id'],
                        'PLAYER_NAME': player['name'],
                        'TEAM_ABBREVIATION': player['team'],
                        'POSITION': player['position'],
                        'GAME_ID': game.get('gameId'),
                        'GAME_DATE': game.get('gameDate'),
                        'HOME_AWAY': 'HOME' if game.get('homeRoadFlag') == 'H' else 'AWAY',
                        'OPPONENT': game.get('opponentAbbrev'),
                        'GOALS': game.get('goals', 0),
                        'ASSISTS': game.get('assists', 0),
                        'POINTS': game.get('points', 0),
                        'PLUS_MINUS': game.get('plusMinus', 0),
                        'PIM': game.get('pim', 0),  # Penalty minutes
                        'SHOTS': game.get('shots', 0),
                        'SHIFTS': game.get('shifts', 0),
                        'TOI': game.get('toi', '0:00'),  # Time on ice
                        'PPG': game.get('powerPlayGoals', 0),  # Power play goals
                        'PPA': game.get('powerPlayAssists', 0),  # Power play assists
                        'SHG': game.get('shorthandedGoals', 0),  # Shorthanded goals
                        'SHA': game.get('shorthandedAssists', 0),  # Shorthanded assists
                        'GWG': game.get('gameWinningGoals', 0),  # Game winning goals
                        'OTG': game.get('otGoals', 0),  # Overtime goals
                    }
                    
                    # Add goalie-specific stats if applicable
                    if player['position'] == 'G':
                        game_data.update({
                            'SHOTS_AGAINST': game.get('shotsAgainst', 0),
                            'SAVES': game.get('saves', 0),
                            'GOALS_AGAINST': game.get('goalsAgainst', 0),
                            'SAVE_PCT': game.get('savePctg', 0.0),
                        })
                    
                    all_game_logs.append(game_data)
            
            time.sleep(0.05)
        
        if all_game_logs:
            df = pd.DataFrame(all_game_logs)
            df.sort_values(by=['GAME_DATE', 'PLAYER_NAME'], inplace=True)
            df.to_csv(output_file, index=False)
            print(f"\nSaved {len(df)} player game records to {season_str}_player_stats.csv")
            return df
        else:
            print("\nNo data collected")
            return pd.DataFrame()
    
    def scrape_season_team_data(self, season):
        season_str = f"{season}{season+1}"
        output_file = self.data_dir / 'team_data' / f'{season_str}_team_stats.csv'
        
        if output_file.exists():
            print(f"Team stats for {season_str} already scraped.")
            return
        
        print(f"\nFetching team stats for {season_str}...")
        
        all_team_stats = []
        for team in tqdm(self.teams, desc="Teams"):
            stats = self.get_team_game_stats(team, season_str)
            if stats:
                team_data = {
                    'SEASON_YEAR': season_str,
                    'TEAM_ABBREVIATION': team,
                    'FIRST NAME': stats.get('firstName'),
                    'LAST NAME': stats.get('lastName'),
                    'POSITION': stats.get('positionCode'),
                    'GAMES_PLAYED': stats.get('gamesPlayed'),
                    'GAMES_STARTED': stats.get('gamesStarted'),
                    'GOALS': stats.get('goals'),
                    'ASSISTS': stats.get('assists'),
                    'POINTS': stats.get('points'),
                    'PLUS_MINUS': stats.get('plusMinus'),
                    'PIM': stats.get('penaltyMinutes'),
                    'POWER_PLAY_GOALS': stats.get('powerPlayGoals'),
                    'SHORT_HANDED_GOALS': stats.get('shorthandedGoals'),
                    'GAME_WINNING_GOALS': stats.get('gameWinningGoals'),
                    'OVER_TIME_GOALS': stats.get('overtimeGoals'),
                    'SHOTS': stats.get('shots'),
                    'SHOOT_PCT': stats.get('shootingPctg'),
                    'AVG_TIME_ON_ICE': stats.get('avgTimeOnIcePerGame'),
                    'AVG_SHIFTS': stats.get('avgShiftsPerGame'),
                    'FACEOFF_WIN_PCT': stats.get('faceoffWinPctg'),
                    'GOALS_AGAINST': stats.get('goalsAgainst'),
                    'SAVE_PCT': stats.get('savePctg'),
                    
                }
                all_team_stats.append(team_data)
            time.sleep(0.1)
        
        if all_team_stats:
            df = pd.DataFrame(all_team_stats)
            df.to_csv(output_file, index=False)
            print(f"Saved team stats to {season_str}_team_stats.csv")
    
    def get_game_boxscore_detailed(self, game_id):
        url = f"{self.base_url}/gamecenter/{game_id}/boxscore"
        
        try:
            response = requests.get(url)
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"Error fetching boxscore for game {game_id}: {e}")
            return None
    
    def scrape_season_games(self, season):
        season_str = f"{season}{season+1}"
        output_file = self.data_dir / 'game_data' / f'{season_str}_game_stats.csv'
        
        if output_file.exists():
            print(f"Game data for {season_str} already scraped.")
            return
        
        print(f"\nFetching game results for {season_str}...")
        
        start_date = f"{season}-10-01"
        url = f"{self.base_url}/schedule/{start_date}"
        
        try:
            response = requests.get(url)
            data = response.json()
            
            all_games = []
            
            for game_week in data.get('gameWeek', []):
                for game in game_week.get('games', []):
                    if game.get('gameType') == 2:
                        home_team = game.get('homeTeam', {})
                        away_team = game.get('awayTeam', {})

                        all_games.append({
                            'SEASON_ID': season_str,
                            'TEAM_ID': home_team.get('id'),
                            'TEAM_ABBREVIATION': home_team.get('abbrev'),
                            'GAME_ID': game.get('id'),
                            'GAME_DATE': game.get('startTimeUTC', '').split('T')[0],
                            'MATCHUP': f"{home_team.get('abbrev')} vs. {away_team.get('abbrev')}",
                            'WL': 'W' if home_team.get('score', 0) > away_team.get('score', 0) else 'L',
                            'PTS': home_team.get('score', 0),
                            'PTS_AGAINST': away_team.get('score', 0),
                        })
                        
                        all_games.append({
                            'SEASON_ID': season_str,
                            'TEAM_ID': away_team.get('id'),
                            'TEAM_ABBREVIATION': away_team.get('abbrev'),
                            'GAME_ID': game.get('id'),
                            'GAME_DATE': game.get('startTimeUTC', '').split('T')[0],
                            'MATCHUP': f"{away_team.get('abbrev')} @ {home_team.get('abbrev')}",
                            'WL': 'W' if away_team.get('score', 0) > home_team.get('score', 0) else 'L',
                            'PTS': away_team.get('score', 0),
                            'PTS_AGAINST': home_team.get('score', 0),
                        })
            
            if all_games:
                df = pd.DataFrame(all_games)
                df.sort_values(by=['GAME_DATE', 'TEAM_ABBREVIATION'], inplace=True)
                df.to_csv(output_file, index=False)
                print(f"Saved {len(df)} game records to {season_str}_game_stats.csv")
        
        except Exception as e:
            print(f"Error fetching schedule: {e}")
    
    def scrape_all_seasons(self, start_year=2008, end_year=None):
        if end_year is None:
            end_year = self.end_year
        
        for year in range(start_year, end_year + 1):            
            try:
                self.scrape_season_games(year)
                self.scrape_season_player_data(year)
                self.scrape_season_team_data(year)
                
                print(f"\nSeason {year}-{year+1} complete!")
                time.sleep(2)
            except Exception as e:
                print(f"\nError scraping season {year}: {e}")
                continue

# Usage
if __name__ == "__main__":
    scraper = HockeyData(data_dir='./data/hockey')
    
    # Scrape a single season
    scraper.scrape_season_player_data(2023)
    
    # Or scrape all seasons from 2008 onwards
    # scraper.scrape_all_seasons(start_year=2001)