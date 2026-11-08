"""Upcoming-games prediction + fake-odds betting test (basketball).

Mirrors `basketball/main.py` -> `bettingRecommendations` ("All") without touching
the network, real data files, models/ or logs/:
  A. Models: trains tiny in-memory XGBoost models (h2h/spread/total) on synthetic
     features, predicts on 3 fake upcoming games (slate table like
     tools/pipeline_smoke_test.py).
  B. predictGames wiring: attaches each trained model to a real
     BettingRecommender (real BettingConfig thresholds, bankroll $40) with a
     stubbed getOdds, and calls the REAL predictGames for all three markets.
  C. Betting: feeds DETERMINISTIC predictions (crafted to clear gates on two
     games and miss on one) plus FAKE books-style odds CSVs through the REAL
     makeH2H/Spread/TotalRecommendations, prints every recommended bet, and
     asserts Kelly sizing per bet (fraction bounds, stake == round(frac *
     bankroll), profit math, independent Kelly recomputation, cap behaviour).

The full fetch -> prepare -> train -> predict wiring on real data is covered by
tools/pipeline_smoke_test.py (too heavy/slow for pytest). This test covers the
predict + recommend contracts with hermetic fakes.

Basketball modules are imported in an isolated interpreter via PYTHONPATH
(basketball/ and hockey/ share package names `model`, `data_pipeline`,
mirroring how `.venv/bin/python basketball/main.py` runs).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def run_in_basketball(code):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "basketball")
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=180,
        env=env,
    )


UPCOMING_CHECK = """
import glob as _glob
import tempfile
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from model.model_h2h import BasketballH2HModel
from model.model_spread import BasketballSpreadModel
from model.model_total import BasketballTotalModel
import betting.betting_recommender as rec_mod
from betting.betting_recommender import BettingRecommender
from betting.betting_config import BettingConfig

rng = np.random.default_rng(42)
pd.set_option('display.width', 250)
pd.set_option('display.max_columns', 30)

# ---- A. Fake upcoming slate (same shape as data/basketball/upcoming_games.csv) ----
upcoming = pd.DataFrame([
    {'game_id': 9001, 'date': '2026-01-20', 'home_team': 'BOS', 'away_team': 'LAL'},
    {'game_id': 9002, 'date': '2026-01-20', 'home_team': 'GSW', 'away_team': 'DAL'},
    {'game_id': 9003, 'date': '2026-01-20', 'home_team': 'DEN', 'away_team': 'PHX'},
])
game_info = upcoming.copy()

FEATURES = [f'f{i}' for i in range(10)]
n_train = 300
X_train = pd.DataFrame(rng.normal(size=(n_train, len(FEATURES))), columns=FEATURES)
X_pred = pd.DataFrame(rng.normal(size=(len(upcoming), len(FEATURES))), columns=FEATURES)
assert list(X_pred.columns) == list(X_train.columns), 'train/predict feature mismatch'

y_h2h = (X_train['f0'] + rng.normal(scale=0.5, size=n_train) > 0).astype(int)
h2h = BasketballH2HModel(n_estimators=20, early_stopping_rounds=None)
h2h.train(X_train, y_h2h, verbose=False)

y_margin = X_train['f0'] * 5 + rng.normal(scale=3, size=n_train)
spread_m = BasketballSpreadModel(n_estimators=20, early_stopping_rounds=None)
spread_m.train(X_train, y_margin, verbose=False)

y_total = 225 + X_train['f1'] * 5 + rng.normal(scale=4, size=n_train)
total_m = BasketballTotalModel(n_estimators=20, early_stopping_rounds=None)
total_m.train(X_train, y_total, verbose=False)

print('=== A. Model slate (synthetic features, in-memory models) ===')
slate = game_info.copy()
slate['home_win_prob'] = h2h.predictProb(X_pred)[:, 1]
slate['predicted_margin'] = spread_m.predict(X_pred)
slate['predicted_total'] = total_m.predict(X_pred)
print(slate.to_string(index=False))
assert ((slate['home_win_prob'] >= 0) & (slate['home_win_prob'] <= 1)).all()
assert ((slate['predicted_total'] > 180) & (slate['predicted_total'] < 270)).all()

# ---- Fake books-style odds (real CSV schema, NEVADA books only) ----
H2H_ODDS = pd.DataFrame([
    {'commence_time': '2026-01-20', 'home_team': 'BOS', 'away_team': 'LAL',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'h2h',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'BOS', 'price': -150},
    {'commence_time': '2026-01-20', 'home_team': 'BOS', 'away_team': 'LAL',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'h2h',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'LAL', 'price': 130},
    {'commence_time': '2026-01-20', 'home_team': 'GSW', 'away_team': 'DAL',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'h2h',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'GSW', 'price': -120},
    {'commence_time': '2026-01-20', 'home_team': 'GSW', 'away_team': 'DAL',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'h2h',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'DAL', 'price': 100},
    {'commence_time': '2026-01-20', 'home_team': 'DEN', 'away_team': 'PHX',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'h2h',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'DEN', 'price': 110},
    {'commence_time': '2026-01-20', 'home_team': 'DEN', 'away_team': 'PHX',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'h2h',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'PHX', 'price': -130},
])
SPREAD_ODDS = pd.DataFrame([
    {'commence_time': '2026-01-20', 'home_team': 'BOS', 'away_team': 'LAL',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'spreads',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'BOS', 'price': -110, 'point': -5.5},
    {'commence_time': '2026-01-20', 'home_team': 'BOS', 'away_team': 'LAL',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'spreads',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'LAL', 'price': -110, 'point': 5.5},
    {'commence_time': '2026-01-20', 'home_team': 'GSW', 'away_team': 'DAL',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'spreads',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'GSW', 'price': -110, 'point': -1.5},
    {'commence_time': '2026-01-20', 'home_team': 'GSW', 'away_team': 'DAL',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'spreads',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'DAL', 'price': -110, 'point': 1.5},
    {'commence_time': '2026-01-20', 'home_team': 'DEN', 'away_team': 'PHX',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'spreads',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'DEN', 'price': -110, 'point': -2.5},
    {'commence_time': '2026-01-20', 'home_team': 'DEN', 'away_team': 'PHX',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'spreads',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'PHX', 'price': -110, 'point': 2.5},
])
TOTAL_ODDS = pd.DataFrame([
    {'commence_time': '2026-01-20', 'home_team': 'DEN', 'away_team': 'PHX',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'totals',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'Over', 'price': -110, 'point': 224.5},
    {'commence_time': '2026-01-20', 'home_team': 'DEN', 'away_team': 'PHX',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'totals',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'Under', 'price': -110, 'point': 224.5},
    {'commence_time': '2026-01-20', 'home_team': 'BOS', 'away_team': 'LAL',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'totals',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'Over', 'price': -110, 'point': 228.5},
    {'commence_time': '2026-01-20', 'home_team': 'BOS', 'away_team': 'LAL',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'totals',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'Under', 'price': -110, 'point': 228.5},
    {'commence_time': '2026-01-20', 'home_team': 'GSW', 'away_team': 'DAL',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'totals',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'Over', 'price': -110, 'point': 228.5},
    {'commence_time': '2026-01-20', 'home_team': 'GSW', 'away_team': 'DAL',
     'bookmakers_key': 'betmgm', 'bookmakers_markets_key': 'totals',
     'bookmakers_markets_last_update': '2026-01-19', 'name': 'Under', 'price': -110, 'point': 228.5},
])


def makeRecommender(model, odds_df):
    # Skip __init__ (Odds API + model files + bankroll logs); use the REAL
    # BettingConfig thresholds so gates behave exactly like main.py.
    rec = BettingRecommender.__new__(BettingRecommender)
    rec.config = BettingConfig()
    rec.model = model
    rec.current_bankroll = 40
    rec.margin_residual_sigma = 11.8
    rec.total_residual_sigma = 14.0
    rec.getOdds = lambda mt: odds_df.copy()
    return rec


# ---- B. REAL predictGames for all three markets (main.py "All" path) ----
print('=== B. predictGames output (trained models + stubbed odds) ===')
rec_h2h = makeRecommender(h2h, H2H_ODDS)
pred_h2h = rec_h2h.predictGames(X_pred, game_info)
print(pred_h2h[['game_id', 'home_team', 'away_team', 'home_win_prob',
                'predicted_winner', 'confidence']].to_string(index=False))
assert not pred_h2h[['home_win_prob', 'confidence']].isna().any().any()

rec_spread = makeRecommender(spread_m, SPREAD_ODDS)
pred_spread = rec_spread.predictGames(X_pred, game_info)
print(pred_spread[['game_id', 'home_team', 'away_team', 'predicted_margin',
                   'predicted_cover', 'confidence']].to_string(index=False))
assert not pred_spread[['predicted_margin', 'confidence']].isna().any().any()

rec_total = makeRecommender(total_m, TOTAL_ODDS)
pred_total = rec_total.predictGames(X_pred, game_info)
print(pred_total[['game_id', 'home_team', 'away_team', 'predicted_total',
                  'confidence']].to_string(index=False))
assert not pred_total[['predicted_total', 'confidence']].isna().any().any()

# ---- B2 regression: bestOutcomeRow pairs point+price+book from the SAME row ----
two_books = pd.DataFrame([
    {'home_team': 'GSW', 'name': 'GSW', 'point': -4.5, 'price': -110, 'bookmakers_key': 'betmgm'},
    {'home_team': 'GSW', 'name': 'GSW', 'point': -5.5, 'price': 100, 'bookmakers_key': 'caesars'},
])
best_gsw = rec_spread.bestOutcomeRow(two_books)
assert best_gsw['price'] == 100 and best_gsw['point'] == -5.5, (
    f'best-price row must carry its own line, got {best_gsw.to_dict()}')

# ---- C. REAL make*Recommendations on deterministic predictions + fake odds ----
# Crafted so two games clear the gates and one misses per market:
#   H2H:    BOS home 0.65 vs -150/+130 -> BET; GSW 0.51 coin-flip -> none; PHX away 0.60 -> BET
#   Spread: BOS +9.0 vs -5.5 -> home BET; GSW +0.5 vs -1.5 -> none; DEN -7.0 -> PHX away BET
#   Total:  DEN 233.5 vs 224.5 -> Over BET; BOS 226 / GSW 221 vs 228.5 -> none
det_h2h = pd.DataFrame([
    {'game_id': 9001, 'date': '2026-01-20', 'home_team': 'BOS', 'away_team': 'LAL',
     'home_win_prob': 0.65, 'away_win_prob': 0.35, 'confidence': 0.30},
    {'game_id': 9002, 'date': '2026-01-20', 'home_team': 'GSW', 'away_team': 'DAL',
     'home_win_prob': 0.51, 'away_win_prob': 0.49, 'confidence': 0.02},
    {'game_id': 9003, 'date': '2026-01-20', 'home_team': 'DEN', 'away_team': 'PHX',
     'home_win_prob': 0.40, 'away_win_prob': 0.60, 'confidence': 0.20},
])
det_spread = pd.DataFrame([
    {'game_id': 9001, 'date': '2026-01-20', 'home_team': 'BOS', 'away_team': 'LAL',
     'predicted_margin': 9.0, 'confidence': 0.45},
    {'game_id': 9002, 'date': '2026-01-20', 'home_team': 'GSW', 'away_team': 'DAL',
     'predicted_margin': 0.5, 'confidence': 0.05},
    {'game_id': 9003, 'date': '2026-01-20', 'home_team': 'DEN', 'away_team': 'PHX',
     'predicted_margin': -7.0, 'confidence': 0.35},
])
det_total = pd.DataFrame([
    {'game_id': 9001, 'date': '2026-01-20', 'home_team': 'BOS', 'away_team': 'LAL',
     'predicted_total': 226.0, 'confidence': 0.10},
    {'game_id': 9002, 'date': '2026-01-20', 'home_team': 'GSW', 'away_team': 'DAL',
     'predicted_total': 221.0, 'confidence': 0.10},
    {'game_id': 9003, 'date': '2026-01-20', 'home_team': 'DEN', 'away_team': 'PHX',
     'predicted_total': 233.5, 'confidence': 0.40},
])

tmp = tempfile.TemporaryDirectory()
h2h_csv = str(Path(tmp.name) / 'h2h_fake.csv')
spread_csv = str(Path(tmp.name) / 'spread_fake.csv')
total_csv = str(Path(tmp.name) / 'total_fake.csv')
H2H_ODDS.to_csv(h2h_csv, index=False)
SPREAD_ODDS.to_csv(spread_csv, index=False)
TOTAL_ODDS.to_csv(total_csv, index=False)


def fake_glob(pattern, **kwargs):
    if 'h2h_' in pattern:
        return [h2h_csv]
    if 'spread_' in pattern:
        return [spread_csv]
    if 'total_' in pattern:
        return [total_csv]
    return _glob.glob(pattern, **kwargs)


def checkKelly(bet, odds_used, bankroll=40, cap=0.05):
    # Every recommended bet must carry a valid Kelly stake.
    frac = bet['bet_size_fraction']
    assert 0 < frac <= cap, f'Kelly fraction out of bounds: {frac} in {bet}'
    assert bet['bet_amount'] == round(frac * bankroll), f'stake mismatch in {bet}'
    assert bet['bet_amount'] > 0, f'stake must be positive in {bet}'
    assert abs(bet['potential_profit'] - rec_h2h.calculateProfit(bet['bet_amount'], odds_used)) < 1e-9, (
        f'profit mismatch in {bet}')


with mock.patch.object(rec_mod.glob, 'glob', side_effect=fake_glob):
    h2h_recs = rec_h2h.makeBettingRecommendations(det_h2h)
    spread_recs = rec_spread.makeBettingRecommendations(det_spread)
    total_recs = rec_total.makeBettingRecommendations(det_total)

print('=== C. H2H recommendations (fake lines) ===')
assert len(h2h_recs) == 2, f'expected BOS-home + PHX-away bets, got {h2h_recs}'
h2h_df = pd.DataFrame(h2h_recs)
print(h2h_df[['matchup', 'bet_side', 'bet_team', 'home_odds', 'away_odds', 'edge',
              'bet_size_fraction', 'bet_amount', 'potential_profit', 'book']].to_string(index=False))
sides = {(r['bet_team'], r['bet_side']) for r in h2h_recs}
assert sides == {('BOS', 'home'), ('PHX', 'away')}, f'unexpected h2h sides: {sides}'
for r in h2h_recs:
    assert r['edge'] >= 0.02 and r['confidence'] >= 0, f'gate breach in {r}'
    prob = r['home_model_prob'] if r['bet_side'] == 'home' else r['away_model_prob']
    assert prob >= 0.55, f'prob gate breach in {r}'
    checkKelly(r, r['home_odds'] if r['bet_side'] == 'home' else r['away_odds'])

# Independent Kelly recomputation for the BOS bet (fractional Kelly 0.2, -150):
# decimal = 100/150 + 1; raw = (p*decimal - 1)/(decimal - 1); frac = min(raw*0.2, cap)
bos = next(r for r in h2h_recs if r['bet_team'] == 'BOS')
dec = 100 / 150 + 1
expected_frac = min(((0.65 * dec - 1) / (dec - 1)) * 0.20, 0.05)
assert abs(bos['bet_size_fraction'] - expected_frac) < 1e-9, (
    f'Kelly formula mismatch: {bos["bet_size_fraction"]} vs {expected_frac}')

print('=== C. Spread recommendations (fake lines) ===')
assert len(spread_recs) == 2, f'expected BOS-home + PHX-away bets, got {spread_recs}'
spread_df = pd.DataFrame(spread_recs)
print(spread_df[['matchup', 'bet_side', 'bet_team', 'home_spread', 'away_spread',
                 'predicted_margin', 'margin_advantage', 'cover_prob',
                 'bet_size_fraction', 'bet_amount', 'potential_profit']].to_string(index=False))
sides = {(r['bet_team'], r['bet_side']) for r in spread_recs}
assert sides == {('BOS', 'home'), ('PHX', 'away')}, f'unexpected spread sides: {sides}'
for r in spread_recs:
    assert r['margin_advantage'] >= 3 and r['cover_prob'] >= 0.55, f'gate breach in {r}'
    checkKelly(r, r['home_odds'] if r['bet_side'] == 'home' else r['away_odds'])

print('=== C. Total recommendations (fake lines) ===')
assert len(total_recs) == 1, f'expected only the DEN Over bet, got {total_recs}'
total_df = pd.DataFrame(total_recs)
print(total_df[['matchup', 'bet_side', 'total_line', 'predicted_total', 'total_advantage',
                'cover_prob', 'bet_size_fraction', 'bet_amount',
                'potential_profit']].to_string(index=False))
t = total_recs[0]
assert t['bet_side'] == 'Over' and t['total_advantage'] >= 8 and t['cover_prob'] >= 0.55
checkKelly(t, t['over_odds'])
# Big total edge must hit the MAX_BET_SIZE_PCT cap (proves the cap works):
assert t['bet_size_fraction'] == 0.05, f'cap not applied: {t["bet_size_fraction"]}'

print('ok: all 3 models predicted; 5 fake-line bets sized by Kelly (2 h2h + 2 spread + 1 total)')
"""


@pytest.mark.parametrize("sport", ["basketball"])
def test_upcoming_prediction_with_fake_odds(sport):
    result = run_in_basketball(UPCOMING_CHECK)
    # Forward the subprocess output so `pytest -s` shows the slate/bet tables.
    if result.stdout:
        print(result.stdout)
    assert result.returncode == 0, (
        f"upcoming prediction + fake odds test failed:\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
