"""Non-interactive export of ManualBets' view of the upcoming slate, as JSON, for other tools
(DeepSports' ensemble-betting context reads it; root docs/DECISIONS.md 2026-11-11, edge 4).

    uv run python tools/export_predictions.py --out /path/to/manualbets.json [--league nba|ncaab|all]

NBA: the XGBoost h2h + spread models for the next slate (nba_api; pause NordVPN), the best price
per side across every US book from The Odds API (2 credits: h2h + spreads), and the Kelly
recommendations exactly as the NBA menu makes them. College: the college model for the next
2 days (reads the DeepSports warehouse); college odds (3 credits) are fetched only when some game
clears MIN_GAMES_PLAYED, since the recommender withholds everything else.

Stakes are exported as fractions of the bankroll, never dollars. Nothing is logged to ../logs/
(the NBA recommender's bet grading is skipped), nothing is placed. ManualBets' own prints go to
stderr; one league failing is recorded in `errors` and doesn't stop the other.
"""
import argparse
import contextlib
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REMAINING = re.compile(r"Remaining requests\s+(\d+)")


def clean(err):
    """Exception text without the Odds API key (it travels in request URLs)."""
    return re.sub(r"(?i)(api_?key=)[^&\s'\"]+", r"\1***", f"{type(err).__name__}: {err}")[:300]


def num(x, nd=3):
    try:
        return None if x is None or x != x else round(float(x), nd)
    except (TypeError, ValueError):
        return None


def bestPrices(odds, home, away, with_point):
    """Best price per side across all books (spreads: best point first, then price)."""
    game = odds[(odds['home_team'] == home) & (odds['away_team'] == away)]
    out = {'books': int(game['bookmakers_key'].nunique())}
    for side, team in (('home', home), ('away', away)):
        rows = game[game['name'] == team]
        if rows.empty:
            continue
        keys = ['point', 'price'] if with_point else ['price']
        best = rows.sort_values(keys, ascending=False).iloc[0]
        entry = {'price': int(best['price']), 'book': best['bookmakers_key']}
        if with_point:
            entry['point'] = num(best['point'], 1)
            entry['median_point'] = num(rows['point'].median(), 1)
        out[side] = entry
    return out


def exportNba():
    sys.path[:0] = [str(ROOT / 'basketball'), str(ROOT)]
    from betting.betting_recommender import BettingRecommender
    from data_pipeline.live_data_updater import LiveDataUpdater

    class ExportRecommender(BettingRecommender):
        def updateBetResults(self, archive=False):  # read-only: never rewrite ../logs/
            pass

    h2h_x, spread_x, _total_x, info = LiveDataUpdater().getPredictionReadyData(model_type='all')
    if h2h_x.empty:
        return {'games': [], 'note': 'no upcoming NBA games found'}
    h2h = ExportRecommender(model_path='./models/basketball_h2h_model.json')
    spread = ExportRecommender(model_path='./models/basketball_spread_model.json')
    p_h2h = h2h.predictGames(h2h_x, info)        # fetches h2h odds (1 credit)
    p_spread = spread.predictGames(spread_x, info)  # fetches spread odds (1 credit)
    recs = h2h.makeBettingRecommendations(p_h2h) + spread.makeBettingRecommendations(p_spread)
    # Same daily risk cap as the menu's displayRecommendations.
    recs.sort(key=h2h.calculateBetPriority, reverse=True)
    risk = sum(r['bet_amount'] for r in recs)
    while recs and risk > h2h.current_bankroll * h2h.config.MAX_RISK_PCT:
        risk -= recs.pop()['bet_amount']

    import glob
    import pandas as pd
    h2h_odds = pd.read_csv(sorted(glob.glob('./data/basketball/odds_data/h2h_*.csv'))[-1])
    spread_odds = pd.read_csv(sorted(glob.glob('./data/basketball/odds_data/spread_*.csv'))[-1])
    tips = h2h_odds.groupby(['home_team', 'away_team'])['commence_time'].first().to_dict()

    margins = p_spread.set_index('game_id')['predicted_margin'].to_dict()
    games = []
    for g in p_h2h.itertuples():
        home, away = g.home_team, g.away_team
        mine = [r for r in recs if r['game_id'] == g.game_id]
        games.append({
            'nba_game_id': str(g.game_id), 'date': str(g.date)[:10], 'home': home, 'away': away,
            'tip': tips.get((home, away)),
            'model': {'home_win_prob': num(g.home_win_prob), 'home_margin': num(margins.get(g.game_id), 1)},
            'best_prices': {'moneyline': bestPrices(h2h_odds, home, away, False),
                            'spread': bestPrices(spread_odds, home, away, True)},
            'recommendations': [{
                'market': 'moneyline' if r['type'] == 'h2h' else 'spread', 'side': r['bet_side'],
                'team': r['bet_team'],
                'line': None if r['type'] == 'h2h' else num(r[f"{r['bet_side']}_spread"], 1),
                'price': int(r[f"{r['bet_side']}_odds"]), 'book': r['book'],
                'win_prob': num(r[f"{r['bet_side']}_model_prob"] if r['type'] == 'h2h' else r['cover_prob']),
                'edge': num(r['edge'] if r['type'] == 'h2h' else r['margin_advantage']),
                'edge_unit': 'probability' if r['type'] == 'h2h' else 'points',
                'kelly_fraction': num(r['bet_size_fraction']),
            } for r in mine],
        })
    return {'games': games, 'models': ['basketball_h2h_model', 'basketball_spread_model'],
            'books_used_for_recommendations': list(h2h.config.NEVADA_BOOKS)}


def exportCollege():
    sys.path.insert(0, str(ROOT))
    from college_basketball.betting.betting_config import BettingConfig
    from college_basketball.betting.betting_recommender import matchLines, parseOdds, recommend
    from college_basketball.data_pipeline.odd_scraping import fetchCollegeOdds
    from college_basketball.main import upcomingPredictions

    preds, metadata = upcomingPredictions()
    gate = BettingConfig.MIN_GAMES_PLAYED
    out = {'min_games_played_gate': gate, 'games': [{
        'game_id': str(p.game_id), 'home': p.home_abbr, 'away': p.away_abbr,
        'model': {'home_win_prob': num(p.p_home_win), 'home_margin': num(p.pred_home_margin, 1),
                  'total': num(p.pred_total, 1)},
        'min_games_played': int(p.min_games_played), 'gated': bool(p.min_games_played < gate),
        'recommendations': [],
    } for p in preds.itertuples()]}
    if all(g['gated'] for g in out['games']):
        out['note'] = f'every game is under {gate} games played: no recommendations, odds not fetched'
        return out
    games, remaining = fetchCollegeOdds(BettingConfig.BOOKS)
    out['odds_api_remaining'] = remaining
    pairs, _ = matchLines(preds, parseOdds(games, BettingConfig.BOOKS))
    sigma = metadata.get('residual_std', {})
    bankroll = float(BettingConfig.STARTING_BANKROLL)
    bets = recommend(pairs, sigma.get('spread', BettingConfig.SPREAD_RESIDUAL_SIGMA_FALLBACK),
                     sigma.get('total', BettingConfig.TOTAL_RESIDUAL_SIGMA_FALLBACK), bankroll)
    by_id = {g['game_id']: g for g in out['games']}
    for b in bets:
        g = by_id.get(str(b['game_id']))
        if g is not None:
            g['recommendations'].append({
                'type': b['type'], 'bet': b['bet'], 'price': int(b['odds']), 'book': b['book'],
                'win_prob': num(b['model_probability']), 'expected_value': num(b['expected_value']),
                'kelly_fraction': num(b['stake'] / bankroll), 'detail': b['detail']})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', required=True)
    ap.add_argument('--league', choices=['nba', 'ncaab', 'all'], default='all')
    args = ap.parse_args()

    import os
    os.chdir(ROOT)  # ManualBets code uses paths relative to ManualBets/
    result = {'source': 'ManualBets', 'created_at': datetime.now(timezone.utc).isoformat(),
              'errors': {}}
    for league, fn in (('nba', exportNba), ('ncaab', exportCollege)):
        if args.league not in (league, 'all'):
            continue
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                result[league] = fn()
        except Exception as err:  # noqa: BLE001 - one league failing must not stop the other
            result['errors'][league] = clean(err)
        finally:
            sys.stderr.write(buf.getvalue())
        found = REMAINING.findall(buf.getvalue())
        if found:
            result['odds_api_remaining'] = int(found[-1])
    if 'ncaab' in result and result['ncaab'].get('odds_api_remaining'):
        result['odds_api_remaining'] = int(result['ncaab']['odds_api_remaining'])
    Path(args.out).write_text(json.dumps(result, indent=1, default=str))
    print(json.dumps({'out': args.out, 'errors': result['errors'],
                      'odds_api_remaining': result.get('odds_api_remaining'),
                      'nba_games': len(result.get('nba', {}).get('games', [])),
                      'ncaab_games': len(result.get('ncaab', {}).get('games', []))}))
    return 0 if not result['errors'] else 1


if __name__ == '__main__':
    sys.exit(main())
