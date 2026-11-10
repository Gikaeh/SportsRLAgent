"""Regression tests: odds scraping must survive pandas 3's arrow-backed 'str'.

`pd.json_normalize` now returns text columns with dtype 'str' (pyarrow), and
assigning a datetime object row by row (`df.iat[i,0] = pst_datetime`) raises
`TypeError: Invalid value ... for dtype 'str'`. The scrapers therefore convert
whole columns with `toPacificTime` / `mapTeamCodes`.

Basketball package names collide with hockey's, so basketball modules are run in
an isolated interpreter via PYTHONPATH (same approach as
`tests/test_basketball_fixes.py`).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def run_with_pythonpath(code, package_dir):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / package_dir)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=120,
        env=env,
    )


H2H_SCRAPE_CHECK = """
import tempfile
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from data_pipeline.odd_scraping import BasketballOddScraping


def iso(delta_hours):
    return (datetime.now(timezone.utc) + timedelta(hours=delta_hours)).strftime(
        '%Y-%m-%dT%H:%M:%SZ')


def event(home, away, commence, last_update):
    return {
        'id': f'{home}-{away}',
        'sport_key': 'basketball_nba',
        'commence_time': commence,
        'home_team': home,
        'away_team': away,
        'bookmakers': [{
            'key': 'draftkings',
            'title': 'DraftKings',
            'markets': [{
                'key': 'h2h',
                'last_update': last_update,
                'outcomes': [
                    {'name': home, 'price': -150},
                    {'name': away, 'price': 130},
                ],
            }],
        }],
    }


payload = [
    event('Boston Celtics', 'Los Angeles Lakers', iso(3), iso(0)),   # upcoming
    event('Denver Nuggets', 'Utah Jazz', iso(-5), iso(-6)),          # started
]


class FakeResponse:
    status_code = 200
    headers = {'x-requests-remaining': '999', 'x-requests-used': '1'}
    text = ''

    def json(self):
        return payload


requests.get = lambda *args, **kwargs: FakeResponse()

with tempfile.TemporaryDirectory() as tmp:
    scraper = BasketballOddScraping(data_dir=tmp)
    df = scraper.getH2hOdds()

# the already-started game must be filtered out by upcomingGamesWindow
assert df is not None, 'getH2hOdds returned nothing'
assert len(df) == 2, f'expected the 2 outcomes of the upcoming game, got {len(df)}'
assert set(df['home_team']) == {'BOS'}, df['home_team'].tolist()
assert set(df['away_team']) == {'LAL'}, df['away_team'].tolist()
assert set(df['name']) == {'BOS', 'LAL'}, df['name'].tolist()

for column in ('commence_time', 'bookmakers_markets_last_update'):
    assert pd.api.types.is_datetime64_any_dtype(df[column]), \\
        f'{column} should be datetime, got {df[column].dtype}'
    assert df[column].dt.tz is not None, f'{column} should stay tz-aware'

assert (df['commence_time'] > pd.Timestamp(scraper.time_now)).all(), \\
    'commence_time must be comparable to now (tz-aware datetime)'
print('ok')
"""


@pytest.mark.parametrize("package_dir", ["basketball"])
def test_h2h_scraping_converts_datetime_columns(package_dir):
    result = run_with_pythonpath(H2H_SCRAPE_CHECK, package_dir)
    assert result.returncode == 0, f"odds scraping regression failed:\n{result.stderr}"


ODD_SCRAPING_FILES = [
    "basketball/data_pipeline/odd_scraping.py",
    "hockey/data_pipeline/odd_scraping.py",
    "baseball/odd_scraping.py",
]


@pytest.mark.parametrize("rel", ODD_SCRAPING_FILES)
def test_odd_scraping_has_no_row_wise_datetime_assignment(rel):
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert "df.iat[i,0] = pst_datetime" not in src, (
        f"{rel} still assigns datetimes row by row into pandas 3 'str' columns"
    )
    assert "toPacificTime(" in src, f"{rel} does not use the column-wise converter"
