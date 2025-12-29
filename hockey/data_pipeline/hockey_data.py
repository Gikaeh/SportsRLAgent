import pandas as pd
from pathlib import Path
from tqdm import tqdm
import time
from datetime import datetime, timedelta
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.base_data_fetcher import BaseDataFetcher

class HockeyData(BaseDataFetcher):
    def __init__(self, data_dir='././data/hockey', max_retries=3, base_delay=2):
        super().__init__(data_dir, max_retries, base_delay)
        
        # Using NHL API
        self.base_api = "https://api-web.nhle.com/v1"

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
    
    def convertSeasonToId(self, season_year):
        return f"{season_year}-{season_year + 1}"
    
    def getSeasonSchedule(self, season_year):
        season_id = self.convertSeasonToId(season_year)
        
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
            
            data = self.makeRequest(url)
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
    
    def scrapeSeasonGames(self, season_year):
        season_str = self.convertSeasonToId(season_year)
        output_file = self.data_dir / 'game_data' / f'{season_str}_game_stats.csv'
        current_season = self.getCurrentSeason()
        
        # For current season, check for incremental updates
        # if season_str == current_season and output_file.exists():
        #     print(f"Checking for new games in current season {season_str}...")
        #     existing_df = pd.read_csv(output_file)
        #     existing_game_ids = set(existing_df['GAME_ID'].unique())
        #     print(f"Found {len(existing_game_ids)} existing games in file")
        if season_str in self.game_files and season_str != current_season:
            print(f"Game data for {season_str} already exists. Skipping...")
            return pd.read_csv(output_file)
        # else:
        #     existing_game_ids = set()
        
        print(f"\nFetching game data for {season_str}...")
        games = self.getSeasonSchedule(season_year)
        print(games)
        
        if not games:
            print(f"No games found for season {season_str}")
            return pd.DataFrame()
        
        all_game_records = []
        # new_games_count = 0
        
        for game in tqdm(games, desc=f"Processing games ({season_str})"):
            if game.get('gameType') != 2:  # Regular season only (gameType=2)
                continue
            
            game_id = game.get('id')
            
            # Skip if we already have this game (for current season incremental updates)
            # if existing_game_ids and game_id in existing_game_ids:
            #     continue
            
            # new_games_count += 1
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
            new_df = pd.DataFrame(all_game_records)
            
            # If updating current season, append to existing data
            # if existing_game_ids:
            #     existing_df = pd.read_csv(output_file)
            #     df = pd.concat([existing_df, new_df], ignore_index=True)
            #     df.sort_values(by=['GAME_DATE', 'TEAM_ABBREVIATION'], ascending=[False, True], inplace=True)
            #     df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE']).dt.strftime('%Y-%m-%d')
            #     df.to_csv(output_file, index=False)
            #     print(f"Added {new_games_count} new games. Total: {len(df)} game records in {output_file}")
            # else:
            new_df.sort_values(by=['GAME_DATE', 'TEAM_ABBREVIATION'], ascending=[False, True], inplace=True)
            new_df['GAME_DATE'] = pd.to_datetime(new_df['GAME_DATE']).dt.strftime('%Y-%m-%d')
            new_df.to_csv(output_file, index=False)
            print(f"Saved {len(new_df)} game records to {output_file}")
            df = new_df
            
            # Update tracking list
            if season_str not in self.game_files:
                self.game_files.append(season_str)
            
            time.sleep(1)  # Rate limiting like basketball
            return df
        # elif existing_game_ids:
        #     # No new games, return existing data
        #     print(f"No new games found for {season_str}")
        #     return pd.read_csv(output_file)
        else:
            print(f"No regular season games found for {season_str}")
            return pd.DataFrame()
    
    def scrapeSeasonData(self, season_year):
        season_str = self.convertSeasonToId(season_year)
        current_season = self.getCurrentSeason()
        
        player_file = self.data_dir / 'player_data' / f'{season_str}_player_stats.csv'
        team_file = self.data_dir / 'team_data' / f'{season_str}_team_stats.csv'
        
        # For current season, check for incremental updates
        if season_str == current_season and player_file.exists() and team_file.exists():
            print(f"Checking for new game data in current season {season_str}...")
            existing_player_df = pd.read_csv(player_file)
            existing_team_df = pd.read_csv(team_file)
            existing_game_ids = set(existing_player_df['GAME_ID'].unique())
            print(f"Found {len(existing_game_ids)} existing games in player/team data")
        elif season_str in self.player_files and season_str in self.team_files:
            print(f"Player data for {season_str} already exists. Skipping...")
            print(f"Team data for {season_str} already exists. Skipping...")
            return
        else:
            existing_game_ids = set()
            existing_player_df = None
            existing_team_df = None
        
        print(f"\nFetching data for {season_str}...")

        game_file = self.data_dir / 'game_data' / f'{season_str}_game_stats.csv'
        if not game_file.exists():
            print("Game data not found. Fetching games first...")
            self.scrapeSeasonGames(season_year)
        
        games = pd.read_csv(game_file)
        games['GAME_DATE'] = pd.to_datetime(games['GAME_DATE'])
        
        # Filter to only games that have been played (before today)
        today = datetime.now().date()
        games_played = games[games['GAME_DATE'].dt.date < today]
        unique_games = games_played['GAME_ID'].unique()
        
        # Filter to only new games if doing incremental update
        if existing_game_ids:
            new_games = [gid for gid in unique_games if gid not in existing_game_ids]
            print(f"Found {len(new_games)} new games to process (out of {len(unique_games)} total played)")
            unique_games = new_games
        else:
            print(f"Found {len(unique_games)} regular season games to process (played before today)")
        
        if len(unique_games) == 0:
            print(f"No new games to process for {season_str}")
            return
        
        all_player_stats = []
        all_team_stats = []
        
        for game_id in tqdm(unique_games, desc="Fetching game boxscores"):
            game_date = games[games['GAME_ID'] == game_id]['GAME_DATE'].iloc[0]
            
            boxscore_url = f"{self.base_api}/gamecenter/{game_id}/boxscore"
            boxscore_data = self.makeRequest(boxscore_url)
            
            if not boxscore_data:
                continue
            
            for side in ['homeTeam', 'awayTeam']:
                team_stats_dict = boxscore_data.get(side, {})
                team_abbr = team_stats_dict.get('abbrev', 'UNK')
                player_stats_dict = boxscore_data.get('playerByGameStats', {}).get(side, {})
                
                # Get game info for this team
                game_info = games[(games['GAME_ID'] == game_id) & (games['TEAM_ABBREVIATION'] == team_abbr)]
                if not game_info.empty:
                    matchup = game_info['MATCHUP'].iloc[0]
                    wl = game_info['WL'].iloc[0]
                    pts = game_info['PTS'].iloc[0]
                    pts_against = game_info['PTS_AGAINST'].iloc[0]
                else:
                    matchup = ''
                    wl = ''
                    pts = 0
                    pts_against = 0
                
                if player_stats_dict:
                    for position_group in ['forwards', 'defense', 'goalies']:
                        players = player_stats_dict.get(position_group, [])
                        
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
                
                if player_stats_dict:
                    # Aggregate player stats to create team stats
                    forwards = player_stats_dict.get('forwards', [])
                    defense = player_stats_dict.get('defense', [])
                    goalies = player_stats_dict.get('goalies', [])
                    
                    # Aggregate skater stats (forwards + defense)
                    skaters = forwards + defense
                    
                    team_goals = sum(p.get('goals', 0) for p in skaters)
                    team_assists = sum(p.get('assists', 0) for p in skaters)
                    team_points = sum(p.get('points', 0) for p in skaters)
                    team_pim = sum(p.get('pim', 0) for p in skaters)
                    team_hits = sum(p.get('hits', 0) for p in skaters)
                    team_power_play_goals = sum(p.get('powerPlayGoals', 0) for p in skaters)
                    team_shots = sum(p.get('sog', 0) for p in skaters)
                    team_blocked_shots = sum(p.get('blockedShots', 0) for p in skaters)
                    team_takeaways = sum(p.get('takeaways', 0) for p in skaters)
                    team_giveaways = sum(p.get('giveaways', 0) for p in skaters)
                    
                    # Goalie stats (use primary goalie or aggregate)
                    team_saves = sum(g.get('saves', 0) for g in goalies)
                    team_shots_against = sum(g.get('shotsAgainst', 0) for g in goalies)
                    team_goals_against = sum(g.get('goalsAgainst', 0) for g in goalies)
                    team_even_strength_ga = sum(g.get('evenStrengthGoalsAgainst', 0) for g in goalies)
                    team_power_play_ga = sum(g.get('powerPlayGoalsAgainst', 0) for g in goalies)
                    team_short_handed_ga = sum(g.get('shortHandedGoalsAgainst', 0) for g in goalies)
                    
                    # Calculate save percentage
                    team_save_pct = team_saves / team_shots_against if team_shots_against > 0 else 0
                    
                    # Calculate shooting percentage
                    team_shooting_pct = team_goals / team_shots if team_shots > 0 else 0
                    
                    team_record = {
                        'SEASON_YEAR': season_str,
                        'GAME_ID': game_id,
                        'GAME_DATE': game_date,
                        'TEAM_ABBREVIATION': team_abbr,
                        'MATCHUP': matchup,
                        'WL': wl,
                        'HOME_AWAY': 'HOME' if side == 'homeTeam' else 'AWAY',
                        'PTS': pts,
                        'PTS_AGAINST': pts_against,
                        'GOALS': team_goals,
                        'ASSISTS': team_assists,
                        'POINTS': team_points,
                        'PIM': team_pim,
                        'HITS': team_hits,
                        'POWER_PLAY_GOALS': team_power_play_goals,
                        'SHOTS': team_shots,
                        'SHOOTING_PCT': team_shooting_pct,
                        'BLOCKED_SHOTS': team_blocked_shots,
                        'TAKEAWAYS': team_takeaways,
                        'GIVEAWAYS': team_giveaways,
                        'SAVES': team_saves,
                        'SHOTS_AGAINST': team_shots_against,
                        'GOALS_AGAINST': team_goals_against,
                        'SAVE_PCT': team_save_pct,
                        'EVEN_STRENGTH_GOALS_AGAINST': team_even_strength_ga,
                        'POWER_PLAY_GOALS_AGAINST': team_power_play_ga,
                        'SHORT_HANDED_GOALS_AGAINST': team_short_handed_ga,
                    }
                    
                    all_team_stats.append(team_record)
            time.sleep(0.3)
        
        if all_player_stats:
            new_player_df = pd.DataFrame(all_player_stats)
            
            # If updating current season, append to existing data
            if existing_player_df is not None:
                player_df = pd.concat([existing_player_df, new_player_df], ignore_index=True)
                player_df.sort_values(by=['GAME_DATE', 'PLAYER_ID'], ascending=[False, True], inplace=True)
                print(f"\nAdded {len(new_player_df)} new player records. Total: {len(player_df)} records")
            else:
                player_df = new_player_df
                print(f"\nSaved {len(player_df)} player records")
            
            player_output = self.data_dir / 'player_data' / f'{season_str}_player_stats.csv'
            player_df['GAME_DATE'] = pd.to_datetime(player_df['GAME_DATE']).dt.strftime('%Y-%m-%d')
            player_df.to_csv(player_output, index=False)
            print(f"Saved to {player_output}")
            
            if season_str not in self.player_files:
                self.player_files.append(season_str)
        
        if all_team_stats:
            new_team_df = pd.DataFrame(all_team_stats)
            
            # If updating current season, append to existing data
            if existing_team_df is not None:
                team_df = pd.concat([existing_team_df, new_team_df], ignore_index=True)
                team_df.sort_values(by=['GAME_DATE', 'TEAM_ABBREVIATION'], ascending=[False, True], inplace=True)
                print(f"Added {len(new_team_df)} new team records. Total: {len(team_df)} records")
            else:
                team_df = new_team_df
                print(f"Saved {len(team_df)} team records")
            
            team_output = self.data_dir / 'team_data' / f'{season_str}_team_stats.csv'
            team_df['GAME_DATE'] = pd.to_datetime(team_df['GAME_DATE']).dt.strftime('%Y-%m-%d')
            team_df.to_csv(team_output, index=False)
            print(f"Saved to {team_output}")
            
            if season_str not in self.team_files:
                self.team_files.append(season_str)
        else:
            print(f"No team stats found for {season_str} or set to false")
    
    def getAllSeasonData(self, season=None):
        """Fetch all data for a season or all seasons. Implements base class method."""
        if season is None:
            self.scrapeAllSeasons()
        else:
            # Extract year from season string like "2024-2025"
            year = int(season.split('-')[0])
            self.scrapeSeasonGames(year)
            self.scrapeSeasonData(year)
    
    def scrapeAllSeasons(self, start_year=2010, end_year=None):
        if end_year is None:
            end_year = self.end_year
        
        print(f"\n{'='*80}")
        print(f"SCRAPING SEASONS {start_year}-{end_year}")
        print(f"{'='*80}")
        
        seasons = range(start_year, end_year + 1)
        
        for year in tqdm(seasons, desc="Overall Progress"):
            season_str = self.convertSeasonToId(year)
            
            try:
                print(f"\n{'='*60}")
                print(f"SEASON {year}-{year+1} ({season_str})")
                print(f"{'='*60}")
                
                if season_str not in self.game_files or season_str == self.getCurrentSeason():
                    self.scrapeSeasonGames(year)
                else:
                    print(f"Game data for {season_str} already exists. Skipping...")
                
                if (season_str not in self.player_files or season_str not in self.team_files) or season_str == self.getCurrentSeason():
                    self.scrapeSeasonData(year)
                else:
                    print(f"Player and team data for {season_str} already exists. Skipping...")
                
                print(f"\nSeason {year}-{year+1} complete!")
                time.sleep(2)
                
            except Exception as e:
                print(f"\nError scraping season {year}: {e}")
                import traceback
                traceback.print_exc()
                continue
    
    def getUpcomingGames(self):
        today = pd.Timestamp.now().normalize()
        
        try:
            url = f"{self.base_api}/schedule/{today.strftime('%Y-%m-%d')}"
            data = self.makeRequest(url)
            games_day = data.get('gameWeek', [])[0]
            
            if not data:
                print("No schedule data available")
                return pd.DataFrame()
            
            games = []
            
            for game in games_day.get('games', []):
                if game.get('gameType') == 2:
                    home_team = game.get('homeTeam', {})
                    away_team = game.get('awayTeam', {})
                    
                    games.append({
                        'GAME_ID': game.get('id'),
                        'GAME_DATE': games_day.get('date'),
                        'HOME_TEAM': home_team.get('placeName', {}).get('default', '') + ' ' + home_team.get('commonName', {}).get('default', ''),
                        'HOME_TEAM_ABBR': home_team.get('abbrev'),
                        'AWAY_TEAM': away_team.get('placeName', {}).get('default', '') + ' ' + away_team.get('commonName', {}).get('default', ''),
                        'AWAY_TEAM_ABBR': away_team.get('abbrev'),
                    })
            
            if games:
                df = pd.DataFrame(games)
                                
                if df.empty:
                    print("No games scheduled for today")
                    return pd.DataFrame()
                
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
        now = datetime.now()
        if now.month >= 10:
            return f"{now.year}-{now.year + 1}"
        else:
            return f"{now.year - 1}-{now.year}"
