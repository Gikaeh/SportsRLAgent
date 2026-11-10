"""getUpcomingGames picks the next slate of not-yet-started games.

Regression for SESSION-LOG "NBA menu: getUpcomingGames only keeps today's local
date, so at night it can't reach tomorrow's slate". The owner is on US Pacific
time; schedules date games by their US Eastern day. "now" is frozen and the
schedule APIs are faked, so no network is used.

Fake slate (Nov 2026, PST = UTC-8, EST = UTC-5):
  Nov 9 ET   F  (yesterday, final)
  Nov 10 ET  A  7:00 PM ET = 4:00 PM PT   B  10:00 PM ET = 7:00 PM PT
  Nov 11 ET  C  7:30 PM ET = 4:30 PM PT   D  10:30 PM ET = 7:30 PM PT
  Nov 12 ET  E  (beyond the today/tomorrow window)
"""

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from shared.base_data_fetcher import nextSlate

ROOT = Path(__file__).resolve().parent.parent

SLATE = [
    # id, ET game date, UTC tip time
    ('F', '2026-11-09', '2026-11-10T00:00:00Z'),
    ('A', '2026-11-10', '2026-11-11T00:00:00Z'),
    ('B', '2026-11-10', '2026-11-11T03:00:00Z'),
    ('C', '2026-11-11', '2026-11-12T00:30:00Z'),
    ('D', '2026-11-11', '2026-11-12T03:30:00Z'),
    ('E', '2026-11-12', '2026-11-13T00:00:00Z'),
]

# (label, frozen now in US Pacific, expected game ids)
CASES = [
    ('noon PT: today still ahead', '2026-11-10 12:00', ['A', 'B']),
    ('6 PM PT: A tipped, B not yet', '2026-11-10 18:00', ['B']),
    ('8 PM PT: all of today tipped', '2026-11-10 20:00', ['C', 'D']),
    ('10 PM PT: already tomorrow in ET', '2026-11-10 22:00', ['C', 'D']),
]


def pacific(ts):
    return pd.Timestamp(ts).tz_localize('America/Los_Angeles')


@pytest.mark.parametrize('label,now,expected', CASES)
def test_next_slate(label, now, expected):
    games = pd.DataFrame(SLATE, columns=['GAME_ID', 'GAME_DATE', 'TIP_TIME_UTC'])
    games['GAME_DATE'] = games['GAME_DATE'] + 'T00:00:00Z'   # NBA gameDateEst shape
    kept = nextSlate(games, pacific(now))
    assert sorted(kept['GAME_ID']) == expected, label


def test_next_slate_empty_when_nothing_left_in_window():
    games = pd.DataFrame(SLATE, columns=['GAME_ID', 'GAME_DATE', 'TIP_TIME_UTC'])
    # Nov 10 at 9 AM PT: A/B are today but E is out of the window; then
    # Nov 12 at 10 PM PT (Nov 13 ET): every game has tipped.
    assert 'E' not in set(nextSlate(games, pacific('2026-11-10 09:00'))['GAME_ID'])
    assert nextSlate(games, pacific('2026-11-12 22:00')).empty


def test_next_slate_rejects_naive_now():
    games = pd.DataFrame(SLATE, columns=['GAME_ID', 'GAME_DATE', 'TIP_TIME_UTC'])
    with pytest.raises(ValueError):
        nextSlate(games, pd.Timestamp('2026-11-10 22:00'))


def run_in_sport(sport, code):
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT / sport)
    return subprocess.run([sys.executable, '-c', code], capture_output=True,
                          text=True, cwd=ROOT, timeout=120, env=env)


BASKETBALL_CHECK = """
import sys, tempfile
import pandas as pd
from data_pipeline.basketball_data import BasketballData

slate = {slate!r}
cases = {cases!r}
names = ['Boston Celtics', 'Los Angeles Lakers', 'Denver Nuggets', 'Houston Rockets',
         'Toronto Raptors', 'Memphis Grizzlies', 'Atlanta Hawks', 'Utah Jazz',
         'Miami Heat', 'Phoenix Suns', 'Chicago Bulls', 'Dallas Mavericks']
tricodes = ['BOS', 'LAL', 'DEN', 'HOU', 'TOR', 'MEM', 'ATL', 'UTA', 'MIA', 'PHX', 'CHI', 'DAL']
schedule = pd.DataFrame([{{
    'gameId': gid, 'gameDateEst': d + 'T00:00:00Z', 'gameDateTimeUTC': tip,
    'gameDateTimeEst': 'ignored', 'gameStatus': 1,
    'homeTeam_teamName': names[2 * i].split()[-1], 'homeTeam_teamTricode': tricodes[2 * i],
    'awayTeam_teamName': names[2 * i + 1].split()[-1], 'awayTeam_teamTricode': tricodes[2 * i + 1],
}} for i, (gid, d, tip) in enumerate(slate)])

with tempfile.TemporaryDirectory() as tmp:
    bd = BasketballData(data_dir=tmp)
    bd.retryApiCall = lambda fn: schedule.copy()   # no network
    for label, now, expected in cases:
        now = pd.Timestamp(now).tz_localize('America/Los_Angeles')
        games = bd.getUpcomingGames(now=now)
        assert sorted(games['GAME_ID']) == expected, (label, list(games['GAME_ID']))
        saved = pd.read_csv(f'{{tmp}}/upcoming_games.csv')
        assert sorted(saved['GAME_ID']) == expected, label
        # downstream shape unchanged: same columns, full team names, ET game date
        assert list(saved.columns) == ['GAME_ID', 'GAME_DATE', 'HOME_TEAM', 'TEAM_ABB_HOME', 'AWAY_TEAM', 'TEAM_ABB_AWAY'], list(saved.columns)
        assert saved['HOME_TEAM'].notna().all() and saved['AWAY_TEAM'].notna().all()
        assert saved['GAME_DATE'].str.endswith('T00:00:00Z').all()
print('ok')
"""


def test_basketball_get_upcoming_games_frozen_now():
    code = BASKETBALL_CHECK.format(slate=SLATE, cases=CASES)
    result = run_in_sport('basketball', code)
    assert result.returncode == 0, f'basketball slate check failed:\n{result.stdout}\n{result.stderr}'


HOCKEY_CHECK = """
import tempfile
from collections import defaultdict
import pandas as pd
from data_pipeline.hockey_data import HockeyData

slate = {slate!r}
cases = {cases!r}
days = defaultdict(list)
for i, (gid, d, tip) in enumerate(slate):
    days[d].append({{
        'id': gid, 'gameType': 2, 'startTimeUTC': tip,
        'homeTeam': {{'abbrev': f'H{{i}}', 'placeName': {{'default': 'Home'}}, 'commonName': {{'default': str(i)}}}},
        'awayTeam': {{'abbrev': f'A{{i}}', 'placeName': {{'default': 'Away'}}, 'commonName': {{'default': str(i)}}}},
    }})

requested = []
def fake_request(url, max_retries=None):
    requested.append(url)
    start = url.rsplit('/', 1)[-1]
    # like the NHL API: gameWeek begins at the requested date
    return {{'gameWeek': [{{'date': d, 'games': g}} for d, g in sorted(days.items()) if d >= start]}}

with tempfile.TemporaryDirectory() as tmp:
    hd = HockeyData(data_dir=tmp)
    hd.makeRequest = fake_request   # no network
    for label, now, expected in cases:
        now = pd.Timestamp(now).tz_localize('America/Los_Angeles')
        games = hd.getUpcomingGames(now=now)
        assert sorted(games['GAME_ID']) == expected, (label, list(games.get('GAME_ID', [])))
        assert 'TIP_TIME_UTC' not in games.columns
    # the schedule is requested by the US Eastern date: 10 PM PT Nov 10 is Nov 11 ET
    assert requested[-1].endswith('/schedule/2026-11-11'), requested[-1]
    assert requested[0].endswith('/schedule/2026-11-10'), requested[0]
print('ok')
"""


def test_hockey_get_upcoming_games_frozen_now():
    code = HOCKEY_CHECK.format(slate=SLATE, cases=CASES)
    result = run_in_sport('hockey', code)
    assert result.returncode == 0, f'hockey slate check failed:\n{result.stdout}\n{result.stderr}'
