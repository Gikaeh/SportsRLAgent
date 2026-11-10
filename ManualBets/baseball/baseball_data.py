from pybaseball import schedule_and_record, batting_stats_bref
import pandas as pd
import warnings
from park_factor_scraping import scrape_park_factors

warnings.simplefilter(action='ignore', category=FutureWarning)

class BaseballData:
    def __init__(self):
        self.error_watch = []

    #Grabs game data
    def grabHistoricalGameData(self, year: int):
        teams_abbr = [
            'BOS','BAL','NYY','TBR','TOR','CHW','CLE','DET','KCR','MIN',
            'HOU','LAA','OAK','SEA','TEX','ARI','ATL','MIA','NYM','PHI',
            'CHC','CIN','COL','LAD','MIL','STL','PIT','SDP','SFG','WSN'
        ]
        
        columns_to_keep = ['Date', 'Tm', 'Home_Away', 'Opp', 'W/L', 'R', 'RA', 'D/N']
        game_data = []

        for team in teams_abbr:
            try:
                team_data = schedule_and_record(year, team)
                filtered_data = team_data[columns_to_keep]
                cleaned_data = cleanupData(filtered_data)
                fixed_dates_data = fixDatesInData(cleaned_data, year)
                game_data.append(fixed_dates_data)
            except Exception as e:
                self.error_watch.append(f"Skipped {team} for {year} due to an error: {e}")        

        print(self.error_watch)
        return game_data

    #Cleans up data renaming columns and removing 'Home_Away' after use
    def cleanupData(self, loaded_data: pd.DataFrame):
        updated_data = loaded_data[loaded_data['Home_Away'] != '@']
        updated_data.drop(columns='Home_Away', inplace=True)

        updated_data.rename(columns={'Date': 'date', 'Tm': 'home_team', 'Opp': 'away_team', 'W/L': 'win', 'R': 'home_runs_scored', 'RA': 'away_runs_scored', 'D/N': 'day'}, inplace=True)

        updated_data['win'].replace({'W': 1, 'W-wo': 1, 'L': 0, 'L-wo': 0}, inplace=True)
        updated_data['day'].replace({'D': 1, 'N': 0}, inplace=True)

        return updated_data

    def grabParkFactor(self, loaded_data: pd.DataFrame, year: int):
        park_factor_data = scrape_park_factors(year)
        
        for i in range(len(loaded_data)):
            team = loaded_data.iloc[i, 1]
            
            if len(park_factor_data[park_factor_data['team'] == team]) != 0:
                loaded_data.iloc[i, len(loaded_data)]
            else:
                print(False)


    #Organize columns
    def organizeColumns(self, loaded_data: pd.DataFrame):
        column_order = [
            'game_id', 'date', 'home_team', 'away_team', 
            'betonline_opening_home_ml', 'betonline_closing_home_ml',
            'betonline_opening_away_ml', 'betonline_closing_away_ml',
            'home_score', 'away_score', 'home_won'
        ]

        updated_data = loaded_data[column_order]

        return updated_data


# for i in range(2019, 2025):
#     try:
#         game_data = grabGameData(i)
#         id_data = buildDataFrame(game_data)
#         park_data = grabParkFactor(game_data, i)
#         final_data = buildDataFrame(park_data)
#         organized_data = organizeColumns(final_data)
#         createCsv(organized_data, i)
#     except Exception as e:
#         errors.append(f'Problem running loop for data collection: {e}')

data = pd.read_csv('./training_data/2020_MLB_Season.csv')
# print(grabParkFactor(data, 2020))
park_data = grabParkFactor(data, 2020)
