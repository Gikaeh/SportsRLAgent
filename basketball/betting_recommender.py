import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from model import BasketballModel
from betting_config import BettingConfig
from data_pipeline.odd_scraping import BasketballOddScraping
import json

class BettingRecommender:
    def __init__(self, model_path=None, config=None):
        self.config = config or BettingConfig()
        self.model = BasketballModel()
        self.odd_scraping = BasketballOddScraping()
        
        # Load trained model
        model_path = model_path or self.config.MODEL_PATH
        if Path(model_path).exists():
            self.model.load(model_path)
            print(f"Loaded model from {model_path}")
        else:
            raise FileNotFoundError(f"Model not found at {model_path}")
        
        # Initialize tracking
        self.current_bankroll = self.config.STARTING_BANKROLL
        self.daily_losses = 0
        self.bets_today = 0
        self.bet_history = []
        
        # Create log directory
        Path(self.config.LOG_DIR).mkdir(parents=True, exist_ok=True)
    
    def odds_to_probability(self, american_odds):
        """Convert American odds to implied probability"""
        if american_odds > 0:
            return 100 / (american_odds + 100)
        else:
            return abs(american_odds) / (abs(american_odds) + 100)
    
    def probability_to_odds(self, probability):
        """Convert probability to American odds"""
        if probability >= 0.5:
            return -100 * probability / (1 - probability)
        else:
            return 100 * (1 - probability) / probability
    
    def kelly_criterion(self, win_prob, american_odds):
        """
        Calculate Kelly Criterion bet size
        Returns: Fraction of bankroll to bet (0-1)
        """
        # Convert to decimal odds
        if american_odds > 0:
            decimal_odds = (american_odds / 100) + 1
        else:
            decimal_odds = (100 / abs(american_odds)) + 1
        
        # Kelly formula: (p * odds - 1) / (odds - 1)
        kelly_fraction = (win_prob * decimal_odds - 1) / (decimal_odds - 1)
        
        # Apply fractional Kelly for risk management
        kelly_fraction = max(0, kelly_fraction * self.config.KELLY_FRACTION)
        
        # Cap at max bet size
        return min(kelly_fraction, self.config.MAX_BET_SIZE_PCT)
    
    def calculate_edge(self, model_prob, market_odds):
        """
        Calculate betting edge
        Returns: edge (model_prob - market_implied_prob)
        """
        market_prob = self.odds_to_probability(market_odds)
        return model_prob - market_prob
    
    def predict_games(self, game_features, game_info):
        """
        Generate predictions for games
        Returns: DataFrame with predictions and confidence
        """
        # Get model predictions
        predictions = self.model.predict_proba(game_features)
        home_win_probs = predictions[:, 1]
        
        # Create results dataframe
        results = game_info.copy()
        results['home_win_prob'] = home_win_probs
        results['away_win_prob'] = 1 - home_win_probs
        results['predicted_winner'] = results.apply(
            lambda row: row['home_team'] if row['home_win_prob'] > 0.5 else row['away_team'],
            axis=1
        )
        results['confidence'] = np.abs(home_win_probs - 0.5) * 2  # Scale to 0-1
        
        return results
    
    def make_betting_recommendations(self, predictions):
        recommendations = []
        odds_data = self.getOdds()
        
        for idx, game in predictions.iterrows():
            game_id = game['game_id']
            home_team = game['home_team']
            away_team = game['away_team']
            home_prob = game['home_win_prob']
            away_prob = game['away_win_prob']
            game_odds = odds_data[(odds_data['home_team'] == home_team) & (odds_data['away_team'] == away_team)]
            
            if len(game_odds) > 0:
                home_odds = game_odds[(game_odds['name'] == home_team)]['price'].max()
                away_odds = game_odds[(game_odds['name'] == away_team)]['price'].max()
                if home_prob > away_prob:
                    book = game_odds[(game_odds['price'] == home_odds)]['bookmakers_key'].values[0]
                else:
                    book = game_odds[(game_odds['price'] == away_odds)]['bookmakers_key'].values[0]
            else:
                home_odds = -110
                away_odds = -110
                book = 'Default'
            
            # Check home bet
            home_edge = self.calculate_edge(home_prob, home_odds)
            if home_prob >= self.config.MIN_CONFIDENCE and home_edge >= self.config.MIN_EDGE:
                bet_size_fraction = self.kelly_criterion(home_prob, home_odds)
                bet_amount = bet_size_fraction * self.current_bankroll
                
                # Validate bet
                is_valid, reason = self.config.validateBet(
                    bet_amount, self.current_bankroll, self.daily_losses, self.bets_today
                )
                
                if is_valid:
                    recommendations.append({
                        'game_id': game_id,
                        'date': game['date'],
                        'matchup': f"{away_team} @ {home_team}",
                        'bet_team': home_team,
                        'bet_side': 'home',
                        'model_prob': home_prob,
                        'odds': home_odds,
                        'market_prob': self.odds_to_probability(home_odds),
                        'edge': home_edge,
                        'confidence': game['confidence'],
                        'bet_size_fraction': bet_size_fraction,
                        'bet_amount': bet_amount,
                        'potential_profit': self._calculate_profit(bet_amount, home_odds),
                        'book': book,
                        'status': 'RECOMMENDED',
                        'reason': f"Edge: {home_edge:.1%}, Confidence: {game['confidence']:.1%}"
                    })
            
            # Check away bet
            away_edge = self.calculate_edge(away_prob, away_odds)
            if away_prob >= self.config.MIN_CONFIDENCE and away_edge >= self.config.MIN_EDGE:
                bet_size_fraction = self.kelly_criterion(away_prob, away_odds)
                bet_amount = bet_size_fraction * self.current_bankroll
                
                # Validate bet
                is_valid, reason = self.config.validateBet(
                    bet_amount, self.current_bankroll, self.daily_losses, self.bets_today
                )
                
                if is_valid:
                    recommendations.append({
                        'game_id': game_id,
                        'date': game['date'],
                        'matchup': f"{away_team} @ {home_team}",
                        'bet_team': away_team,
                        'bet_side': 'away',
                        'model_prob': away_prob,
                        'odds': away_odds,
                        'market_prob': self.odds_to_probability(away_odds),
                        'edge': away_edge,
                        'confidence': game['confidence'],
                        'bet_size_fraction': bet_size_fraction,
                        'bet_amount': bet_amount,
                        'potential_profit': self._calculate_profit(bet_amount, away_odds),
                        'book': book,
                        'status': 'RECOMMENDED',
                        'reason': f"Edge: {away_edge:.1%}, Confidence: {game['confidence']:.1%}"
                    })
        
        return recommendations
    
    def _calculate_profit(self, bet_amount, american_odds):
        """Calculate potential profit from a bet"""
        if american_odds > 0:
            return bet_amount * (american_odds / 100)
        else:
            return bet_amount * (100 / abs(american_odds))
    
    def display_recommendations(self, recommendations):
        """Display betting recommendations in a readable format"""
        if not recommendations:
            print("\n" + "="*80)
            print("NO BETTING OPPORTUNITIES FOUND")
            print("="*80)
            print("No games meet the minimum edge and confidence requirements.")
            return

        recommendations.sort(key=lambda x: (x['confidence'], x['model_prob']), reverse=True)
        
        print("\n" + "="*80)
        print(f"BETTING RECOMMENDATIONS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        print(f"Current Bankroll: ${self.current_bankroll:,.2f}")
        print(f"Bets Today: {self.bets_today}/{self.config.MAX_BETS_PER_DAY}")
        print(f"Daily Losses: ${self.daily_losses:.2f} / ${self.config.getDailyLossLimit(self.current_bankroll):.2f}")
        print("="*80)
        
        for i, rec in enumerate(recommendations, 1):
            print(f"\nRECOMMENDATION #{i}")
            print(f"   Matchup: {rec['matchup']}")
            print(f"   Bet: {rec['bet_team']} ({rec['bet_side'].upper()})")
            print(f"   Odds: {rec['odds']:+d} (Book: {rec['book']})")
            print(f"   Model Probability: {rec['model_prob']:.1%}")
            print(f"   Market Probability: {rec['market_prob']:.1%}")
            print(f"   Edge: {rec['edge']:.1%}")
            print(f"   Confidence: {rec['confidence']:.1%}")
            print(f"   Recommended Bet: ${rec['bet_amount']:.2f} ({rec['bet_size_fraction']:.1%} of bankroll)")
            print(f"   Potential Profit: ${rec['potential_profit']:.2f}")
            print(f"   Reason: {rec['reason']}")
        
        print("\n" + "="*80)
        total_risk = sum(r['bet_amount'] for r in recommendations)
        total_potential = sum(r['potential_profit'] for r in recommendations)
        print(f"TOTAL RISK: ${total_risk:.2f} ({total_risk/self.current_bankroll:.1%} of bankroll)")
        print(f"TOTAL POTENTIAL PROFIT: ${total_potential:.2f}")
        print("="*80)
    
    def log_predictions(self, predictions):
        """Log all predictions to CSV"""
        log_file = Path(self.config.LOG_DIR) / self.config.PREDICTIONS_LOG
        
        predictions['timestamp'] = datetime.now()
        
        if log_file.exists():
            predictions.to_csv(log_file, mode='a', header=False, index=False)
        else:
            predictions.to_csv(log_file, index=False)
    
    def log_recommendations(self, recommendations):
        """Log betting recommendations to CSV"""
        if not recommendations:
            return
        
        log_file = Path(self.config.LOG_DIR) / self.config.BETS_LOG
        
        df = pd.DataFrame(recommendations)
        df['timestamp'] = datetime.now()
        
        if log_file.exists():
            df.to_csv(log_file, mode='a', header=False, index=False)
        else:
            df.to_csv(log_file, index=False)
    
    def update_bankroll(self, bet_result):
        """
        Update bankroll after bet result
        
        Args:
            bet_result: dict with 'bet_amount', 'won' (bool), 'profit' (if won)
        """
        if bet_result['won']:
            self.current_bankroll += bet_result['profit']
            print(f"✅ Bet WON! Profit: ${bet_result['profit']:.2f}")
        else:
            self.current_bankroll -= bet_result['bet_amount']
            self.daily_losses += bet_result['bet_amount']
            print(f"❌ Bet LOST! Loss: ${bet_result['bet_amount']:.2f}")
        
        print(f"Updated Bankroll: ${self.current_bankroll:,.2f}")
    
    def reset_daily_limits(self):
        """Reset daily counters (call at start of each day)"""
        self.daily_losses = 0
        self.bets_today = 0
        print("Daily limits reset.")

    def getOdds(self):
        return self.odd_scraping.getCurrentOdds()

if __name__ == "__main__":
    # Example usage
    from data_pipeline.live_data_updater import LiveDataUpdater
    
    print("="*80)
    print("BETTING RECOMMENDER SYSTEM")
    print("="*80)
    
    # Initialize
    recommender = BettingRecommender()
    updater = LiveDataUpdater()
    
    # Get today's games
    prediction_data, game_info = updater.getPredictionReadyData()
    
    if not prediction_data.empty:
        # Generate predictions
        predictions = recommender.predict_games(prediction_data, game_info)
        
        print("\n" + "="*80)
        print("PREDICTIONS")
        print("="*80)
        for _, game in predictions.iterrows():
            print(f"{game['away_team']} @ {game['home_team']}")
            print(f"  Predicted Winner: {game['predicted_winner']}")
            print(f"  Home Win Prob: {game['home_win_prob']:.1%}")
            print(f"  Confidence: {game['confidence']:.1%}")
            print()
        
        # Make betting recommendations (using default odds for demo)
        recommendations = recommender.make_betting_recommendations(predictions)
        
        # Display recommendations
        recommender.display_recommendations(recommendations)
        
        # Log everything
        recommender.log_predictions(predictions)
        recommender.log_recommendations(recommendations)
        
    else:
        print("\nNo games to predict today.")
