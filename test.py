import json
import pandas as pd
from datetime import datetime
import pytz
import os

_, _, files = next(os.walk('./data/odds_data'))
pst_timezone = pytz.timezone('America/Los_Angeles')
current_time = datetime.now(pst_timezone)

all_data = []

for i in range(len(files)):
    loaded_data = pd.read_csv(f'./data/odds_data/{files[i]}')

    loaded_data['sequence'] = i + 1
    all_data.append(loaded_data)

# Combine all data
combined_df = pd.concat(all_data, ignore_index=True)

# Group by game, bookmaker, and team
result_rows = []

for (commence_time, home_team, away_team, bookmaker, team), group in combined_df.groupby(['commence_time', 'home_team', 'away_team', 'bookmakers_key', 'name']):
    
    # Base row
    row = {
        'commence_time': commence_time,
        'home_team': home_team, 
        'away_team': away_team,
        'bookmakers_key': bookmaker,
        'name': team
    }
    
    # Sort by sequence and add prices as sequential columns
    group_sorted = group.sort_values('sequence')
    for i, (_, odds_row) in enumerate(group_sorted.iterrows()):
        if pd.notna(odds_row['price']):  # Only add if price exists
            row[f'price_{i+1}'] = odds_row['price']
    
    result_rows.append(row)

result_df = pd.DataFrame(result_rows)


result_df.sort_values(['commence_time', 'home_team', 'bookmakers_key'], inplace=True)
result_df.to_csv('./data/odds_data/combined_data/combined_bookmaker_prices.csv', index=False)
    



# df = pd.read_csv('./data/odds_data/combined_data/combined_bookmaker_prices.csv')
# df_date = df[df['commence_time'] == '2025-10-01 12:08:00-07:00']
# df_team = df_date[df_date['name'] == 'SDP']
# print(df_team['price_1'].max())
# df_team_2 = df_date[df_date['name'] == 'CHC']
# print(df_team_2['price_1'].max())