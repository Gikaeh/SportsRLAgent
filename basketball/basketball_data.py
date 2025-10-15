from nba_api.stats.endpoints import leaguegamefinder, playergamelogs, teamgamelogs, teamyearbyyearstats
from nba_api.stats.static import teams, players
import pandas as pd
import time
from tqdm import tqdm
from pathlib import Path

class BasketballData:
    def __init__(self):
        self.teams_to_keep = [
            'Atlanta Hawks', 'Boston Celtics', 'Cleveland Cavaliers', 'New Orleans Pelicans', 'Chicago Bulls', 'Dallas Mavericks', 'Denver Nuggets', 'Golden State Warriors', 'Houston Rockets', 'Los Angeles Clippers',
            'Los Angeles Lakers', 'Miami Heat', 'Milwaukee Bucks', 'Minnesota Timberwolves', 'Brooklyn Nets', 'New York Knicks', 'Orlando Magic', 'Indiana Pacers', 'Philadelphia 76ers', 'Phoenix Suns',
            'Portland Trail Blazers', 'Sacramento Kings', 'San Antonio Spurs', 'Oklahoma City Thunder', 'Toronto Raptors', 'Utah Jazz', 'Memphis Grizzlies', 'Washington Wizards', 'Detroit Pistons', 'Charlotte Hornets',
            'New Jersey Nets', 'Charlotte Bobcats', 'Vancouver Grizzlies', 'New Orleans Hornets', ' Seattle SuperSonics', 'New Orleans/Oklahoma City Hornets'
        ]
    
    def getAllSeasonData(self):
        seasons = [f'{i}-0{i-1999}' if (i < 2009) else f'{i}-{i-1899}' if (i < 1999) else f'{i}-{i-1999}' for i in range(2000, 2025)]
        game_files = [f.stem.replace('_game_stats', '') for f in Path('./data/basketball/game_data').glob('*_game_stats.csv')]
        team_files = [f.stem.replace('_team_stats', '') for f in Path('./data/basketball/team_data').glob('*_team_stats.csv')]
        player_files = [f.stem.replace('_player_stats', '') for f in Path('./data/basketball/player_data').glob('*_player_stats.csv')]
        for season in tqdm(seasons, desc="Overall Progress"):
            if season not in game_files:
                self.getSeasonGames(season)
            if season not in team_files:
                self.getTeamGames(season)
            if season not in player_files:
                self.getPlayerGames(season)
            
    def getSeasonGames(self, season):
        print(f"\nFetching game results for {season}...")
        gamefinder = leaguegamefinder.LeagueGameFinder(season_nullable=season)
        games = gamefinder.get_data_frames()[0]
        games = games[games['TEAM_NAME'].isin(self.teams_to_keep)]
        games.sort_values(by=['GAME_DATE', 'TEAM_NAME'], inplace=True)
        games.to_csv(f'././data/basketball/game_data/{season}_game_stats.csv', index=False)
        time.sleep(1)
        
    def getTeamGames(self, season):
        all_team_logs = []
        team_list = teams.get_teams()
        print(f"Fetching team stats for {season}...")
        for team in tqdm(team_list, desc=f"Teams ({season})"):
            team_logs = teamgamelogs.TeamGameLogs(season_nullable=season, team_id_nullable=team['id'])
            all_team_logs.append(team_logs.get_data_frames()[0])
            time.sleep(0.6)
        
        team_data = pd.concat(all_team_logs)
        team_data = team_data[team_data['TEAM_NAME'].isin(self.teams_to_keep)]
        team_data.sort_values(by=['GAME_DATE', 'TEAM_NAME'], inplace=True)
        team_data.to_csv(f'././data/basketball/team_data/{season}_team_stats.csv', index=False)
        
    def getPlayerGames(self, season):
        print(f"\nFetching player stats for {season}...")
        player_logs = playergamelogs.PlayerGameLogs(season_nullable=season)
        player_data = player_logs.get_data_frames()[0]
        player_data = player_data[player_data['TEAM_NAME'].isin(self.teams_to_keep)]
        player_data.sort_values(by=['GAME_DATE', 'TEAM_NAME', 'MIN'], inplace=True, ascending=[True, True, False])
        player_data.to_csv(f'././data/basketball/player_data/{season}_player_stats.csv', index=False)

        print(f"Exported all {season} data to CSV files")

    def getTeamYearlyStats(self):
        for team in tqdm(teams.get_teams(), desc="Teams"):
            team_abbreviation = team['abbreviation'].lower()
            print(f"\nFetching team yearly stats for {team_abbreviation}...")
            team_yearly_stats = teamyearbyyearstats.TeamYearByYearStats(team_id=team['id'])
            team_yearly_data = team_yearly_stats.get_data_frames()[0]
            team_yearly_data.to_csv(f'././data/basketball/season_data/{team_abbreviation}_season_stats.csv', index=False)
