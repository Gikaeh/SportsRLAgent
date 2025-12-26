from nba_api.stats.endpoints import commonteamroster
from nba_api.stats.static import teams
import pandas as pd
import time
from pathlib import Path
from datetime import datetime
import requests
from bs4 import BeautifulSoup

class InjuryData:
    
    def __init__(self, data_dir='././data/basketball'):
        self.data_dir = Path(data_dir)
        self.injury_dir = self.data_dir / 'injury_data'
        self.injury_dir.mkdir(parents=True, exist_ok=True)
        self.injury_file = self.injury_dir / 'current_injuries.csv'
        
    def getInjuredPlayers(self):
        if self.injury_file.exists():
            try:
                injury_df = pd.read_csv(self.injury_file)
                active_injuries = injury_df[injury_df['status'].isin(['OUT', 'DOUBTFUL', 'QUESTIONABLE'])]
                return set(active_injuries['player_id'].astype(int).values)
            except Exception as e:
                print(f"Error reading injury file: {e}")
                return set()
        return set()
    
    def getInjuredPlayersByTeam(self, team_abbr):
        if self.injury_file.exists():
            try:
                injury_df = pd.read_csv(self.injury_file)
                team_injuries = injury_df[
                    (injury_df['team_abbreviation'] == team_abbr) & 
                    (injury_df['status'].isin(['OUT', 'DOUBTFUL', 'QUESTIONABLE']))
                ]
                return set(team_injuries['player_id'].astype(int).values)
            except Exception as e:
                print(f"Error reading injury file for team {team_abbr}: {e}")
                return set()
        return set()
    
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
        injury_df.to_csv(self.injury_file, index=False)
        print(f"Updated injury status for {player_name} ({team_abbr}): {status}")
    
    def bulkUpdateInjuries(self, injury_list):
        if not injury_list:
            return
        
        injury_df = pd.DataFrame(injury_list)
        injury_df['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        injury_df.to_csv(self.injury_file, index=False)
        print(f"Bulk updated {len(injury_list)} injury records")
    
    def clearInjuries(self):
        if self.injury_file.exists():
            self.injury_file.unlink()
            print("Cleared all injury data")
    
    def getInjuryReport(self):
        if not self.injury_file.exists():
            return "No injury data available"
        
        injury_df = pd.read_csv(self.injury_file)
        
        if injury_df.empty:
            return "No injuries reported"
        report = "\n" + "="*80 + "\n"
        report += "CURRENT INJURY REPORT\n"
        report += "="*80 + "\n\n"
        
        for team in sorted(injury_df['team_abbreviation'].unique()):
            team_injuries = injury_df[injury_df['team_abbreviation'] == team]
            report += f"{team}:\n"
            for _, player in team_injuries.iterrows():
                report += f"  - {player['player_name']}: {player['status']}"
                if pd.notna(player['injury_description']) and player['injury_description']:
                    report += f" ({player['injury_description']})"
                report += "\n"
            report += "\n"
        
        report += "="*80 + "\n"
        return report
    
    def exportInjuryTemplate(self):
        template_file = self.injury_dir / 'injury_template.csv'
        template_df = pd.DataFrame(columns=[
            'player_id', 'player_name', 'team_abbreviation', 
            'status', 'injury_description'
        ])
        template_df = pd.concat([template_df, pd.DataFrame([{
            'player_id': 0,
            'player_name': 'Example Player',
            'team_abbreviation': 'LAL',
            'status': 'OUT',
            'injury_description': 'Knee injury'
        }])], ignore_index=True)
        
        template_df.to_csv(template_file, index=False)
        print(f"Exported injury template to {template_file}")
        print("Status options: OUT, DOUBTFUL, QUESTIONABLE, PROBABLE, ACTIVE")
        return template_file
    
    def importInjuriesFromCSV(self, csv_path):
        try:
            import_df = pd.read_csv(csv_path)
            required_cols = ['player_id', 'player_name', 'team_abbreviation', 'status']
            
            if not all(col in import_df.columns for col in required_cols):
                raise ValueError(f"CSV must contain columns: {required_cols}")
            import_df = import_df[import_df['player_id'] != 0]
            
            if 'injury_description' not in import_df.columns:
                import_df['injury_description'] = ''
            
            import_df['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            import_df.to_csv(self.injury_file, index=False)
            
            print(f"Imported {len(import_df)} injury records from {csv_path}")
            return True
            
        except Exception as e:
            print(f"Error importing injuries: {e}")
            return False
    
    def correctTeamAbbreviation(self, espn_abbr):
        corrections = {
            'GS': 'GSW',    # Golden State Warriors
            'NO': 'NOP',    # New Orleans Pelicans
            'NY': 'NYK',    # New York Knicks
            'UTAH': 'UTA',  # Utah Jazz
            'WSH': 'WAS',   # Washington Wizards
        }
        return corrections.get(espn_abbr, espn_abbr)
    
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
                
                # Correct team abbreviation to match NBA API format
                team_abbr = self.correctTeamAbbreviation(team_abbr)
                
                print(f"Processing team: {team_name} ({team_abbr})")
                
                roster_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
                
                try:
                    roster_response = requests.get(roster_url, headers=headers, timeout=10)
                    roster_response.raise_for_status()
                    roster_data = roster_response.json()
                    
                    for athlete_data in roster_data.get('athletes', []):
                        player_name = athlete_data.get('displayName', '')
                        player_injuries = athlete_data.get('injuries', [])
                        
                        if player_injuries:
                            for injury in player_injuries:
                                status_text = injury.get('status', '')
                                injury_type = injury.get('type', '')
                                injury_date = injury.get('date', '')
                                
                                status_mapped = self._mapInjuryStatus(status_text)
                                
                                print(f"  Player: {player_name} | Status: {status_text} -> {status_mapped}")
                                
                                if status_mapped in ['OUT', 'DOUBTFUL', 'QUESTIONABLE']:
                                    injuries.append({
                                        'player_id': 0,
                                        'player_name': player_name,
                                        'team_abbreviation': team_abbr,
                                        'status': status_mapped,
                                        'injury_description': injury_type if injury_type else injury_date
                                    })
                                    print(f"    ADDED to injury list")
                    
                    time.sleep(0.2)
                    
                except Exception as e:
                    print(f"  Error fetching roster for {team_name}: {e}")
                    continue
            
            if injuries:
                injury_df = pd.DataFrame(injuries)
                injury_df['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                injury_df.to_csv(self.injury_file, index=False)
                print(f"\nFetched {len(injuries)} injuries from ESPN API")
                return True
            else:
                print("\nNo injuries found")
                return False
                
        except Exception as e:
            print(f"Error fetching injuries from ESPN API: {e}")
            import traceback
            traceback.print_exc()
            return False
    
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
    
    def fixTeamAbbreviations(self):
        if not self.injury_file.exists():
            print("No injury file found to fix")
            return False
        
        try:
            injury_df = pd.read_csv(self.injury_file)
            
            corrections = {
                'GS': 'GSW',
                'NO': 'NOP',
                'NY': 'NYK',
                'UTAH': 'UTA',
                'WSH': 'WAS',
            }
            
            fixed_count = 0
            for old_abbr, new_abbr in corrections.items():
                mask = injury_df['team_abbreviation'] == old_abbr
                count = mask.sum()
                if count > 0:
                    injury_df.loc[mask, 'team_abbreviation'] = new_abbr
                    fixed_count += count
                    print(f"Fixed {count} entries: {old_abbr} -> {new_abbr}")
            
            if fixed_count > 0:
                injury_df.to_csv(self.injury_file, index=False)
                print(f"\nTotal: Fixed {fixed_count} team abbreviations")
                return True
            else:
                print("No team abbreviations needed fixing")
                return False
                
        except Exception as e:
            print(f"Error fixing team abbreviations: {e}")
            return False
    
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
            player_lookup['PLAYER_NAME_LOWER'] = player_lookup['PLAYER_NAME'].str.lower()
            
            if not self.injury_file.exists():
                return False
            
            injury_df = pd.read_csv(self.injury_file)
            
            updated = False
            matched_count = 0
            unmatched_count = 0
            
            for idx, row in injury_df.iterrows():
                if row['player_id'] == 0:
                    player_name_lower = row['player_name'].lower()
                    match = player_lookup[player_lookup['PLAYER_NAME_LOWER'] == player_name_lower]
                    
                    if not match.empty:
                        injury_df.at[idx, 'player_id'] = match.iloc[0]['PLAYER_ID']
                        print(f"  Matched: {row['player_name']} -> ID {match.iloc[0]['PLAYER_ID']}")
                        updated = True
                        matched_count += 1
                    else:
                        print(f"  NOT MATCHED: {row['player_name']} ({row['team_abbreviation']})")
                        unmatched_count += 1
            
            if updated:
                injury_df.to_csv(self.injury_file, index=False)
                print(f"Matched {matched_count} players, {unmatched_count} unmatched")
                return True
            
            print(f"No matches found ({unmatched_count} unmatched)")
            return False
            
        except Exception as e:
            print(f"Error matching player IDs: {e}")
            return False
