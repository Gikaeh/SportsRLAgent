import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from model.model_h2h import BasketballH2HModel
from model.model_spread import BasketballSpreadModel
from betting.betting_config import BettingConfig
from data_pipeline.odd_scraping import BasketballOddScraping
from data_pipeline.prepare_data import NBATrainingDataPreparer

class BettingRecommender:
    def __init__(self, model_path=None, config=None):
        self.config = config or BettingConfig()
        self.odd_scraping = BasketballOddScraping()
        self.preparer = NBATrainingDataPreparer()

        if model_path.split('_')[1] == 'h2h':
            self.model = BasketballH2HModel()
        elif model_path.split('_')[1] == 'spread':
            self.model = BasketballSpreadModel()
        
        model_path = model_path or self.config.MODEL_PATH
        if Path(model_path).exists():
            self.model.load(model_path)
            print(f"Loaded model from {model_path}")
        else:
            raise FileNotFoundError(f"Model not found at {model_path}")

        self.current_bankroll = self.setBankroll()
        # self.current_bankroll = self.config.STARTING_BANKROLL
        
        Path(self.config.LOG_DIR).mkdir(parents=True, exist_ok=True)
    
    def oddsToProbability(self, american_odds):
        if american_odds > 0:
            return 100 / (american_odds + 100)
        else:
            return abs(american_odds) / (abs(american_odds) + 100)
    
    def probabilityToOdds(self, probability):
        if probability >= 0.5:
            return -100 * probability / (1 - probability)
        else:
            return 100 * (1 - probability) / probability
    
    def kellyCriterion(self, win_prob, american_odds):
        if american_odds > 0:
            decimal_odds = (american_odds / 100) + 1
        else:
            decimal_odds = (100 / abs(american_odds)) + 1
        
        # Kelly formula: (p * odds - 1) / (odds - 1)
        kelly_fraction = (win_prob * decimal_odds - 1) / (decimal_odds - 1)
        
        # Apply fractional Kelly for risk management
        kelly_fraction = max(0, kelly_fraction * self.config.KELLY_FRACTION)
        
        return min(kelly_fraction, self.config.MAX_BET_SIZE_PCT)
    
    def calculateEdge(self, model_prob, market_odds):
        market_prob = self.oddsToProbability(market_odds)
        return model_prob - market_prob
    
    def predictGames(self, game_features, game_info):
        results = game_info.copy()

        if self.model.getModelType() == 'h2h':
            predictions = self.model.predictProb(game_features)
            home_win_probs = predictions[:, 1]
        
            results['home_win_prob'] = home_win_probs
            results['away_win_prob'] = 1 - home_win_probs
            results['predicted_winner'] = results.apply(lambda row: row['home_team'] if row['home_win_prob'] > 0.5 else row['away_team'], axis=1)
            results['confidence'] = np.abs(home_win_probs - 0.5) * 2 

        if self.model.getModelType() == 'spread':
            predictions = self.model.predict(game_features)
            results['predicted_margin'] = predictions
            results['predicted_cover'] = results.apply(lambda row: row['home_team'] if row['predicted_margin'] > 0 else row['away_team'], axis=1)
            results['confidence'] = np.minimum(np.abs(predictions) / 20, 1)
        
        return results
    
    def makeBettingRecommendations(self, predictions):
        if self.model.getModelType() == 'h2h':
            return self.makeH2HRecommendations(predictions)
        elif self.model.getModelType() == 'spread':
            return self.makeSpreadRecommendations(predictions)
        
    
    def makeH2HRecommendations(self, predictions):
        recommendations = []
        odds_data = self.getOdds('h2h')
        odds_data = odds_data[odds_data['bookmakers_key'].isin(self.config.NEVADA_BOOKS)]
        
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
            
                home_edge = self.calculateEdge(home_prob, home_odds)
                away_edge = self.calculateEdge(away_prob, away_odds)
                
                if home_prob >= self.config.MIN_PROBABILITY and home_edge >= self.config.MIN_EDGE:
                    bet_size_fraction = self.kellyCriterion(home_prob, home_odds)
                    bet_amount = bet_size_fraction * self.current_bankroll

                    recommendations.append({
                        'game_id': game_id,
                        'date': game['date'],
                        'matchup': f"{away_team} @ {home_team}",
                        'bet_team': home_team,
                        'bet_side': 'home',
                        'home_model_prob': home_prob,
                        'home_odds': home_odds,
                        'away_model_prob': away_prob,
                        'away_odds': away_odds,
                        'market_prob': self.oddsToProbability(home_odds),
                        'edge': home_edge,
                        'confidence': game['confidence'],
                        'bet_size_fraction': bet_size_fraction,
                        'bet_amount': bet_amount,
                        'potential_profit': self.calculateProfit(bet_amount, home_odds),
                        'book': book,
                        'type': 'h2h',
                        'result': '',
                        'reason': f"Edge: {home_edge:.1%}, Confidence: {game['confidence']:.1%}"
                    })
                
                if away_prob >= self.config.MIN_PROBABILITY and away_edge >= self.config.MIN_EDGE:
                    bet_size_fraction = self.kellyCriterion(away_prob, away_odds)
                    bet_amount = bet_size_fraction * self.current_bankroll
                    
                    recommendations.append({
                        'game_id': game_id,
                        'date': game['date'],
                        'matchup': f"{away_team} @ {home_team}",
                        'bet_team': away_team,
                        'bet_side': 'away',
                        'home_model_prob': home_prob,
                        'home_odds': home_odds,
                        'away_model_prob': away_prob,
                        'away_odds': away_odds,
                        'market_prob': self.oddsToProbability(away_odds),
                        'edge': away_edge,
                        'confidence': game['confidence'],
                        'bet_size_fraction': bet_size_fraction,
                        'bet_amount': bet_amount,
                        'potential_profit': self.calculateProfit(bet_amount, away_odds),
                        'book': book,
                        'type': 'h2h',
                        'result': '',
                        'reason': f"Edge: {away_edge:.1%}, Confidence: {game['confidence']:.1%}"
                    })
        
        return pd.DataFrame(recommendations)

    def makeSpreadRecommendations(self, predictions):
        recommendations = []
        odds_data = self.getOdds('spreads')
        odds_data = odds_data[odds_data['bookmakers_key'].isin(self.config.NEVADA_BOOKS)]
        
        for idx, game in predictions.iterrows():
            game_id = game['game_id']
            home_team = game['home_team']
            away_team = game['away_team']
            predicted_margin = game['predicted_margin']
            game_odds = odds_data[(odds_data['home_team'] == home_team) & (odds_data['away_team'] == away_team)]
            
            if len(game_odds) == 0:
                continue
            
            home_spread_odds = game_odds[game_odds['name'] == home_team]
            away_spread_odds = game_odds[game_odds['name'] == away_team]

            if len(home_spread_odds) == 0 or len(away_spread_odds) == 0:
                continue
            
            home_spread = home_spread_odds['point'].values[0]
            home_odds = home_spread_odds['price'].max()
            away_spread = away_spread_odds['point'].values[0]
            away_odds = away_spread_odds['price'].max()

            is_home_favored = home_spread < 0
            is_away_favored = away_spread < 0

            if is_home_favored:
                home_margin_advantage = predicted_margin - abs(home_spread)
            else:
                home_margin_advantage = predicted_margin + home_spread
            if is_away_favored:
                away_margin_advantage = (-predicted_margin) - abs(away_spread)
            else:
                away_margin_advantage = away_spread + (-predicted_margin)

            MIN_MARGIN_EDGE = getattr(self.config, 'MIN_MARGIN_EDGE', 3)

            if home_margin_advantage >= MIN_MARGIN_EDGE:
                cover_prob = self.marginToProbability(home_margin_advantage)

                if cover_prob >= self.config.MIN_PROBABILITY:
                    bet_size_fraction = self.kellyCriterion(cover_prob, home_odds)
                    bet_amount = bet_size_fraction * self.current_bankroll

                    book = home_spread_odds[home_spread_odds['price'] == home_odds]['bookmakers_key'].values[0]

                    recommendations.append({
                        'game_id': game_id,
                        'date': game['date'],
                        'matchup': f"{away_team} @ {home_team}",
                        'bet_team': home_team,
                        'bet_side': 'home',
                        'home_spread': home_spread,
                        'home_odds': home_odds,
                        'away_spread': away_spread,
                        'away_odds': away_odds,
                        'predicted_margin': predicted_margin,
                        'margin_advantage': home_margin_advantage,
                        'cover_prob': cover_prob,
                        'confidence': game['confidence'],
                        'bet_size_fraction': bet_size_fraction,
                        'bet_amount': bet_amount,
                        'potential_profit': self.calculateProfit(bet_amount, home_odds),
                        'book': book,
                        'type': 'spread',
                        'is_home_favored': is_home_favored,
                        'result': '',
                        'reason': f"Predicted Margin: {predicted_margin:.1f}, Home Spread: {home_spread:.1f}, Home Odds: {home_odds}, Edge: {home_margin_advantage:.1f}, Cover Probability: {cover_prob:.1%}, Confidence: {game['confidence']:.1%}"
                    })
            
            if away_margin_advantage >= MIN_MARGIN_EDGE:
                cover_prob = self.marginToProbability(away_margin_advantage)

                if cover_prob >= self.config.MIN_PROBABILITY:
                    bet_size_fraction = self.kellyCriterion(cover_prob, away_odds)
                    bet_amount = bet_size_fraction * self.current_bankroll
                
                    book = away_spread_odds[away_spread_odds['price'] == away_odds]['bookmakers_key'].values[0]
                    
                    recommendations.append({
                        'game_id': game_id,
                        'date': game['date'],
                        'matchup': f"{away_team} @ {home_team}",
                        'bet_team': away_team,
                        'bet_side': 'away',
                        'home_spread': home_spread,
                        'home_odds': home_odds,
                        'away_spread': away_spread,
                        'away_odds': away_odds,
                        'predicted_margin': predicted_margin,
                        'margin_advantage': away_margin_advantage,
                        'cover_prob': cover_prob,
                        'confidence': game['confidence'],
                        'bet_size_fraction': bet_size_fraction,
                        'bet_amount': bet_amount,
                        'potential_profit': self.calculateProfit(bet_amount, away_odds),
                        'book': book,
                        'type': 'spread',
                        'is_away_favored': is_away_favored,
                        'result': '',
                        'reason': f"Predicted Margin: {predicted_margin:.1f}, Away Spread: {away_spread:.1f}, Away Odds: {away_odds}, Edge: {away_margin_advantage:.1f}, Cover Probability: {cover_prob:.1%}, Confidence: {game['confidence']:.1%}"
                    })
        
        return pd.DataFrame(recommendations)

    def marginToProbability(self, margin):
        k = 0.15
        x0 = 5
        prob = 0.5 + 0.4 / (1 + np.exp(-k * (margin - x0))) # Logistic function

        return min(max(prob, 0.5), 0.95) # Ensure probability is between 50% and 95%
    
    def calculateProfit(self, bet_amount, american_odds):
        if american_odds > 0:
            return bet_amount * (american_odds / 100)
        else:
            return bet_amount * (100 / abs(american_odds))
    
    def displayRecommendations(self, recommendations):
        if not recommendations:
            print("\n" + "="*80)
            print("NO BETTING OPPORTUNITIES FOUND")
            print("="*80)
            print("No games meet the minimum edge and probability requirements.")
            return
        
        # recommendations.sort(key=lambda x: (x['confidence']), reverse=True)
        recommendations.sort_values(by='confidence', ascending=False, inplace=True)
        
        print("\n" + "="*80)
        print(f"BETTING RECOMMENDATIONS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        print(f"Current Bankroll: ${self.current_bankroll:,.2f}")
        print("="*80)
        
        for i, rec in enumerate(recommendations, 1):
            print(f"\nRECOMMENDATION #{i} - {rec['type']}")
            print(f"   Matchup: {rec['matchup']}")
            print(f"   Bet: {rec['bet_team']} ({rec['bet_side'].upper()})")

            if rec['type'] == 'h2h':
                print(f"   Odds: Home {rec['home_odds']:+d}, Away {rec['away_odds']:+d} (Book: {rec['book']})")
                print(f"   Model Probability: Home {rec['home_model_prob']:.1%}, Away {rec['away_model_prob']:.1%}")
                print(f"   Market Probability: {rec['market_prob']:.1%}")
                print(f"   Edge: {rec['edge']:.1%}")
            elif rec['type'] == 'spread':
                print(f"   Home Spread: {rec['home_spread']:+.1f} @ {rec['home_odds']:+d} (Book: {rec['book']})")
                print(f"   Away Spread: {rec['away_spread']:+.1f} @ {rec['away_odds']:+d} (Book: {rec['book']})")
                print(f"   Predicted Margin: {rec['predicted_margin']:+.1f} points")
                print(f"   Margin Advantage: {rec['margin_advantage']:.1f} points")
                print(f"   Cover Probability: {rec['cover_prob']:.1%}")

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
    
    def logRecommendations(self, recommendations, numbers = None):
        if not recommendations:
            return
        
        if numbers is not None:
            recommendations = [recommendations[i-1] for i in numbers]
        
        log_file = Path(self.config.LOG_DIR) / self.config.BETS_LOG
        
        df = pd.DataFrame(recommendations)
        df['timestamp'] = datetime.now()
        
        if log_file.exists():
            df.to_csv(log_file, mode='a', header=False, index=False)
        else:
            df.to_csv(log_file, index=False)

    def getOdds(self, model_type):
        if model_type == 'h2h':
            return self.odd_scraping.getH2hOdds()
        elif model_type == 'spreads':
            return self.odd_scraping.getSpreadOdds()

    def updateBetResults(self):
        log_file = Path(self.config.LOG_DIR) / self.config.BETS_LOG
        game_data = pd.read_csv(f'././data/basketball/game_data/{self.preparer.getCurrentSeason()}_game_stats.csv')

        if log_file.exists():
            df = pd.read_csv(log_file)

            for idx, row in df.iterrows():
                game_id = int(row['game_id'])

                if game_id in game_data['GAME_ID'].values.astype(int):
                    if row['type'] == 'h2h':
                        game_data_row = game_data[(game_data['GAME_ID'] == game_id) & (game_data['TEAM_ABBREVIATION'] == row['bet_team'])]

                        if game_data_row['WL'].values[0] == 'W':
                            df.at[idx, 'result'] = 'W'
                        elif game_data_row['WL'].values[0] == 'L':
                            df.at[idx, 'result'] = 'L'
                    elif row['type'] == 'spread':
                        home_data = game_data[(game_data['GAME_ID'] == game_id) & (game_data['TEAM_ABBREVIATION'] == row['matchup'].split(' ')[2])]
                        away_data = game_data[(game_data['GAME_ID'] == game_id) & (game_data['TEAM_ABBREVIATION'] == row['matchup'].split(' ')[0])]

                        if len(home_data) > 0 and len(away_data) > 0:
                            home_score = home_data['PTS'].values[0]
                            away_score = away_data['PTS'].values[0]
                            actual_margin = home_score - away_score
                            
                            spread = row['spread']
                            
                            if actual_margin > spread:
                                df.at[idx, 'result'] = 'W'
                            else:
                                df.at[idx, 'result'] = 'L'
                    else:
                        df.at[idx, 'result'] = ''

            df.to_csv(log_file, index=False)

    def setBankroll(self):
        try:
            self.updateBetResults()
        except Exception as e:
            print(f"Error updating bet results: {e}")
            return self.config.STARTING_BANKROLL
        
        log_file = Path(self.config.LOG_DIR) / self.config.BETS_LOG
        bankroll = self.config.STARTING_BANKROLL

        if log_file.exists():
            df = pd.read_csv(log_file)
            
            for _, row in df.iterrows():
                if row['result'] == 'W':
                    bankroll += row['potential_profit']
                elif row['result'] == 'L':
                    bankroll -= row['bet_amount']

        return bankroll

    def getCurrentBankroll(self):
        return self.current_bankroll

    def getActiveBets(self):
        log_file = Path(self.config.LOG_DIR) / self.config.BETS_LOG
        
        if log_file.exists():
            df = pd.read_csv(log_file)
            
            return df[df['result'].isnull()]
