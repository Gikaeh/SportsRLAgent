import sys
from pathlib import Path
# sys.path.insert(0, str(Path(__file__).parent.parent.parent))
# from unified_bankroll import UnifiedBankroll

class BettingConfig:
    # Bankroll - now uses unified bankroll across all sports
    STARTING_BANKROLL = 40
    USE_UNIFIED_BANKROLL = True  # Set to False to use sport-specific bankroll
    MAX_BET_SIZE_PCT = 0.05   # Maximum 2% of bankroll per bet
    KELLY_FRACTION = 0.20      # Use 10% Kelly for conservative sizing
    MAX_RISK_PCT = 0.5        # Maximum 20% total daily exposure
    
    # Edge
    MIN_EDGE_H2H = 0.02 # Minimum 3% edge to place bet (model_prob - market_prob)
    MIN_EDGE_SPREAD = .5
    MIN_TOTAL_EDGE = 1
    MIN_PROBABILITY = 0.55
    
    # Kelly adjustments for underdog bets (H2H)
    UNDERDOG_KELLY_MULTIPLIER = 0.3  # Use 30% of normal Kelly for underdog bets
    
    # Risk Limits
    # MAX_BETS_PER_DAY = 3      # Maximum number of bets per day
    # DAILY_LOSS_LIMIT_PCT = 0.10  # Stop betting if down 10% in a day
    # MAX_DRAWDOWN_PCT = 0.10   # Alert if drawdown exceeds 10%
    
    # Model Settings
    MODEL_PATH = './models/hockey_h2h_model.json'
    CONFIDENCE_THRESHOLD_HIGH = 0.70  # High confidence threshold
    CONFIDENCE_THRESHOLD_LOW = 0.30   # Low confidence threshold
    UNDERDOG_ODDS_THRESHOLD = 150     # Odds above this are considered underdog bets
    
    # Odds Settings
    # Books to track (for future Phase 3 implementation)
    SHARP_BOOKS = ['BetOnline', 'Pinnacle', 'LowVig']
    SOFT_BOOKS = ['DraftKings', 'FanDuel', 'BetMGM', 'Caesars']
    NEVADA_BOOKS = ['betmgm', 'caesars']
    
    # Logging
    LOG_DIR = '././logs/hockey/betting'
    H2H_BETS_LOG = 'h2h_bets.csv'
    SPREAD_BETS_LOG = 'spread_bets.csv'
    TOTAL_BETS_LOG = 'total_bets.csv'
    
    # Alerts
    ALERT_ON_HIGH_EDGE = 0.10  # Alert if edge exceeds 10% (potential data issue)
    ALERT_ON_LOSS_STREAK = 5   # Alert after 5 consecutive losses
