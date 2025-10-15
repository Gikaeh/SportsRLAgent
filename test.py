import pandas as pd
import os

for file in os.listdir('data/basketball/player_data'):
    loaded_data = pd.read_csv('data/basketball/player_data/' + file)
    loaded_data.sort_values(by=['GAME_DATE', 'TEAM_NAME', 'PLAYER_NAME'], inplace=True)
    loaded_data.to_csv('data/basketball/player_data/' + file, index=False)