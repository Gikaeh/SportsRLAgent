import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz
from pathlib import Path

class BasketballOddScraping:
    def __init__(self, data_dir='././data/basketball/odds_data'):
        self.team_mapping = {
            'Atlanta Hawks': 'ATL', 'Boston Celtics': 'BOS', 'Cleveland Cavaliers': 'CLE', 'New Orleans Pelicans': 'NOP', 'Chicago Bulls': 'CHI', 'Dallas Mavericks': 'DAL', 'Denver Nuggets': 'DEN', 'Golden State Warriors': 'GSW', 'Houston Rockets': 'HOU', 'Los Angeles Clippers': 'LAC',
            'Los Angeles Lakers': 'LAL', 'Miami Heat': 'MIA', 'Milwaukee Bucks': 'MIL', 'Minnesota Timberwolves': 'MIN', 'Brooklyn Nets': 'BKN', 'New York Knicks': 'NYK', 'Orlando Magic': 'ORL', 'Indiana Pacers': 'IND', 'Philadelphia 76ers': 'PHI', 'Phoenix Suns': 'PHX',
            'Portland Trail Blazers': 'POR', 'Sacramento Kings': 'SAC', 'San Antonio Spurs': 'SAS', 'Oklahoma City Thunder': 'OKC', 'Toronto Raptors': 'TOR', 'Utah Jazz': 'UTA', 'Memphis Grizzlies': 'MEM', 'Washington Wizards': 'WAS', 'Detroit Pistons': 'DET', 'Charlotte Hornets': 'CHA',
        }
        self.api_key = '13a6a49f229ace0bb115d8f83f3bf63e'
        self.sport = 'basketball_nba'
        self.regions = 'us,us2'
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
            data_not_to_drop = df_sorted['commence_time'] < self.time_now + timedelta(days=1)
            cleaned_data = df_sorted[data_not_to_drop]
            
            cleaned_data.to_csv(f'{self.data_dir}/spreads_{self.time_now_string}.csv', index=False)

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
            data_not_to_drop = df_sorted['commence_time'] < self.time_now + timedelta(days=1)
            cleaned_data = df_sorted[data_not_to_drop]
            
            cleaned_data.to_csv(f'{self.data_dir}/total_{self.time_now_string}.csv', index=False)

            return cleaned_data