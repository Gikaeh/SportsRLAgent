import requests
import pandas as pd
from datetime import datetime
import pytz
import json
import schedule
import time

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
        self.sport = 'basketball_nba'
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

            for i in range(len(df)):
                utc_date = df.iat[i,0]
                utc_datetime = datetime.fromisoformat(utc_date.replace('Z', '+00:00'))
                pst_datetime = utc_datetime.astimezone(self.pst_timezone)
                df.iat[i,0] = pst_datetime

                utc_last_update = df.iat[i,5]
                utc_last_update_datetime = datetime.fromisoformat(utc_last_update.replace('Z', '+00:00'))
                pst_last_update_datetime = utc_last_update_datetime.astimezone(self.pst_timezone)
                df.iat[i,5] = pst_last_update_datetime

                home_team = df.at[i,'home_team']
                away_team = df.at[i, 'away_team']
                bet_team = df.at[i, 'name']

                if home_team in self.team_mapping:
                    df.at[i, 'home_team'] = self.team_mapping.get(home_team)

                if away_team in self.team_mapping:
                    df.at[i, 'away_team'] = self.team_mapping.get(away_team)

                if bet_team in self.team_mapping:
                    df.at[i, 'name'] = self.team_mapping.get(bet_team)

            df_sorted = df.sort_values(['commence_time', 'home_team', 'bookmakers_key'])
            
            data_not_to_drop = df_sorted['commence_time'] > self.time_now
            cleaned_data = df_sorted[data_not_to_drop]
            
            cleaned_data.to_csv(f'././data/basketball/odds_data/current_{self.time_now_string}.csv', index=False)

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