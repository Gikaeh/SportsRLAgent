import pandas as pd
import time
from pathlib import Path
from datetime import datetime
import requests

class HockeyInjuryData:
    
    def __init__(self, data_dir='././data/hockey'):
        self.data_dir = Path(data_dir)
        self.injury_dir = self.data_dir / 'injury_data'
        self.injury_dir.mkdir(parents=True, exist_ok=True)
        self.injury_file = self.injury_dir / 'current_injuries.csv'
        
        # NHL team abbreviations mapping
        self.team_mapping = {
            'Anaheim Ducks': 'ANA', 'Arizona Coyotes': 'ARI', 'Boston Bruins': 'BOS', 
            'Buffalo Sabres': 'BUF', 'Calgary Flames': 'CGY', 'Carolina Hurricanes': 'CAR', 
            'Chicago Blackhawks': 'CHI', 'Colorado Avalanche': 'COL', 'Columbus Blue Jackets': 'CBJ', 
            'Dallas Stars': 'DAL', 'Detroit Red Wings': 'DET', 'Edmonton Oilers': 'EDM', 
            'Florida Panthers': 'FLA', 'Los Angeles Kings': 'LAK', 'Minnesota Wild': 'MIN', 
            'Montreal Canadiens': 'MTL', 'Nashville Predators': 'NSH', 'New Jersey Devils': 'NJD', 
            'New York Islanders': 'NYI', 'New York Rangers': 'NYR', 'Ottawa Senators': 'OTT', 
            'Philadelphia Flyers': 'PHI', 'Pittsburgh Penguins': 'PIT', 'San Jose Sharks': 'SJS', 
            'Seattle Kraken': 'SEA', 'St. Louis Blues': 'STL', 'Tampa Bay Lightning': 'TBL', 
            'Toronto Maple Leafs': 'TOR', 'Vancouver Canucks': 'VAN', 'Vegas Golden Knights': 'VGK', 
            'Washington Capitals': 'WSH', 'Winnipeg Jets': 'WPG', 'Utah Hockey Club': 'UTA'
        }
        
    def getInjuredPlayers(self):
        """Get set of all injured player IDs"""
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
        """Get set of injured player IDs for a specific team"""
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
        """Update injury status for a single player"""
        if self.injury_file.exists():
            injury_df = pd.read_csv(self.injury_file)
        else:
            injury_df = pd.DataFrame(columns=[
                'player_id', 'player_name', 'team_abbreviation', 
                'status', 'injury_description', 'last_updated'
            ])
        
        # Remove existing entry for this player
        injury_df = injury_df[injury_df['player_id'] != player_id]
        
        # Add new entry if not active
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
        """Bulk update injuries from a list"""
        if not injury_list:
            return
        
        injury_df = pd.DataFrame(injury_list)
        injury_df['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        injury_df.to_csv(self.injury_file, index=False)
        print(f"Bulk updated {len(injury_list)} injury records")
    
    def clearInjuries(self):
        """Clear all injury data"""
        if self.injury_file.exists():
            self.injury_file.unlink()
            print("Cleared all injury data")
    
    def getInjuryReport(self):
        """Generate a formatted injury report"""
        if not self.injury_file.exists():
            return "No injury data available"
        
        injury_df = pd.read_csv(self.injury_file)
        
        if injury_df.empty:
            return "No injuries reported"
        
        report = "\n" + "="*80 + "\n"
        report += "CURRENT NHL INJURY REPORT\n"
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
    
    def fetchInjuriesFromESPN(self):
        """Fetch current injuries from ESPN API"""
        try:
            url = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/teams"
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
                
                # Correct team abbreviation if needed
                team_abbr = self._correctTeamAbbreviation(team_abbr)
                
                print(f"Processing team: {team_name} ({team_abbr})")
                
                roster_url = f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/teams/{team_id}/roster"
                
                try:
                    roster_response = requests.get(roster_url, headers=headers, timeout=10)
                    roster_response.raise_for_status()
                    roster_data = roster_response.json()
                                        
                    for position_data in roster_data.get('athletes', []):
                        for athlete_data in position_data.get('items', []):
                            player_name = athlete_data.get('shortName', '')
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
                                            'player_id': 0,  # Will be matched later
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
    
    def _correctTeamAbbreviation(self, espn_abbr):
        """Correct ESPN team abbreviations to match NHL API format"""
        corrections = {
            'LA': 'LAK',    # Los Angeles Kings
            'NJ': 'NJD',    # New Jersey Devils
            'TB': 'TBL',    # Tampa Bay Lightning
            'SJ': 'SJS',    # San Jose Sharks
            'VGK': 'VGK',   # Vegas Golden Knights (already correct)
            'UTAH': 'UTA',  # Utah Hockey Club
        }
        return corrections.get(espn_abbr, espn_abbr)
    
    def _mapInjuryStatus(self, status):
        """Map various injury status strings to standard statuses"""
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
    
    def matchPlayerIDs(self, player_data_dir='././data/hockey/player_data'):
        """Match player names to IDs from player data files"""
        try:
            player_dir = Path(player_data_dir)
            player_files = sorted(player_dir.glob('*_player_stats.csv'))
            
            if not player_files:
                print("No player data files found to match IDs")
                return False
            
            # Use the most recent player data file
            latest_file = player_files[-1]
            print(f"Matching player IDs using: {latest_file.name}")
            player_df = pd.read_csv(latest_file)
            
            # Create lookup table
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
                    
                    print(f"  Player: {row['player_name']} | Match: {match.empty}")
                    
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
    
    def exportInjuryTemplate(self):
        """Export a template CSV for manual injury entry"""
        template_file = self.injury_dir / 'injury_template.csv'
        template_df = pd.DataFrame(columns=[
            'player_id', 'player_name', 'team_abbreviation', 
            'status', 'injury_description'
        ])
        template_df = pd.concat([template_df, pd.DataFrame([{
            'player_id': 0,
            'player_name': 'Example Player',
            'team_abbreviation': 'TOR',
            'status': 'OUT',
            'injury_description': 'Upper body injury'
        }])], ignore_index=True)
        
        template_df.to_csv(template_file, index=False)
        print(f"Exported injury template to {template_file}")
        print("Status options: OUT, DOUBTFUL, QUESTIONABLE, PROBABLE, ACTIVE")
        return template_file
    
    def calculateInjuryImpact(self, team_abbr, latest_skater_stats):
        """
        Calculate the impact of injuries on a team's production.
        Returns dict with injury impact metrics.
        """
        injured_player_ids = self.getInjuredPlayersByTeam(team_abbr)
        
        if not injured_player_ids:
            return {
                'points_lost': 0.0,
                'goals_lost': 0.0,
                'assists_lost': 0.0,
                'toi_lost': 0.0,
                'num_injured': 0,
                'star_out': 0,
                'star_name': '',
                'rotation_players_out': 0,
                'injury_severity': 0.0
            }
        
        team_players = latest_skater_stats[latest_skater_stats['TEAM_ABBREVIATION'] == team_abbr]
        injured_players = team_players[team_players['PLAYER_ID'].isin(injured_player_ids)]
        
        if injured_players.empty:
            return {
                'points_lost': 0.0,
                'goals_lost': 0.0,
                'assists_lost': 0.0,
                'toi_lost': 0.0,
                'num_injured': 0,
                'star_out': 0,
                'star_name': '',
                'rotation_players_out': 0,
                'injury_severity': 0.0
            }
        
        points_lost = injured_players['points_rolling'].sum() if 'points_rolling' in injured_players.columns else 0
        goals_lost = injured_players['goals_rolling'].sum() if 'goals_rolling' in injured_players.columns else 0
        assists_lost = injured_players['assists_rolling'].sum() if 'assists_rolling' in injured_players.columns else 0
        toi_lost = injured_players['toi_rolling'].sum() if 'toi_rolling' in injured_players.columns else 0
        
        # Star out = one of team's top 3 points players is injured
        star_out = 0
        star_name = ''
        if 'points_rolling' in team_players.columns:
            top_3_points = team_players.nlargest(3, 'points_rolling')['PLAYER_ID'].tolist()
            injured_stars = injured_players[injured_players['PLAYER_ID'].isin(top_3_points)]
            if not injured_stars.empty:
                star_out = 1
                if 'PLAYER_NAME' in injured_stars.columns:
                    star_name = injured_stars.iloc[0]['PLAYER_NAME']
        
        rotation_players_out = len(injured_players[injured_players['toi_rolling'] >= 12])  # 12+ min = rotation player
        
        injury_severity = (points_lost / 50) + (toi_lost / 100) + (star_out * 0.3)
        injury_severity = min(injury_severity, 1.0)
        
        return {
            'points_lost': round(points_lost, 1),
            'goals_lost': round(goals_lost, 1),
            'assists_lost': round(assists_lost, 1),
            'toi_lost': round(toi_lost, 1),
            'num_injured': len(injured_players),
            'star_out': star_out,
            'star_name': star_name,
            'rotation_players_out': rotation_players_out,
            'injury_severity': round(injury_severity, 3)
        }
    
    def getInjuryImpactForGame(self, home_team, away_team, latest_skater_stats):
        """
        Get injury impact for both teams in a game.
        Returns dict with home and away injury metrics.
        """
        home_impact = self.calculateInjuryImpact(home_team, latest_skater_stats)
        away_impact = self.calculateInjuryImpact(away_team, latest_skater_stats)
        
        return {
            'home_points_lost': home_impact['points_lost'],
            'home_goals_lost': home_impact['goals_lost'],
            'home_assists_lost': home_impact['assists_lost'],
            'home_toi_lost': home_impact['toi_lost'],
            'home_num_injured': home_impact['num_injured'],
            'home_star_out': home_impact['star_out'],
            'home_rotation_out': home_impact['rotation_players_out'],
            'home_injury_severity': home_impact['injury_severity'],
            'away_points_lost': away_impact['points_lost'],
            'away_goals_lost': away_impact['goals_lost'],
            'away_assists_lost': away_impact['assists_lost'],
            'away_toi_lost': away_impact['toi_lost'],
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
    
    def getInjurySummaryForGame(self, home_team, away_team, latest_skater_stats):
        """
        Get a formatted injury summary for display in betting recommendations.
        """
        home_impact = self.calculateInjuryImpact(home_team, latest_skater_stats)
        away_impact = self.calculateInjuryImpact(away_team, latest_skater_stats)
        
        summary = []
        
        if home_impact['num_injured'] > 0 or away_impact['num_injured'] > 0:
            summary.append(f"INJURY IMPACT:")
            
            if home_impact['num_injured'] > 0:
                star_indicator = f" STAR OUT ({home_impact['star_name']})" if home_impact['star_out'] and home_impact['star_name'] else (" ⚠️ STAR OUT" if home_impact['star_out'] else "")
                summary.append(f"  {home_team} (Home): {home_impact['num_injured']} out, -{home_impact['points_lost']:.1f} PTS{star_indicator}")
            
            if away_impact['num_injured'] > 0:
                star_indicator = f" STAR OUT ({away_impact['star_name']})" if away_impact['star_out'] and away_impact['star_name'] else (" ⚠️ STAR OUT" if away_impact['star_out'] else "")
                summary.append(f"  {away_team} (Away): {away_impact['num_injured']} out, -{away_impact['points_lost']:.1f} PTS{star_indicator}")
            
            if home_impact['injury_severity'] > away_impact['injury_severity']:
                summary.append(f"  → Injury advantage: {away_team}")
            elif away_impact['injury_severity'] > home_impact['injury_severity']:
                summary.append(f"  → Injury advantage: {home_team}")
        
        return "\n".join(summary) if summary else ""
    
    def importInjuriesFromCSV(self, csv_path):
        """Import injuries from a CSV file"""
        try:
            import_df = pd.read_csv(csv_path)
            required_cols = ['player_id', 'player_name', 'team_abbreviation', 'status']
            
            if not all(col in import_df.columns for col in required_cols):
                raise ValueError(f"CSV must contain columns: {required_cols}")
            
            # Remove example entries
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
