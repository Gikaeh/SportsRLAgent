import subprocess
import json
import sys
from pathlib import Path
from datetime import datetime

class UnifiedBettingSystem:
    def __init__(self):
        self.base_path = Path(__file__).parent
        self.unified_bankroll = self.calculateUnifiedBankroll()
        
    def calculateUnifiedBankroll(self):
        """Calculate unified bankroll across all sports"""
        # Get basketball bankroll
        basketball_bankroll = 80.0  # Default
        try:
            result = subprocess.run(
                [sys.executable, '-c', 
                 "import sys; sys.path.insert(0, 'basketball'); "
                 "from basketball.betting.betting_recommender import BettingRecommender; "
                 "r = BettingRecommender(model_path='./models/basketball_h2h_model.json'); "
                 "print(r.getCurrentBankroll())"],
                cwd=str(self.base_path),
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                # Get last line which should be the bankroll value
                lines = result.stdout.strip().split('\n')
                basketball_bankroll = float(lines[-1])
        except Exception as e:
            print(f"Error getting basketball bankroll: {e}")
        
        # Get hockey bankroll
        hockey_bankroll = 80.0  # Default
        try:
            result = subprocess.run(
                [sys.executable, '-c',
                 "import sys; sys.path.insert(0, 'hockey'); "
                 "from hockey.betting.betting_recommender import BettingRecommender; "
                 "r = BettingRecommender(model_path='./models/hockey_h2h_model.json'); "
                 "print(r.getCurrentBankroll())"],
                cwd=str(self.base_path),
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                # Get last line which should be the bankroll value
                lines = result.stdout.strip().split('\n')
                hockey_bankroll = float(lines[-1])
        except Exception as e:
            print(f"Error getting hockey bankroll: {e}")
        
        unified = max(basketball_bankroll, hockey_bankroll, 80.0)
        
        print(f"\n{'='*80}")
        print("UNIFIED BANKROLL CALCULATION")
        print(f"{'='*80}")
        print(f"Basketball Bankroll: ${basketball_bankroll:,.2f}")
        print(f"Hockey Bankroll: ${hockey_bankroll:,.2f}")
        print(f"Unified Bankroll: ${unified:,.2f}")
        print(f"{'='*80}\n")
        
        return unified
    
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
                    
            except subprocess.TimeoutExpired:
                print(f"Timeout getting {sport} recommendations (>300s)")
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
            print(f"\nRECOMMENDATION #{i} - {rec['sport'].upper()} {rec['type'].upper()}")
            print(f"   Matchup: {rec['matchup']}")
            
            if rec['type'] == 'h2h':
                print(f"   Bet: {rec['bet_team']} ({rec['bet_side'].upper()})")
                print(f"   Odds: Home {rec['home_odds']:+d}, Away {rec['away_odds']:+d} (Book: {rec['book']})")
                print(f"   Model Probability: Home {rec['home_model_prob']:.1%}, Away {rec['away_model_prob']:.1%}")
                print(f"   Market Probability: {rec['market_prob']:.1%}")
                print(f"   Edge: {rec['edge']:.1%}")
            elif rec['type'] == 'spread':
                print(f"   Bet: {rec['bet_team']} ({rec['bet_side'].upper()})")
                print(f"   Home Spread: {rec['home_spread']:+.1f} @ {rec['home_odds']:+d} (Book: {rec['book']})")
                print(f"   Away Spread: {rec['away_spread']:+.1f} @ {rec['away_odds']:+d} (Book: {rec['book']})")
                print(f"   Predicted Margin: {rec['predicted_margin']:+.1f} points")
                print(f"   Margin Advantage: {rec['margin_advantage']:.1f} points")
                print(f"   Cover Probability: {rec['cover_prob']:.1%}")
            elif rec['type'] == 'total':
                print(f"   Bet: {rec['total_line']} points ({rec['bet_side'].upper()})")
                print(f"   Over Odds: {rec['over_odds']:+d}, Under Odds: {rec['under_odds']:+d} (Book: {rec['book']})")
                print(f"   Predicted Total: {rec['predicted_total']:.1f} points")
                print(f"   Total Advantage: {rec['total_advantage']:.1f} points")
                print(f"   Cover Probability: {rec['cover_prob']:.1%}")
            
            print(f"   Confidence: {rec['confidence']:.1%}")
            print(f"   Recommended Bet: ${rec['bet_amount']:.2f} ({rec['bet_size_fraction']:.1%} of bankroll)")
            print(f"   Potential Profit: ${rec['potential_profit']:.2f}")
            print(f"   Reason: {rec['reason']}")
        
        print("\n" + "="*80)
        print(f"TOTAL RISK: ${total_risk:.2f} ({total_risk/self.unified_bankroll:.1%} of bankroll)")
        print(f"TOTAL POTENTIAL PROFIT: ${total_potential:.2f}")
        print(f"NUMBER OF BETS: {len(recommendations)}")
        print("="*80)
        
        save = input("\nWould you like to save any of these recommendations? (y/n): ")
        if save.lower() == 'y':
            games_to_save = input("Which ones would you like to save? (comma separated list of numbers or 0 for all): ")
            self.saveRecommendations(recommendations, games_to_save)
    
    def saveRecommendations(self, recommendations, numbers_str):
        """Save recommendations using subprocess calls"""
        if numbers_str != '0':
            try:
                numbers = [int(n.strip()) for n in numbers_str.split(',')]
                recommendations = [recommendations[i-1] for i in numbers if 0 < i <= len(recommendations)]
            except:
                print("Invalid input")
                return
        
        # Separate by sport
        basketball_recs = [r for r in recommendations if r['sport'] == 'basketball']
        hockey_recs = [r for r in recommendations if r['sport'] == 'hockey']
        
        # Save basketball recommendations
        if basketball_recs:
            print(f"Saving {len(basketball_recs)} basketball recommendations...")
            # Would need to implement save logic via subprocess
        
        # Save hockey recommendations
        if hockey_recs:
            print(f"Saving {len(hockey_recs)} hockey recommendations...")
            # Would need to implement save logic via subprocess

def main():
    print("\n" + "="*80)
    print("UNIFIED SPORTS BETTING SYSTEM")
    print("="*80)
    print("Choose an option to run:\n")
    
    options = [
        ("Unified Betting Recommendations (All Sports)", unifiedBettingRecommendations),
        ("Basketball Only", basketballOnly),
        ("Hockey Only", hockeyOnly),
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

if __name__ == "__main__":
    main()
