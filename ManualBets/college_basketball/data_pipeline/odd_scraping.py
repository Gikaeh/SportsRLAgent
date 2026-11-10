"""College lines from The Odds API, with the shared key held in basketball's scraper."""
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
ODDS_DIR = ROOT / 'data' / 'college_basketball' / 'odds_data'
ODDS_URL = 'https://api.the-odds-api.com/v4/sports/basketball_ncaab/odds/'


def fetchCollegeOdds(books, odds_dir=ODDS_DIR):
    """Costs 3 quota credits. Returns (games, requests remaining). Never prints the key."""
    from basketball.data_pipeline.odd_scraping import BasketballOddScraping
    api_key = BasketballOddScraping(data_dir=str(odds_dir)).api_key
    try:
        response = requests.get(ODDS_URL, timeout=30, params={
            'apiKey': api_key, 'bookmakers': ','.join(books), 'markets': 'h2h,spreads,totals',
            'oddsFormat': 'american', 'dateFormat': 'iso'})
    except requests.RequestException as error:
        # The exception text can contain the request URL, and the URL contains the key.
        raise RuntimeError(f"Odds request failed: {type(error).__name__}") from None
    if not response.ok:
        raise RuntimeError(f"Odds API returned HTTP {response.status_code}")
    games = response.json()
    Path(odds_dir).mkdir(parents=True, exist_ok=True)
    (Path(odds_dir) / 'latest.json').write_text(json.dumps(games))
    return games, response.headers.get('x-requests-remaining')
