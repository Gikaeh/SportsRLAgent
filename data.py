from pybaseball import schedule_and_record
import pandas as pd

teamsAbbr = [
    'BOS','BAL','NYY','TB','TOR','CHW','CLE','DET','KC','MIN',
    'HOU','LAA','OAK','SEA','TEX','ARI','ATL','MIA','NYM','PHI',
    'CHC','CIN','COL','LAD','MIL','STL','PIT','SD','SF','WSH'
]

errorWatch = []


columnsToKeep = ['Date', 'Tm', 'Home_Away', 'Opp', 'W/L', 'R', 'RA', 'D/N', 'Streak']

for year in range(2020, 2025):
    gameData = []

    for team in teamsAbbr:
        try:
            team_data = schedule_and_record(year, team)
            filteredData = team_data[columnsToKeep]
            gameData.append(filteredData)
        except Exception as e:
            # Use a more specific exception to not hide other errors
            errorWatch.append(f"Skipped {team} for {year} due to an error: {e}")        

    masterDf = pd.concat(gameData, ignore_index=True)
    masterDf['unique_game_id'] = masterDf.apply(
        lambda row: f"{row['Date']}_{sorted([row['Tm'], row['Opp']])[0]}_{sorted([row['Tm'], row['Opp']])[1]}", 
        axis=1
    )

    masterDf.drop_duplicates(subset='unique_game_id', keep='first', inplace=True)
    masterDf.drop(columns='unique_game_id', inplace=True)

    masterDf.to_csv(f'{year}_MLB_Season.csv', index=False)

print(errorWatch)