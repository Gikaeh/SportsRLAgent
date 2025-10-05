# Sports Betting Project: Hybrid ML Approach Roadmap
**Pure Prediction Model → Market-Aware Enhancement → RL Injury Adaptation**

## Project Overview

**Goal**: Build a betting system that uses ML for base predictions, incorporates market intelligence, and uses RL to dynamically adjust confidence based on real-time player availability.

**Strategy**:
- **Phase 1**: Pure prediction model (game data only - lowest cost)
- **Phase 2**: Add market odds as features (enhanced predictions)
- **Phase 3**: Multi-book integration for line shopping
- **Phase 4**: RL injury adaptation system
- **Phase 5**: Production deployment

**Key Insight**: Start with pure game predictions to establish independent edge, then layer in market intelligence.

---

## Phase 1: Pure Prediction Model (Weeks 1-4)

### 1.1 Core Data Collection (No Odds Required)

**Priority 1: Game Results**
- Historical game outcomes (2019, 2021-2024)
- Scores, win/loss records
- Data structure:
```
columns = ['game_id', 'date', 'home_team', 'away_team',
           'home_score', 'away_score', 'home_won']
```

**Priority 2: Team Performance Stats**
- Offensive rating, defensive rating, net rating
- Recent form: Last 10 games win percentage
- Points per game (season and L10)
- Opponent points allowed (season and L10)
- Home/away splits
- Rest days and back-to-back game tracking

**Priority 3: Key Player Stats**
- 5 starters + 6th man per team (12 players total per game)
- Season averages: Points, assists, rebounds, efficiency, PER
- Recent form: Last 5 games performance
- Usage rate and minutes per game
- Plus/minus and net rating when on court

**Priority 4: Game Context**
- Home court advantage metrics
- Days of rest for both teams
- Back-to-back game flags
- Travel distance (if available)
- Season timing (early/mid/late season)

### 1.2 Data Sources (All Free)

**Basketball-Reference.com**:
- Team stats by season
- Player stats and game logs
- Historical game results

**NBA.com Stats API**:
- Advanced team metrics
- Player tracking data
- Lineup statistics

**Cost: $0** (all historical game/player data is free)

### 1.3 Build Pure Prediction Model

**Core Features (No Odds):**
```python
pure_prediction_features = [
    # Team performance
    'home_net_rating', 'away_net_rating',
    'home_off_rating', 'away_off_rating',
    'home_def_rating', 'away_def_rating',
    
    # Recent form
    'home_wins_l10', 'away_wins_l10',
    'home_ppg_l10', 'away_ppg_l10',
    
    # Game context
    'home_rest_days', 'away_rest_days',
    'is_back_to_back_home', 'is_back_to_back_away',
    'home_court_advantage',
    
    # Key players (top 3 per team)
    'home_star1_ppg', 'home_star2_ppg', 'home_star3_ppg',
    'away_star1_ppg', 'away_star2_ppg', 'away_star3_ppg'
]
```

**Model Training:**
- Train: 2019, 2021-2022
- Validate: 2023
- Test: 2024
- Target: Win probability (0-1)

### 1.4 Phase 1 Success Criteria

**Technical:**
- Accuracy >52% (baseline threshold)
- Well-calibrated probabilities (log loss <0.69)
- Reasonable confidence intervals

**Deliverable:**
- Model predicts win probabilities based purely on game features
- Establishes your "independent opinion" separate from market
- No betting yet - just prediction validation

**Cost: $0** (only free data sources)

---

## Phase 2: Market-Aware Enhancement (Weeks 5-7)

### 2.1 NOW Add Betting Odds Data

**Single Sharp Book for Training:**
- Collect historical closing odds (2019, 2021-2024)
- Use BetOnline, LowVig, or most accurate book available
- Structure:
```
columns = ['game_id', 'date', 'home_team', 'away_team',
           'closing_home_ml', 'closing_away_ml',
           'home_won']
```

**Cost**: ~30 tokens per historical call
- ~150 games/season × 4 seasons = 600 calls
- 600 × 30 = 18,000 tokens = ~$60-80 one-time cost

### 2.2 Hybrid Model Architecture

**Compare Model Performance:**

**Model A: Pure Prediction (Phase 1)**
```python
features_A = game_features_only
target = home_won
```

**Model B: Market-Aware (Phase 2)**
```python
features_B = game_features + [
    'closing_home_implied_prob',
    'closing_away_implied_prob',
    'opening_closing_movement',  # If available
    'no_vig_home_prob',
    'no_vig_away_prob'
]
target = home_won
```

### 2.3 Evaluate Hybrid Approach

**Key Questions:**
1. Does adding odds improve prediction accuracy?
2. Does the model learn when to trust/fade the market?
3. What's the correlation between model predictions and market odds?

**Feature Importance Analysis:**
- How much weight does the model give to odds vs game features?
- When does the model deviate from market consensus?
- Are those deviations profitable?

### 2.4 Phase 2 Success Criteria

**Technical:**
- Market-aware model accuracy >54%
- Better calibration than pure model
- Identifies systematic market biases

**Business:**
- Positive expected value on historical test set
- Model finds spots where market is consistently wrong

**Deliverable:**
- Two models to compare: pure prediction vs market-aware
- Understanding of when odds help vs hurt predictions
- Ready to make actual betting decisions

---

## Phase 3: Live Betting & Multi-Book Integration (Weeks 8-10)

### 3.1 Expand to Multiple Sportsbooks

**Start Live Odds Collection:**
- Sharp books: BetOnline, LowVig
- Soft books: DraftKings, BetMGM, FanDuel
- Collection frequency: 2-3 times daily
- Cost: 1 token per call (very cheap)

**Daily Collection Schedule:**
- 10 AM: Morning lines
- 2 PM: Afternoon update
- 5 PM: Pre-game closing lines

### 3.2 Build Betting Decision System

**Complete Pipeline:**
```python
def make_betting_decision(game_data, current_odds):
    # 1. Get pure model prediction
    pure_prob = pure_model.predict_proba(game_data)[0][1]
    
    # 2. Get market-aware prediction
    game_plus_consensus = add_consensus_odds(game_data, current_odds)
    market_aware_prob = hybrid_model.predict_proba(game_plus_consensus)[0][1]
    
    # 3. Find best available odds across books
    best_home_odds = max([book['home_ml'] for book in current_odds])
    best_away_odds = max([book['away_ml'] for book in current_odds])
    
    # 4. Calculate edge
    if market_aware_prob > 0.5:
        # Bet home team
        market_implied = odds_to_prob(best_home_odds)
        edge = market_aware_prob - market_implied
        if edge > 0.03:  # 3% minimum edge
            return {'bet': 'home', 'book': best_book, 'edge': edge}
    else:
        # Bet away team
        market_implied = odds_to_prob(best_away_odds)
        edge = (1 - market_aware_prob) - market_implied
        if edge > 0.03:
            return {'bet': 'away', 'book': best_book, 'edge': edge}
    
    return {'bet': None}  # No edge found
```

### 3.3 Line Shopping Optimization

**Track Book Characteristics:**
- Which books consistently offer best odds?
- Sharp vs soft book identification
- Line movement patterns
- When do inefficiencies appear?

### 3.4 Phase 3 Success Criteria

**Technical:**
- Live odds collection working reliably
- Betting decisions made in real-time
- Line shopping finds 5-10 cent improvements regularly

**Business:**
- Positive ROI on first 30-50 live bets
- System places 3-5 bets per week with positive edge
- Bankroll management working correctly

---

## Phase 4: RL Injury Adaptation (Weeks 11-14)

### 4.1 Add Injury/Availability Tracking

**Real-Time Monitoring:**
- NBA injury reports (updated 2 hours before games)
- Lineup confirmations
- Load management decisions
- Player status changes

**Data Structure:**
```python
injury_data = [
    'player_name', 'team', 'date', 'status',
    'importance_weight', 'replacement_player'
]
```

### 4.2 RL Architecture

**State Space:**
```python
rl_state = [
    base_model_confidence,        # From Phase 2
    key_player_availability,      # 6 players × 2 teams
    learned_player_weights,       # Impact scores
    recent_rl_accuracy,          # Performance tracking
    market_consensus              # Current odds
]
```

**Action Space:**
Confidence adjustments: [-0.3, -0.2, -0.1, 0, +0.1, +0.2, +0.3]

**Reward:**
```python
reward = +1 if adjustment improved accuracy
reward = -1 if adjustment made prediction worse
reward = 0 if no meaningful change
```

### 4.3 Phase 4 Success Criteria

**Technical:**
- RL adapts predictions based on injury news
- Player importance weights stabilize
- System reacts within 30 minutes of lineup changes

**Business:**
- RL improves ROI by 1-2% over pure ML
- Successful adaptation to late scratches
- No catastrophic betting decisions

---

## Phase 5: Production Deployment (Weeks 15-16)

### 5.1 Automated Daily Pipeline

**Game Day Workflow:**
```python
# 10:00 AM: Collect morning odds, generate initial predictions
# 2:00 PM: Update with latest injury news and odds
# 5:00 PM: Final check, place bets if edge exists
# 11:00 PM: Collect results, update models
```

### 5.2 Risk Management

**Automated Safeguards:**
- Max bet size: 2% of bankroll
- Daily loss limit: 5% of bankroll
- Minimum edge threshold: 3%
- Confidence threshold: Only bet >60% final confidence

### 5.3 Success Criteria

**6-Month Performance Targets:**
- Positive ROI (>4% minimum)
- Max drawdown <15%
- System uptime >99%
- Handle 3-5 bets per week consistently

---

## Implementation Checklist

### Phase 1: Pure Prediction (Cost: $0)
- [ ] Historical game results (2019, 2021-2024)
- [ ] Team performance statistics
- [ ] Key player statistics
- [ ] Build pure prediction model
- [ ] Validate accuracy >52%

### Phase 2: Market-Aware (Cost: ~$80)
- [ ] Purchase historical closing odds
- [ ] Train market-aware model
- [ ] Compare pure vs hybrid performance
- [ ] Identify profitable deviations from market

### Phase 3: Live Betting (Cost: ~$5/month)
- [ ] Set up live odds collection (multiple books)
- [ ] Build betting decision system
- [ ] Implement line shopping
- [ ] Place first live bets

### Phase 4: RL Enhancement (Cost: minimal)
- [ ] Add injury data collection
- [ ] Implement RL confidence adjustment
- [ ] Track player importance weights
- [ ] Validate RL improvement

### Phase 5: Production
- [ ] Automated daily pipeline
- [ ] Risk management system
- [ ] Performance monitoring
- [ ] Continuous improvement

---

## Cost Breakdown

**Phase 1**: $0 (free data sources)
**Phase 2**: $60-80 (one-time historical odds purchase)
**Phase 3+**: $5-10/month (live odds collection)

**Total first-year cost: <$200**

---

## Expected Outcomes

### Realistic Scenario
- **Pure Model (Phase 1)**: 52-53% accuracy, establishes baseline
- **Market-Aware (Phase 2)**: 54-55% accuracy, 3-4% ROI
- **RL Enhancement (Phase 4)**: +1-2% ROI improvement
- **Total System**: 5-6% annual ROI

### Key Advantages of Hybrid Approach

1. **Lower initial cost** - Start with free data
2. **Independent validation** - Pure model proves you can predict games
3. **Market intelligence** - Learn when to trust/fade consensus
4. **Gradual complexity** - Add odds only after proving base concept
5. **Clear comparison** - Always know if odds help or hurt

*This hybrid approach minimizes upfront costs while building a robust foundation. You prove your prediction ability first, then enhance with market intelligence.*