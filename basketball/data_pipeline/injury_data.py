from nba_api.stats.endpoints import commonteamroster
from nba_api.stats.static import teams
import pandas as pd
import time
from pathlib import Path
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import unicodedata

class InjuryData:
    
    # Injury status weights for impact calculation
    # OUT/DOUBTFUL = 100% impact (fully removed from selection)
    # QUESTIONABLE = 50% impact (kept in selection, weighted in impact calc)
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
        self.injury_file = self.injury_dir / 'current_injuries.csv'
        
    def getInjuredPlayers(self):
        """Get players who should be REMOVED from top player selection (OUT, DOUBTFUL only)."""
        if self.injury_file.exists():
            try:
                injury_df = pd.read_csv(self.injury_file)
                # Only OUT and DOUBTFUL are removed - QUESTIONABLE players stay in selection
                active_injuries = injury_df[injury_df['status'].isin(['OUT', 'DOUBTFUL'])]
                return set(active_injuries['player_id'].astype(int).values)
            except Exception as e:
                print(f"Error reading injury file: {e}")
                return set()
        return set()
    
    def getInjuredPlayersByTeam(self, team_abbr):
        """Get players who should be REMOVED from top player selection for a team (OUT, DOUBTFUL only)."""
        if self.injury_file.exists():
            try:
                injury_df = pd.read_csv(self.injury_file)
                # Only OUT and DOUBTFUL are removed - QUESTIONABLE players stay in selection
                team_injuries = injury_df[
                    (injury_df['team_abbreviation'] == team_abbr) & 
                    (injury_df['status'].isin(['OUT', 'DOUBTFUL']))
                ]
                return set(team_injuries['player_id'].astype(int).values)
            except Exception as e:
                print(f"Error reading injury file for team {team_abbr}: {e}")
                return set()
        return set()
    
    def getQuestionablePlayersByTeam(self, team_abbr):
        """Get QUESTIONABLE players for a team (for weighted impact calculation)."""
        if self.injury_file.exists():
            try:
                injury_df = pd.read_csv(self.injury_file)
                questionable = injury_df[
                    (injury_df['team_abbreviation'] == team_abbr) & 
                    (injury_df['status'] == 'QUESTIONABLE')
                ]
                return set(questionable['player_id'].astype(int).values)
            except Exception as e:
                print(f"Error getting questionable players for {team_abbr}: {e}")
                return set()
        return set()
    
    def getAllInjuredPlayersByTeam(self, team_abbr):
        """Get ALL injured players for a team with their status (for impact calculation)."""
        if self.injury_file.exists():
            try:
                injury_df = pd.read_csv(self.injury_file)
                team_injuries = injury_df[
                    (injury_df['team_abbreviation'] == team_abbr) & 
                    (injury_df['status'].isin(['OUT', 'DOUBTFUL', 'QUESTIONABLE']))
                ]
                # Return dict of player_id -> status
                return dict(zip(team_injuries['player_id'].astype(int), team_injuries['status']))
            except Exception as e:
                print(f"Error getting all injured players for {team_abbr}: {e}")
                return {}
        return {}
    
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
            'SA': 'SAS',    # San Antonio Spurs
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
                
                # print(f"Processing team: {team_name} ({team_abbr})")
                
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
                                
                                # print(f"  Player: {player_name} | Status: {status_text} -> {status_mapped}")
                                
                                if status_mapped in ['OUT', 'DOUBTFUL', 'QUESTIONABLE']:
                                    injuries.append({
                                        'player_id': 0,
                                        'player_name': player_name,
                                        'team_abbreviation': team_abbr,
                                        'status': status_mapped,
                                        'injury_description': injury_type if injury_type else injury_date
                                    })
                                    # print(f"    ADDED to injury list")
                    
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
                'SA': 'SAS',
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
    
    def calculateInjuryImpact(self, team_abbr, latest_player_stats, debug=False):
        """
        Calculate the impact of injuries on a team's production.
        Uses weighted impact: OUT/DOUBTFUL = 100%, QUESTIONABLE = 50%
        Returns dict with injury impact metrics.
        """
        # Get all injured players with their status (includes OUT, DOUBTFUL, QUESTIONABLE)
        injured_player_status = self.getAllInjuredPlayersByTeam(team_abbr)
        
        if not injured_player_status:
            return {
                'ppg_lost': 0.0,
                'mpg_lost': 0.0,
                'apg_lost': 0.0,
                'rpg_lost': 0.0,
                'num_injured': 0,
                'num_out': 0,
                'num_questionable': 0,
                'star_out': 0,
                'rotation_players_out': 0,
                'injury_severity': 0.0
            }
        
        team_players = latest_player_stats[latest_player_stats['TEAM_ABBREVIATION'] == team_abbr]
        injured_player_ids = set(injured_player_status.keys())
        injured_players = team_players[team_players['PLAYER_ID'].isin(injured_player_ids)].copy()
        
        if debug:
            print(f"\n  DEBUG: calculateInjuryImpact for {team_abbr}")
            print(f"    Injured players from injury file: {injured_player_status}")
            print(f"    Team players in stats: {len(team_players)}")
            print(f"    Injured players matched in stats: {len(injured_players)}")
        
        if injured_players.empty:
            return {
                'ppg_lost': 0.0,
                'mpg_lost': 0.0,
                'apg_lost': 0.0,
                'rpg_lost': 0.0,
                'num_injured': 0,
                'num_out': 0,
                'num_questionable': 0,
                'star_out': 0,
                'star_name': '',
                'rotation_players_out': 0,
                'injury_severity': 0.0
            }
        
        # Add weight column based on injury status
        injured_players['injury_weight'] = injured_players['PLAYER_ID'].map(
            lambda pid: self.INJURY_WEIGHTS.get(injured_player_status.get(pid, 'OUT'), 1.0)
        )
        injured_players['injury_status'] = injured_players['PLAYER_ID'].map(injured_player_status)
        
        if debug and 'PLAYER_NAME' in injured_players.columns:
            print(f"    Matched injured players (with weights):")
            for _, p in injured_players.iterrows():
                print(f"      - {p['PLAYER_NAME']}: {p['ppg_rolling']:.1f} PPG, {p['mpg_rolling']:.1f} MPG, "
                      f"Status: {p['injury_status']}, Weight: {p['injury_weight']:.0%}")
        
        # Calculate weighted stats lost
        ppg_lost = (injured_players['ppg_rolling'] * injured_players['injury_weight']).sum() if 'ppg_rolling' in injured_players.columns else 0
        mpg_lost = (injured_players['mpg_rolling'] * injured_players['injury_weight']).sum() if 'mpg_rolling' in injured_players.columns else 0
        apg_lost = (injured_players['apg_rolling'] * injured_players['injury_weight']).sum() if 'apg_rolling' in injured_players.columns else 0
        rpg_lost = (injured_players['rpg_rolling'] * injured_players['injury_weight']).sum() if 'rpg_rolling' in injured_players.columns else 0
        
        # Count by status
        num_out = len(injured_players[injured_players['injury_status'].isin(['OUT', 'DOUBTFUL'])])
        num_questionable = len(injured_players[injured_players['injury_status'] == 'QUESTIONABLE'])
        
        # Star out = one of team's top 3 PPG players is OUT or DOUBTFUL (not questionable)
        star_out = 0
        star_name = ''
        if 'ppg_rolling' in team_players.columns:
            top_3_ppg = team_players.nlargest(3, 'ppg_rolling')['PLAYER_ID'].tolist()
            # Only count as star out if they're OUT or DOUBTFUL
            out_doubtful_ids = {pid for pid, status in injured_player_status.items() if status in ['OUT', 'DOUBTFUL']}
            injured_stars = injured_players[
                (injured_players['PLAYER_ID'].isin(top_3_ppg)) & 
                (injured_players['PLAYER_ID'].isin(out_doubtful_ids))
            ]
            if not injured_stars.empty:
                star_out = 1
                if 'PLAYER_NAME' in injured_stars.columns:
                    star_name = injured_stars.iloc[0]['PLAYER_NAME']
            
            if debug:
                print(f"    Top 3 PPG players on team: {top_3_ppg}")
                if 'PLAYER_NAME' in team_players.columns:
                    top_3_names = team_players.nlargest(3, 'ppg_rolling')[['PLAYER_NAME', 'ppg_rolling']].values.tolist()
                    print(f"    Top 3 by name: {top_3_names}")
                print(f"    Star out (OUT/DOUBTFUL only): {bool(star_out)} ({star_name if star_name else 'N/A'})")
        
        # Rotation players out = OUT/DOUBTFUL players with 15+ MPG
        out_doubtful_players = injured_players[injured_players['injury_status'].isin(['OUT', 'DOUBTFUL'])]
        rotation_players_out = len(out_doubtful_players[out_doubtful_players['mpg_rolling'] >= 15])
        
        injury_severity = (ppg_lost / 100) + (mpg_lost / 200) + (star_out * 0.3)
        injury_severity = min(injury_severity, 1.0)
        
        if debug:
            print(f"    Weighted PPG lost: {ppg_lost:.1f}")
            print(f"    OUT/DOUBTFUL: {num_out}, QUESTIONABLE: {num_questionable}")
            print(f"    Rotation players out (15+ MPG, OUT/DOUBTFUL): {rotation_players_out}")
        
        return {
            'ppg_lost': round(ppg_lost, 1),
            'mpg_lost': round(mpg_lost, 1),
            'apg_lost': round(apg_lost, 1),
            'rpg_lost': round(rpg_lost, 1),
            'num_injured': len(injured_players),
            'num_out': num_out,
            'num_questionable': num_questionable,
            'star_out': star_out,
            'star_name': star_name,
            'rotation_players_out': rotation_players_out,
            'injury_severity': round(injury_severity, 3)
        }
    
    def getInjuryImpactForGame(self, home_team, away_team, latest_player_stats):
        """
        Get injury impact for both teams in a game.
        Returns dict with home and away injury metrics.
        """
        home_impact = self.calculateInjuryImpact(home_team, latest_player_stats)
        away_impact = self.calculateInjuryImpact(away_team, latest_player_stats)
        
        return {
            'home_ppg_lost': home_impact['ppg_lost'],
            'home_mpg_lost': home_impact['mpg_lost'],
            'home_apg_lost': home_impact['apg_lost'],
            'home_rpg_lost': home_impact['rpg_lost'],
            'home_num_injured': home_impact['num_injured'],
            'home_star_out': home_impact['star_out'],
            'home_rotation_out': home_impact['rotation_players_out'],
            'home_injury_severity': home_impact['injury_severity'],
            'away_ppg_lost': away_impact['ppg_lost'],
            'away_mpg_lost': away_impact['mpg_lost'],
            'away_apg_lost': away_impact['apg_lost'],
            'away_rpg_lost': away_impact['rpg_lost'],
            'away_num_injured': away_impact['num_injured'],
            'away_star_out': away_impact['star_out'],
            'away_rotation_out': away_impact['rotation_players_out'],
            'away_injury_severity': away_impact['injury_severity'],
            'injury_advantage': away_impact['injury_severity'] - home_impact['injury_severity']
        }
    
    def getQuestionablePlayers(self, team_abbr):
        """Get players with QUESTIONABLE status for a team."""
        if self.injury_file.exists():
            try:
                injury_df = pd.read_csv(self.injury_file)
                questionable = injury_df[
                    (injury_df['team_abbreviation'] == team_abbr) & 
                    (injury_df['status'] == 'QUESTIONABLE')
                ]
                return list(questionable['player_name'].values)
            except Exception as e:
                print(f"Error getting questionable players: {e}")
                return []
        return []
    
    def getInjurySummaryForGame(self, home_team, away_team, latest_player_stats):
        """
        Get a formatted injury summary for display in betting recommendations.
        Now shows OUT/DOUBTFUL count separately from QUESTIONABLE.
        """
        home_impact = self.calculateInjuryImpact(home_team, latest_player_stats)
        away_impact = self.calculateInjuryImpact(away_team, latest_player_stats)
        
        summary = []
        
        if home_impact['num_injured'] > 0 or away_impact['num_injured'] > 0:
            summary.append(f"INJURY IMPACT:")
            
            if home_impact['num_injured'] > 0:
                star_indicator = f" STAR OUT ({home_impact['star_name']})" if home_impact['star_out'] and home_impact.get('star_name') else (" STAR OUT" if home_impact['star_out'] else "")
                # Show breakdown: X out, Y questionable
                out_count = home_impact.get('num_out', home_impact['num_injured'])
                q_count = home_impact.get('num_questionable', 0)
                status_str = f"{out_count} out" if out_count > 0 else ""
                if q_count > 0:
                    status_str += f", {q_count} questionable" if status_str else f"{q_count} questionable"
                summary.append(f"  {home_team} (Home): {status_str}, -{home_impact['ppg_lost']:.1f} PPG{star_indicator}")
            
            if away_impact['num_injured'] > 0:
                star_indicator = f" STAR OUT ({away_impact['star_name']})" if away_impact['star_out'] and away_impact.get('star_name') else (" STAR OUT" if away_impact['star_out'] else "")
                # Show breakdown: X out, Y questionable
                out_count = away_impact.get('num_out', away_impact['num_injured'])
                q_count = away_impact.get('num_questionable', 0)
                status_str = f"{out_count} out" if out_count > 0 else ""
                if q_count > 0:
                    status_str += f", {q_count} questionable" if status_str else f"{q_count} questionable"
                summary.append(f"  {away_team} (Away): {status_str}, -{away_impact['ppg_lost']:.1f} PPG{star_indicator}")
            
            if home_impact['injury_severity'] > away_impact['injury_severity']:
                summary.append(f"  → Injury advantage: {away_team}")
            elif away_impact['injury_severity'] > home_impact['injury_severity']:
                summary.append(f"  → Injury advantage: {home_team}")
        
        return "\n".join(summary) if summary else ""
    
    def _normalizePlayerName(self, name):
        """Normalize player name by removing diacritics and converting to lowercase.
        Handles cases like Jokić -> jokic, Valančiūnas -> valanciunas
        """
        # Normalize unicode to decomposed form (separates base char from diacritics)
        normalized = unicodedata.normalize('NFD', name)
        # Remove diacritical marks (combining characters)
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
                        # print(f"  Matched: {row['player_name']} -> ID {match.iloc[0]['PLAYER_ID']}")
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
