# Phase 1: Streamlined 28-Feature Dataset

## Overview

The training data has been updated to generate a **streamlined 28-feature dataset** optimized for NBA moneyline prediction, as specified in the updated roadmap.

## Feature Breakdown

### 1. Team Performance (8 features)
```
home_wins_l10              # Win count in last 10 games
away_wins_l10
home_net_rating_l10        # Point differential per game (L10)
away_net_rating_l10
home_ppg_l10               # Points scored per game (L10)
away_ppg_l10
home_opp_ppg_l10           # Points allowed per game (L10) - defense
away_opp_ppg_l10
```

### 2. Game Context (4 features)
```
home_rest_days             # Days since last game
away_rest_days
is_back_to_back_home       # Binary: 0 or 1
is_back_to_back_away       # Binary: 0 or 1
```

### 3. Player Aggregates (12 features)
```
home_top3_avg_ppg          # Average PPG of top 3 scorers
away_top3_avg_ppg
home_top5_avg_mpg          # Average minutes of top 5 (starter quality)
away_top5_avg_mpg
home_top6_total_plusminus  # Sum of top 6 players' plus/minus
away_top6_total_plusminus
home_star_ppg              # Best player's PPG (star power)
away_star_ppg
home_6thman_quality        # 6th player's PPG (bench strength)
away_6thman_quality
home_depth_variance        # Std dev of 6 players' PPG (roster balance)
away_depth_variance
```

### 4. Shooting Efficiency (4 features)
```
home_fg_pct_l10            # Field goal % (L10)
away_fg_pct_l10
home_fg3_pct_l10           # Three-point % (L10)
away_fg3_pct_l10
```

## Key Changes from Previous Version

### Before (120+ features):
- 18 team L10 features
- 4 game context features
- **72 individual player features** (6 players × 6 stats × 2 teams)
- 24 previous season team features

### After (28 features):
- 8 team L10 features (streamlined)
- 4 game context features (same)
- **12 aggregated player features** (reduced from 72)
- 4 shooting efficiency features (streamlined)
- **Removed**: Previous season team features (not needed for Phase 1)

## Why Aggregated Features?

### Prevents Overfitting
- 72 individual player features → 12 aggregated features
- Reduces model complexity
- More generalizable predictions

### Captures Essential Information
- **Top 3 avg PPG**: Offensive firepower
- **Top 5 avg MPG**: Starter quality/health
- **Top 6 total +/-**: Overall team impact
- **Star PPG**: Presence of elite talent
- **6th man quality**: Bench strength
- **Depth variance**: Roster balance (low = balanced, high = top-heavy)

### Focused on Moneyline
- Individual player stats better suited for player props
- Team-level aggregates sufficient for win/loss prediction
- Aligns with Phase 1 goal: prove moneyline profitability

## Data Output

### Location
```
data/training_data/basketball/phase1/
├── 2015-16_training_data.csv
├── 2016-17_training_data.csv
├── 2017-18_training_data.csv
├── 2018-19_training_data.csv
├── 2019-20_training_data.csv
├── 2021-22_training_data.csv
├── 2022-23_training_data.csv
├── 2023-24_training_data.csv
├── 2024-25_training_data.csv
└── all_seasons_training_data.csv
```

### File Structure
Each CSV contains:
- **7 metadata columns**: game_id, date, season, home_team, away_team, home_score, away_score
- **1 target variable**: home_won
- **28 model features**: As listed above

### Total Columns: 36
- 7 metadata
- 1 target
- 28 features

## Usage

### Generate Data
```bash
cd basketball
python prepare_training_data.py
```

### Load for Training
```python
import pandas as pd

df = pd.read_csv('./data/training_data/basketball/phase1/all_seasons_training_data.csv')

# 28 features for model
features = [
    'home_wins_l10', 'away_wins_l10', 'home_net_rating_l10', 'away_net_rating_l10',
    'home_ppg_l10', 'away_ppg_l10', 'home_opp_ppg_l10', 'away_opp_ppg_l10',
    'home_rest_days', 'away_rest_days', 'is_back_to_back_home', 'is_back_to_back_away',
    'home_top3_avg_ppg', 'away_top3_avg_ppg', 'home_top5_avg_mpg', 'away_top5_avg_mpg',
    'home_top6_total_plusminus', 'away_top6_total_plusminus', 'home_star_ppg', 'away_star_ppg',
    'home_6thman_quality', 'away_6thman_quality', 'home_depth_variance', 'away_depth_variance',
    'home_fg_pct_l10', 'away_fg_pct_l10', 'home_fg3_pct_l10', 'away_fg3_pct_l10'
]

X = df[features]
y = df['home_won']
```

## Expected Performance

### Training Data Size
- **~10,000 games** across 9 seasons (2015-2025)
- **Train**: 2015-2022 (~7,400 games)
- **Validation**: 2022-23 (~1,230 games)
- **Test**: 2023-24 (~1,230 games)
- **Live**: 2024-25 (ongoing)

### Phase 1 Goals
- **Accuracy**: >52% on test set
- **Brier Score**: <0.25
- **Log Loss**: <0.69
- **Well-calibrated probabilities**

## Next Steps

1. **Run data preparation**: Generate the 28-feature dataset
2. **Exploratory analysis**: Check distributions, correlations, missing values
3. **Model training**: XGBoost, Random Forest, Logistic Regression
4. **Feature importance**: Validate logical patterns
5. **Model evaluation**: Test set performance
6. **Phase 2**: Add market odds (5 additional features → 33 total)

---

**Status**: ✅ Implementation complete  
**Ready for**: Phase 1 model training
