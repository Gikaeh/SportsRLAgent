# Moneyline Betting Model: NBA Implementation Roadmap
**Pure Prediction → Market Intelligence → Live Betting System**

## Project Overview

**Primary Goal**: Build a profitable NBA moneyline betting model that predicts game winners.

**Secondary Goals** (Future):
- Expand to other sports (MLB, NFL, NHL)
- Build specialized models for other bet types (spreads, totals, player props)

**Current Focus**: NBA moneyline only - prove profitability before expansion.

**Strategy**:
- Phase 1: Pure game prediction model (no odds data)
- Phase 2: Add market intelligence (historical odds)
- Phase 3: Live betting with line shopping
- Phase 4: RL injury adaptation
- Phase 5: Production deployment

---

## Phase 1: Pure Prediction Model (Weeks 1-4)

### 1.1 Data Collection (Cost: $0)

**Game Results Data:**
```
Required fields:
- game_id, date, season
- home_team, away_team
- home_score, away_score, home_won
```

**Team Performance Data:**
- Last 10 games: wins, net rating, PPG, opponent PPG
- Shooting percentages (FG%, 3P%)
- Rest days and back-to-back game indicators

**Player Data:**
- Top 6 players by minutes for each team
- Season averages: PPG, RPG, APG, FG%, minutes, plus/minus
- Used to create aggregated features (not individual stats in model)

**Data Sources (All Free):**
- NBA.com Stats API (`nba_api` Python package)
- Basketball-Reference.com
- Historical seasons: 2015-16 through 2024-25

### 1.2 Feature Engineering

**Minimal Feature Set (28 features total):**

```python
# Team Performance (8 features)
'home_wins_l10'              # Win rate last 10 games
'away_wins_l10'
'home_net_rating_l10'        # Point differential per game
'away_net_rating_l10'
'home_ppg_l10'               # Points scored
'away_ppg_l10'
'home_opp_ppg_l10'           # Points allowed (defense)
'away_opp_ppg_l10'

# Game Context (4 features)
'home_rest_days'             # Days since last game
'away_rest_days'
'is_back_to_back_home'       # 0 or 1
'is_back_to_back_away'       # 0 or 1

# Player Aggregates (12 features)
'home_top3_avg_ppg'          # Average PPG of top 3 scorers
'away_top3_avg_ppg'
'home_top5_avg_mpg'          # Average minutes (starter quality)
'away_top5_avg_mpg'
'home_top6_total_plusminus'  # Sum of top 6 players' plus/minus
'away_top6_total_plusminus'
'home_star_ppg'              # Best player's PPG only
'away_star_ppg'
'home_6thman_quality'        # 6th man PPG (bench strength)
'away_6thman_quality'
'home_depth_variance'        # Std dev of player PPG (roster balance)
'away_depth_variance'

# Shooting Efficiency (4 features)
'home_fg_pct_l10'
'away_fg_pct_l10'
'home_fg3_pct_l10'
'away_fg3_pct_l10'
```

**Why These Features:**
- Proven predictive value in basketball
- Captures team quality, recent form, rest, and player talent
- Aggregated player features prevent overfitting (12 features vs 72 individual)
- Minimal correlation between features
- All available at prediction time (no look-ahead bias)

### 1.3 Model Development

**Model Selection:**

Train and compare multiple models:
1. **XGBoost** (primary choice - usually best for tabular data)
2. **Random Forest** (good interpretability)
3. **Logistic Regression** (simple baseline)
4. **LightGBM** (alternative gradient boosting)

**Training Strategy:**
```python
# Time-based splits (no shuffling)
Train: 2015-16 through 2021-22 seasons (~7,400 games)
Validate: 2022-23 season (~1,230 games)
Test: 2023-24 season (~1,230 games)
Future live: 2024-25 season (ongoing)

# No data leakage
- L10 stats calculated using only prior games
- No season-end stats used for mid-season games
- All features available at prediction time
```

**Target Variable:**
- Binary: `home_won` (1 if home team won, 0 if away team won)
- Model outputs: Win probability (0-1 continuous)

### 1.4 Model Evaluation

**Technical Metrics:**
- **Accuracy**: >52% (break-even threshold at -110 odds)
- **Brier Score**: <0.25 (probability calibration)
- **Log Loss**: <0.69 (penalizes confident wrong predictions)
- **ROC AUC**: >0.55 (discrimination ability)

**Calibration Check:**
```python
# Predicted 60% win prob should win ~60% of the time
# Plot calibration curve to verify
```

**Feature Importance:**
Verify logical patterns:
- `net_rating_l10` should rank high
- `star_ppg` should matter more than `6thman_quality`
- Rest days should have measurable impact

### 1.5 Phase 1 Deliverables

**Must Have:**
- Working model predicting NBA game winners
- Accuracy >52% on 2023-24 test set
- Well-calibrated probabilities
- Feature importance analysis documented
- Validation that model works without odds data

**Data Preservation:**
- Keep full individual player stats collected
- Save aggregated dataset separately for moneyline model
- Individual stats reserved for future player props models

**No Betting Yet:**
This phase proves you can predict games better than random. Betting comes in Phase 3.

---

## Phase 2: Market-Aware Model (Weeks 5-7)

### 2.1 Add Historical Odds Data

**Data Purchase:**
- Source: The Odds API historical endpoint
- Cost: ~30 tokens per call
- Seasons needed: 2015-16 through 2023-24
- Estimated: ~8,000 games × 30 tokens = 240,000 tokens ≈ $80-100

**Odds Data Structure:**
```python
columns = [
    'game_id', 'date', 'home_team', 'away_team',
    'closing_home_ml',  # Most important
    'closing_away_ml',
    'opening_home_ml',  # If available
    'opening_away_ml'
]
```

**Single Sharp Book Focus:**
Use BetOnline or most accurate available book for training data.

### 2.2 Market-Enhanced Features

**Add to feature set:**
```python
# Market intelligence (5 additional features)
'closing_home_implied_prob'   # Convert odds to probability
'closing_away_implied_prob'
'no_vig_home_prob'            # Remove bookmaker vig
'no_vig_away_prob'
'line_movement'               # Opening to closing change (if available)
```

**New total: 33 features (28 game + 5 market)**

### 2.3 Compare Model Performance

**Model A: Pure Prediction (Phase 1)**
- Uses only 28 game features
- Independent market opinion

**Model B: Market-Aware (Phase 2)**
- Uses 33 features (game + odds)
- Learns when market is right/wrong

**Evaluation Questions:**
1. Does Model B beat Model A on test set?
2. When does Model B deviate from market consensus?
3. Are those deviations profitable?
4. How much weight does model give to odds vs game features?

### 2.4 Phase 2 Deliverables

**Must Have:**
- Market-aware model trained and validated
- Side-by-side comparison: Pure vs Market-Aware
- Feature importance showing odds vs game features
- Analysis of when to trust/fade market
- Accuracy >54% on test set

**Decision Point:**
If adding odds doesn't improve performance, stick with Pure model. If it helps, use Market-Aware for betting.

---

## Phase 3: Live Betting System (Weeks 8-10)

### 3.1 Multi-Book Odds Collection

**Books to Track:**
- **Sharp books**: BetOnline, LowVig (training comparison)
- **Soft books**: DraftKings, BetMGM, FanDuel (betting targets)

**Collection Schedule:**
```python
Daily during NBA season:
- 10:00 AM PST: Morning lines (early value)
- 2:00 PM PST: Afternoon update
- 5:00 PM PST: Pre-game closing (1-2 hours before first game)

Cost: ~1 token per call
- 3 collections × ~10 games/day × 180 days = 5,400 tokens ≈ $5-10/season
```

### 3.2 Betting Decision Pipeline

**Complete System:**
```python
def make_betting_decision(game_data, current_odds):
    # 1. Get model prediction
    model_home_prob = model.predict_proba(game_features)[0][1]
    
    # 2. Find best available odds
    best_home_odds = max([book['home_ml'] for book in current_odds])
    best_away_odds = max([book['away_ml'] for book in current_odds])
    
    # 3. Calculate edge
    if model_home_prob > 0.5:
        # Consider home bet
        market_implied = odds_to_probability(best_home_odds)
        edge = model_home_prob - market_implied
        
        if edge > 0.03:  # 3% minimum edge
            bet_size = kelly_criterion(model_home_prob, best_home_odds)
            return {
                'bet': 'home',
                'team': game_data['home_team'],
                'confidence': model_home_prob,
                'edge': edge,
                'odds': best_home_odds,
                'book': best_book_name,
                'size': bet_size
            }
    else:
        # Consider away bet
        model_away_prob = 1 - model_home_prob
        market_implied = odds_to_probability(best_away_odds)
        edge = model_away_prob - market_implied
        
        if edge > 0.03:
            bet_size = kelly_criterion(model_away_prob, best_away_odds)
            return {
                'bet': 'away',
                'team': game_data['away_team'],
                'confidence': model_away_prob,
                'edge': edge,
                'odds': best_away_odds,
                'book': best_book_name,
                'size': bet_size
            }
    
    return {'bet': None}  # No edge found
```

**Kelly Criterion Bet Sizing:**
```python
def kelly_criterion(win_prob, american_odds):
    # Convert odds to decimal
    if american_odds > 0:
        decimal_odds = (american_odds / 100) + 1
    else:
        decimal_odds = (100 / abs(american_odds)) + 1
    
    # Kelly formula: (p * odds - 1) / (odds - 1)
    kelly_fraction = (win_prob * decimal_odds - 1) / (decimal_odds - 1)
    
    # Use fractional Kelly (0.25x) for risk management
    return max(0, kelly_fraction * 0.25)
```

### 3.3 Risk Management

**Betting Constraints:**
- Maximum bet size: 2% of bankroll per game
- Minimum edge: 3% (model probability - market probability)
- Minimum confidence: 60% win probability
- Daily loss limit: Stop betting if down 5% of bankroll
- Maximum bets per day: 5 games

**Bankroll Tracking:**
```python
starting_bankroll = 10000  # Example
current_bankroll = starting_bankroll
max_drawdown = 0
total_bets = 0
winning_bets = 0
```

### 3.4 Phase 3 Deliverables

**Must Have:**
- Live odds collection working reliably
- Automated betting decision system
- Line shopping finding best available odds
- Risk management enforced
- First 30-50 live bets placed

**Success Criteria:**
- Positive ROI on first month of betting
- System executes 3-5 bets per week
- No catastrophic losses (proper risk management)
- Line shopping saves 5-10 cents per bet on average

---

## Phase 4: RL Injury Adaptation (Weeks 11-14)

### 4.1 Injury Data Collection

**Real-Time Sources:**
- ESPN NBA Injury Report
- NBA.com official injury updates
- RotoWorld injury news
- Twitter/social media for breaking news

**Collection Timing:**
- Morning check (10 AM)
- Afternoon update (2 PM) - lineup announcements typically here
- Pre-game final check (5 PM) - catch last-minute scratches

**Data Structure:**
```python
injury_status = {
    'player_name': 'LeBron James',
    'team': 'LAL',
    'date': '2024-11-15',
    'status': 'OUT',  # OUT, DOUBTFUL, QUESTIONABLE, PROBABLE, ACTIVE
    'injury': 'ankle',
    'importance_weight': 0.85  # Learned by RL
}
```

### 4.2 RL Architecture

**Problem Definition:**

The RL agent learns to adjust model confidence based on player availability.

**State Space (~20 dimensions):**
```python
rl_state = [
    base_model_confidence,        # From Phase 2 model
    
    # Player availability (12 binary flags)
    home_starter1_available,      # 0 = out, 1 = playing
    home_starter2_available,
    home_starter3_available,
    home_starter4_available,
    home_starter5_available,
    home_6thman_available,
    away_starter1_available,
    away_starter2_available,
    away_starter3_available,
    away_starter4_available,
    away_starter5_available,
    away_6thman_available,
    
    # Context (8 features)
    learned_home_star_weight,     # How important is this player?
    learned_away_star_weight,
    replacement_quality_home,     # Aggregate backup quality
    replacement_quality_away,
    games_since_injury,           # Context for return-from-injury
    recent_rl_accuracy,           # Is RL helping or hurting?
    market_volatility,            # How much are odds moving?
    time_until_game               # Hours until tipoff
]
```

**Action Space (7 actions):**
```python
# Confidence adjustments
actions = [-0.15, -0.10, -0.05, 0.00, +0.05, +0.10, +0.15]
```

**Reward Function:**
```python
def calculate_reward(base_confidence, adjusted_confidence, actual_result):
    # Did the adjustment improve prediction accuracy?
    base_error = abs(base_confidence - actual_result)
    adjusted_error = abs(adjusted_confidence - actual_result)
    
    improvement = base_error - adjusted_error
    
    if improvement > 0.10:
        return +2      # Large improvement
    elif improvement > 0.05:
        return +1      # Moderate improvement
    elif improvement > -0.05:
        return 0       # No meaningful change
    else:
        return -1      # Made prediction worse
```

**DQN Implementation:**
- Neural network: [20 input] → [64] → [32] → [7 output]
- Experience replay buffer: 10,000 transitions
- Target network updated every 1000 steps
- Epsilon-greedy exploration: start 0.9, decay to 0.05

### 4.3 Learning Player Impact

**The RL agent learns:**
- Which players matter most for each team
- How much to adjust confidence when key players are out
- Whether backup players can adequately replace starters
- Context-dependent impacts (injuries vs rest days vs matchup-specific)

**Not hardcoded - discovered through experience:**
```python
# Example learned weights after training
player_weights = {
    'LeBron James': 0.85,  # Huge impact
    'Anthony Davis': 0.78,
    'Austin Reaves': 0.45,  # Moderate impact
    # ... learned for all key players
}
```

### 4.4 Phase 4 Deliverables

**Must Have:**
- RL agent trained on historical injury data
- Player importance weights converged
- System reacts to late injury news within 30 minutes
- RL improves ROI by >1% over pure ML baseline

**Success Criteria:**
- Successful adaptation to 10+ late scratch scenarios
- No catastrophic betting decisions
- Player weights make intuitive sense (stars weighted higher)
- Confidence adjustments are reasonable (no ±0.5 swings)

---

## Phase 5: Production Deployment (Weeks 15-16)

### 5.1 Automated Daily Pipeline

**Game Day Workflow:**
```python
# 10:00 AM PST
- Collect morning odds from all books
- Check injury reports
- Generate preliminary predictions for today's games
- Flag games with injury uncertainty

# 2:00 PM PST
- Update with latest injury news
- Collect updated odds
- Finalize predictions with RL adjustments
- Identify games with positive edge

# 5:00 PM PST
- Final injury/lineup check
- Get closing odds
- Execute bets if edge still exists
- Log all decisions and reasoning

# 11:00 PM PST
- Collect game results
- Update model performance metrics
- Log wins/losses
- Update bankroll tracking
```

### 5.2 System Infrastructure

**Technology Stack:**
- Python 3.9+ (core)
- PostgreSQL (data storage)
- Redis (real-time odds caching)
- Docker (containerization)
- Cron jobs (scheduling)

**Monitoring:**
- Model prediction accuracy tracking
- Betting performance dashboard
- Bankroll visualization
- Alert system for anomalies

**Logging:**
- All predictions with confidence scores
- All betting decisions with reasoning
- Game outcomes and bet results
- Model drift detection

### 5.3 Production Safeguards

**Automated Risk Management:**
- Hard cap: 2% max bet per game
- Daily loss limit: 5% bankroll
- Confidence threshold: 60% minimum
- Edge threshold: 3% minimum
- RL adjustment cap: ±15% maximum

**Manual Overrides:**
- Kill switch to disable all betting
- Ability to skip specific games
- Bankroll adjustment capability
- Model version control

### 5.4 Phase 5 Deliverables

**Must Have:**
- Fully automated daily pipeline
- Monitoring dashboard
- Risk management enforced
- Performance tracking system
- 30+ days of successful operation

**Success Targets (6 months):**
- Positive ROI (>3% minimum)
- Max drawdown <15%
- System uptime >99% during betting hours
- Consistent weekly betting activity

---

## Future Expansion (Post Phase 5)

### Other Sports

**Same methodology applies:**
1. Build pure prediction model (sport-specific features)
2. Add market intelligence
3. Live betting with line shopping
4. Sport-specific RL enhancements (e.g., pitcher injuries for MLB)

**Priority order:**
- MLB (next target - 162 games/team = more data)
- NFL (fewer games but high handle)
- NHL (similar to NBA in structure)

### Other Bet Types

**Each requires separate specialized model:**

**Spreads** (point spread betting):
- Similar features to moneyline
- Target: margin of victory prediction
- Requires different model calibration

**Totals** (over/under):
- Needs pace and defensive efficiency features
- Target: total points scored prediction
- Weather less relevant than MLB totals

**Player Props**:
- Requires individual player stats (not aggregates)
- Target: specific player performance thresholds
- Opponent defensive matchup analysis critical
- Completely separate modeling approach

**Build order:**
Only expand after moneyline model is consistently profitable for 6+ months.

---

## Implementation Checklist

### Phase 1: Pure Prediction ($0)
- [ ] Collect NBA game data (2015-2024)
- [ ] Collect team stats (L10, shooting, etc.)
- [ ] Collect player data (top 6 per team)
- [ ] Engineer 28 features
- [ ] Train multiple models (XGBoost, RF, etc.)
- [ ] Validate on 2023-24 test set (>52% accuracy)
- [ ] Document feature importance
- [ ] Verify probability calibration

### Phase 2: Market Intelligence ($80-100)
- [ ] Purchase historical odds data
- [ ] Add 5 market features
- [ ] Train market-aware model
- [ ] Compare performance vs pure model
- [ ] Identify profitable deviations
- [ ] Validate on test set (>54% accuracy)
- [ ] Document when to trust/fade market

### Phase 3: Live Betting ($5-10/month)
- [ ] Set up multi-book odds collection
- [ ] Build betting decision pipeline
- [ ] Implement Kelly criterion sizing
- [ ] Add risk management constraints
- [ ] Create line shopping logic
- [ ] Place first 30-50 live bets
- [ ] Track and analyze results

### Phase 4: RL Enhancement (Minimal cost)
- [ ] Set up injury data monitoring
- [ ] Build RL environment
- [ ] Train DQN agent
- [ ] Learn player importance weights
- [ ] Test on historical injury scenarios
- [ ] Validate 1-2% ROI improvement
- [ ] Deploy for live injury adaptation

### Phase 5: Production (Ongoing)
- [ ] Automate daily pipeline
- [ ] Build monitoring dashboard
- [ ] Implement logging system
- [ ] Set up alerting
- [ ] Run for 30+ days
- [ ] Analyze 6-month performance
- [ ] Make go/no-go decision on expansion

---

## Expected Performance

### Phase 1 (Pure Model)
- Accuracy: 52-53%
- Proves prediction capability
- No betting yet

### Phase 2 (Market-Aware)
- Accuracy: 54-55%
- ROI: 2-3% on historical backtest
- Identifies market inefficiencies

### Phase 3 (Live Betting)
- First month: 0-2% ROI (learning period)
- Months 2-6: 3-5% ROI target
- Line shopping adds 0.5-1% ROI

### Phase 4 (With RL)
- Additional 1-2% ROI improvement
- Total system: 4-7% ROI

### Realistic 1-Year Outcome
- 5% ROI on $10,000 starting bankroll = $500 profit
- 100-150 total bets placed
- 55-57% win rate
- Proof of concept for expansion

---

## Critical Success Factors

**What Makes or Breaks This:**

1. **Discipline**: Only bet when edge exists (>3%)
2. **Patience**: Wait for the right opportunities (3-5 bets/week)
3. **Risk Management**: Never exceed 2% per bet
4. **Data Quality**: Clean, accurate feature engineering
5. **Model Validation**: Rigorous backtesting before live betting
6. **Continuous Monitoring**: Track performance and adapt
7. **Emotional Control**: Don't chase losses or increase bets after wins

**Warning Signs to Stop:**
- 3 consecutive months of negative ROI
- Drawdown exceeds 20%
- Model accuracy falls below 52%
- Systematic behavioral issues (chasing, tilt)

**This is a marathon, not a sprint.** The goal is consistent, small positive returns over many bets, not huge wins on single games.

---

## Cost Summary

**Phase 1**: $0 (free data)
**Phase 2**: $80-100 (one-time odds purchase)
**Phase 3-5**: $5-10/month (live odds)

**Total Year 1**: <$200

**Time Investment**: 15-20 hours/week for 16 weeks, then 2-3 hours/week maintenance.

---

*This roadmap focuses exclusively on NBA moneyline betting with a minimal 28-feature model. Expansion to other sports and bet types only occurs after proving consistent profitability on this focused approach.*