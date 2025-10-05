from nba_api.stats.endpoints import leaguegamefinder, playergamelogs, teamgamelogs, teamyearbyyearstats
from nba_api.stats.static import teams, players
import pandas as pd
import time
from tqdm import tqdm

class BasketballData:
    def __init__(self):
        pass
    
    def get_all_season_data(self):
        seasons = [f'{i}-{i-1999}' for i in range(2015, 2025)]
        for season in tqdm(seasons, desc="Overall Progress"):
            # 1. Game results
            print(f"Fetching game results for {season}...")
            gamefinder = leaguegamefinder.LeagueGameFinder(season_nullable=season)
            games = gamefinder.get_data_frames()[0]
            games.to_csv(f'././data/basketball/game_data/{season}_game_stats.csv', index=False)
            time.sleep(1)
            
            # 2. Team game logs (all teams)
            all_team_logs = []
            team_list = teams.get_teams()
            print(f"Fetching team stats for {season}...")
            for team in tqdm(team_list, desc=f"Teams ({season})"):
                team_logs = teamgamelogs.TeamGameLogs(season_nullable=season, team_id_nullable=team['id'])
                all_team_logs.append(team_logs.get_data_frames()[0])
                time.sleep(0.6)
            
            team_data = pd.concat(all_team_logs)
            team_data.to_csv(f'././data/basketball/team_data/{season}_team_stats.csv', index=False)
            
            print(f"Fetching player stats for {season}...")
            player_logs = playergamelogs.PlayerGameLogs(season_nullable=season)
            player_data = player_logs.get_data_frames()[0]
            player_data.to_csv(f'././data/basketball/player_data/{season}_player_stats.csv', index=False)

            print(f"Exported all {season} data to CSV files")

        for team in tqdm(teams.get_teams(), desc="Teams"):
            team_abbreviation = team['abbreviation'].lower()
            print(f"Fetching team yearly stats for {team_abbreviation}...")
            team_yearly_stats = teamyearbyyearstats.TeamYearByYearStats(team_id=team['id'])
            team_yearly_data = team_yearly_stats.get_data_frames()[0]
            team_yearly_data.to_csv(f'././data/basketball/season_data/{team_abbreviation}_season_stats.csv', index=False)
