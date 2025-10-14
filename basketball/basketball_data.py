from nba_api.stats.endpoints import leaguegamefinder, playergamelogs, teamgamelogs, teamyearbyyearstats
from nba_api.stats.static import teams, players
import pandas as pd
import time
from tqdm import tqdm
from pathlib import Path

class BasketballData:
    def __init__(self):
        self.teams_to_keep = ['ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW', 'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK', 'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS']
    
    def getAllSeasonData(self):
        seasons = [f'{i}-0{i-1999}' if (i < 2009) else f'{i}-{i-1899}' if (i < 1999) else f'{i}-{i-1999}' for i in range(2000, 2025)]
        files = [f.stem.replace('_game_stats', '') for f in Path('./data/basketball/game_data').glob('*_game_stats.csv')]
        for season in tqdm(seasons, desc="Overall Progress"):
            if season in files:
                print(f"Skipping {season} as it already exists")
                continue
            self.getSeasonGames(season)
            self.getTeamGames(season)
            self.getPlayerGames(season)
            
    def getSeasonGames(self, season):
        print(f"Fetching game results for {season}...")
        gamefinder = leaguegamefinder.LeagueGameFinder(season_nullable=season)
        games = gamefinder.get_data_frames()[0]
        games = games[games['TEAM_ABBREVIATION'].isin(self.teams_to_keep)]
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
        team_data = team_data[team_data['TEAM_ABBREVIATION'].isin(self.teams_to_keep)]
        team_data.to_csv(f'././data/basketball/team_data/{season}_team_stats.csv', index=False)
        
    def getPlayerGames(self, season):
        print(f"Fetching player stats for {season}...")
        player_logs = playergamelogs.PlayerGameLogs(season_nullable=season)
        player_data = player_logs.get_data_frames()[0]
        player_data.to_csv(f'././data/basketball/player_data/{season}_player_stats.csv', index=False)

        print(f"Exported all {season} data to CSV files")

    def getTeamYearlyStats(self):
        for team in tqdm(teams.get_teams(), desc="Teams"):
            team_abbreviation = team['abbreviation'].lower()
            print(f"Fetching team yearly stats for {team_abbreviation}...")
            team_yearly_stats = teamyearbyyearstats.TeamYearByYearStats(team_id=team['id'])
            team_yearly_data = team_yearly_stats.get_data_frames()[0]
            team_yearly_data.to_csv(f'././data/basketball/season_data/{team_abbreviation}_season_stats.csv', index=False)
