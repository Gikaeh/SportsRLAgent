from pybaseball import schedule_and_record, batting_stats_bref
import pandas as pd
import warnings

warnings.simplefilter(action='ignore', category=FutureWarning)

teamsAbbr = [
    'BOS','BAL','NYY','TBR','TOR','CHW','CLE','DET','KCR','MIN',
    'HOU','LAA','OAK','SEA','TEX','ARI','ATL','MIA','NYM','PHI',
    'CHC','CIN','COL','LAD','MIL','STL','PIT','SD','SF','WSN'
]

errorWatch = []


columnsToKeep = ['Date', 'Tm', 'Home_Away', 'Opp', 'W/L', 'R', 'RA', 'D/N', 'Streak']

# for year in range(2020, 2025):
#     gameData = []

#     for team in teamsAbbr:
#         try:
#             team_data = schedule_and_record(year, team)
#             filteredData = team_data[columnsToKeep]
#             gameData.append(filteredData)
#         except Exception as e:
#             errorWatch.append(f"Skipped {team} for {year} due to an error: {e}")        

#     masterDf = pd.concat(gameData, ignore_index=True)
#     masterDf['unique_game_id'] = masterDf.apply(
#         lambda row: f"{row['Date']}_{sorted([row['Tm'], row['Opp']])[0]}_{sorted([row['Tm'], row['Opp']])[1]}", 
#         axis=1
#     )

#     masterDf.drop_duplicates(subset='unique_game_id', keep='first', inplace=True)
#     masterDf.drop(columns='unique_game_id', inplace=True)

#     masterDf.to_csv(f'./training_data/{year}_MLB_Season.csv', index=False)

# print(errorWatch)

for year in range(2020, 2025):
    gameData = []

    for team in teamsAbbr:
        try:
            team_data = batting_stats_bref(year)
            print(team_data)
            # filteredData = team_data[columnsToKeep]
            # gameData.append(filteredData)
        except Exception as e:
            errorWatch.append(f"Skipped {team} for {year} due to an error: {e}")        

    # masterDf = pd.concat(gameData, ignore_index=True)
    # masterDf['unique_game_id'] = masterDf.apply(
    #     lambda row: f"{row['Date']}_{sorted([row['Tm'], row['Opp']])[0]}_{sorted([row['Tm'], row['Opp']])[1]}", 
    #     axis=1
    # )

    # masterDf.drop_duplicates(subset='unique_game_id', keep='first', inplace=True)
    # masterDf.drop(columns='unique_game_id', inplace=True)

    # masterDf.to_csv(f'./training_data/{year}_MLB_Season.csv', index=False)

# print(errorWatch)