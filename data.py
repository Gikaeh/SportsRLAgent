import pandas as pd
# from baseball_data import BaseballData
# from basketball_data import BasketballData
import os

#Fixes the dates to have year and be - separated (called in grabGameData)
def fixDatesInData(loaded_data: pd.DataFrame, year: int):
    months_name_to_num = {
        'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
        'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
    }
    updated_data = loaded_data

    for i in range(len(updated_data)):
        month = months_name_to_num[updated_data.iloc[i,0].split(' ')[1]]
        day = updated_data.iloc[i,0].split(' ')[2]

        if month < 10:
            month = f'0{month}'
        if int(day) < 10:
            day = f'0{day}'

        updated_data.iloc[i,0] = f'{year}-{month}-{day}'
    
    return updated_data

def buildDataFrame(loaded_data: pd.DataFrame):
    master_df = pd.concat(loaded_data, ignore_index=True)
    master_df['game_id'] = master_df.apply(
        lambda row: f"{row['date']}_{sorted([row['home_team'], row['away_team']])[0]}_{sorted([row['home_team'], row['away_team']])[1]}", 
        axis=1
    )

def createCsv(loaded_data: pd.DataFrame, year):
    loaded_data.to_csv(f'./training_data/{year}_MLB_Season.csv', index=False)

_, _, files = next(os.walk('./data/basketball/team_data'))
teams_to_keep = ['ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW', 'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK', 'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS']


for i in range(len(files)):
    loaded_data = pd.read_csv(f'./data/basketball/team_data/{files[i]}')
    loaded_data.sort_values(['TEAM_NAME', 'GAME_DATE'], inplace=True)
    loaded_data = loaded_data[loaded_data['TEAM_ABBREVIATION'].isin(teams_to_keep)]
    loaded_data.to_csv(f'./data/basketball/team_data/{files[i]}', index=False)