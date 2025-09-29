import requests
import pandas as pd
from bs4 import BeautifulSoup
import json
import re

def scrape_park_factors(year: int) -> pd.DataFrame:
    team_mapping = {
        'Athletics': 'OAK', 'White Sox': 'CHW', 'Cardinals': 'STL', 'Astros': 'HOU',
        'Padres': 'SDP', 'Guardians': 'CLE', 'Blue Jays': 'TOR', 'Brewers': 'MIL',
        'Reds': 'CIN', 'Nationals': 'WSN', 'Mariners': 'SEA', 'Royals': 'KCR',
        'Tigers': 'DET', 'Red Sox': 'BOS', 'Orioles': 'BAL', 'Angels': 'LAA',
        'Pirates': 'PIT', 'D-backs': 'ARI', 'Yankees': 'NYY', 'Dodgers': 'LAD',
        'Phillies': 'PHI', 'Rockies': 'COL', 'Rangers': 'TEX', 'Mets': 'NYM',
        'Marlins': 'MIA', 'Braves': 'ATL', 'Giants': 'SFG', 'Twins': 'MIN',
        'Cubs': 'CHC', 'Rays': 'TBR'
    }
    url = f'https://baseballsavant.mlb.com/leaderboard/statcast-park-factors?type=year&year={year}&batSide=&stat=index_wOBA&condition=All&rolling=1&parks=mlb'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        script_tags = soup.find_all('script')
        
        for script in script_tags:
            if script.string:
                data_match = re.search(r'var data = (\[.*?\]);', script.string, re.DOTALL)
                if data_match:
                    try:
                        data = json.loads(data_match.group(1))                        
                        park_factors = []
                        
                        for park in data:
                            team_name = park.get('name_display_club', '')
                            team_abbr = team_mapping.get(team_name, team_name[:3].upper())
                            
                            park_factor = {
                                'year': year,
                                'team': team_abbr,
                                # 'venue': park.get('venue_name', ''),
                                'park_factor': int(park.get('index_woba', 100)) / 100,  # Normalize to 1.0 = average
                                # 'runs_factor': park.get('index_runs', 100) / 100,
                                # 'hr_factor': park.get('index_hr', 100) / 100,
                                # 'woba_factor': int(park.get('index_woba', 100)) / 100,
                                # 'bb_factor': park.get('index_bb', 100) / 100,
                                # 'so_factor': park.get('index_so', 100) / 100
                            }
                            park_factors.append(park_factor)
                        
                        df = pd.DataFrame(park_factors)
                        df.to_csv(f'./data/park_data/{year}')
                        return df
                        
                    except json.JSONDecodeError as e:
                        print(f"Error parsing JSON: {e}")
                        continue
        
        print(f"No park factors data found for {year}")
        return pd.DataFrame()
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data for {year}: {e}")
        return pd.DataFrame()