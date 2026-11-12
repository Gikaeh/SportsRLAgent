"""Walk-forward backtest of the NBA total (over/under) model against closing lines.

Implements the pre-registration in docs/results/2026-11-11-nba-totals-walkforward.md (section 1):
features from NBATrainingDataPreparer.createGameMatchupData (unchanged), hyperparameters tuned once
on games before 2021-10-01, monthly refits, the recommender's 8-point edge rule at closing prices,
slate-clustered bootstrap CIs and the ship rule on the 2025-26 holdout.

Usage (from ManualBets/):
    uv run python tools/total_walkforward.py --data-dir <nba data dir> --start 2021-10-01 \
        --end 2026-11-11 --out <dir> [--params-json <file>] [--tune-trials 100] [--rebuild-features]
--end is exclusive. Set NBA_WAREHOUSE_DB to read a warehouse copy (opened read-only).
Writes only to --out (and the preparer's cache under --data-dir). Never calls the Odds API.
"""
import argparse
import importlib.util
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WAREHOUSE = ROOT.parent / 'DeepSports' / 'data' / 'deepsports.duckdb'
MODEL_PATH = ROOT / 'models' / 'basketball_total_model.json'
METADATA_PATH = ROOT / 'models' / 'metadata' / 'basketball' / 'retraining_total_metadata.json'
CONFIG_PATH = ROOT / 'basketball' / 'betting' / 'betting_config.py'

TARGET = 'total_score'
TUNE_CUTOFF = pd.Timestamp('2021-10-01')
FALLBACK_PRICE = -110
ES_FRAC = 0.10
FIXED_XGB = {
    # As BasketballTotalModel.trainWithBestParams sets them.
    'objective': 'reg:absoluteerror', 'eval_metric': 'mae', 'tree_method': 'hist',
    'enable_categorical': True, 'n_estimators': 1000, 'early_stopping_rounds': 50,
    'random_state': 42,
}
# NBA.com code -> ESPN abbreviation where they differ (DeepSports analysis/manualbets_context.py).
NBA_CODES = {'NYK': 'NY', 'SAS': 'SA', 'NOP': 'NO', 'UTA': 'UTAH', 'GSW': 'GS', 'WAS': 'WSH'}
PERIODS = {
    'development': ['2021-22', '2022-23', '2023-24', '2024-25'],
    'holdout': ['2025-26'],
    'forward': ['2026-27'],
}
SHIP_MAE_MARGIN = 0.5

MARKET_SQL = """
SELECT g.game_id AS ws_game_id, g.season_year, g.season_type,
       CAST(timezone('America/New_York', g.start_time_utc) AS DATE) AS et_date,
       h.abbreviation AS ws_home, a.abbreviation AS ws_away,
       g.home_score AS ws_home_score, g.away_score AS ws_away_score,
       c.over_under AS close_total, c.over_price AS close_over_price,
       c.under_price AS close_under_price, c.provider AS close_provider,
       o.over_under AS open_total
FROM games g
JOIN teams h ON h.team_id = g.home_team_id AND h.league = g.league
JOIN teams a ON a.team_id = g.away_team_id AND a.league = g.league
LEFT JOIN (SELECT * FROM odds_snapshots WHERE source = 'closing'
           QUALIFY row_number() OVER (PARTITION BY game_id ORDER BY captured_at DESC) = 1) c
       ON c.game_id = g.game_id
LEFT JOIN (SELECT * FROM odds_snapshots WHERE source = 'opening'
           QUALIFY row_number() OVER (PARTITION BY game_id ORDER BY captured_at DESC) = 1) o
       ON o.game_id = g.game_id
WHERE g.league = 'nba' AND g.season_type IN (2, 3, 5)
"""


# ---------- config and ManualBets betting math ----------

def loadBettingConfig(path=CONFIG_PATH):
    """BettingConfig loaded by file path: the `betting` package name collides across sports."""
    spec = importlib.util.spec_from_file_location('nba_betting_config', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BettingConfig


def normalCoverProbability(advantage, sigma):
    """Same as BettingRecommender.normalCoverProbability (equality tested)."""
    if not sigma or sigma <= 0:
        raise ValueError("residual sigma must be positive")
    z = advantage / float(sigma)
    prob = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    return min(max(prob, 0.01), 0.99)


def kellyFraction(win_prob, american_odds, config):
    """Same as BettingRecommender.kellyCriterion (equality tested)."""
    if american_odds > 0:
        decimal_odds = (american_odds / 100) + 1
    else:
        decimal_odds = (100 / abs(american_odds)) + 1
    kelly = (win_prob * decimal_odds - 1) / (decimal_odds - 1)
    kelly = max(0, kelly * config.KELLY_FRACTION)
    return min(kelly, config.MAX_BET_SIZE_PCT)


def oddsToProbability(american_odds):
    """Break-even rate of an American price (BettingRecommender.oddsToProbability)."""
    if american_odds > 0:
        return 100 / (american_odds + 100)
    return abs(american_odds) / (abs(american_odds) + 100)


def unitProfit(american_odds):
    """Profit of a winning 1-unit bet (BettingRecommender.calculateProfit with stake 1)."""
    if american_odds > 0:
        return american_odds / 100
    return 100 / abs(american_odds)


def cleanPrice(price):
    if price is None or (isinstance(price, float) and math.isnan(price)) or pd.isna(price):
        return FALLBACK_PRICE
    return float(price)


def decideTotalBet(pred, line, sigma, over_price, under_price, config):
    """makeTotalRecommendations' rule at one line: returns dict(side, edge, cover_prob, kelly, price)
    with side None when no bet."""
    min_edge = getattr(config, 'MIN_TOTAL_EDGE', 8.0)
    out = {'side': None, 'edge': abs(pred - line), 'cover_prob': np.nan, 'kelly': np.nan, 'price': np.nan}
    if pd.isna(line) or pd.isna(pred):
        return out
    if pred > line and pred - line >= min_edge:
        side, price = 'Over', cleanPrice(over_price)
    elif pred < line and line - pred >= min_edge:
        side, price = 'Under', cleanPrice(under_price)
    else:
        return out
    cover = normalCoverProbability(abs(pred - line), sigma)
    out.update(cover_prob=cover, price=price)
    if cover < config.MIN_PROBABILITY:
        return out
    kelly = kellyFraction(cover, price, config)
    out['kelly'] = kelly
    if kelly <= 0:
        return out
    out['side'] = side
    return out


def gradeTotal(side, line, actual):
    if side is None or pd.isna(line):
        return None
    if actual == line:
        return 'P'
    won = actual > line if side == 'Over' else actual < line
    return 'W' if won else 'L'


def betProfit(result, price):
    if result == 'W':
        return unitProfit(price)
    if result == 'L':
        return -1.0
    if result == 'P':
        return 0.0
    return np.nan


def clvPoints(side, open_line, close_line):
    """Points the total moved toward the bet from opening to closing (positive = our way)."""
    if side is None or pd.isna(open_line) or pd.isna(close_line):
        return np.nan
    return (close_line - open_line) if side == 'Over' else (open_line - close_line)


# ---------- statistics ----------

def clusterBootstrap(num, den, clusters, reps=10000, seed=0):
    """Ratio sum(num)/sum(den) with a 95% percentile CI, resampling whole clusters (slates) with
    replacement, as DeepSports analysis/ensemble.py::cluster_bootstrap."""
    num = np.asarray(num, dtype=float)
    den = np.asarray(den, dtype=float)
    clusters = np.asarray(clusters)
    if len(num) == 0 or den.sum() == 0:
        return {'mean': np.nan, 'lo': np.nan, 'hi': np.nan, 'n': int(len(num)), 'clusters': 0}
    keys, inv = np.unique(clusters, return_inverse=True)
    sums = np.bincount(inv, weights=num, minlength=len(keys))
    cnts = np.bincount(inv, weights=den, minlength=len(keys))
    rng = np.random.default_rng(seed)
    stats = np.empty(reps)
    k = len(keys)
    for b in range(reps):
        pick = rng.integers(0, k, k)
        d = cnts[pick].sum()
        stats[b] = sums[pick].sum() / d if d > 0 else np.nan
    return {
        'mean': float(num.sum() / den.sum()),
        'lo': float(np.nanpercentile(stats, 2.5)),
        'hi': float(np.nanpercentile(stats, 97.5)),
        'n': int(len(num)),
        'clusters': int(k),
    }


def wilsonInterval(wins, n, z=1.959963984540054):
    if n == 0:
        return (np.nan, np.nan)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (centre - half, centre + half)


# ---------- data ----------

def seasonLabels(first=2000, last=2026):
    return [f"{y}-{str(y + 1)[-2:]}" for y in range(first, last + 1)]


def toEspn(code):
    return NBA_CODES.get(code, code)


def buildFeatureFrame(data_dir, cache_file, rebuild=False, seasons=None, log=print):
    """Concatenate createGameMatchupData over seasons; cached as parquet at cache_file."""
    cache_file = Path(cache_file)
    sidecar = cache_file.with_suffix('.json')
    if cache_file.exists() and sidecar.exists() and not rebuild:
        info = json.loads(sidecar.read_text())
        if info.get('data_dir') == str(Path(data_dir).resolve()):
            log(f"Loading cached features {cache_file}")
            return pd.read_parquet(cache_file), info
        log("Feature cache was built from another --data-dir; rebuilding")
    sys.path.insert(0, str(ROOT / 'basketball'))
    sys.path.insert(0, str(ROOT))
    from data_pipeline.prepare_data import NBATrainingDataPreparer

    preparer = NBATrainingDataPreparer(data_dir=str(data_dir))
    assert Path(preparer.cache_dir).resolve().is_relative_to(Path(data_dir).resolve())
    frames = []
    info = {'data_dir': str(Path(data_dir).resolve()), 'built': [], 'missing': [], 'failed': {}}
    for season in seasons or seasonLabels():
        if not (preparer.game_data_dir / f'{season}_game_stats.csv').exists():
            info['missing'].append(season)
            continue
        try:
            frames.append(preparer.createGameMatchupData(season))
            info['built'].append(season)
        except Exception as e:  # report and continue, as prepareAllSeasons does
            info['failed'][season] = f"{type(e).__name__}: {e}"
            log(f"Season {season} failed: {e}")
    frame = pd.concat(frames, ignore_index=True)
    frame = normalizeFrame(frame)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(cache_file, index=False)
    cache_file.with_suffix('.json').write_text(json.dumps(info, indent=2))
    return frame, info


def normalizeFrame(frame):
    frame = frame.copy()
    frame['date'] = pd.to_datetime(frame['date']).dt.tz_localize(None).dt.normalize()
    frame['game_id'] = frame['game_id'].map(lambda g: f"{int(g):010d}")
    frame['game_type'] = frame['game_id'].str[2].astype(int)  # 1 pre, 2 reg, 4 playoffs, 5 play-in
    return frame.sort_values(['date', 'game_id']).reset_index(drop=True)


def featureColumns(frame, saved_features, leakage_cols):
    """The saved model's inputs; also returns the diff against frame minus drop lists."""
    drop = set(leakage_cols) | {TARGET, 'game_type'}
    derived = [c for c in frame.columns if c not in drop]
    diff = {'only_in_frame': sorted(set(derived) - set(saved_features)),
            'only_in_model': sorted(set(saved_features) - set(derived)),
            'same_order': derived == list(saved_features)}
    return list(saved_features), diff


def loadMarket(db_path):
    import duckdb
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        market = con.execute(MARKET_SQL).df()
    finally:
        con.close()
    assert market['ws_game_id'].is_unique, "one closing/opening row per game expected"
    market['et_date'] = pd.to_datetime(market['et_date'])
    return market


def matchMarket(preds, market):
    """Left-join warehouse games onto predictions by US Eastern date and ESPN home/away codes."""
    p = preds.copy()
    p['espn_home'] = p['home_team'].map(toEspn)
    p['espn_away'] = p['away_team'].map(toEspn)
    m = market.drop_duplicates(['et_date', 'ws_home', 'ws_away'], keep=False)
    out = p.merge(m, how='left', left_on=['date', 'espn_home', 'espn_away'],
                  right_on=['et_date', 'ws_home', 'ws_away'])
    assert len(out) == len(p)
    return out


# ---------- model ----------

def tuneParams(frame, features, n_trials=100, cutoff=TUNE_CUTOFF, log=print):
    sys.path.insert(0, str(ROOT / 'basketball'))
    sys.path.insert(0, str(ROOT))
    from model.model_total import BasketballTotalModel
    from shared.splitting import chronologicalSplit

    pre = frame[frame['date'] < cutoff]
    train, val, test = chronologicalSplit(pre, date_col='date', test_frac=0.2, val_frac_of_test=0.5)
    log(f"Tuning on {len(train)} train ({train.date.min().date()}..{train.date.max().date()}), "
        f"{len(val)} val ({val.date.min().date()}..{val.date.max().date()}); test unused")
    model = BasketballTotalModel()
    best = model.tuneHyperparameters(train[features], train[TARGET], val[features], val[TARGET],
                                     n_trials=n_trials)
    return {'best_params': best, 'tune_rows': {'train': len(train), 'val': len(val), 'test': len(test)},
            'tune_ranges': {k: [str(d.date.min().date()), str(d.date.max().date())]
                            for k, d in (('train', train), ('val', val), ('test', test))},
            'cutoff': str(cutoff.date()), 'n_trials': n_trials}


def fitRefit(train, features, params):
    """Fit on all but the last 10% (by date) of train; early-stop and measure sigma on that 10%."""
    import xgboost as xgb

    train = train.sort_values(['date', 'game_id'])
    n_es = max(1, int(round(len(train) * ES_FRAC)))
    fit, es = train.iloc[:-n_es], train.iloc[-n_es:]
    model = xgb.XGBRegressor(**{**FIXED_XGB, **params})
    model.fit(fit[features], fit[TARGET], eval_set=[(es[features], es[TARGET])], verbose=False)
    sigma = float(np.std(es[TARGET].to_numpy() - model.predict(es[features])))
    return model, sigma, set(fit['game_id']) | set(es['game_id'])


def walkForward(frame, features, params, start, end, log=print):
    """Monthly refits: train on games before the month, predict games in [month, end)."""
    results = []
    for month in pd.period_range(start, end - pd.Timedelta(days=1), freq='M'):
        lo = max(month.start_time, start)
        test = frame[(frame['date'] >= lo) & (frame['date'] <= month.end_time) & (frame['date'] < end)]
        if test.empty:
            continue
        train = frame[frame['date'] < month.start_time]
        t0 = time.time()
        model, sigma, seen = fitRefit(train, features, params)
        assert train['date'].max() < test['date'].min()
        assert not (seen & set(test['game_id'])), "scored game in fit/ES set"
        out = test[['game_id', 'date', 'season', 'game_type', 'home_team', 'away_team',
                    'home_score', 'away_score', TARGET]].copy()
        out['pred_total'] = model.predict(test[features]).astype(float)
        out['sigma'] = sigma
        out['refit_month'] = str(month)
        out['train_games'] = len(train)
        out['train_max_date'] = train['date'].max()
        out['best_iteration'] = model.best_iteration
        log(f"{month}: train {len(train)} test {len(test)} trees {model.best_iteration} "
            f"sigma {sigma:.2f} ({time.time() - t0:.0f}s)")
        results.append(out)
    return pd.concat(results, ignore_index=True)


def applyBets(df, config):
    rows = []
    for r in df.itertuples(index=False):
        if pd.isna(r.close_total):
            rows.append({'bet_side': None, 'edge': np.nan, 'cover_prob': np.nan, 'kelly': np.nan,
                         'bet_price': np.nan, 'result': None, 'profit': np.nan, 'clv': np.nan})
            continue
        d = decideTotalBet(r.pred_total, r.close_total, r.sigma, r.close_over_price,
                           r.close_under_price, config)
        side = d['side']
        result = gradeTotal(side, r.close_total, r.total_score)
        rows.append({'bet_side': side, 'edge': d['edge'], 'cover_prob': d['cover_prob'],
                     'kelly': d['kelly'], 'bet_price': d['price'] if side else np.nan,
                     'result': result, 'profit': betProfit(result, d['price']) if side else np.nan,
                     'clv': clvPoints(side, r.open_total, r.close_total)})
    return pd.concat([df.reset_index(drop=True), pd.DataFrame(rows)], axis=1)


# ---------- metrics ----------

def summarize(games, reps=10000, seed=0):
    """Metrics for one subset of scored games (each must have a closing total)."""
    g = games
    s = {'games': int(len(g))}
    if len(g):
        s['model_mae'] = float((g['pred_total'] - g[TARGET]).abs().mean())
        s['closing_mae'] = float((g['close_total'] - g[TARGET]).abs().mean())
        s['mae_diff'] = s['model_mae'] - s['closing_mae']
        s['bias'] = float((g['pred_total'] - g[TARGET]).mean())
    s.update(summarizeBets(g[g['bet_side'].notna()], reps, seed))
    return s


def summarizeBets(b, reps=10000, seed=0):
    s = {'bets': int(len(b))}
    w, l, p = (int((b['result'] == x).sum()) for x in 'WLP')
    s.update(wins=w, losses=l, pushes=p)
    decided = b[b['result'].isin(['W', 'L'])]
    clusters = decided['date'].dt.strftime('%Y-%m-%d')
    s['win_rate'] = w / (w + l) if w + l else np.nan
    s['break_even'] = float(decided['bet_price'].map(oddsToProbability).mean()) if len(decided) else np.nan
    s['roi'] = float(b['profit'].sum() / len(b)) if len(b) else np.nan
    s['win_rate_ci'] = clusterBootstrap((decided['result'] == 'W').astype(float), np.ones(len(decided)),
                                        clusters, reps, seed)
    s['roi_ci'] = clusterBootstrap(b['profit'], np.ones(len(b)), b['date'].dt.strftime('%Y-%m-%d'),
                                   reps, seed)
    s['win_rate_wilson'] = list(wilsonInterval(w, w + l))
    clv = b['clv'].dropna()
    s['clv'] = {'mean': float(clv.mean()) if len(clv) else np.nan,
                'share_positive': float((clv > 0).mean()) if len(clv) else np.nan,
                'n': int(len(clv))}
    return s


def shipVerdict(holdout):
    lo = holdout['win_rate_ci']['lo']
    be = holdout['break_even']
    c1 = bool(lo > be) if not (pd.isna(lo) or pd.isna(be)) else False
    c2 = bool(holdout.get('mae_diff', np.inf) <= SHIP_MAE_MARGIN)
    return {'cond1_ci_lo_gt_break_even': c1, 'win_rate_ci_lo': lo, 'mean_break_even': be,
            'cond2_mae_diff_le_0.5': c2, 'mae_diff': holdout.get('mae_diff'),
            'ship': c1 and c2}


def buildSummary(scored, all_preds, match_info, reps=10000, seed=0):
    out = {'match': match_info, 'by_season': {}, 'by_period': {}, 'by_period_side': {}}
    for season, g in scored.groupby('season'):
        out['by_season'][season] = summarize(g, reps, seed)
    for name, seasons in PERIODS.items():
        g = scored[scored['season'].isin(seasons)]
        out['by_period'][name] = summarize(g, reps, seed)
        bets = g[g['bet_side'].notna()]
        out['by_period_side'][name] = {side: summarizeBets(bets[bets['bet_side'] == side], reps, seed)
                                       for side in ('Over', 'Under')}
    out['all_predicted_model_mae'] = {
        season: {'games': int(len(g)), 'model_mae': float((g['pred_total'] - g[TARGET]).abs().mean())}
        for season, g in all_preds.groupby('season')}
    out['ship_rule'] = shipVerdict(out['by_period']['holdout'])
    return out


def fmt(x, nd=2, pct=False):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return '-'
    return f"{x:.1%}" if pct else f"{x:.{nd}f}"


def ci(c, pct=True):
    return f"{fmt(c['lo'], pct=pct)} to {fmt(c['hi'], pct=pct)}"


def renderMarkdown(summary, params_info, feature_diff, saved_meta, runtime):
    lines = []
    m = summary['match']
    lines += ['### Match and coverage', '',
              f"- Predicted games in range (excluding preseason): {m['predicted_non_preseason']}",
              f"- Matched to a warehouse game (season_type 2/3/5): {m['matched']} "
              f"({fmt(m['match_rate'], pct=True)}); with a closing total: {m['with_closing_total']}",
              f"- Score mismatches between ManualBets and warehouse among matched: {m['score_mismatch']}",
              f"- Closing prices missing (-110 used) among bets: {m['bets_price_fallback']}",
              f"- Unmatched by season: {m['unmatched_by_season']}", '']

    def gameRow(name, s):
        return (f"| {name} | {s['games']} | {fmt(s.get('model_mae'))} | {fmt(s.get('closing_mae'))} | "
                f"{fmt(s.get('mae_diff'))} | {fmt(s.get('bias'))} | {s['bets']} | "
                f"{s['wins']}-{s['losses']}-{s['pushes']} | {fmt(s['win_rate'], pct=True)} | "
                f"{ci(s['win_rate_ci'])} | {fmt(s['win_rate_wilson'][0], pct=True)} to "
                f"{fmt(s['win_rate_wilson'][1], pct=True)} | {fmt(s['break_even'], pct=True)} | "
                f"{fmt(s['roi'], pct=True)} | {ci(s['roi_ci'])} | {fmt(s['clv']['mean'])} / "
                f"{fmt(s['clv']['share_positive'], pct=True)} / {s['clv']['n']} |")

    header = ('| {} | Games | Model MAE | Closing MAE | Diff | Bias | Bets | W-L-P | Win rate | '
              'Win CI (slate) | Win CI (Wilson) | Break-even | ROI | ROI CI (slate) | '
              'CLV mean / share + / n |')
    sep = '|' + '---|' * 15
    lines += ['### By period', '', header.format('Period'), sep]
    for name, s in summary['by_period'].items():
        lines.append(gameRow(name, s))
    lines += ['', '### By season', '', header.format('Season'), sep]
    for name, s in summary['by_season'].items():
        lines.append(gameRow(name, s))
    lines += ['', '### Over vs Under (bets only)', '',
              '| Period | Side | Bets | W-L-P | Win rate | Win CI (slate) | Break-even | ROI | '
              'ROI CI (slate) | CLV mean / share + / n |', '|' + '---|' * 10]
    for name, sides in summary['by_period_side'].items():
        for side, s in sides.items():
            lines.append(f"| {name} | {side} | {s['bets']} | {s['wins']}-{s['losses']}-{s['pushes']} | "
                         f"{fmt(s['win_rate'], pct=True)} | {ci(s['win_rate_ci'])} | "
                         f"{fmt(s['break_even'], pct=True)} | {fmt(s['roi'], pct=True)} | "
                         f"{ci(s['roi_ci'])} | {fmt(s['clv']['mean'])} / "
                         f"{fmt(s['clv']['share_positive'], pct=True)} / {s['clv']['n']} |")
    v = summary['ship_rule']
    lines += ['', '### Ship rule (2025-26 holdout)', '',
              f"1. Win-rate slate-clustered 95% CI lower bound {fmt(v['win_rate_ci_lo'], pct=True)} > "
              f"mean break-even {fmt(v['mean_break_even'], pct=True)}: "
              f"**{'PASS' if v['cond1_ci_lo_gt_break_even'] else 'FAIL'}**",
              f"2. Model MAE - closing MAE = {fmt(v['mae_diff'])} <= {SHIP_MAE_MARGIN}: "
              f"**{'PASS' if v['cond2_mae_diff_le_0.5'] else 'FAIL'}**",
              f"\n**Verdict: {'SHIP (watch-only export)' if v['ship'] else 'DO NOT SHIP'}**", '']
    lines += ['### All predicted games (incl. unmatched), model MAE', '',
              '| Season | Games | Model MAE |', '|---|---|---|']
    for season, s in summary['all_predicted_model_mae'].items():
        lines.append(f"| {season} | {s['games']} | {fmt(s['model_mae'])} |")
    bp = params_info['best_params']
    lines += ['', '### Setup', '',
              f"- Tuned params ({params_info.get('n_trials')} trials, TPE seed 42, games before "
              f"{params_info.get('cutoff')}; split ranges {params_info.get('tune_ranges')}): "
              + ', '.join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in bp.items()),
              f"- Feature check vs saved model: {feature_diff}",
              f"- Saved model's own test split (metadata, not this backtest): "
              f"MAE {fmt(saved_meta.get('test_mae'))}, residual std {fmt(saved_meta.get('test_residual_std'))}, "
              f"val residual std {fmt(saved_meta.get('val_residual_std'))}",
              f"- Runtime: {runtime}", '']
    return '\n'.join(lines)


# ---------- CLI ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--data-dir', required=True)
    ap.add_argument('--start', default='2021-10-01')
    ap.add_argument('--end', default='2026-11-11', help='exclusive')
    ap.add_argument('--out', required=True)
    ap.add_argument('--params-json', help='skip tuning; JSON file with best_params (or a flat dict)')
    ap.add_argument('--tune-trials', type=int, default=100)
    ap.add_argument('--rebuild-features', action='store_true')
    ap.add_argument('--bootstrap-reps', type=int, default=10000)
    args = ap.parse_args(argv)

    t_start = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    config = loadBettingConfig()

    frame, build_info = buildFeatureFrame(args.data_dir, out / 'features.parquet', args.rebuild_features)
    print(f"Feature frame: {len(frame)} games, seasons built {len(build_info['built'])}, "
          f"missing {build_info['missing']}, failed {list(build_info['failed'])}")

    import xgboost as xgb
    booster = xgb.Booster()
    booster.load_model(str(MODEL_PATH))
    sys.path.insert(0, str(ROOT / 'basketball'))
    from model.model_total import BasketballTotalModel
    features, feature_diff = featureColumns(frame, booster.feature_names,
                                            BasketballTotalModel().getLeakageColumns())
    print(f"Features: {len(features)}; diff vs frame: {feature_diff}")
    # Pre-registration: the pipeline output minus the drop lists must equal the saved model's inputs.
    assert not feature_diff['only_in_frame'] and not feature_diff['only_in_model'], feature_diff

    if args.params_json:
        loaded = json.loads(Path(args.params_json).read_text())
        params_info = loaded if 'best_params' in loaded else {'best_params': loaded}
    else:
        t0 = time.time()
        params_info = tuneParams(frame, features, n_trials=args.tune_trials)
        params_info['tune_seconds'] = round(time.time() - t0)
        (out / 'params.json').write_text(json.dumps(params_info, indent=2))
    print(f"Params: {params_info['best_params']}")

    t0 = time.time()
    preds = walkForward(frame, features, params_info['best_params'], start, end)
    wf_seconds = round(time.time() - t0)

    db_path = os.environ.get('NBA_WAREHOUSE_DB', DEFAULT_WAREHOUSE)
    print(f"Warehouse (read-only): {db_path}")
    market = loadMarket(db_path)
    matched = matchMarket(preds, market)
    matched = applyBets(matched, config)
    non_pre = matched[matched['game_type'] != 1]
    hit = non_pre[non_pre['ws_game_id'].notna()]
    scored = hit[hit['close_total'].notna()].copy()
    score_mismatch = int(((hit['ws_home_score'] != hit['home_score']) |
                          (hit['ws_away_score'] != hit['away_score'])).sum())
    bets = scored[scored['bet_side'].notna()]
    fallback = int((bets['close_over_price'].isna() & (bets['bet_side'] == 'Over')).sum()
                   + (bets['close_under_price'].isna() & (bets['bet_side'] == 'Under')).sum())
    unmatched = non_pre[non_pre['ws_game_id'].isna()]
    match_info = {
        'predicted_non_preseason': int(len(non_pre)), 'matched': int(len(hit)),
        'match_rate': len(hit) / len(non_pre) if len(non_pre) else np.nan,
        'with_closing_total': int(len(scored)), 'score_mismatch': score_mismatch,
        'bets_price_fallback': fallback,
        'unmatched_by_season': unmatched.groupby('season').size().to_dict(),
        'unmatched_by_game_type': unmatched.groupby('game_type').size().to_dict(),
        'preseason_rows_predicted': int((matched['game_type'] == 1).sum()),
    }

    cols = ['game_id', 'ws_game_id', 'date', 'season', 'game_type', 'season_type', 'home_team',
            'away_team', 'pred_total', TARGET, 'close_total', 'close_over_price', 'close_under_price',
            'close_provider', 'open_total', 'sigma', 'refit_month', 'train_games', 'best_iteration',
            'edge', 'cover_prob', 'kelly', 'bet_side', 'bet_price', 'result', 'profit', 'clv']
    matched[cols].to_csv(out / 'predictions.csv', index=False)

    summary = buildSummary(scored, non_pre, match_info, reps=args.bootstrap_reps)
    saved_meta = json.loads(METADATA_PATH.read_text())['retrain_history'][-1]
    tune_s = params_info.get('tune_seconds')
    tune_txt = f"{tune_s}s" if tune_s is not None else 'skipped (--params-json)'
    runtime = f"total {round(time.time() - t_start)}s; tuning {tune_txt}; walk-forward {wf_seconds}s"
    summary.update(params=params_info, feature_diff=feature_diff, feature_build=build_info,
                   saved_model_metadata=saved_meta, runtime=runtime,
                   args={k: v for k, v in vars(args).items()})
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, default=str))
    md = renderMarkdown(summary, params_info, feature_diff, saved_meta, runtime)
    (out / 'summary.md').write_text(md)
    print(md)
    return 0


if __name__ == '__main__':
    sys.exit(main())
