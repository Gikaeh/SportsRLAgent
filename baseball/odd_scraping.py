import requests
import pandas as pd
from datetime import datetime
import pytz
import json
import schedule
import time


def toPacificTime(series, timezone):
    """ISO-8601 UTC strings -> tz-aware Pacific datetimes.

    pandas 3 stores json_normalize's text columns as the arrow-backed 'str'
    dtype, which raises TypeError when a datetime object is assigned row by row
    (the old `df.iat[i,0] = ...` loops). Converting the whole column at once
    also gives a real datetime dtype, which the commence_time filter needs."""
    return pd.to_datetime(series, utc=True, format='ISO8601').dt.tz_convert(timezone)


def mapTeamCodes(series, team_mapping):
    """Full team names -> repo abbreviations; names not in the map pass through."""
    return series.map(lambda name: team_mapping.get(name, name))


class BaseballOddScraping:
    def __init__(self):
        self.team_mapping = {
            'Oakland Athletics': 'OAK', 'Chicago White Sox': 'CHW', 'St. Louis Cardinals': 'STL', 'Houston Astros': 'HOU',
            'San Diego Padres': 'SDP', 'Cleveland Guardians': 'CLE', 'Toronto Blue Jays': 'TOR', 'Milwaukee Brewers': 'MIL',
            'Cincinnati Reds': 'CIN', 'Washington Nationals': 'WSN', 'Seattle Mariners': 'SEA', 'Kansas City Royals': 'KCR',
            'Detroit Tigers': 'DET', 'Boston Red Sox': 'BOS', 'Baltimore Orioles': 'BAL', 'Los Angeles Angels': 'LAA',
            'Pittsburgh Pirates': 'PIT', 'Arizona Diamondbacks': 'ARI', 'New York Yankees': 'NYY', 'Los Angeles Dodgers': 'LAD',
            'Philadelphia Phillies': 'PHI', 'Colorado Rockies': 'COL', 'Texas Rangers': 'TEX', 'New York Mets': 'NYM',
            'Miami Marlins': 'MIA', 'Atlanta Braves': 'ATL', 'San Francisco Giants': 'SFG', 'Minnesota Twins': 'MIN',
            'Chicago Cubs': 'CHC', 'Tampa Bay Rays': 'TBR'
        }
        self.api_key = '13a6a49f229ace0bb115d8f83f3bf63e'
        self.sport = 'baseball_mlb'
        self.regions = 'us,us2'
        self.markets = 'h2h'
        self.odds = 'american'
        self.date = 'iso'
        self.pst_timezone = pytz.timezone('America/Los_Angeles')
        self.time_now = datetime.now(self.pst_timezone)
        self.time_now_string = datetime.now(tz=self.pst_timezone).strftime("%Y-%m-%d_%H-%M")

    def getCurrentOdds(self):
        odds_response = requests.get(
            f'https://api.the-odds-api.com/v4/sports/{self.sport}/odds/?apiKey={self.api_key}&regions={self.regions}&markets={self.markets}',
            params={
                'api_key': self.api_key,
                'regions': self.regions,
                'markets': self.markets,
                'oddsFormat': self.odds,
                'dateFormat': self.date,
            }
        )

        if odds_response.status_code != 200:
            print(f'Failed to get odds: status_code {odds_response.status_code}, response body {odds_response.text}')

        else:
            odds_json = odds_response.json()
            print('Number of events:', len(odds_json))
            print(odds_json)

            # Check the usage quota
            print('Remaining requests', odds_response.headers['x-requests-remaining'])
            print('Used requests', odds_response.headers['x-requests-used'])

            df = pd.json_normalize(
                odds_json,
                record_path=['bookmakers','markets','outcomes'],
                meta=['commence_time', 'home_team', 'away_team', ['bookmakers','key'],['bookmakers', 'markets', 'key'], ['bookmakers', 'markets', 'last_update']],
                sep='_'
            )

            df = df[['commence_time','home_team','away_team','bookmakers_key','bookmakers_markets_key','bookmakers_markets_last_update','name','price']]

            df['commence_time'] = toPacificTime(df['commence_time'], self.pst_timezone)
            df['bookmakers_markets_last_update'] = toPacificTime(
                df['bookmakers_markets_last_update'], self.pst_timezone)

            for column in ('home_team', 'away_team', 'name'):
                df[column] = mapTeamCodes(df[column], self.team_mapping)

            df_sorted = df.sort_values(['commence_time', 'home_team', 'bookmakers_key'])
            
            data_not_to_drop = df_sorted['commence_time'] > self.time_now
            cleaned_data = df_sorted[data_not_to_drop]
            
            cleaned_data.to_csv(f'././data/baseball/odds_data/current_{self.time_now_string}.csv', index=False)

            return cleaned_data

# schedule.every().day.at('06:00').do(getCurrentOdds)
# schedule.every().day.at('10:00').do(getCurrentOdds)
# schedule.every().day.at('13:00').do(getCurrentOdds)
# schedule.every().day.at('16:00').do(getCurrentOdds)

# while True:
#     schedule.run_pending()
#     time.sleep(1)    
baseball_odd_scraping = BaseballOddScraping()
baseball_odd_scraping.getCurrentOdds()