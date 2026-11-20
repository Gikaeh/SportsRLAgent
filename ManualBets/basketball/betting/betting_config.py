import sys
from pathlib import Path
# sys.path.insert(0, str(Path(__file__).parent.parent.parent))
# from unified_bankroll import UnifiedBankroll

class BettingConfig:
    # Bankroll - now uses unified bankroll across all sports
    STARTING_BANKROLL = 70 #UnifiedBankroll.STARTING_BANKROLL
    BANKROLL_START_DATE = '2026-11-08'  # Older log rows stay as history but don't count
    MIN_BET_AMOUNT = 1        # Bets under this are dropped; stakes are whole dollars
    USE_UNIFIED_BANKROLL = False  # Set to False to use sport-specific bankroll
    MAX_BET_SIZE_PCT = 0.02   # Kelly mode: maximum 2% of bankroll per bet
    KELLY_FRACTION = 0.10     # Kelly mode: 1/10 Kelly
    MAX_RISK_PCT = 0.15       # Maximum 15% total daily exposure

    # Sizing (docs/DECISIONS.md 2026-11-20). Kelly needs a probability that is
    # close to right; the model's live disagreements lose, so Kelly mode shrinks
    # the model probability toward the devigged market. Flat mode is the default.
    SIZING_MODE = 'flat'          # 'flat' or 'kelly'
    FLAT_STAKE_AMOUNT = 2         # Whole dollars per bet in flat mode
    MAX_FLAT_STAKE_PCT = 0.05     # Flat mode: never more than 5% of bankroll
    MODEL_PROB_WEIGHT = 0.25      # Kelly mode: p_eff = 0.25*p_model + 0.75*p_market

    # Edge bands. Edge = model vs line IN POINTS for spread/total
    # (e.g. predicted margin 8.0 vs line -3.5 = 4.5 points), and model vs
    # devigged market IN PROBABILITY for h2h. Capping the top of the band
    # tests the observed winner's curse (biggest claimed edges lost most).
    ENABLED_MARKETS = ('spread',)   # h2h paused 2026-11-20: 23 bets, 11-12, -$15.47
    MIN_EDGE_H2H = 0.05
    MAX_EDGE_H2H = 0.08
    MIN_EDGE_SPREAD = 1
    MAX_EDGE_SPREAD = 7.0
    MIN_EDGE_TOTAL = 8.0
    MAX_EDGE_TOTAL = 12.0
    MIN_PROBABILITY = 0.55
    MIN_BET_ODDS = -150       # Do not take prices worse than this (e.g. -160)
    MAX_ODDS_AGE_MINUTES = 60 # Drop odds rows older than this; stale lines make phantom edges

    # Cover-probability model (NOTES.md C1): P(cover) = NormalCDF(edge / sigma),
    # sigma = model's validation residual std, written into
    # models/metadata/retraining_*_metadata.json by Model Retraining.
    # Fallbacks are league-typical placeholders until the first post-fix retrain.
    SPREAD_RESIDUAL_SIGMA_FALLBACK = 11.8
    TOTAL_RESIDUAL_SIGMA_FALLBACK = 14.0

    # Kelly adjustments for underdog bets (H2H)
    UNDERDOG_KELLY_MULTIPLIER = 0.3  # Use 30% of normal Kelly for underdog bets
    
    # Risk Limits
    # MAX_BETS_PER_DAY = 3      # Maximum number of bets per day
    # DAILY_LOSS_LIMIT_PCT = 0.10  # Stop betting if down 10% in a day
    # MAX_DRAWDOWN_PCT = 0.10   # Alert if drawdown exceeds 10%
    
    # Model Settings
    MODEL_PATH = './models/basketball_h2h_model.json'
    CONFIDENCE_THRESHOLD_HIGH = 0.70  # High confidence threshold
    CONFIDENCE_THRESHOLD_LOW = 0.30   # Low confidence threshold
    UNDERDOG_ODDS_THRESHOLD = 150     # Odds above this are considered underdog bets
    
    # Odds Settings
    # Books to track (for future Phase 3 implementation)
    SHARP_BOOKS = ['BetOnline', 'Pinnacle', 'LowVig']
    SOFT_BOOKS = ['DraftKings', 'FanDuel', 'BetMGM', 'Caesars']
    NEVADA_BOOKS = ['draftkings'] #['betmgm', 'caesars']
    
    # Logging — bet journals live at the repo root (../logs), shared read-only with DeepSports.
    LOG_DIR = '../logs/basketball/betting'
    H2H_BETS_LOG = 'h2h_bets.csv'
    SPREAD_BETS_LOG = 'spread_bets.csv'
    TOTAL_BETS_LOG = 'total_bets.csv'
    COLLEGE_BETS_LOG = '../logs/college_basketball/betting/bets.csv'  # Counted in the bankroll (docs/DECISIONS.md)
    
    # Alerts
    ALERT_ON_HIGH_EDGE = 0.10  # Alert if edge exceeds 10% (potential data issue)
    ALERT_ON_LOSS_STREAK = 5   # Alert after 5 consecutive losses