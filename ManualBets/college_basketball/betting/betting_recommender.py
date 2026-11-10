"""College bet suggestions. Prints only: it places nothing and writes no bet log."""
import math
import re

import pandas as pd

from college_basketball.betting.betting_config import BettingConfig
from shared.bankroll import kellyFraction, wholeDollarStake

# Odds API spellings that differ from the warehouse's display names, normalized.
NAME_ALIASES = {
    'stthomasmntommies': 'stthomastommies',
    'semissouristredhawks': 'southeastmissouristredhawks',
    'csubakersfieldroadrunners': 'calstbakersfieldroadrunners',
}


def normalizeName(name):
    text = re.sub(r"[^a-z0-9 ]", '', name.lower()).replace('state', 'st').replace('saint', 'st')
    return NAME_ALIASES.get(text.replace(' ', ''), text.replace(' ', ''))


def americanToProbability(odds):
    return -odds / (100 - odds) if odds < 0 else 100 / (odds + 100)


def profitPerUnit(odds):
    return 100 / -odds if odds < 0 else odds / 100


def coverProbability(advantage, sigma):
    return 0.5 * (1 + math.erf(advantage / sigma / math.sqrt(2)))


def parseOdds(games, books):
    """One row per game per book, always oriented to the book's own team names."""
    rows = []
    for game in games:
        for book in game.get('bookmakers', []):
            if book['key'] not in books:
                continue
            row = {'book': book['key'], 'commence_time': pd.Timestamp(game['commence_time']).tz_localize(None),
                   'book_home': game['home_team'], 'book_away': game['away_team']}
            for market in book.get('markets', []):
                outcomes = {o['name']: o for o in market['outcomes']}
                if market['key'] == 'h2h':
                    row['ml'] = {normalizeName(n): o['price'] for n, o in outcomes.items()}
                elif market['key'] == 'spreads':
                    row['spread'] = {normalizeName(n): (o['point'], o['price']) for n, o in outcomes.items()}
                elif market['key'] == 'totals' and 'Over' in outcomes and 'Under' in outcomes:
                    row['total'] = outcomes['Over']['point']
                    row['over_price'] = outcomes['Over']['price']
                    row['under_price'] = outcomes['Under']['price']
            rows.append(row)
    return rows


def matchLines(predictions, lines, max_hours=8):
    """Pairs lines with predictions by team names and tip time. Books sometimes list a
    neutral-site game the other way round, so home/away order is not required.
    Returns (pairs, unmatched lines)."""
    keyed = {}
    for pred in predictions.itertuples():
        keyed.setdefault(frozenset((normalizeName(pred.home_name), normalizeName(pred.away_name))), []).append(pred)
    pairs, unmatched = [], []
    for line in lines:
        names = frozenset((normalizeName(line['book_home']), normalizeName(line['book_away'])))
        close = [p for p in keyed.get(names, [])
                 if abs((p.start_time - line['commence_time']).total_seconds()) <= max_hours * 3600]
        if close:
            pairs.append((close[0], line))
        else:
            unmatched.append(line)
    return pairs, unmatched


def recommend(pairs, spread_sigma, total_sigma, bankroll=BettingConfig.STARTING_BANKROLL, config=BettingConfig):
    """Bets clearing the thresholds, best first, sized by fractional Kelly in whole dollars.
    Same rules as the NBA recommender, including dropping the lowest priority over the risk cap."""
    bets = []
    for pred, line in pairs:
        matchup = f"{pred.away_abbr} @ {pred.home_abbr}"
        home, away = normalizeName(pred.home_name), normalizeName(pred.away_name)
        confidence = abs(pred.p_home_win - 0.5) * 2
        if pred.min_games_played < config.MIN_GAMES_PLAYED:
            continue
        base = {'game_id': pred.game_id, 'start_time': pred.start_time, 'matchup': matchup,
                'book': line['book'], 'min_games_played': int(pred.min_games_played)}

        def add(bet_type, label, probability, odds, detail):
            ev = probability * profitPerUnit(odds) - (1 - probability)
            priority = confidence * ev * (1 + profitPerUnit(odds) * 0.2) * config.PRIORITY_WEIGHTS[bet_type]
            stake = wholeDollarStake(kellyFraction(probability, odds, config.KELLY_FRACTION, config.MAX_BET_SIZE_PCT),
                                     bankroll, config.MIN_BET_AMOUNT)
            if stake:
                bets.append({**base, 'type': bet_type, 'bet': label, 'odds': odds, 'model_probability': probability,
                             'expected_value': ev, 'priority': priority, 'detail': detail, 'stake': stake,
                             'potential_profit': stake * profitPerUnit(odds)})

        ml = line.get('ml', {})
        if home in ml and away in ml:
            fair_home = americanToProbability(ml[home]) / (americanToProbability(ml[home]) + americanToProbability(ml[away]))
            for team, abbr, probability, fair in ((home, pred.home_abbr, pred.p_home_win, fair_home),
                                                  (away, pred.away_abbr, 1 - pred.p_home_win, 1 - fair_home)):
                if probability >= config.MIN_PROBABILITY and probability - fair >= config.MIN_EDGE_H2H:
                    add('h2h', f"{abbr} moneyline", probability, ml[team], f"fair {fair:.1%}")

        spread = line.get('spread', {})
        if home in spread and away in spread:
            for team, abbr, margin in ((home, pred.home_abbr, pred.pred_home_margin),
                                       (away, pred.away_abbr, -pred.pred_home_margin)):
                point, odds = spread[team]
                advantage = margin + point
                probability = coverProbability(advantage, spread_sigma)
                if advantage >= config.MIN_EDGE_SPREAD and probability >= config.MIN_PROBABILITY:
                    add('spread', f"{abbr} {point:+g}", probability, odds, f"model margin {margin:+.1f}, cushion {advantage:.1f}")

        if 'total' in line:
            gap = pred.pred_total - line['total']
            probability = coverProbability(abs(gap), total_sigma)
            if abs(gap) >= config.MIN_EDGE_TOTAL and probability >= config.MIN_PROBABILITY:
                over = gap > 0
                add('total', f"{'Over' if over else 'Under'} {line['total']:g}", probability,
                    line['over_price'] if over else line['under_price'], f"model {pred.pred_total:.1f}")
    bets.sort(key=lambda b: b['priority'], reverse=True)
    while sum(b['stake'] for b in bets) > bankroll * config.MAX_RISK_PCT:
        bets.pop()
    return bets
