from nba_api.stats.endpoints import leaguegamefinder, playergamelogs, teamgamelogs, teamyearbyyearstats, scheduleleaguev2
from nba_api.stats.static import teams
import pandas as pd
import time
from tqdm import tqdm
from pathlib import Path
import datetime
from requests.exceptions import ReadTimeout, ConnectionError, Timeout
import random

class BasketballData:
    def __init__(self, data_dir='././data/basketball', max_retries=3, base_delay=2):
        self.data_dir = Path(data_dir)
        self.teams_to_keep = [
            'Atlanta Hawks', 'Boston Celtics', 'Cleveland Cavaliers', 'New Orleans Pelicans', 'Chicago Bulls', 'Dallas Mavericks', 'Denver Nuggets', 'Golden State Warriors', 'Houston Rockets', 'LA Clippers',
            'Los Angeles Lakers', 'Miami Heat', 'Milwaukee Bucks', 'Minnesota Timberwolves', 'Brooklyn Nets', 'New York Knicks', 'Orlando Magic', 'Indiana Pacers', 'Philadelphia 76ers', 'Phoenix Suns',
            'Portland Trail Blazers', 'Sacramento Kings', 'San Antonio Spurs', 'Oklahoma City Thunder', 'Toronto Raptors', 'Utah Jazz', 'Memphis Grizzlies', 'Washington Wizards', 'Detroit Pistons', 'Charlotte Hornets',
            'New Jersey Nets', 'Charlotte Bobcats', 'Vancouver Grizzlies', 'New Orleans Hornets', ' Seattle SuperSonics', 'New Orleans/Oklahoma City Hornets', 'Los Angeles Clippers'
        ]
        self.end_year = datetime.date.today().year if datetime.date.today().month >= 7 else datetime.date.today().year - 1
        self.game_files = [f.stem.replace('_game_stats', '') for f in self.data_dir.glob('game_data/*_game_stats.csv')]
        self.team_files = [f.stem.replace('_team_stats', '') for f in self.data_dir.glob('team_data/*_team_stats.csv')]
        self.player_files = [f.stem.replace('_player_stats', '') for f in self.data_dir.glob('player_data/*_player_stats.csv')]
        self.max_retries = max_retries
        self.base_delay = base_delay
    
    def getAllSeasonData(self, season=None):
        if season == None:
            seasons = [f'{i}-0{i-1999}' if (i < 2009) else f'{i}-{i-1899}' if (i < 1999) else f'{i}-{i-1999}' for i in range(2000, self.end_year)]
        
            for season in tqdm(seasons, desc="Overall Progress"):
                if season not in self.game_files:
                    self.getSeasonGames(season)
                if season not in self.team_files:
                    self.getTeamGames(season)
                if season not in self.player_files:
                    self.getPlayerGames(season)
        else:
            self.getSeasonGames(season)
            self.getTeamGames(season)
            self.getPlayerGames(season)

                    
    def retryApiCall(self, func, *args, **kwargs):
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except (ReadTimeout, ConnectionError, Timeout) as e:
                if attempt < self.max_retries - 1:
                    delay = self.base_delay * (2 ** attempt) + random.uniform(0, 1)
                    print(f"\nAPI timeout/connection error (attempt {attempt + 1}/{self.max_retries})")
                    print(f"Retrying in {delay:.1f} seconds...")
                    time.sleep(delay)
                else:
                    print(f"\nFailed after {self.max_retries} attempts")
                    raise
            except Exception as e:
                print(f"\nUnexpected error: {type(e).__name__}: {e}")
                raise
    
    def getSeasonGames(self, season):
        print(f"\nFetching game results for {season}...")
        
        def fetch_games():
            gamefinder = leaguegamefinder.LeagueGameFinder(season_nullable=season)
            return gamefinder.get_data_frames()[0]
        
        games = self.retryApiCall(fetch_games)
        games = games[games['TEAM_NAME'].isin(self.teams_to_keep)]
        games.drop(games[games['GAME_DATE'] < f'{season.split("-")[0]}-10-01'].index, inplace=True)
        games.sort_values(by=['GAME_DATE', 'TEAM_NAME'], inplace=True)
        games.to_csv(f'{self.data_dir}/game_data/{season}_game_stats.csv', index=False)
        
        time.sleep(1)
        
    def getTeamGames(self, season):
        all_team_logs = []
        team_list = teams.get_teams()
        print(f"Fetching team stats for {season}...")
        
        for team in tqdm(team_list, desc=f"Teams ({season})"):
            def fetch_team_logs():
                team_logs = teamgamelogs.TeamGameLogs(season_nullable=season, team_id_nullable=team['id'])
                return team_logs.get_data_frames()[0]
            
            team_data = self.retryApiCall(fetch_team_logs)
            all_team_logs.append(team_data)
            time.sleep(0.6)
        
        team_data = pd.concat(all_team_logs)
        team_data = team_data[team_data['TEAM_NAME'].isin(self.teams_to_keep)]
        team_data.drop(team_data[team_data['GAME_DATE'] < f'{season.split("-")[0]}-10-01'].index, inplace=True)
        team_data.sort_values(by=['GAME_DATE', 'TEAM_NAME'], inplace=True)
        team_data.to_csv(f'{self.data_dir}/team_data/{season}_team_stats.csv', index=False)
        
    def getPlayerGames(self, season):
        print(f"\nFetching player stats for {season}...")
        
        def fetch_player_logs():
            player_logs = playergamelogs.PlayerGameLogs(season_nullable=season)
            return player_logs.get_data_frames()[0]
        
        player_data = self.retryApiCall(fetch_player_logs)
        player_data = player_data[player_data['TEAM_NAME'].isin(self.teams_to_keep)]
        player_data.drop(player_data[player_data['GAME_DATE'] < f'{season.split("-")[0]}-10-01'].index, inplace=True)
        player_data.sort_values(by=['GAME_DATE', 'TEAM_NAME', 'MIN'], inplace=True, ascending=[True, True, False])
        player_data.to_csv(f'{self.data_dir}/player_data/{season}_player_stats.csv', index=False)

    def getTeamYearlyStats(self):
        for team in tqdm(teams.get_teams(), desc="Teams"):
            team_abbreviation = team['abbreviation'].lower()
            
            print(f"\nFetching team yearly stats for {team_abbreviation}...")
            
            team_yearly_stats = teamyearbyyearstats.TeamYearByYearStats(team_id=team['id'])
            team_yearly_data = team_yearly_stats.get_data_frames()[0]
            team_yearly_data.to_csv(f'{self.data_dir}/season_data/{team_abbreviation}_season_stats.csv', index=False)

    def getUpcomingGames(self):
        today = pd.Timestamp.now().normalize()
        tomorrow = today + pd.Timedelta(days=1)
        columns = ['gameId', 'gameDateEst', 'homeTeam_teamName', 'homeTeam_teamTricode', 'awayTeam_teamName', 'awayTeam_teamTricode']
        
        def fetch_schedule():
            gamefinder = scheduleleaguev2.ScheduleLeagueV2()
            return gamefinder.get_data_frames()[0]
        
        games = self.retryApiCall(fetch_schedule)
        games = games[columns]
        games.rename(columns={'gameId': 'GAME_ID', 'gameDateEst': 'GAME_DATE', 'homeTeam_teamName': 'HOME_TEAM', 'awayTeam_teamName': 'AWAY_TEAM', 'homeTeam_teamTricode': 'TEAM_ABB_HOME', 'awayTeam_teamTricode': 'TEAM_ABB_AWAY'}, inplace=True)
        games = games[(games['GAME_DATE'] < tomorrow.strftime('%Y-%m-%dT00:00:00Z')) & (games['GAME_DATE'] >= today.strftime('%Y-%m-%dT00:00:00Z'))]
        games['HOME_TEAM'] = games['HOME_TEAM'].apply(self.matchTeamName)
        games['AWAY_TEAM'] = games['AWAY_TEAM'].apply(self.matchTeamName)
        games.to_csv(f'{self.data_dir}/upcoming_games.csv', index=False)

        return games

    def matchTeamName(self, substring):
        for team in self.teams_to_keep:
            if substring in team:
                return team
        return None