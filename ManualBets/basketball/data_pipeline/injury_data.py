"""Basketball injury data: ESPN fetch + player-ID matching layer.

Extracted from origin/injury (commit b64cab7 lineage) per basketball/NOTES.md
salvage decision. Deliberately EXCLUDES that branch's severity composite and any
probability/margin adjustment math — when Tier-2 injuries are revived, raw
components feed the MODEL; it learns the weights (NOTES.md §Owner rulings).

Change vs source branch: every snapshot write also appends a dated copy under
injury_data/archive/ so point-in-time history accumulates and becomes trainable
(NOTES.md Tier-2 requirement #1). This module is NOT wired into the pipeline yet.
"""

import time
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests


class InjuryData:

    # OUT/DOUBTFUL = fully out; QUESTIONABLE = half-weight; kept for the future
    # availability features — do NOT use for hard selection removal.
    INJURY_WEIGHTS = {
        'OUT': 1.0,
        'DOUBTFUL': 1.0,
        'QUESTIONABLE': 0.5,
        'PROBABLE': 0.1,
    }

    def __init__(self, data_dir='././data/basketball'):
        self.data_dir = Path(data_dir)
        self.injury_dir = self.data_dir / 'injury_data'
        self.injury_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir = self.injury_dir / 'archive'
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.injury_file = self.injury_dir / 'current_injuries.csv'

    # ------------------------------------------------------------------ reads

    def getInjuredPlayers(self):
        """Player IDs to REMOVE from top-player selection (OUT, DOUBTFUL only)."""
        df = self._loadInjuries()
        if df is None:
            return set()
        active = df[df['status'].isin(['OUT', 'DOUBTFUL'])]
        return set(active['player_id'].astype(int).values)

    def getInjuredPlayersByTeam(self, team_abbr):
        """OUT/DOUBTFUL player IDs for one team."""
        df = self._loadInjuries()
        if df is None:
            return set()
        team_injuries = df[
            (df['team_abbreviation'] == team_abbr) &
            (df['status'].isin(['OUT', 'DOUBTFUL']))
        ]
        return set(team_injuries['player_id'].astype(int).values)

    def getQuestionablePlayersByTeam(self, team_abbr):
        """QUESTIONABLE player IDs for one team (weighted, never removed)."""
        df = self._loadInjuries()
        if df is None:
            return set()
        questionable = df[
            (df['team_abbreviation'] == team_abbr) &
            (df['status'] == 'QUESTIONABLE')
        ]
        return set(questionable['player_id'].astype(int).values)

    def getAllInjuredPlayersByTeam(self, team_abbr):
        """{player_id: status} for OUT/DOUBTFUL/QUESTIONABLE on one team."""
        df = self._loadInjuries()
        if df is None:
            return {}
        team_injuries = df[
            (df['team_abbreviation'] == team_abbr) &
            (df['status'].isin(['OUT', 'DOUBTFUL', 'QUESTIONABLE']))
        ]
        return dict(zip(team_injuries['player_id'].astype(int), team_injuries['status']))

    def getInjuryReport(self):
        df = self._loadInjuries()
        if df is None or df.empty:
            return "No injury data available"

        report = "\n" + "=" * 80 + "\nCURRENT INJURY REPORT\n" + "=" * 80 + "\n\n"
        for team in sorted(df['team_abbreviation'].unique()):
            report += f"{team}:\n"
            for _, player in df[df['team_abbreviation'] == team].iterrows():
                report += f"  - {player['player_name']}: {player['status']}"
                if pd.notna(player['injury_description']) and player['injury_description']:
                    report += f" ({player['injury_description']})"
                report += "\n"
            report += "\n"
        report += "=" * 80 + "\n"
        return report

    def _loadInjuries(self):
        if not self.injury_file.exists():
            return None
        try:
            return pd.read_csv(self.injury_file)
        except Exception as e:
            print(f"Error reading injury file: {e}")
            return None

    # ----------------------------------------------------------------- writes

    def updateInjuryData(self, player_id, player_name, team_abbr, status, injury_description=''):
        if self.injury_file.exists():
            injury_df = pd.read_csv(self.injury_file)
        else:
            injury_df = pd.DataFrame(columns=[
                'player_id', 'player_name', 'team_abbreviation',
                'status', 'injury_description', 'last_updated'
            ])
        injury_df = injury_df[injury_df['player_id'] != player_id]
        if status != 'ACTIVE':
            new_entry = pd.DataFrame([{
                'player_id': player_id,
                'player_name': player_name,
                'team_abbreviation': team_abbr,
                'status': status,
                'injury_description': injury_description,
                'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }])
            injury_df = pd.concat([injury_df, new_entry], ignore_index=True)
        self._writeSnapshot(injury_df)

    def bulkUpdateInjuries(self, injury_list):
        if not injury_list:
            return
        injury_df = pd.DataFrame(injury_list)
        injury_df['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self._writeSnapshot(injury_df)

    def clearInjuries(self):
        if self.injury_file.exists():
            self.injury_file.unlink()

    def _writeSnapshot(self, injury_df):
        """Write current snapshot AND a dated archive copy (trainable history)."""
        injury_df.to_csv(self.injury_file, index=False)
        today = datetime.now().strftime('%Y-%m-%d')
        injury_df.to_csv(self.archive_dir / f'injuries_{today}.csv', index=False)

    # ------------------------------------------------------------- ESPN fetch

    def correctTeamAbbreviation(self, espn_abbr):
        corrections = {
            'GS': 'GSW',    # Golden State Warriors
            'NO': 'NOP',    # New Orleans Pelicans
            'NY': 'NYK',    # New York Knicks
            'UTAH': 'UTA',  # Utah Jazz
            'WSH': 'WAS',   # Washington Wizards
            'SA': 'SAS',    # San Antonio Spurs
        }
        return corrections.get(espn_abbr, espn_abbr)

    def getTeamAbbreviation(self, team_name):
        team_map = {
            'Atlanta Hawks': 'ATL', 'Boston Celtics': 'BOS', 'Brooklyn Nets': 'BKN',
            'Charlotte Hornets': 'CHA', 'Chicago Bulls': 'CHI', 'Cleveland Cavaliers': 'CLE',
            'Dallas Mavericks': 'DAL', 'Denver Nuggets': 'DEN', 'Detroit Pistons': 'DET',
            'Golden State Warriors': 'GSW', 'Houston Rockets': 'HOU', 'Indiana Pacers': 'IND',
            'LA Clippers': 'LAC', 'Los Angeles Lakers': 'LAL', 'Memphis Grizzlies': 'MEM',
            'Miami Heat': 'MIA', 'Milwaukee Bucks': 'MIL', 'Minnesota Timberwolves': 'MIN',
            'New Orleans Pelicans': 'NOP', 'New York Knicks': 'NYK', 'Oklahoma City Thunder': 'OKC',
            'Orlando Magic': 'ORL', 'Philadelphia 76ers': 'PHI', 'Phoenix Suns': 'PHX',
            'Portland Trail Blazers': 'POR', 'Sacramento Kings': 'SAC', 'San Antonio Spurs': 'SAS',
            'Toronto Raptors': 'TOR', 'Utah Jazz': 'UTA', 'Washington Wizards': 'WAS'
        }
        return team_map.get(team_name, None)

    def fetchInjuriesFromESPN(self):
        try:
            url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            injuries = []

            for team_data in data.get('sports', [{}])[0].get('leagues', [{}])[0].get('teams', []):
                team = team_data.get('team', {})
                team_name = team.get('displayName', '')
                team_abbr = team.get('abbreviation', '')
                team_id = team.get('id', '')

                if not team_abbr or not team_id:
                    continue

                team_abbr = self.correctTeamAbbreviation(team_abbr)

                roster_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"

                try:
                    roster_response = requests.get(roster_url, headers=headers, timeout=10)
                    roster_response.raise_for_status()
                    roster_data = roster_response.json()

                    for athlete_data in roster_data.get('athletes', []):
                        player_name = athlete_data.get('displayName', '')
                        for injury in athlete_data.get('injuries', []):
                            status_text = injury.get('status', '')
                            injury_type = injury.get('type', '')
                            injury_date = injury.get('date', '')

                            status_mapped = self._mapInjuryStatus(status_text)

                            if status_mapped in ['OUT', 'DOUBTFUL', 'QUESTIONABLE']:
                                injuries.append({
                                    'player_id': 0,
                                    'player_name': player_name,
                                    'team_abbreviation': team_abbr,
                                    'status': status_mapped,
                                    'injury_description': injury_type if injury_type else injury_date
                                })

                    time.sleep(0.2)

                except Exception as e:
                    print(f"  Error fetching roster for {team_name}: {e}")
                    continue

            if injuries:
                injury_df = pd.DataFrame(injuries)
                injury_df['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                self._writeSnapshot(injury_df)
                print(f"\nFetched {len(injuries)} injuries from ESPN API")
                return True

            print("\nNo injuries found")
            return False

        except Exception as e:
            print(f"Error fetching injuries from ESPN API: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _mapInjuryStatus(self, status):
        status_upper = status.upper()
        if 'OUT' in status_upper:
            return 'OUT'
        elif 'DOUBT' in status_upper:
            return 'DOUBTFUL'
        elif 'QUESTION' in status_upper:
            return 'QUESTIONABLE'
        elif 'PROB' in status_upper:
            return 'PROBABLE'
        elif 'DAY' in status_upper:
            return 'QUESTIONABLE'
        else:
            return 'OUT'

    # ------------------------------------------------------------ ID matching

    def _normalizePlayerName(self, name):
        """Remove diacritics and lowercase: Jokic -> jokic, Valanciunas -> valanciunas."""
        normalized = unicodedata.normalize('NFD', name)
        ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
        return ascii_name.lower()

    def matchPlayerIDs(self, player_data_dir='././data/basketball/player_data'):
        try:
            player_dir = Path(player_data_dir)
            player_files = sorted(player_dir.glob('*_player_stats.csv'))

            if not player_files:
                print("No player data files found to match IDs")
                return False

            latest_file = player_files[-1]
            print(f"Matching player IDs using: {latest_file.name}")
            player_df = pd.read_csv(latest_file)

            player_lookup = player_df[['PLAYER_ID', 'PLAYER_NAME']].drop_duplicates()
            player_lookup['PLAYER_NAME_NORMALIZED'] = player_lookup['PLAYER_NAME'].apply(self._normalizePlayerName)

            if not self.injury_file.exists():
                return False

            injury_df = pd.read_csv(self.injury_file)

            updated = False
            matched_count = 0
            unmatched_count = 0

            for idx, row in injury_df.iterrows():
                if row['player_id'] == 0:
                    player_name_normalized = self._normalizePlayerName(row['player_name'])
                    match = player_lookup[player_lookup['PLAYER_NAME_NORMALIZED'] == player_name_normalized]

                    if not match.empty:
                        injury_df.at[idx, 'player_id'] = match.iloc[0]['PLAYER_ID']
                        updated = True
                        matched_count += 1
                    else:
                        print(f"  NOT MATCHED: {row['player_name']} ({row['team_abbreviation']})")
                        unmatched_count += 1

            if updated:
                self._writeSnapshot(injury_df)
                print(f"Matched {matched_count} players, {unmatched_count} unmatched")
                return True

            print(f"No matches found ({unmatched_count} unmatched)")
            return False

        except Exception as e:
            print(f"Error matching player IDs: {e}")
            return False
