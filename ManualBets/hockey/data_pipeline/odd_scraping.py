import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz
from pathlib import Path


def toPacificTime(series, timezone):
    """ISO-8601 UTC strings -> tz-aware Pacific datetimes.

    pandas 3 stores json_normalize's text columns as the arrow-backed 'str'
    dtype, which raises TypeError when a datetime object is assigned row by row
    (the old `df.iat[i,0] = ...` loops). Converting the whole column at once
    also gives a real datetime dtype, which the commence_time filters need."""
    return pd.to_datetime(series, utc=True, format='ISO8601').dt.tz_convert(timezone)


def mapTeamCodes(series, team_mapping):
    """Full team names -> repo abbreviations; names not in the map pass through."""
    return series.map(lambda name: team_mapping.get(name, name))


class HockeyOddScraping:
    def __init__(self, data_dir='././data/hockey/odds_data'):
        self.team_mapping = {
            'Anaheim Ducks': 'ANA', 'Arizona Coyotes': 'ARI', 'Boston Bruins': 'BOS', 'Buffalo Sabres': 'BUF', 'Calgary Flames': 'CGY', 'Carolina Hurricanes': 'CAR', 'Chicago Blackhawks': 'CHI', 'Colorado Avalanche': 'COL', 'Columbus Blue Jackets': 'CBJ', 'Dallas Stars': 'DAL',
            'Detroit Red Wings': 'DET', 'Edmonton Oilers': 'EDM', 'Florida Panthers': 'FLA', 'Los Angeles Kings': 'LAK', 'Minnesota Wild': 'MIN', 'Montreal Canadiens': 'MTL', 'Nashville Predators': 'NSH', 'New Jersey Devils': 'NJD', 'New York Islanders': 'NYI', 'New York Rangers': 'NYR',
            'Ottawa Senators': 'OTT', 'Philadelphia Flyers': 'PHI', 'Pittsburgh Penguins': 'PIT', 'San Jose Sharks': 'SJS', 'Seattle Kraken': 'SEA', 'St. Louis Blues': 'STL', 'Tampa Bay Lightning': 'TBL', 'Toronto Maple Leafs': 'TOR', 'Vancouver Canucks': 'VAN', 'Vegas Golden Knights': 'VGK',
            'Washington Capitals': 'WSH', 'Winnipeg Jets': 'WPG', 'Utah Hockey Club': 'UTA',
        }
        self.api_key = '13a6a49f229ace0bb115d8f83f3bf63e'
        self.sport = 'icehockey_nhl'
        self.regions = 'us'
        self.odds = 'american'
        self.date = 'iso'
        self.pst_timezone = pytz.timezone('America/Los_Angeles')
        self.time_now = datetime.now(self.pst_timezone)
        self.time_now_string = datetime.now(tz=self.pst_timezone).strftime("%Y-%m-%d_%H-%M")
        self.data_dir = Path(data_dir)

    def getH2hOdds(self):
        odds_response = requests.get(
            f'https://api.the-odds-api.com/v4/sports/{self.sport}/odds/?apiKey={self.api_key}&regions={self.regions}&markets=h2h',
            params={
                'api_key': self.api_key,
                'regions': self.regions,
                'markets': 'h2h',
                'oddsFormat': self.odds,
                'dateFormat': self.date,
            }
        )

        if odds_response.status_code != 200:
            print(f'Failed to get odds: status_code {odds_response.status_code}, response body {odds_response.text}')

        else:
            odds_json = odds_response.json()
            print('Number of events:', len(odds_json))
            # print(odds_json)

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
            data_not_to_drop = df_sorted['commence_time'] < self.time_now + timedelta(days=1)
            cleaned_data = df_sorted[data_not_to_drop]
            
            cleaned_data.to_csv(f'{self.data_dir}/h2h_{self.time_now_string}.csv', index=False)

            return cleaned_data

    def getSpreadOdds(self):
        odds_response = requests.get(
            f'https://api.the-odds-api.com/v4/sports/{self.sport}/odds/?apiKey={self.api_key}&regions={self.regions}&markets=spreads',
            params={
                'api_key': self.api_key,
                'regions': self.regions,
                'markets': 'spreads',
                'oddsFormat': self.odds,
                'dateFormat': self.date,
            }
        )

        if odds_response.status_code != 200:
            print(f'Failed to get odds: status_code {odds_response.status_code}, response body {odds_response.text}')

        else:
            odds_json = odds_response.json()
            print('Number of events:', len(odds_json))
            # print(odds_json)

            print('Remaining requests', odds_response.headers['x-requests-remaining'])
            print('Used requests', odds_response.headers['x-requests-used'])

            df = pd.json_normalize(
                odds_json,
                record_path=['bookmakers','markets','outcomes'],
                meta=['commence_time', 'home_team', 'away_team', ['bookmakers','key'],['bookmakers', 'markets', 'key'], ['bookmakers', 'markets', 'last_update']],
                sep='_'
            )

            df = df[['commence_time','home_team','away_team','bookmakers_key','bookmakers_markets_key','bookmakers_markets_last_update','name','price','point']]

            df['commence_time'] = toPacificTime(df['commence_time'], self.pst_timezone)
            df['bookmakers_markets_last_update'] = toPacificTime(
                df['bookmakers_markets_last_update'], self.pst_timezone)

            for column in ('home_team', 'away_team', 'name'):
                df[column] = mapTeamCodes(df[column], self.team_mapping)

            df_sorted = df.sort_values(['commence_time', 'home_team', 'bookmakers_key'])
            
            data_not_to_drop = df_sorted['commence_time'] > self.time_now
            cleaned_data = df_sorted[data_not_to_drop]
            data_not_to_drop = df_sorted['commence_time'] < self.time_now + timedelta(days=1)
            cleaned_data = df_sorted[data_not_to_drop]
            
            cleaned_data.to_csv(f'{self.data_dir}/spread_{self.time_now_string}.csv', index=False)

            return cleaned_data

    def getTotalOdds(self):
        odds_response = requests.get(
            f'https://api.the-odds-api.com/v4/sports/{self.sport}/odds/?apiKey={self.api_key}&regions={self.regions}&markets=totals',
            params={
                'api_key': self.api_key,
                'regions': self.regions,
                'markets': 'totals',
                'oddsFormat': self.odds,
                'dateFormat': self.date,
            }
        )

        if odds_response.status_code != 200:
            print(f'Failed to get odds: status_code {odds_response.status_code}, response body {odds_response.text}')

        else:
            odds_json = odds_response.json()
            print('Number of events:', len(odds_json))
            # print(odds_json)

            print('Remaining requests', odds_response.headers['x-requests-remaining'])
            print('Used requests', odds_response.headers['x-requests-used'])

            df = pd.json_normalize(
                odds_json,
                record_path=['bookmakers','markets','outcomes'],
                meta=['commence_time', 'home_team', 'away_team', ['bookmakers','key'],['bookmakers', 'markets', 'key'], ['bookmakers', 'markets', 'last_update']],
                sep='_'
            )

            df = df[['commence_time','home_team','away_team','bookmakers_key','bookmakers_markets_key','bookmakers_markets_last_update','name','price','point']]

            df['commence_time'] = toPacificTime(df['commence_time'], self.pst_timezone)
            df['bookmakers_markets_last_update'] = toPacificTime(
                df['bookmakers_markets_last_update'], self.pst_timezone)

            for column in ('home_team', 'away_team', 'name'):
                df[column] = mapTeamCodes(df[column], self.team_mapping)

            df_sorted = df.sort_values(['commence_time', 'home_team', 'bookmakers_key'])
            
            data_not_to_drop = df_sorted['commence_time'] > self.time_now
            cleaned_data = df_sorted[data_not_to_drop]
            data_not_to_drop = df_sorted['commence_time'] < self.time_now + timedelta(days=1)
            cleaned_data = df_sorted[data_not_to_drop]
            
            cleaned_data.to_csv(f'{self.data_dir}/total_{self.time_now_string}.csv', index=False)

            return cleaned_data

# odds = HockeyOddScraping()
# odds.getH2hOdds()
# odds.getSpreadOdds()
# odds.getTotalOdds()