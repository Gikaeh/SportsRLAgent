"""Tests for tools/total_walkforward.py (NBA totals walk-forward backtest).

No network, no warehouse: synthetic frames and a throwaway DuckDB file. The tool's helpers import
only numpy/pandas at module level, so it loads in-process; the equality check against
BettingRecommender runs in a basketball subprocess (package names collide with hockey's).
"""
import importlib.util
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / 'tools' / 'total_walkforward.py'


def loadTool():
    spec = importlib.util.spec_from_file_location('total_walkforward', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tw = loadTool()
CONFIG = tw.loadBettingConfig()


class TestBetRule:
    def test_exactly_min_edge_bets_over_and_under(self):
        assert getattr(CONFIG, 'MIN_TOTAL_EDGE', 8.0) == 8.0
        over = tw.decideTotalBet(228.0, 220.0, 19.0, -110, -110, CONFIG)
        under = tw.decideTotalBet(212.0, 220.0, 19.0, -110, -110, CONFIG)
        assert over['side'] == 'Over' and under['side'] == 'Under'
        assert over['cover_prob'] == pytest.approx(0.5 * (1 + math.erf(8 / 19 / math.sqrt(2))))

    def test_just_below_min_edge_no_bet(self):
        assert tw.decideTotalBet(227.99, 220.0, 19.0, -110, -110, CONFIG)['side'] is None
        assert tw.decideTotalBet(212.01, 220.0, 19.0, -110, -110, CONFIG)['side'] is None

    def test_probability_gate_binds_with_large_sigma(self):
        # Phi(8/80) = 0.54 < MIN_PROBABILITY 0.55
        assert tw.decideTotalBet(228.0, 220.0, 80.0, -110, -110, CONFIG)['side'] is None

    def test_missing_price_falls_back_to_minus_110(self):
        d = tw.decideTotalBet(230.0, 220.0, 19.0, float('nan'), -105, CONFIG)
        assert d['side'] == 'Over' and d['price'] == -110
        d = tw.decideTotalBet(210.0, 220.0, 19.0, -105, None, CONFIG)
        assert d['side'] == 'Under' and d['price'] == -110

    def test_side_price_is_used(self):
        assert tw.decideTotalBet(210.0, 220.0, 19.0, -130, +105, CONFIG)['price'] == 105

    def test_grading_and_push(self):
        assert tw.gradeTotal('Over', 220.0, 221) == 'W'
        assert tw.gradeTotal('Over', 220.0, 219) == 'L'
        assert tw.gradeTotal('Under', 220.0, 219) == 'W'
        assert tw.gradeTotal('Over', 220.0, 220) == 'P'
        assert tw.gradeTotal('Under', 220.0, 220) == 'P'
        assert tw.betProfit('P', -110) == 0.0
        assert tw.betProfit('L', -110) == -1.0
        assert tw.gradeTotal(None, 220.0, 230) is None

    def test_clv_direction(self):
        assert tw.clvPoints('Over', 220.0, 222.5) == 2.5
        assert tw.clvPoints('Under', 220.0, 222.5) == -2.5
        assert math.isnan(tw.clvPoints('Over', float('nan'), 222.5))


class TestPriceMath:
    def test_break_even(self):
        assert tw.oddsToProbability(-110) == pytest.approx(110 / 210)
        assert tw.oddsToProbability(150) == pytest.approx(0.4)

    def test_unit_profit(self):
        assert tw.betProfit('W', -110) == pytest.approx(100 / 110)
        assert tw.betProfit('W', 150) == pytest.approx(1.5)

    def test_roi_and_win_rate_exclude_push_from_win_rate_only(self):
        bets = pd.DataFrame({
            'date': pd.to_datetime(['2025-01-01', '2025-01-01', '2025-01-02', '2025-01-03']),
            'result': ['W', 'L', 'P', 'W'],
            'bet_price': [-110.0, -110.0, -110.0, 100.0],
            'profit': [100 / 110, -1.0, 0.0, 1.0],
            'clv': [1.0, -0.5, np.nan, 0.0],
        })
        s = tw.summarizeBets(bets, reps=200)
        assert (s['wins'], s['losses'], s['pushes']) == (2, 1, 1)
        assert s['win_rate'] == pytest.approx(2 / 3)
        assert s['roi'] == pytest.approx((100 / 110 - 1 + 0 + 1) / 4)
        assert s['break_even'] == pytest.approx((110 / 210 * 2 + 0.5) / 3)
        assert s['clv'] == {'mean': pytest.approx(1 / 6), 'share_positive': pytest.approx(1 / 3), 'n': 3}


def test_matches_betting_recommender_math():
    """The tool's cover probability and Kelly equal BettingRecommender's own methods."""
    code = f"""
import importlib.util, types
from betting.betting_recommender import BettingRecommender
from betting.betting_config import BettingConfig
spec = importlib.util.spec_from_file_location('tw', r'{TOOL}')
tw = importlib.util.module_from_spec(spec); spec.loader.exec_module(tw)
fake = types.SimpleNamespace(config=BettingConfig())
for edge in [0.5, 8.0, 12.3, 25.0, 60.0]:
    for sigma in [5.0, 14.0, 19.14]:
        a = BettingRecommender.normalCoverProbability(None, edge, sigma)
        assert a == tw.normalCoverProbability(edge, sigma), (edge, sigma)
        for price in [-130, -110, -105, 100, 120, 250]:
            b = BettingRecommender.kellyCriterion(fake, a, price, None)
            assert b == tw.kellyFraction(a, price, BettingConfig()), (edge, sigma, price)
            assert BettingRecommender.oddsToProbability(None, price) == tw.oddsToProbability(price)
            assert BettingRecommender.calculateProfit(None, 1, price) == tw.unitProfit(price)
cfg = tw.loadBettingConfig()
assert getattr(cfg, 'MIN_TOTAL_EDGE', 8.0) == getattr(BettingConfig, 'MIN_TOTAL_EDGE', 8.0)
assert cfg.MIN_PROBABILITY == BettingConfig.MIN_PROBABILITY
print('ok')
"""
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT / 'basketball')
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=ROOT,
                       timeout=120, env=env)
    assert r.returncode == 0, r.stderr[-2000:]
    assert 'ok' in r.stdout


class TestClusterBootstrap:
    def deepsportsReference(self, num, clusters, reps, seed):
        # Copy of DeepSports analysis/ensemble.py::cluster_bootstrap (den = 1 per row).
        from collections import defaultdict
        by_day = defaultdict(list)
        for i, c in enumerate(clusters):
            by_day[c].append(i)
        days = [by_day[k] for k in sorted(by_day)]
        sums = np.array([num[ix].sum() for ix in days])
        cnts = np.array([len(ix) for ix in days], dtype=float)
        rng = np.random.default_rng(seed)
        stats = np.empty(reps)
        for b in range(reps):
            pick = rng.integers(0, len(days), len(days))
            stats[b] = sums[pick].sum() / cnts[pick].sum()
        return np.percentile(stats, 2.5), np.percentile(stats, 97.5)

    def test_equals_deepsports_reference(self):
        rng = np.random.default_rng(1)
        num = rng.integers(0, 2, 60).astype(float)
        clusters = [f"2025-01-{d:02d}" for d in rng.integers(1, 15, 60)]
        got = tw.clusterBootstrap(num, np.ones(60), clusters, reps=500, seed=0)
        lo, hi = self.deepsportsReference(num, clusters, 500, 0)
        assert got['lo'] == pytest.approx(lo) and got['hi'] == pytest.approx(hi)
        assert got['mean'] == pytest.approx(num.mean())
        assert got['clusters'] == len(set(clusters))

    def test_single_cluster_degenerate(self):
        got = tw.clusterBootstrap([1, 0, 1, 1], [1, 1, 1, 1], ['d'] * 4, reps=100)
        assert got['lo'] == got['hi'] == got['mean'] == 0.75

    def test_ratio_weights_by_cluster_size(self):
        # identical per-cluster rates -> every resample gives the same ratio
        got = tw.clusterBootstrap([1, 0, 1, 0, 1, 0], [1] * 6, ['a', 'a', 'b', 'b', 'c', 'c'], reps=100)
        assert got['lo'] == got['hi'] == 0.5

    def test_empty(self):
        assert math.isnan(tw.clusterBootstrap([], [], [], reps=10)['mean'])

    def test_wilson(self):
        lo, hi = tw.wilsonInterval(55, 100)
        assert lo == pytest.approx(0.4524, abs=1e-4) and hi == pytest.approx(0.6438, abs=1e-4)


class TestTeamMatching:
    def test_code_map(self):
        for nba, espn in {'NYK': 'NY', 'SAS': 'SA', 'NOP': 'NO', 'UTA': 'UTAH', 'GSW': 'GS',
                          'WAS': 'WSH', 'BOS': 'BOS', 'LAL': 'LAL'}.items():
            assert tw.toEspn(nba) == espn

    def test_load_and_match_market_eastern_date(self, tmp_path):
        import duckdb
        db = tmp_path / 'w.duckdb'
        con = duckdb.connect(str(db))
        con.execute("CREATE TABLE teams (league VARCHAR, team_id VARCHAR, abbreviation VARCHAR)")
        con.execute("INSERT INTO teams VALUES ('nba','1','NY'),('nba','2','GS'),('nba','3','UTAH'),"
                    "('nba','4','BOS')")
        con.execute("CREATE TABLE games (game_id VARCHAR, league VARCHAR, season_year INT, season_type INT,"
                    " start_time_utc TIMESTAMPTZ, home_team_id VARCHAR, away_team_id VARCHAR,"
                    " home_score INT, away_score INT)")
        # 7:30 pm ET on Jan 10 = 00:30 UTC Jan 11; preseason game must be excluded.
        con.execute("INSERT INTO games VALUES ('g1','nba',2025,2,'2025-01-11 00:30:00+00','1','2',110,100),"
                    "('g2','nba',2025,3,'2025-04-20 17:00:00+00','3','4',99,98),"
                    "('g3','nba',2025,1,'2024-10-10 23:00:00+00','1','4',90,91)")
        con.execute("CREATE TABLE odds_snapshots (game_id VARCHAR, source VARCHAR, captured_at TIMESTAMPTZ,"
                    " provider VARCHAR, over_under DOUBLE, over_price INT, under_price INT)")
        con.execute("INSERT INTO odds_snapshots VALUES ('g1','closing',now(),'X',221.5,-110,-110),"
                    "('g1','opening',now(),'X',219.5,-110,-110),('g2','closing',now(),'X',210.0,NULL,NULL),"
                    # A second, older closing row must not duplicate (and so drop) g1.
                    "('g1','closing',now() - INTERVAL 1 HOUR,'X',220.0,-110,-110)")
        con.close()
        market = tw.loadMarket(db)
        assert set(market['ws_game_id']) == {'g1', 'g2'}
        preds = pd.DataFrame({
            'game_id': ['0022400001', '0042400001', '0022400002'],
            'date': pd.to_datetime(['2025-01-10', '2025-04-20', '2025-01-11']),
            'home_team': ['NYK', 'UTA', 'NYK'], 'away_team': ['GSW', 'BOS', 'GSW'],
        })
        m = tw.matchMarket(preds, market)
        assert list(m['ws_game_id'].fillna('')) == ['g1', 'g2', '']
        assert m.loc[0, 'close_total'] == 221.5 and m.loc[0, 'open_total'] == 219.5
        assert pd.isna(m.loc[1, 'close_over_price'])


def syntheticFrame(n_days=150, games_per_day=4, seed=0):
    rng = np.random.default_rng(seed)
    dates = np.repeat(pd.date_range('2024-01-01', periods=n_days, freq='D'), games_per_day)
    n = len(dates)
    x1, x2 = rng.normal(size=n), rng.normal(size=n)
    return pd.DataFrame({
        'game_id': [f"{i:010d}" for i in range(n)], 'date': dates, 'season': '2023-24',
        'game_type': 2, 'home_team': 'BOS', 'away_team': 'NYK', 'home_score': 110, 'away_score': 105,
        'f1': x1, 'f2': x2, 'total_score': 220 + 10 * x1 - 5 * x2 + rng.normal(scale=8, size=n),
    })


class TestWalkForward:
    PARAMS = {'n_estimators': 30, 'max_depth': 2, 'learning_rate': 0.3, 'early_stopping_rounds': 5,
              'n_jobs': 1}

    def test_train_strictly_before_test_month(self):
        frame = syntheticFrame()
        preds = tw.walkForward(frame, ['f1', 'f2'], self.PARAMS, pd.Timestamp('2024-03-01'),
                               pd.Timestamp('2024-05-15'), log=lambda *_: None)
        assert set(preds['refit_month']) == {'2024-03', '2024-04', '2024-05'}
        month_start = pd.PeriodIndex(preds['refit_month'], freq='M').start_time
        assert (preds['train_max_date'] < month_start).all()
        assert (preds['date'] >= month_start).all()
        assert preds['date'].max() < pd.Timestamp('2024-05-15')
        assert (preds['sigma'] > 0).all()

    def test_future_rows_do_not_change_earlier_predictions(self):
        frame = syntheticFrame()
        start, end = pd.Timestamp('2024-03-01'), pd.Timestamp('2024-05-01')
        base = tw.walkForward(frame, ['f1', 'f2'], self.PARAMS, start, end, log=lambda *_: None)
        perturbed = frame.copy()
        future = perturbed['date'] >= pd.Timestamp('2024-04-01')
        perturbed.loc[future, 'total_score'] += 50
        perturbed.loc[future, 'f1'] = -perturbed.loc[future, 'f1']
        other = tw.walkForward(perturbed, ['f1', 'f2'], self.PARAMS, start, end, log=lambda *_: None)
        march = base['refit_month'] == '2024-03'
        np.testing.assert_array_equal(base.loc[march, 'pred_total'], other.loc[march, 'pred_total'])
        assert base.loc[march, 'sigma'].iloc[0] == other.loc[march, 'sigma'].iloc[0]
        april = base['refit_month'] == '2024-04'
        assert not np.allclose(base.loc[april, 'pred_total'], other.loc[april, 'pred_total'])

    def test_early_stopping_set_is_last_tenth_by_date(self):
        frame = syntheticFrame(n_days=50)
        model, sigma, seen = tw.fitRefit(frame, ['f1', 'f2'], self.PARAMS)
        assert seen == set(frame['game_id']) and sigma > 0


def test_feature_columns_diff():
    frame = pd.DataFrame(columns=['game_id', 'date', 'a', 'b', 'total_score', 'game_type', 'season'])
    feats, diff = tw.featureColumns(frame, ['a', 'b'], ['game_id', 'date', 'season'])
    assert feats == ['a', 'b'] and diff == {'only_in_frame': [], 'only_in_model': [], 'same_order': True}
    feats, diff = tw.featureColumns(frame, ['a', 'c'], ['game_id', 'date', 'season'])
    assert feats == ['a', 'c'] and diff['only_in_frame'] == ['b'] and diff['only_in_model'] == ['c']


def test_ship_verdict():
    s = {'win_rate_ci': {'lo': 0.53}, 'break_even': 0.524, 'mae_diff': 0.4}
    assert tw.shipVerdict(s)['ship'] is True
    assert tw.shipVerdict({**s, 'mae_diff': 0.51})['ship'] is False
    assert tw.shipVerdict({**s, 'win_rate_ci': {'lo': 0.52}})['ship'] is False
