from pybaseball import schedule_and_record, batting_stats_bref
import pandas as pd
import warnings
from park_factor_scraping import scrape_park_factors

warnings.simplefilter(action='ignore', category=FutureWarning)

#Grabs game data
def grabGameData(year: int):
    teams_abbr = [
        'BOS','BAL','NYY','TBR','TOR','CHW','CLE','DET','KCR','MIN',
        'HOU','LAA','OAK','SEA','TEX','ARI','ATL','MIA','NYM','PHI',
        'CHC','CIN','COL','LAD','MIL','STL','PIT','SDP','SFG','WSN'
    ]
    error_watch = []
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
            error_watch.append(f"Skipped {team} for {year} due to an error: {e}")        

    print(error_watch)
    return game_data

#Cleans up data renaming columns and removing 'Home_Away' after use
def cleanupData(loaded_data: pd.DataFrame):
    updated_data = loaded_data[loaded_data['Home_Away'] != '@']
    updated_data.drop(columns='Home_Away', inplace=True)

    updated_data.rename(columns={'Date': 'date', 'Tm': 'home_team', 'Opp': 'away_team', 'W/L': 'win', 'R': 'home_runs_scored', 'RA': 'away_runs_scored', 'D/N': 'day'}, inplace=True)

    updated_data['win'].replace({'W': 1, 'W-wo': 1, 'L': 0, 'L-wo': 0}, inplace=True)
    updated_data['day'].replace({'D': 1, 'N': 0}, inplace=True)

    return updated_data

#Fixes the dates to have year and be - separated (called in grabGameData)
def fixDatesInData(loaded_data: pd.DataFrame, year: int):
    months_name_to_num = {
        'Jan': 1,
        'Feb': 2,
        'Mar': 3,
        'Apr': 4,
        'May': 5,
        'Jun': 6,
        'Jul': 7,
        'Aug': 8,
        'Sep': 9,
        'Oct': 10,
        'Nov': 11,
        'Dec': 12
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

def grabParkFactor(loaded_data: pd.DataFrame, year: int):
    park_factor_data = scrape_park_factors(year)
    
    for i in range(len(loaded_data)):
        team = loaded_data.iloc[i, 1]
        
        if len(park_factor_data[park_factor_data['team'] == team]) != 0:
            loaded_data.iloc[i, len(loaded_data)]
        else:
            print(False)

def grabOdds(loaded)


#Organize columns
def organizeColumns(loaded_data: pd.DataFrame):
    column_order = [
        'game_id', 'date', 'home_team', 'away_team', 
        'betonline_opening_home_ml', 'betonline_closing_home_ml',
        'betonline_opening_away_ml', 'betonline_closing_away_ml',
        'home_score', 'away_score', 'home_won'
    ]

    updated_data = loaded_data[column_order]

    return updated_data

def buildDataFrame(loaded_data: pd.DataFrame):
    master_df = pd.concat(loaded_data, ignore_index=True)
    master_df['game_id'] = master_df.apply(
        lambda row: f"{row['date']}_{sorted([row['home_team'], row['away_team']])[0]}_{sorted([row['home_team'], row['away_team']])[1]}", 
        axis=1
    )

def createCsv(loaded_data: pd.DataFrame, year):
    loaded_data.to_csv(f'./training_data/{year}_MLB_Season.csv', index=False)

errors = []

for i in range(2019, 2025):
    try:
        game_data = grabGameData(i)
        park_data = grabParkFactor(game_data, i)
        final_data = buildDataFrame(park_data)
        organized_data = organizeColumns(final_data)
        createCsv(organized_data, i)
    except Exception as e:
        errors.append(f'Problem running loop for data collection: {e}')

data = pd.read_csv('./training_data/2020_MLB_Season.csv')
print(grabParkFactor(data, 2020))