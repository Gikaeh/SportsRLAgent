import requests
import json
import pandas as pd

def getOdds():
    api_key = '13a6a49f229ace0bb115d8f83f3bf63e'
    sport = 'baseball_mlb'
    regions = 'us'
    markets = 'h2h'
    odds = 'american'
    date = 'iso'

    # sports_response = requests.get(
    #     'https://api.the-odds-api.com/v4/sports', 
    #     params={
    #         'api_key': api_key
    #     }
    # )

    odds_response = requests.get(
        f'https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={api_key}&regions={regions}&markets={markets}',
        params={
            'api_key': api_key,
            'regions': regions,
            'markets': markets,
            'oddsFormat': odds,
            'dateFormat': date,
        }
    )

    if odds_response.status_code != 200:
        print(f'Failed to get odds: status_code {odds_response.status_code}, response body {odds_response.text}')

    else:
        odds_json = odds_response.json()
        print('Number of events:', len(odds_json))
        # print(odds_json)
        with open("output.json", "w") as json_file:
            json.dump(odds_json, json_file, indent=4)

        # Check the usage quota
        print('Remaining requests', odds_response.headers['x-requests-remaining'])
        print('Used requests', odds_response.headers['x-requests-used'])

        df = pd.json_normalize(
            odds_json,
            record_path=['bookmakers','markets','outcomes'],
            meta=['commence_time', 'home_team', 'away_team', ['bookmakers','key'],['bookmakers', 'markets', 'key']],
            sep='_'
        )
        print(df)
        return df

getOdds().to_csv('output.csv')
