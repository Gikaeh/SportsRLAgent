from os import path
import sys
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from model.model_h2h import BasketballH2HModel
from model.model_spread import BasketballSpreadModel
from model.model_total import BasketballTotalModel
from betting.betting_config import BettingConfig
from data_pipeline.odd_scraping import BasketballOddScraping
from data_pipeline.prepare_data import NBATrainingDataPreparer
from data_pipeline.injury_data import InjuryData
import glob
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from unified_bankroll import UnifiedBankroll

class BettingRecommender:
    def __init__(self, model_path=None, config=None):
        self.config = config or BettingConfig()
        self.odd_scraping = BasketballOddScraping()
        self.preparer = NBATrainingDataPreparer()
        self.injury_data = InjuryData()

        if model_path.split('_')[1] == 'h2h':
            self.model = BasketballH2HModel()
        elif model_path.split('_')[1] == 'spread':
            self.model = BasketballSpreadModel()
        # elif model_path.split('_')[1] == 'total':
        #     self.model = BasketballTotalModel()
        
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
    
    def kellyCriterion(self, win_prob, american_odds, confidence, is_underdog_h2h=False):
        if american_odds > 0:
            decimal_odds = (american_odds / 100) + 1
        else:
            decimal_odds = (100 / abs(american_odds)) + 1

        # Kelly formula: (p * odds - 1) / (odds - 1)
        kelly_fraction = (win_prob * decimal_odds - 1) / (decimal_odds - 1)
        
        # Apply fractional Kelly for risk management
        kelly_fraction = max(0, kelly_fraction * self.config.KELLY_FRACTION)
        
        # Apply additional reduction for H2H underdog bets
        if is_underdog_h2h:
            underdog_multiplier = getattr(self.config, 'UNDERDOG_KELLY_MULTIPLIER', 0.3)
            kelly_fraction = kelly_fraction * underdog_multiplier
        
        return min(kelly_fraction, self.config.MAX_BET_SIZE_PCT)
    
    def calculateEdge(self, model_prob, market_odds):
        market_prob = self.oddsToProbability(market_odds)
        return model_prob - market_prob
    
    def adjustProbabilityForInjuries(self, prob, home_team, away_team, latest_player_stats):
        """
        Adjust win probability based on injury impact.
        Reduces probability for teams with significant injuries (especially stars).
        """
        injury_impact = self.injury_data.getInjuryImpactForGame(home_team, away_team, latest_player_stats)
        
        home_ppg_lost = injury_impact.get('home_ppg_lost', 0)
        away_ppg_lost = injury_impact.get('away_ppg_lost', 0)
        home_star_out = injury_impact.get('home_star_out', 0)
        away_star_out = injury_impact.get('away_star_out', 0)
        
        # Base adjustment: ~2% per 5 PPG lost (0.4% per PPG)
        home_base_adj = home_ppg_lost * 0.004
        away_base_adj = away_ppg_lost * 0.004
        
        # Star multiplier: additional 5% penalty if star is out
        home_star_penalty = 0.05 if home_star_out else 0
        away_star_penalty = 0.05 if away_star_out else 0
        
        # Total adjustments (capped at 20%)
        home_total_adj = min(home_base_adj + home_star_penalty, 0.20)
        away_total_adj = min(away_base_adj + away_star_penalty, 0.20)
        
        # Net adjustment: positive means home team is more hurt by injuries
        net_injury_effect = home_total_adj - away_total_adj
        
        # Adjust probability: if home is more hurt, reduce home prob
        adjusted_prob = prob * (1 - net_injury_effect)
        
        # Clamp to valid probability range
        adjusted_prob = max(0.05, min(0.95, adjusted_prob))
        
        return adjusted_prob, injury_impact
    
    def adjustMarginForInjuries(self, predicted_margin, home_team, away_team, latest_player_stats):
        """
        Adjust predicted margin based on injury impact.
        Positive margin = home team favored, so injuries to home team reduce margin.
        """
        injury_impact = self.injury_data.getInjuryImpactForGame(home_team, away_team, latest_player_stats)
        
        home_ppg_lost = injury_impact.get('home_ppg_lost', 0)
        away_ppg_lost = injury_impact.get('away_ppg_lost', 0)
        home_star_out = injury_impact.get('home_star_out', 0)
        away_star_out = injury_impact.get('away_star_out', 0)
        
        # Base adjustment: ~0.5 points per 5 PPG lost (0.1 per PPG)
        home_margin_adj = home_ppg_lost * 0.1
        away_margin_adj = away_ppg_lost * 0.1
        
        # Star multiplier: additional 2 points if star is out
        home_star_penalty = 2.0 if home_star_out else 0
        away_star_penalty = 2.0 if away_star_out else 0
        
        # Total adjustments (capped at 8 points)
        home_total_adj = min(home_margin_adj + home_star_penalty, 8.0)
        away_total_adj = min(away_margin_adj + away_star_penalty, 8.0)
        
        # Net adjustment: home injuries reduce margin, away injuries increase it
        margin_adjustment = away_total_adj - home_total_adj
        
        adjusted_margin = predicted_margin + margin_adjustment
        
        return adjusted_margin, injury_impact
    
    def predictGames(self, game_features, game_info):
        results = game_info.copy()

        if self.model.getModelType() == 'h2h':
            odds_data = self.getOdds('h2h')
            # odds_data = pd.read_csv(sorted(glob.glob(f'./data/basketball/odds_data/h2h_*.csv'))[-1])

            predictions = self.model.predictProb(game_features)
            home_win_probs = predictions[:, 1]
        
            results['home_win_prob'] = home_win_probs
            results['away_win_prob'] = 1 - home_win_probs
            results['predicted_winner'] = results.apply(lambda row: row['home_team'] if row['home_win_prob'] > 0.5 else row['away_team'], axis=1)
            results['confidence'] = np.abs(home_win_probs - 0.5) * 2 

        if self.model.getModelType() == 'spread':
            odds_data = self.getOdds('spread')
            # odds_data = pd.read_csv(sorted(glob.glob(f'./data/basketball/odds_data/spread_*.csv'))[-1])            

            predictions = self.model.predict(game_features)
            results['predicted_margin'] = predictions
            results['predicted_cover'] = results.apply(lambda row: row['home_team'] if row['predicted_margin'] > 0 else row['away_team'], axis=1)
            results['confidence'] = np.minimum(np.abs(predictions) / 20, 1)

        # if self.model.getModelType() == 'total':
        #     predictions = self.model.predict(game_features)
        #     odds_data = self.getOdds('total')
        #     # odds_data = pd.read_csv(sorted(glob.glob(f'./data/basketball/odds_data/total_*.csv'))[-1])
        #     odds_data = odds_data[odds_data['bookmakers_key'].isin(self.config.NEVADA_BOOKS)]
        #     odds_data.sort_values('price', inplace=True)

        #     results['predicted_total'] = predictions
        #     for idx, row in results.iterrows():
        #         game_odds = odds_data[odds_data['home_team'] == row['home_team']]
        #         if len(game_odds) == 0:
        #             continue
        #         total_distance = abs(row['predicted_total'] - game_odds['point'].values[0])
        #         results.at[idx, 'confidence'] = np.minimum(total_distance / 20, 1)
        return results
    
    def makeBettingRecommendations(self, predictions):
        if self.model.getModelType() == 'h2h':
            return self.makeH2HRecommendations(predictions)
        elif self.model.getModelType() == 'spread':
            return self.makeSpreadRecommendations(predictions)
        # elif self.model.getModelType() == 'total':
        #     return self.makeTotalRecommendations(predictions)
        
    
    def makeH2HRecommendations(self, predictions):
        recommendations = []
        data_file_path = sorted(glob.glob(f'./data/basketball/odds_data/h2h_*.csv'))[-1]
        odds_data = pd.read_csv(data_file_path)
        odds_data = odds_data[odds_data['bookmakers_key'].isin(self.config.NEVADA_BOOKS)]
        
        # Get latest player stats for injury adjustment
        try:
            player_df = self.preparer.precomputePlayerRollingAverages(self.preparer.getCurrentSeason())
            latest_player_stats = player_df.sort_values('GAME_DATE').groupby('PLAYER_ID').last().reset_index()
        except Exception as e:
            print(f"Warning: Could not load player stats for injury adjustment: {e}")
            latest_player_stats = pd.DataFrame()
        
        for idx, game in predictions.iterrows():
            game_id = game['game_id']
            home_team = game['home_team']
            away_team = game['away_team']
            home_prob_raw = game['home_win_prob']
            away_prob_raw = game['away_win_prob']
            
            # Apply injury adjustment to probabilities
            if not latest_player_stats.empty:
                home_prob, injury_impact = self.adjustProbabilityForInjuries(
                    home_prob_raw, home_team, away_team, latest_player_stats
                )
                away_prob = 1 - home_prob
            else:
                home_prob = home_prob_raw
                away_prob = away_prob_raw
                injury_impact = {}
            
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
                
                # Determine if this is an underdog bet (positive odds = underdog)
                underdog_threshold = getattr(self.config, 'UNDERDOG_ODDS_THRESHOLD', 150)
                home_is_underdog = home_odds > underdog_threshold
                away_is_underdog = away_odds > underdog_threshold
                
                if home_edge >= self.config.MIN_EDGE_H2H:
                    bet_size_fraction = self.kellyCriterion(home_prob, home_odds, game['confidence'], is_underdog_h2h=home_is_underdog)
                    bet_amount = round(bet_size_fraction * self.current_bankroll)
                    if bet_amount < 1:
                        continue

                    # Build reason string with injury info
                    injury_note = ""
                    if injury_impact:
                        if injury_impact.get('home_star_out'):
                            injury_note += f" [HOME STAR OUT: -{injury_impact.get('home_ppg_lost', 0):.0f}PPG]"
                        if injury_impact.get('away_star_out'):
                            injury_note += f" [AWAY STAR OUT: -{injury_impact.get('away_ppg_lost', 0):.0f}PPG]"
                    
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
                        'reason': f"Probability: {home_prob:.1%} (raw: {home_prob_raw:.1%}), Edge: {home_edge:.1%}, Confidence: {game['confidence']:.1%}{injury_note}"
                    })
                
                if away_edge >= self.config.MIN_EDGE_H2H:
                    bet_size_fraction = self.kellyCriterion(away_prob, away_odds, game['confidence'], is_underdog_h2h=away_is_underdog)
                    bet_amount = round(bet_size_fraction * self.current_bankroll)
                    if bet_amount < 1:
                        continue
                    
                    # Build reason string with injury info
                    injury_note = ""
                    if injury_impact:
                        if injury_impact.get('home_star_out'):
                            injury_note += f" [HOME STAR OUT: -{injury_impact.get('home_ppg_lost', 0):.0f}PPG]"
                        if injury_impact.get('away_star_out'):
                            injury_note += f" [AWAY STAR OUT: -{injury_impact.get('away_ppg_lost', 0):.0f}PPG]"
                    
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
                        'reason': f"Probability: {away_prob:.1%} (raw: {away_prob_raw:.1%}), Edge: {away_edge:.1%}, Confidence: {game['confidence']:.1%}{injury_note}"
                    })
        
        return recommendations

    def makeSpreadRecommendations(self, predictions):
        recommendations = []
        data_file_path = sorted(glob.glob(f'./data/basketball/odds_data/spread_*.csv'))[-1]
        odds_data = pd.read_csv(data_file_path)
        odds_data = odds_data[odds_data['bookmakers_key'].isin(self.config.NEVADA_BOOKS)]
        
        # Get latest player stats for injury adjustment
        try:
            player_df = self.preparer.precomputePlayerRollingAverages(self.preparer.getCurrentSeason())
            latest_player_stats = player_df.sort_values('GAME_DATE').groupby('PLAYER_ID').last().reset_index()
        except Exception as e:
            print(f"Warning: Could not load player stats for injury adjustment: {e}")
            latest_player_stats = pd.DataFrame()
        
        for idx, game in predictions.iterrows():
            game_id = game['game_id']
            home_team = game['home_team']
            away_team = game['away_team']
            predicted_margin_raw = game['predicted_margin']
            
            # Apply injury adjustment to predicted margin
            if not latest_player_stats.empty:
                predicted_margin, injury_impact = self.adjustMarginForInjuries(
                    predicted_margin_raw, home_team, away_team, latest_player_stats
                )
            else:
                predicted_margin = predicted_margin_raw
                injury_impact = {}
            
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
            
            min_confidence = getattr(self.config, 'MIN_CONFIDENCE', 0.0)
            if home_margin_advantage >= self.config.MIN_EDGE_SPREAD:
                cover_prob = self.marginToProbability(home_margin_advantage)

                if cover_prob >= self.config.MIN_PROBABILITY:
                    bet_size_fraction = self.kellyCriterion(cover_prob, home_odds, game['confidence'])
                    bet_amount = round(bet_size_fraction * self.current_bankroll)
                    if bet_amount < 1:
                        continue

                    book = home_spread_odds[home_spread_odds['price'] == home_odds]['bookmakers_key'].values[0]

                    # Build reason string with injury info
                    injury_note = ""
                    if injury_impact:
                        if injury_impact.get('home_star_out'):
                            injury_note += f" [HOME STAR OUT: -{injury_impact.get('home_ppg_lost', 0):.0f}PPG]"
                        if injury_impact.get('away_star_out'):
                            injury_note += f" [AWAY STAR OUT: -{injury_impact.get('away_ppg_lost', 0):.0f}PPG]"
                    
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
                        'is_away_favored': is_away_favored,
                        'result': '',
                        'reason': f"Predicted Margin: {predicted_margin:.1f} (raw: {predicted_margin_raw:.1f}), Home Spread: {home_spread:.1f}, Home Odds: {home_odds}, Edge: {home_margin_advantage:.1f}, Cover Probability: {cover_prob:.1%}, Confidence: {game['confidence']:.1%}{injury_note}"
                    })
            
            if away_margin_advantage >= self.config.MIN_EDGE_SPREAD:
                cover_prob = self.marginToProbability(away_margin_advantage)

                if cover_prob >= self.config.MIN_PROBABILITY:
                    bet_size_fraction = self.kellyCriterion(cover_prob, away_odds, game['confidence'])
                    bet_amount = round(bet_size_fraction * self.current_bankroll)
                    if bet_amount < 1:
                        continue
                
                    book = away_spread_odds[away_spread_odds['price'] == away_odds]['bookmakers_key'].values[0]
                    
                    # Build reason string with injury info
                    injury_note = ""
                    if injury_impact:
                        if injury_impact.get('home_star_out'):
                            injury_note += f" [HOME STAR OUT: -{injury_impact.get('home_ppg_lost', 0):.0f}PPG]"
                        if injury_impact.get('away_star_out'):
                            injury_note += f" [AWAY STAR OUT: -{injury_impact.get('away_ppg_lost', 0):.0f}PPG]"
                    
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
                        'is_home_favored': is_home_favored,
                        'is_away_favored': is_away_favored,
                        'result': '',
                        'reason': f"Predicted Margin: {predicted_margin:.1f} (raw: {predicted_margin_raw:.1f}), Away Spread: {away_spread:.1f}, Away Odds: {away_odds}, Edge: {away_margin_advantage:.1f}, Cover Probability: {cover_prob:.1%}, Confidence: {game['confidence']:.1%}{injury_note}"
                    })
        
        return recommendations

    # def makeTotalRecommendations(self, predictions):
    #     recommendations = []
    #     data_file_path = sorted(glob.glob(f'./data/basketball/odds_data/total_*.csv'))[-1]
    #     odds_data = pd.read_csv(data_file_path)
    #     odds_data = odds_data[odds_data['bookmakers_key'].isin(self.config.NEVADA_BOOKS)]
        
    #     for idx, game in predictions.iterrows():
    #         game_id = game['game_id']
    #         home_team = game['home_team']
    #         away_team = game['away_team']
    #         predicted_total = game['predicted_total']
    #         game_odds = odds_data[(odds_data['home_team'] == home_team) & (odds_data['away_team'] == away_team)]
            
    #         if len(game_odds) == 0:
    #             continue
            
    #         over_odds_data = game_odds[game_odds['name'] == 'Over']
    #         under_odds_data = game_odds[game_odds['name'] == 'Under']

    #         if len(over_odds_data) == 0 or len(under_odds_data) == 0:
    #             continue
            
    #         total_line = over_odds_data['point'].values[0]
    #         over_odds = over_odds_data['price'].max()
    #         under_odds = under_odds_data['price'].max()
            
    #         total_advantage = abs(predicted_total - total_line)
            
    #         MIN_TOTAL_EDGE = getattr(self.config, 'MIN_TOTAL_EDGE', 8.0)  
            
    #         if predicted_total > total_line and total_advantage >= MIN_TOTAL_EDGE:
    #             cover_prob = self.totalToProbability(total_advantage)
                
    #             if cover_prob >= self.config.MIN_PROBABILITY:
    #                 bet_size_fraction = self.kellyCriterion(cover_prob, over_odds, game['confidence'])
    #                 bet_amount = round(bet_size_fraction * self.current_bankroll)
                    
    #                 book = over_odds_data[over_odds_data['price'] == over_odds]['bookmakers_key'].values[0]
                    
    #                 recommendations.append({
    #                     'game_id': game_id,
    #                     'date': game['date'],
    #                     'matchup': f"{away_team} @ {home_team}",
    #                     'bet_side': 'Over',
    #                     'total_line': total_line,
    #                     'over_odds': over_odds,
    #                     'under_odds': under_odds,
    #                     'predicted_total': predicted_total,
    #                     'total_advantage': total_advantage,
    #                     'cover_prob': cover_prob,
    #                     'confidence': game['confidence'],
    #                     'bet_size_fraction': bet_size_fraction,
    #                     'bet_amount': bet_amount,
    #                     'potential_profit': self.calculateProfit(bet_amount, over_odds),
    #                     'book': book,
    #                     'type': 'total',
    #                     'result': '',
    #                     'reason': f"Predicted: {predicted_total:.1f}, Line: {total_line:.1f}, Edge: {total_advantage:.1f}pts, Probability: {cover_prob:.1%}, Confidence: {game['confidence']:.1%}"
    #                 })
            
    #         elif predicted_total < total_line and total_advantage >= MIN_TOTAL_EDGE:
    #             cover_prob = self.totalToProbability(total_advantage)
                
    #             if cover_prob >= self.config.MIN_PROBABILITY:
    #                 bet_size_fraction = self.kellyCriterion(cover_prob, under_odds, game['confidence'])
    #                 bet_amount = round(bet_size_fraction * self.current_bankroll)
                    
    #                 book = under_odds_data[under_odds_data['price'] == under_odds]['bookmakers_key'].values[0]
                    
    #                 recommendations.append({
    #                     'game_id': game_id,
    #                     'date': game['date'],
    #                     'matchup': f"{away_team} @ {home_team}",
    #                     'bet_side': 'Under',
    #                     'total_line': total_line,
    #                     'over_odds': over_odds,
    #                     'under_odds': under_odds,
    #                     'predicted_total': predicted_total,
    #                     'total_advantage': total_advantage,
    #                     'cover_prob': cover_prob,
    #                     'confidence': game['confidence'],
    #                     'bet_size_fraction': bet_size_fraction,
    #                     'bet_amount': bet_amount,
    #                     'potential_profit': self.calculateProfit(bet_amount, under_odds),
    #                     'book': book,
    #                     'type': 'total',
    #                     'result': '',
    #                     'reason': f"Predicted: {predicted_total:.1f}, Line: {total_line:.1f}, Edge: {total_advantage:.1f}pts, Probability: {cover_prob:.1%}, Confidence: {game['confidence']:.1%}"
    #                 })
        
    #     return recommendations

    # def totalToProbability(self, total_advantage):
    #     k = 0.10 
    #     x0 = 10 
    #     prob = 0.5 + 0.45 / (1 + np.exp(-k * (total_advantage - x0)))
        
    #     return min(max(prob, 0.5), 0.95)

    def marginToProbability(self, margin):
        k = 0.15
        x0 = 5
        prob = 0.5 + 0.4 / (1 + np.exp(-k * (margin - x0)))

        return min(max(prob, 0.5), 0.95)

    def calculateBetPriority(self, bet):
        weights = {'h2h': .3, 'spread': 1, 'total': .001}

        if bet['type'] == 'h2h':
            if bet['bet_side'] == 'home':
                win_prob = bet.get('home_model_prob', 0.5)
            else:
                win_prob = bet.get('away_model_prob', 0.5)
        elif bet['type'] in ['spread', 'total']:
            win_prob = bet.get('cover_prob', 0.5)

        loss_prob = 1 - win_prob
        expected_value = (win_prob * bet['potential_profit']) - (loss_prob * bet['bet_amount'])
        ev_per_dollar = expected_value / bet['bet_amount']
        roi = bet['potential_profit'] / bet['bet_amount']
        base_priority = bet['confidence'] * ev_per_dollar * (1+roi*.2)

        return base_priority * weights[bet['type']]
    
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
        
        recommendations.sort(key=self.calculateBetPriority, reverse=True)
        
        total_risk = sum(r['bet_amount'] for r in recommendations)
        while total_risk > self.current_bankroll * self.config.MAX_RISK_PCT:
            lowest_bet_priority = recommendations.pop()
            total_risk -= lowest_bet_priority['bet_amount']

        total_potential = sum(r['potential_profit'] for r in recommendations)

        print("\n" + "="*80)
        print(f"BETTING RECOMMENDATIONS - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        print(f"Current Bankroll: ${self.current_bankroll:,.2f}")
        print("="*80)
        
        # Get latest player stats for injury summary
        try:
            player_df = self.preparer.precomputePlayerRollingAverages(self.preparer.getCurrentSeason())
            latest_player_stats = player_df.sort_values('GAME_DATE').groupby('PLAYER_ID').last().reset_index()
        except:
            latest_player_stats = pd.DataFrame()
        
        for i, rec in enumerate(recommendations, 1):
            if rec['type'] == 'total':
                continue
            
            print(f"\nRECOMMENDATION #{i} - {rec['type']}")
            print(f"   Matchup: {rec['matchup']}")
            
            # Display injury summary for this game
            if not latest_player_stats.empty:
                matchup_parts = rec['matchup'].split(' @ ')
                if len(matchup_parts) == 2:
                    away_team, home_team = matchup_parts
                    injury_summary = self.injury_data.getInjurySummaryForGame(home_team, away_team, latest_player_stats)
                    if injury_summary:
                        for line in injury_summary.split('\n'):
                            print(f"   {line}")

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
            # elif rec['type'] == 'total':
            #     print(f"   Bet: {rec['total_line']} points ({rec['bet_side'].upper()})")
            #     print(f"   Over Odds: {rec['over_odds']:+d}, Under Odds: {rec['under_odds']:+d} (Book: {rec['book']})")
            #     print(f"   Predicted Total: {rec['predicted_total']:.1f} points")
            #     print(f"   Total Advantage: {rec['total_advantage']:.1f} points")
            #     print(f"   Cover Probability: {rec['cover_prob']:.1%}")

            print(f"   Confidence: {rec['confidence']:.1%}")
            print(f"   Recommended Bet: ${rec['bet_amount']:.2f} ({rec['bet_size_fraction']:.1%} of bankroll)")
            print(f"   Potential Profit: ${rec['potential_profit']:.2f}")
            print(f"   Reason: {rec['reason']}")
        
        print("\n" + "="*80)
        print(f"TOTAL RISK: ${total_risk:.2f} ({total_risk/self.current_bankroll:.1%} of bankroll)")
        print(f"TOTAL POTENTIAL PROFIT: ${total_potential:.2f}")
        print("="*80)

        save = input("Would you like to save any of these recommendations? (y/n)\n")
        if save.lower() == 'y':
            games_to_save = input("Which ones would you like to save? (comma separated list of numbers or 0 for all)\n")
            games_to_save = [int(game) for game in games_to_save.split(",")] if games_to_save != '0' else None
            
            self.logRecommendations(recommendations, games_to_save)

        files = [Path(self.config.LOG_DIR) / 'archive' / self.config.H2H_BETS_LOG, Path(self.config.LOG_DIR) / 'archive' / self.config.SPREAD_BETS_LOG, Path(self.config.LOG_DIR) / 'archive' / self.config.TOTAL_BETS_LOG]
        self.logRecommendations(recommendations, files=files)
        
    
    def logRecommendations(self, recommendations, numbers = None, files = None):
        if not recommendations:
            return
        
        if numbers is not None:
            recommendations = [recommendations[i-1] for i in numbers]
        
        if files:
            h2h_log_file = files[0]
            spread_log_file = files[1]
            total_log_file = files[2]
        else:
            h2h_log_file = Path(self.config.LOG_DIR) / self.config.H2H_BETS_LOG
            spread_log_file = Path(self.config.LOG_DIR) / self.config.SPREAD_BETS_LOG
            total_log_file = Path(self.config.LOG_DIR) / self.config.TOTAL_BETS_LOG
        
        df = pd.DataFrame(recommendations)
        df['timestamp'] = datetime.now()
        h2h = df[df['type'] == 'h2h']
        spread = df[df['type'] == 'spread']
        total = df[df['type'] == 'total']
        
        data_files = [
            (h2h, h2h_log_file),
            (spread, spread_log_file),
            (total, total_log_file)
        ]
        
        for i, (data, file) in enumerate(data_files):
            if not data.empty:
                write_header = True
                
                if file.exists() and file.stat().st_size > 0:
                    existing_data = pd.read_csv(file)
                    with open(file, 'r') as f:
                        first_line = f.readline().strip()
                        existing_columns = first_line.split(',')
                        
                        cols_to_keep = [col for col in existing_columns if col in data.columns]
                        data = data[cols_to_keep]

                data = pd.concat([existing_data, data], ignore_index=True)
                if i in [0, 1]:
                    data.drop_duplicates(subset=['game_id', 'matchup', 'bet_side', 'home_odds', 'away_odds'], keep='last', inplace=True)
                else:
                    data.drop_duplicates(subset=['game_id', 'matchup', 'bet_side', 'total_line', 'over_odds', 'under_odds'], keep='last', inplace=True)
                data.to_csv(file, mode='w', header=True, index=False)

    def getOdds(self, model_type):
        if model_type == 'h2h':
            return self.odd_scraping.getH2hOdds()
        elif model_type == 'spread':
            return self.odd_scraping.getSpreadOdds()
        elif model_type == 'total':
            return self.odd_scraping.getTotalOdds()

    def updateBetResults(self, archive = False):
        if archive:
            h2h_log_file = Path(self.config.LOG_DIR) / 'archive' / self.config.H2H_BETS_LOG
            spread_log_file = Path(self.config.LOG_DIR) / 'archive' / self.config.SPREAD_BETS_LOG
            total_log_file = Path(self.config.LOG_DIR) / 'archive' / self.config.TOTAL_BETS_LOG
        else:
            h2h_log_file = Path(self.config.LOG_DIR) / self.config.H2H_BETS_LOG
            spread_log_file = Path(self.config.LOG_DIR) / self.config.SPREAD_BETS_LOG
            total_log_file = Path(self.config.LOG_DIR) / self.config.TOTAL_BETS_LOG
        files = [h2h_log_file, spread_log_file, total_log_file]
        game_data = pd.read_csv(f'././data/basketball/game_data/{self.preparer.getCurrentSeason()}_game_stats.csv')

        for file in files:
            if file.exists():
                df = pd.read_csv(file)

                for idx, row in df.iterrows():
                    game_id = int(row['game_id'])

                    if row['date'].split(' ')[0] == datetime.now().strftime('%Y-%m-%d'):
                        continue

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

                                if row['bet_side'] == 'home':
                                    spread = row['home_spread']
                                    home_score += spread

                                    if home_score > away_score:
                                        df.at[idx, 'result'] = 'W'
                                    elif home_score < away_score:
                                        df.at[idx, 'result'] = 'L'
                                    else:
                                        df.at[idx, 'result'] = 'D'
                                elif row['bet_side'] == 'away':
                                    spread = row['away_spread']
                                    away_score += spread

                                    if away_score > home_score:
                                        df.at[idx, 'result'] = 'W'
                                    elif away_score < home_score:
                                        df.at[idx, 'result'] = 'L'
                                    else:
                                        df.at[idx, 'result'] = 'D'
                            else:
                                df.at[idx, 'result'] = ''

                        elif row['type'] == 'total':
                            home_data = game_data[(game_data['GAME_ID'] == game_id) & (game_data['TEAM_ABBREVIATION'] == row['matchup'].split(' ')[2])]
                            away_data = game_data[(game_data['GAME_ID'] == game_id) & (game_data['TEAM_ABBREVIATION'] == row['matchup'].split(' ')[0])]

                            if len(home_data) > 0 and len(away_data) > 0:
                                home_score = home_data['PTS'].values[0]
                                away_score = away_data['PTS'].values[0]
                                total_score = home_score + away_score
                                
                                if row['bet_side'].lower() == 'over':
                                    if total_score > row['total_line']:
                                        df.at[idx, 'result'] = 'W'
                                    elif total_score < row['total_line']:
                                        df.at[idx, 'result'] = 'L'
                                    else:
                                        df.at[idx, 'result'] = 'D'
                                elif row['bet_side'].lower() == 'under':
                                    if total_score < row['total_line']:
                                        df.at[idx, 'result'] = 'W'
                                    elif total_score > row['total_line']:
                                        df.at[idx, 'result'] = 'L'
                                    else:
                                        df.at[idx, 'result'] = 'D'
                            else:
                                df.at[idx, 'result'] = ''
                                
                df.to_csv(file, index=False)

    def setBankroll(self, archive = False):
        try:
            self.updateBetResults(archive)
        except Exception as e:
            print(f"Error updating bet results: {e}")
            return self.config.STARTING_BANKROLL
        
        # Use unified bankroll if enabled
        if getattr(self.config, 'USE_UNIFIED_BANKROLL', False):
            return UnifiedBankroll.getUnifiedBankroll()
        
        # Otherwise use sport-specific bankroll
        if archive:
            h2h_log_file = Path(self.config.LOG_DIR) / 'archive' / self.config.H2H_BETS_LOG
            spread_log_file = Path(self.config.LOG_DIR) / 'archive' / self.config.SPREAD_BETS_LOG
            total_log_file = Path(self.config.LOG_DIR) / 'archive' / self.config.TOTAL_BETS_LOG
        else:
            h2h_log_file = Path(self.config.LOG_DIR) / self.config.H2H_BETS_LOG
            spread_log_file = Path(self.config.LOG_DIR) / self.config.SPREAD_BETS_LOG
            total_log_file = Path(self.config.LOG_DIR) / self.config.TOTAL_BETS_LOG
        
        files = [h2h_log_file, spread_log_file, total_log_file]
        bankroll = self.config.STARTING_BANKROLL
         
        for file in files:
            if file.exists():
                df = pd.read_csv(file)
                
                for _, row in df.iterrows():
                    if row['result'] == 'W':
                        bankroll += row['potential_profit']
                    elif row['result'] == 'L':
                        bankroll -= row['bet_amount']

        return bankroll

    def getCurrentBankroll(self):
        return self.current_bankroll

    def getActiveBets(self):
        h2h_log_file = Path(self.config.LOG_DIR) / self.config.H2H_BETS_LOG
        spread_log_file = Path(self.config.LOG_DIR) / self.config.SPREAD_BETS_LOG
        total_log_file = Path(self.config.LOG_DIR) / self.config.TOTAL_BETS_LOG
        
        files = [h2h_log_file, spread_log_file, total_log_file]
        
        for file in files:
            if file.exists():
                df = pd.read_csv(file)
                
                return df[df['result'].isnull()]

    def displayModelWinRate(self, archive = False):
        if archive:
            h2h_log_file = Path(self.config.LOG_DIR) / 'archive' / self.config.H2H_BETS_LOG
            spread_log_file = Path(self.config.LOG_DIR) / 'archive' / self.config.SPREAD_BETS_LOG
            total_log_file = Path(self.config.LOG_DIR) / 'archive' / self.config.TOTAL_BETS_LOG
        else:
            h2h_log_file = Path(self.config.LOG_DIR) / self.config.H2H_BETS_LOG
            spread_log_file = Path(self.config.LOG_DIR) / self.config.SPREAD_BETS_LOG
            total_log_file = Path(self.config.LOG_DIR) / self.config.TOTAL_BETS_LOG
        
        files = [('h2h', h2h_log_file), ('spread', spread_log_file), ('total', total_log_file)]
        
        for model_type, file in files:
            wins = 0
            losses = 0
            money_wins = 0
            money_losses = 0
            
            if file.exists():
                df = pd.read_csv(file)
                
                for _, row in df.iterrows():
                    if row['result'] == 'W':
                        wins += 1
                        money_wins += row['potential_profit']
                    elif row['result'] == 'L':
                        losses += 1
                        money_losses += row['bet_amount']
        
            print("\nModel Win Rates:")
            print(f"{model_type} Win Rate: {wins/(wins + losses)}% ({wins} - {losses})")
            print(f"{model_type} Money Win: {money_wins} | {model_type} Money Loss: {money_losses}")
