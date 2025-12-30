import subprocess
import json
import sys
from pathlib import Path
from datetime import datetime
from unified_bankroll import UnifiedBankroll

class UnifiedBettingSystem:
    def __init__(self):
        self.base_path = Path(__file__).parent
        self.unified_bankroll = self.calculateUnifiedBankroll()
        
    def calculateUnifiedBankroll(self):
        """Calculate unified bankroll across all sports using the UnifiedBankroll class"""
        return UnifiedBankroll.displayBankrollBreakdown()
    
    def getAllRecommendations(self, sport_choices):
        """Get recommendations from all selected sports using subprocess"""
        all_recommendations = []
        
        for sport in sport_choices:
            print(f"\n{'='*80}")
            print(f"FETCHING {sport.upper()} RECOMMENDATIONS")
            print(f"{'='*80}")
            
            try:
                result = subprocess.run(
                    [sys.executable, 'unified_betting_helper.py', sport],
                    cwd=str(self.base_path),
                    capture_output=True,
                    text=True,
                    timeout=300  # Increased to 5 minutes
                )
                
                if result.returncode == 0:
                    # Parse JSON output
                    output_lines = result.stdout.strip().split('\n')
                    
                    # Print all output except last line for debugging
                    if len(output_lines) > 1:
                        for line in output_lines[:-1]:
                            if line.strip():
                                print(f"  {line}")
                    
                    json_line = output_lines[-1]  # Last line should be JSON
                    
                    try:
                        recommendations = json.loads(json_line)
                        all_recommendations.extend(recommendations)
                        print(f"Found {len(recommendations)} {sport} recommendations")
                    except json.JSONDecodeError as e:
                        print(f"Error parsing {sport} recommendations: {e}")
                        print("Last line:", json_line[:200])
                        print("Full output:", result.stdout[:500])
                else:
                    print(f"Error getting {sport} recommendations (exit code {result.returncode}):")
                    if result.stderr:
                        print("STDERR:", result.stderr[:500])
                    if result.stdout:
                        print("STDOUT:", result.stdout[:500])
                    
            # except subprocess.TimeoutExpired:
            #     print(f"Timeout getting {sport} recommendations (>300s)")
            except Exception as e:
                print(f"Error: {e}")
                import traceback
                traceback.print_exc()
        
        return all_recommendations
    
    def calculateBetPriority(self, bet):
        """Calculate bet priority with sport-specific weights"""
        weights = {'h2h': .3, 'spread': 1, 'total': .001}
        
        if bet['type'] == 'h2h':
            if bet['bet_side'] == 'home':
                win_prob = bet.get('home_model_prob', 0.5)
            else:
                win_prob = bet.get('away_model_prob', 0.5)
        elif bet['type'] in ['spread', 'total']:
            win_prob = bet.get('cover_prob', 0.5)
        else:
            win_prob = 0.5
        
        loss_prob = 1 - win_prob
        expected_value = (win_prob * bet['potential_profit']) - (loss_prob * bet['bet_amount'])
        ev_per_dollar = expected_value / bet['bet_amount'] if bet['bet_amount'] > 0 else 0
        roi = bet['potential_profit'] / bet['bet_amount'] if bet['bet_amount'] > 0 else 0
        base_priority = bet['confidence'] * ev_per_dollar * (1 + roi * 0.2)
        
        return base_priority * weights[bet['type']]
    
    def displayUnifiedRecommendations(self, recommendations):
        """Display recommendations from all sports with unified bankroll management"""
        if not recommendations:
            print("\n" + "="*80)
            print("NO BETTING OPPORTUNITIES FOUND")
            print("="*80)
            print("No games meet the minimum edge and probability requirements.")
            return
        
        # Sort by priority
        recommendations.sort(key=self.calculateBetPriority, reverse=True)
        
        # Apply unified bankroll constraint (max 100% of bankroll)
        max_risk_pct = 1.0
        total_risk = sum(r['bet_amount'] for r in recommendations)
        
        while total_risk > self.unified_bankroll * max_risk_pct:
            if not recommendations:
                break
            lowest_bet = recommendations.pop()
            total_risk -= lowest_bet['bet_amount']
        
        total_potential = sum(r['potential_profit'] for r in recommendations)
        
        print("\n" + "="*80)
        print(f"UNIFIED BETTING RECOMMENDATIONS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        print(f"Unified Bankroll: ${self.unified_bankroll:,.2f}")
        print(f"Sports: {', '.join(set(r['sport'].upper() for r in recommendations))}")
        print("="*80)
        
        for i, rec in enumerate(recommendations, 1):
            try:
                # Convert odds to int (they may be strings like '-475' or '333')
                home_odds = int(float(rec.get('home_odds', 0)))
                away_odds = int(float(rec.get('away_odds', 0)))
                
                print(f"\nRECOMMENDATION #{i} - {rec['sport'].upper()} {rec['type'].upper()}")
                print(f"   Matchup: {rec['matchup']}")
                
                # Display injury summary if available
                if rec.get('injury_summary'):
                    for line in rec['injury_summary'].split('\n'):
                        print(f"   {line}")
                
                if rec['type'] == 'h2h':
                    print(f"   Bet: {rec['bet_team']} ({rec['bet_side'].upper()})")
                    print(f"   Odds: Home {home_odds:+d}, Away {away_odds:+d} (Book: {rec['book']})")
                    print(f"   Model Probability: Home {rec['home_model_prob']:.1%}, Away {rec['away_model_prob']:.1%}")
                    print(f"   Market Probability: {rec['market_prob']:.1%}")
                    print(f"   Edge: {rec['edge']:.1%}")
                elif rec['type'] == 'spread':
                    print(f"   Bet: {rec['bet_team']} ({rec['bet_side'].upper()})")
                    print(f"   Home Spread: {rec['home_spread']:+.1f} @ {home_odds:+d} (Book: {rec['book']})")
                    print(f"   Away Spread: {rec['away_spread']:+.1f} @ {away_odds:+d} (Book: {rec['book']})")
                    print(f"   Predicted Margin: {rec['predicted_margin']:+.1f} points")
                    print(f"   Margin Advantage: {rec['margin_advantage']:.1f} points")
                    print(f"   Cover Probability: {rec['cover_prob']:.1%}")
                elif rec['type'] == 'total':
                    over_odds = int(float(rec.get('over_odds', 0)))
                    under_odds = int(float(rec.get('under_odds', 0)))
                    print(f"   Bet: {rec['total_line']} points ({rec['bet_side'].upper()})")
                    print(f"   Over Odds: {over_odds:+d}, Under Odds: {under_odds:+d} (Book: {rec['book']})")
                    print(f"   Predicted Total: {rec['predicted_total']:.1f} points")
                    print(f"   Total Advantage: {rec['total_advantage']:.1f} points")
                    print(f"   Cover Probability: {rec['cover_prob']:.1%}")
                
                print(f"   Confidence: {rec['confidence']:.1%}")
                print(f"   Recommended Bet: ${rec['bet_amount']:.2f} ({rec['bet_size_fraction']:.1%} of bankroll)")
                print(f"   Potential Profit: ${rec['potential_profit']:.2f}")
                print(f"   Reason: {rec['reason']}")
            except Exception as e:
                print(f"   Error displaying recommendation: {e}")
                print(f"   Raw data: {rec}")
        
        print("\n" + "="*80)
        print(f"TOTAL RISK: ${total_risk:.2f} ({total_risk/self.unified_bankroll:.1%} of bankroll)")
        print(f"TOTAL POTENTIAL PROFIT: ${total_potential:.2f}")
        print(f"NUMBER OF BETS: {len(recommendations)}")
        print("="*80)
        
        # Flush stdout to ensure all output is displayed before input prompt
        sys.stdout.flush()
        
        try:
            save = input("\nWould you like to save any of these recommendations? (y/n): ").strip().lower()
            if save == 'y':
                games_to_save = input("Which ones would you like to save? (comma separated list of numbers or 0 for all): ").strip()
                if games_to_save:
                    self.saveRecommendations(recommendations, games_to_save)
                else:
                    print("No games selected.")
            elif save == 'n':
                print("Recommendations not saved.")
                self.saveRecommendations(recommendations)
            else:
                print(f"Unrecognized input '{save}', no action taken.")
        except EOFError:
            print("\nNo input received, skipping save.")
        except KeyboardInterrupt:
            print("\nCancelled.")
    
    def saveRecommendations(self, recommendations, numbers_str=None):
        """Save selected recommendations to active log and all to archive"""
        # Archive all recommendations first
        basketball_recs_archive = [r for r in recommendations if r['sport'] == 'basketball']
        hockey_recs_archive = [r for r in recommendations if r['sport'] == 'hockey']
        
        # Save all to archive
        if basketball_recs_archive:
            print(f"Archiving {len(basketball_recs_archive)} basketball recommendations...")
            self._logRecommendationsToFile(basketball_recs_archive, 'basketball', archive=True)
        if hockey_recs_archive:
            print(f"Archiving {len(hockey_recs_archive)} hockey recommendations...")
            self._logRecommendationsToFile(hockey_recs_archive, 'hockey', archive=True)
        
        # Parse selected bets to save to active log
        if numbers_str is None:
            print("Recommendations archived (no active bets selected).")
            return
        
        if numbers_str == '0':
            # Save all to active
            selected_recs = recommendations
        else:
            try:
                numbers = [int(n.strip()) for n in numbers_str.split(',')]
                selected_recs = [recommendations[i-1] for i in numbers if 0 < i <= len(recommendations)]
            except:
                print("Invalid input for bet selection")
                return
        
        if not selected_recs:
            print("No bets selected to save.")
            return
        
        # Separate selected by sport
        basketball_recs = [r for r in selected_recs if r['sport'] == 'basketball']
        hockey_recs = [r for r in selected_recs if r['sport'] == 'hockey']
        
        # Save selected to active logs
        if basketball_recs:
            print(f"Saving {len(basketball_recs)} basketball bets to active log...")
            self._logRecommendationsToFile(basketball_recs, 'basketball')
        if hockey_recs:
            print(f"Saving {len(hockey_recs)} hockey bets to active log...")
            self._logRecommendationsToFile(hockey_recs, 'hockey')
        
        print("Recommendations saved successfully!")
    
    def _logRecommendationsToFile(self, recommendations, sport, archive=False):
        """Log recommendations to CSV files by bet type"""
        import pandas as pd
        
        if not recommendations:
            return
        
        if archive:
            log_dir = Path(f'./logs/{sport}/betting/archive')
        else:
            log_dir = Path(f'./logs/{sport}/betting')
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_files = {
            'h2h': log_dir / 'h2h_bets.csv',
            'spread': log_dir / 'spread_bets.csv',
            'total': log_dir / 'total_bets.csv'
        }
        
        df = pd.DataFrame(recommendations)
        df['timestamp'] = datetime.now()
        
        # Group by bet type
        for bet_type, log_file in log_files.items():
            type_recs = df[df['type'] == bet_type].copy()
            if type_recs.empty:
                continue
            
            # If file exists, merge with existing data
            if log_file.exists() and log_file.stat().st_size > 0:
                existing_data = pd.read_csv(log_file)
                
                # Keep only columns that exist in the file
                with open(log_file, 'r') as f:
                    first_line = f.readline().strip()
                    existing_columns = first_line.split(',')
                    cols_to_keep = [col for col in existing_columns if col in type_recs.columns]
                    type_recs = type_recs[cols_to_keep]
                
                # Merge and deduplicate
                type_recs = pd.concat([existing_data, type_recs], ignore_index=True)
                
                if bet_type in ['h2h', 'spread']:
                    type_recs.drop_duplicates(
                        subset=['game_id', 'matchup', 'bet_side', 'home_odds', 'away_odds'], 
                        keep='last', inplace=True
                    )
                else:  # total
                    type_recs.drop_duplicates(
                        subset=['game_id', 'matchup', 'bet_side', 'total_line', 'over_odds', 'under_odds'], 
                        keep='last', inplace=True
                    )
            
            type_recs.to_csv(log_file, mode='w', header=True, index=False)
            print(f"  Saved {len(df[df['type'] == bet_type])} {bet_type} bets to {log_file}")

def main():
    print("\n" + "="*80)
    print("UNIFIED SPORTS BETTING SYSTEM")
    print("="*80)
    print("Choose an option to run:\n")
    
    options = [
        ("Unified Betting Recommendations (All Sports)", unifiedBettingRecommendations),
        ("Basketball Only", basketballOnly),
        ("Hockey Only", hockeyOnly),
        ("View Unified Bankroll Breakdown", viewBankrollBreakdown),
    ]
    
    for i, (name, _) in enumerate(options, 1):
        print(f"{i}. {name}")
    
    print("0. Exit")
    
    choice = input("\nEnter your choice: ")
    
    try:
        choice = int(choice)
        if choice == 0:
            print("Exiting...")
            return
        elif 1 <= choice <= len(options):
            options[choice - 1][1]()
        else:
            print("Invalid choice")
    except ValueError:
        print("Invalid input")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

def unifiedBettingRecommendations():
    """Get betting recommendations from all sports"""
    print("\n" + "="*80)
    print("UNIFIED BETTING RECOMMENDATIONS")
    print("="*80)
    
    system = UnifiedBettingSystem()
    
    print("\nSelect sports to include:")
    print("1. Both Basketball and Hockey")
    print("2. Basketball Only")
    print("3. Hockey Only")
    
    choice = input("\nEnter your choice: ")
    
    sport_choices = []
    if choice == '1':
        sport_choices = ['basketball', 'hockey']
    elif choice == '2':
        sport_choices = ['basketball']
    elif choice == '3':
        sport_choices = ['hockey']
    else:
        print("Invalid choice")
        return
    
    recommendations = system.getAllRecommendations(sport_choices)
    system.displayUnifiedRecommendations(recommendations)

def basketballOnly():
    """Run basketball betting system only"""
    subprocess.run([sys.executable, 'basketball/main.py'], cwd=str(Path(__file__).parent))

def hockeyOnly():
    """Run hockey betting system only"""
    subprocess.run([sys.executable, 'hockey/main.py'], cwd=str(Path(__file__).parent))

def viewBankrollBreakdown():
    """Display unified bankroll breakdown across all sports"""
    UnifiedBankroll.displayBankrollBreakdown()

if __name__ == "__main__":
    main()
