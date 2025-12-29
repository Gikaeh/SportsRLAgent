import pandas as pd
import numpy as np
from pathlib import Path
from tqdm import tqdm
from datetime import datetime
import warnings
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.base_data_preparer import BaseTrainingDataPreparer

warnings.filterwarnings('ignore', category=pd.errors.PerformanceWarning)

class NHLTrainingDataPreparer(BaseTrainingDataPreparer):
    def __init__(self, data_dir='././data/hockey'):
        super().__init__(data_dir, 'hockey')
        # Override data_dir for training data output
        self.training_data_dir = Path('././data/training_data/hockey')
        self.training_data_dir.mkdir(parents=True, exist_ok=True)

    def calculateTeamRollingStats(self, season, window_sizes=[5, 7, 10]):
        team_file = self.team_data_dir / f'{season}_team_stats.csv'
        if not team_file.exists():
            raise FileNotFoundError(f"Team data file not found: {team_file}")
        
        df = pd.read_csv(team_file)
        
        if df.empty:
            raise ValueError(f"Team data file for {season} is empty: {team_file}")
        
        df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])
        df = df.sort_values(['TEAM_ABBREVIATION', 'GAME_DATE'])
        
        df['TOT_GOALS'] = df['GOALS'] + df['GOALS_AGAINST']
        
        rolling_stats = []
        
        for team, team_df in df.groupby('TEAM_ABBREVIATION'):
            team_df = team_df.reset_index(drop=True)
            
            team_df['win_flag'] = (team_df['WL'] == 'W').astype(int)
            
            # Calculate win/loss streaks
            team_df['streak'] = 0
            current_streak = 0
            last_result = None
            for idx in range(len(team_df)):
                result = team_df.iloc[idx]['WL']
                if result == last_result:
                    current_streak += 1 if result == 'W' else -1
                else:
                    current_streak = 1 if result == 'W' else -1
                team_df.at[idx, 'streak'] = current_streak
                last_result = result
            
            # Shift streak to avoid leakage
            team_df['current_streak'] = team_df['streak'].shift(1).fillna(0)
            
            # Home/Away splits
            team_df['is_home'] = (team_df['HOME_AWAY'] == 'HOME').astype(int)
            team_df['home_win'] = ((team_df['HOME_AWAY'] == 'HOME') & (team_df['WL'] == 'W')).astype(int)
            team_df['away_win'] = ((team_df['HOME_AWAY'] == 'AWAY') & (team_df['WL'] == 'W')).astype(int)
            
            for window in window_sizes:
                # Basic rolling stats
                team_df[f'wins_l{window}'] = team_df['win_flag'].rolling(window=window, min_periods=1).sum().shift(1)
                team_df[f'goals_l{window}'] = team_df['GOALS'].rolling(window=window, min_periods=1).mean().shift(1)
                team_df[f'goals_against_l{window}'] = team_df['GOALS_AGAINST'].rolling(window=window, min_periods=1).mean().shift(1)
                team_df[f'total_goals_l{window}'] = team_df['TOT_GOALS'].rolling(window=window, min_periods=1).mean().shift(1)
                team_df[f'shots_l{window}'] = team_df['SHOTS'].rolling(window=window, min_periods=1).mean().shift(1)
                team_df[f'shots_against_l{window}'] = team_df['SHOTS_AGAINST'].rolling(window=window, min_periods=1).mean().shift(1)
                team_df[f'shooting_pct_l{window}'] = team_df['SHOOTING_PCT'].rolling(window=window, min_periods=1).mean().shift(1)
                team_df[f'save_pct_l{window}'] = team_df['SAVE_PCT'].rolling(window=window, min_periods=1).mean().shift(1)
                team_df[f'pp_goals_l{window}'] = team_df['POWER_PLAY_GOALS'].rolling(window=window, min_periods=1).mean().shift(1)
                team_df[f'pp_goals_against_l{window}'] = team_df['POWER_PLAY_GOALS_AGAINST'].rolling(window=window, min_periods=1).mean().shift(1)
                team_df[f'hits_l{window}'] = team_df['HITS'].rolling(window=window, min_periods=1).mean().shift(1)
                team_df[f'pim_l{window}'] = team_df['PIM'].rolling(window=window, min_periods=1).mean().shift(1)
                team_df[f'blocked_shots_l{window}'] = team_df['BLOCKED_SHOTS'].rolling(window=window, min_periods=1).mean().shift(1)
                team_df[f'takeaways_l{window}'] = team_df['TAKEAWAYS'].rolling(window=window, min_periods=1).mean().shift(1)
                team_df[f'giveaways_l{window}'] = team_df['GIVEAWAYS'].rolling(window=window, min_periods=1).mean().shift(1)
                
                # Home/Away performance splits
                team_df[f'home_wins_l{window}'] = team_df['home_win'].rolling(window=window, min_periods=1).sum().shift(1)
                team_df[f'away_wins_l{window}'] = team_df['away_win'].rolling(window=window, min_periods=1).sum().shift(1)
                team_df[f'home_games_l{window}'] = team_df['is_home'].rolling(window=window, min_periods=1).sum().shift(1)
                
                # Goals trend (recent vs longer term) - only for larger windows
                if window >= 7:
                    team_df[f'goals_l3'] = team_df['GOALS'].rolling(window=3, min_periods=1).mean().shift(1)
                    team_df[f'goals_trend_l{window}'] = team_df[f'goals_l3'] - team_df[f'goals_l{window}']
                    team_df[f'goals_against_trend_l{window}'] = team_df['GOALS_AGAINST'].rolling(window=3, min_periods=1).mean().shift(1) - team_df[f'goals_against_l{window}']
                
                # Consistency metrics (std dev)
                team_df[f'goals_std_l{window}'] = team_df['GOALS'].rolling(window=window, min_periods=2).std().shift(1).fillna(0)
                team_df[f'goals_against_std_l{window}'] = team_df['GOALS_AGAINST'].rolling(window=window, min_periods=2).std().shift(1).fillna(0)
            
            max_window = max(window_sizes)
            team_df = team_df.iloc[max_window:].copy()
            
            cols_to_keep = ['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID', 'current_streak']
            for window in window_sizes:
                cols_to_keep.extend([
                    f'wins_l{window}', f'goals_l{window}', f'goals_against_l{window}',
                    f'total_goals_l{window}', f'shots_l{window}', f'shots_against_l{window}',
                    f'shooting_pct_l{window}', f'save_pct_l{window}', f'pp_goals_l{window}',
                    f'pp_goals_against_l{window}', f'hits_l{window}', f'pim_l{window}',
                    f'blocked_shots_l{window}', f'takeaways_l{window}', f'giveaways_l{window}',
                    f'home_wins_l{window}', f'away_wins_l{window}', f'home_games_l{window}',
                    f'goals_std_l{window}', f'goals_against_std_l{window}'
                ])
                if window >= 7:
                    cols_to_keep.extend([f'goals_trend_l{window}', f'goals_against_trend_l{window}'])
            
            team_rolling = team_df[cols_to_keep]
            rolling_stats.append(team_rolling)
        
        result = pd.concat(rolling_stats, ignore_index=True)
        
        if result.empty:
            raise ValueError(f"calculateTeamRollingStats returned empty dataframe for season {season}")
        
        return result
    
    def calculateRestDays(self, df):
        df = df.sort_values(['TEAM_ABBREVIATION', 'GAME_DATE'])
        df['prev_game_date'] = df.groupby('TEAM_ABBREVIATION')['GAME_DATE'].shift(1)
        df['rest_days'] = (df['GAME_DATE'] - df['prev_game_date']).dt.days - 1
        df['is_back_to_back'] = (df['rest_days'] == 0).astype(int)
        
        return df
    
    def precomputePlayerRollingAverages(self, season):
        player_file = self.player_data_dir / f'{season}_player_stats.csv'
        if not player_file.exists():
            return pd.DataFrame(), pd.DataFrame()
        
        # Check cache first
        skaters_cached = self.getCachedData('skater_rolling', season)
        goalies_cached = self.getCachedData('goalie_rolling', season)
        if skaters_cached is not None and goalies_cached is not None:
            return skaters_cached, goalies_cached
        
        df = pd.read_csv(player_file)
        
        if df.empty:
            return pd.DataFrame(), pd.DataFrame()
        
        df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])
        
        # Separate skaters and goalies
        skaters_df = df[df['POSITION'] != 'G'].copy()
        goalies_df = df[df['POSITION'] == 'G'].copy()
        
        # Process skaters with vectorized operations
        skater_numeric_cols = ['GOALS', 'ASSISTS', 'POINTS', 'PLUS_MINUS', 'SHOTS', 'HITS', 
                               'BLOCK_SHOTS', 'TOI', 'FACEOFF_WIN_PCTG', 'SHIFTS', 'TAKEAWAY', 'GIVEAWAY']
        for col in skater_numeric_cols:
            if col in skaters_df.columns:
                skaters_df[col] = pd.to_numeric(skaters_df[col], errors='coerce').fillna(0)
        
        skaters_df = skaters_df.sort_values(['PLAYER_ID', 'GAME_DATE'])
        
        # Vectorized rolling stats for skaters
        skater_rolling_map = {
            'GOALS': 'goals_rolling',
            'ASSISTS': 'assists_rolling',
            'POINTS': 'points_rolling',
            'PLUS_MINUS': 'plus_minus_rolling',
            'SHOTS': 'shots_rolling',
            'HITS': 'hits_rolling',
            'BLOCK_SHOTS': 'blocked_shots_rolling',
            'TOI': 'toi_rolling',
            'FACEOFF_WIN_PCTG': 'faceoff_win_pct_rolling',
            'SHIFTS': 'shifts_rolling',
            'TAKEAWAY': 'takeaway_rolling',
            'GIVEAWAY': 'giveaway_rolling',
        }
        skaters_df = self.computeRollingStatsVectorized(skaters_df, 'PLAYER_ID', skater_rolling_map, window=None, min_periods=1)
        
        # Std dev metrics
        skater_std_map = {'POINTS': 'points_std', 'GOALS': 'goals_std'}
        skaters_df = self.computeRollingStdVectorized(skaters_df, 'PLAYER_ID', skater_std_map, window=10, min_periods=2)
        
        # Shooting percentage
        skaters_df['shooting_pct'] = skaters_df.groupby('PLAYER_ID').apply(
            lambda x: (x['GOALS'] / (x['SHOTS'] + 0.001)).rolling(window=10, min_periods=1).mean().shift(1)
        ).reset_index(level=0, drop=True).fillna(0)
        
        # Process goalies with vectorized operations
        goalie_numeric_cols = ['SAVES', 'SHOTS_AGAINST', 'GOALS_AGAINST', 'SAVE_PCT', 'TOI',
                               'EVEN_STRENGTH_GOALS_AGAINST', 'POWER_PLAY_GOALS_AGAINST', 'SHORT_HANDED_GOALS_AGAINST']
        for col in goalie_numeric_cols:
            if col in goalies_df.columns:
                goalies_df[col] = pd.to_numeric(goalies_df[col], errors='coerce').fillna(0)
        
        goalies_df = goalies_df.sort_values(['PLAYER_ID', 'GAME_DATE'])
        
        # Vectorized rolling stats for goalies
        goalie_rolling_map = {
            'SAVES': 'saves_rolling',
            'SHOTS_AGAINST': 'shots_against_rolling',
            'GOALS_AGAINST': 'goals_against_rolling',
            'SAVE_PCT': 'save_pct_rolling',
            'TOI': 'toi_rolling',
            'EVEN_STRENGTH_GOALS_AGAINST': 'es_goals_against_rolling',
            'POWER_PLAY_GOALS_AGAINST': 'pp_goals_against_rolling',
            'SHORT_HANDED_GOALS_AGAINST': 'sh_goals_against_rolling',
        }
        goalies_df = self.computeRollingStatsVectorized(goalies_df, 'PLAYER_ID', goalie_rolling_map, window=None, min_periods=1)
        
        # Goalie workload - games in last 7 days (needs special handling)
        if not goalies_df.empty:
            goalies_df = goalies_df.set_index('GAME_DATE')
            goalies_df['games_last_7_days'] = goalies_df.groupby('PLAYER_ID').apply(
                lambda x: x.index.to_series().rolling(window='7D').count().shift(1)
            ).reset_index(level=0, drop=True).fillna(0)
            goalies_df = goalies_df.reset_index()
        
        # Std dev for goalies
        goalie_std_map = {'SAVE_PCT': 'save_pct_std'}
        goalies_df = self.computeRollingStdVectorized(goalies_df, 'PLAYER_ID', goalie_std_map, window=10, min_periods=2)
        
        # Save to cache
        self.saveCachedData(skaters_df, 'skater_rolling', season)
        self.saveCachedData(goalies_df, 'goalie_rolling', season)
        
        return skaters_df, goalies_df
    
    def getTopSkatersWithStats(self, skater_df, game_id, team_abbr, top_n=6):
        # Try to get game-specific data first (for historical games)
        game_skaters = skater_df[(skater_df['GAME_ID'] == game_id) & (skater_df['TEAM_ABBREVIATION'] == team_abbr)].copy()
        
        # If no game-specific data, get latest stats for team (for upcoming games)
        if game_skaters.empty:
            team_skaters = skater_df[skater_df['TEAM_ABBREVIATION'] == team_abbr].copy()
            if team_skaters.empty:
                return pd.DataFrame()
            # Get most recent stats for each player
            latest_skaters = team_skaters.sort_values('GAME_DATE').groupby('PLAYER_ID').last().reset_index()
            # Sort by points rolling to get top performers
            game_skaters = latest_skaters.sort_values('points_rolling', ascending=False).head(top_n)
        else:
            if len(game_skaters) < top_n:
                return pd.DataFrame()
            game_skaters = game_skaters.sort_values('TOI', ascending=False).head(top_n)
        
        return game_skaters[['PLAYER_ID', 'goals_rolling', 'assists_rolling', 'points_rolling', 
                             'plus_minus_rolling', 'shots_rolling', 'hits_rolling', 
                             'blocked_shots_rolling', 'toi_rolling', 'faceoff_win_pct_rolling',
                             'shifts_rolling', 'takeaway_rolling', 'giveaway_rolling',
                             'points_std', 'goals_std', 'shooting_pct']]
    
    def getTopGoaliesWithStats(self, goalie_df, game_id, team_abbr, top_n=2):
        # Try to get game-specific data first (for historical games)
        game_goalies = goalie_df[(goalie_df['GAME_ID'] == game_id) & (goalie_df['TEAM_ABBREVIATION'] == team_abbr)].copy()
        
        # If no game-specific data, get latest stats for team (for upcoming games)
        if game_goalies.empty:
            team_goalies = goalie_df[goalie_df['TEAM_ABBREVIATION'] == team_abbr].copy()
            if team_goalies.empty:
                return pd.DataFrame()
            # Get most recent stats for each goalie
            latest_goalies = team_goalies.sort_values('GAME_DATE').groupby('PLAYER_ID').last().reset_index()
            # Sort by games in last 7 days and TOI to get likely starters
            game_goalies = latest_goalies.sort_values(['games_last_7_days', 'toi_rolling'], ascending=[False, False]).head(top_n)
        else:
            # Sort by TOI to get starting goalie first
            game_goalies = game_goalies.sort_values('TOI', ascending=False).head(top_n)
        
        return game_goalies[['PLAYER_ID', 'saves_rolling', 'shots_against_rolling', 'goals_against_rolling',
                             'save_pct_rolling', 'toi_rolling', 'es_goals_against_rolling',
                             'pp_goals_against_rolling', 'sh_goals_against_rolling',
                             'games_last_7_days', 'save_pct_std']]
    
    def addPlayerFeatures(self, matchup_data, season):
        print(f"Adding player features for {season}...")
        print(f"Precomputing player rolling averages...")
        
        skater_df, goalie_df = self.precomputePlayerRollingAverages(season)
        
        if skater_df.empty and goalie_df.empty:
            print(f"Warning: No player data found for {season}")
            return pd.DataFrame()
        
        player_features = []
        
        for idx, row in tqdm(matchup_data.iterrows(), total=len(matchup_data), desc="Processing games"):
            game_id = row['GAME_ID']
            home_team = row['TEAM_ABBREVIATION_home']
            away_team = row['TEAM_ABBREVIATION_away']
            
            game_features = {'game_id': game_id}

            # Add top 6 skaters for home team
            home_skaters = self.getTopSkatersWithStats(skater_df, game_id, home_team, top_n=6)
            for i in range(6):
                prefix = f'home_skater{i+1}_'
                if i < len(home_skaters):
                    skater = home_skaters.iloc[i]
                    game_features[f'{prefix}goals'] = skater['goals_rolling']
                    game_features[f'{prefix}assists'] = skater['assists_rolling']
                    game_features[f'{prefix}points'] = skater['points_rolling']
                    game_features[f'{prefix}plus_minus'] = skater['plus_minus_rolling']
                    game_features[f'{prefix}shots'] = skater['shots_rolling']
                    game_features[f'{prefix}hits'] = skater['hits_rolling']
                    game_features[f'{prefix}blocked_shots'] = skater['blocked_shots_rolling']
                    game_features[f'{prefix}toi'] = skater['toi_rolling']
                    game_features[f'{prefix}faceoff_win_pct'] = skater['faceoff_win_pct_rolling']
                    game_features[f'{prefix}shifts'] = skater['shifts_rolling']
                    game_features[f'{prefix}takeaway'] = skater['takeaway_rolling']
                    game_features[f'{prefix}giveaway'] = skater['giveaway_rolling']
                else:
                    for stat in ['goals', 'assists', 'points', 'plus_minus', 'shots', 'hits', 
                                'blocked_shots', 'toi', 'faceoff_win_pct', 'shifts', 'takeaway', 'giveaway']:
                        game_features[f'{prefix}{stat}'] = 0
            
            # Add goalies for home team
            home_goalies = self.getTopGoaliesWithStats(goalie_df, game_id, home_team, top_n=2)
            for i in range(2):
                prefix = f'home_goalie{i+1}_'
                if i < len(home_goalies):
                    goalie = home_goalies.iloc[i]
                    game_features[f'{prefix}saves'] = goalie['saves_rolling']
                    game_features[f'{prefix}shots_against'] = goalie['shots_against_rolling']
                    game_features[f'{prefix}goals_against'] = goalie['goals_against_rolling']
                    game_features[f'{prefix}save_pct'] = goalie['save_pct_rolling']
                    game_features[f'{prefix}toi'] = goalie['toi_rolling']
                    game_features[f'{prefix}es_goals_against'] = goalie['es_goals_against_rolling']
                    game_features[f'{prefix}pp_goals_against'] = goalie['pp_goals_against_rolling']
                    game_features[f'{prefix}sh_goals_against'] = goalie['sh_goals_against_rolling']
                else:
                    for stat in ['saves', 'shots_against', 'goals_against', 'save_pct', 'toi',
                                'es_goals_against', 'pp_goals_against', 'sh_goals_against']:
                        game_features[f'{prefix}{stat}'] = 0
            
            # Add top 6 skaters for away team
            away_skaters = self.getTopSkatersWithStats(skater_df, game_id, away_team, top_n=6)
            for i in range(6):
                prefix = f'away_skater{i+1}_'
                if i < len(away_skaters):
                    skater = away_skaters.iloc[i]
                    game_features[f'{prefix}goals'] = skater['goals_rolling']
                    game_features[f'{prefix}assists'] = skater['assists_rolling']
                    game_features[f'{prefix}points'] = skater['points_rolling']
                    game_features[f'{prefix}plus_minus'] = skater['plus_minus_rolling']
                    game_features[f'{prefix}shots'] = skater['shots_rolling']
                    game_features[f'{prefix}hits'] = skater['hits_rolling']
                    game_features[f'{prefix}blocked_shots'] = skater['blocked_shots_rolling']
                    game_features[f'{prefix}toi'] = skater['toi_rolling']
                    game_features[f'{prefix}faceoff_win_pct'] = skater['faceoff_win_pct_rolling']
                    game_features[f'{prefix}shifts'] = skater['shifts_rolling']
                    game_features[f'{prefix}takeaway'] = skater['takeaway_rolling']
                    game_features[f'{prefix}giveaway'] = skater['giveaway_rolling']
                    game_features[f'{prefix}points_std'] = skater['points_std']
                    game_features[f'{prefix}goals_std'] = skater['goals_std']
                    game_features[f'{prefix}shooting_pct'] = skater['shooting_pct']
                else:
                    for stat in ['goals', 'assists', 'points', 'plus_minus', 'shots', 'hits', 
                                'blocked_shots', 'toi', 'faceoff_win_pct', 'shifts', 'takeaway', 'giveaway',
                                'points_std', 'goals_std', 'shooting_pct']:
                        game_features[f'{prefix}{stat}'] = 0
            
            # Add goalies for away team
            away_goalies = self.getTopGoaliesWithStats(goalie_df, game_id, away_team, top_n=2)
            for i in range(2):
                prefix = f'away_goalie{i+1}_'
                if i < len(away_goalies):
                    goalie = away_goalies.iloc[i]
                    game_features[f'{prefix}saves'] = goalie['saves_rolling']
                    game_features[f'{prefix}shots_against'] = goalie['shots_against_rolling']
                    game_features[f'{prefix}goals_against'] = goalie['goals_against_rolling']
                    game_features[f'{prefix}save_pct'] = goalie['save_pct_rolling']
                    game_features[f'{prefix}toi'] = goalie['toi_rolling']
                    game_features[f'{prefix}es_goals_against'] = goalie['es_goals_against_rolling']
                    game_features[f'{prefix}pp_goals_against'] = goalie['pp_goals_against_rolling']
                    game_features[f'{prefix}sh_goals_against'] = goalie['sh_goals_against_rolling']
                    game_features[f'{prefix}games_last_7_days'] = goalie['games_last_7_days']
                    game_features[f'{prefix}save_pct_std'] = goalie['save_pct_std']
                else:
                    for stat in ['saves', 'shots_against', 'goals_against', 'save_pct', 'toi',
                                'es_goals_against', 'pp_goals_against', 'sh_goals_against',
                                'games_last_7_days', 'save_pct_std']:
                        game_features[f'{prefix}{stat}'] = 0
            
            player_features.append(game_features)
        
        return pd.DataFrame(player_features)
    
    def createGameMatchupData(self, season, window_sizes=[10]):
        game_file = self.game_data_dir / f'{season}_game_stats.csv'
        if not game_file.exists():
            raise FileNotFoundError(f"Game data file not found: {game_file}")
        
        games_df = pd.read_csv(game_file)
        games_df['GAME_DATE'] = pd.to_datetime(games_df['GAME_DATE'])
        
        print(f"Calculating rolling stats for {season} (windows: {window_sizes})...")
        rolling_stats = self.calculateTeamRollingStats(season, window_sizes)
        
        print(f"Calculating rest days for {season}...")
        team_rest = self.calculateRestDays(games_df[['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID']].copy())
        
        team_features = rolling_stats.merge(
            team_rest[['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID', 'rest_days', 'is_back_to_back']],
            on=['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID'],
            how='left'
        )

        games_df.dropna(subset=['MATCHUP'], inplace=True)
        
        games_df['is_home'] = games_df['HOME_AWAY'] == 'HOME'
        
        home_games = games_df[games_df['is_home']].copy()
        away_games = games_df[~games_df['is_home']].copy()
        
        home_features = home_games.merge(
            team_features,
            on=['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID'],
            how='inner',
            suffixes=('', '_home')
        )
        
        away_features = away_games.merge(
            team_features,
            on=['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID'],
            how='inner',
            suffixes=('', '_away')
        )
        
        matchup_data = home_features.merge(
            away_features,
            on='GAME_ID',
            suffixes=('_home', '_away')
        )
        
        player_features = self.addPlayerFeatures(matchup_data, season)
        if not player_features.empty:
            matchup_data = matchup_data.merge(player_features, left_on='GAME_ID', right_on='game_id', how='left')
            
            print(f"Calculating aggregated player features for {season}...")
            
            player_cols = [col for col in matchup_data.columns if col.startswith(('home_skater', 'away_skater', 'home_goalie', 'away_goalie'))]
            for col in player_cols:
                matchup_data[col] = pd.to_numeric(matchup_data[col], errors='coerce').fillna(0)
            
            # Skater aggregations
            home_top3_avg_goals = matchup_data[['home_skater1_goals', 'home_skater2_goals', 'home_skater3_goals']].mean(axis=1)
            home_top6_avg_goals = matchup_data[['home_skater1_goals', 'home_skater2_goals', 'home_skater3_goals', 'home_skater4_goals', 'home_skater5_goals', 'home_skater6_goals']].mean(axis=1)
            home_top3_avg_assists = matchup_data[['home_skater1_assists', 'home_skater2_assists', 'home_skater3_assists']].mean(axis=1)
            home_top6_avg_assists = matchup_data[['home_skater1_assists', 'home_skater2_assists', 'home_skater3_assists', 'home_skater4_assists', 'home_skater5_assists', 'home_skater6_assists']].mean(axis=1)
            home_top3_avg_points = matchup_data[['home_skater1_points', 'home_skater2_points', 'home_skater3_points']].mean(axis=1)
            home_top6_avg_points = matchup_data[['home_skater1_points', 'home_skater2_points', 'home_skater3_points', 'home_skater4_points', 'home_skater5_points', 'home_skater6_points']].mean(axis=1)
            home_top6_total_plusminus = matchup_data[['home_skater1_plus_minus', 'home_skater2_plus_minus', 'home_skater3_plus_minus', 'home_skater4_plus_minus', 'home_skater5_plus_minus', 'home_skater6_plus_minus']].sum(axis=1)
            home_top6_avg_shots = matchup_data[['home_skater1_shots', 'home_skater2_shots', 'home_skater3_shots', 'home_skater4_shots', 'home_skater5_shots', 'home_skater6_shots']].mean(axis=1)
            home_top6_avg_hits = matchup_data[['home_skater1_hits', 'home_skater2_hits', 'home_skater3_hits', 'home_skater4_hits', 'home_skater5_hits', 'home_skater6_hits']].mean(axis=1)
            home_top6_avg_blocked_shots = matchup_data[['home_skater1_blocked_shots', 'home_skater2_blocked_shots', 'home_skater3_blocked_shots', 'home_skater4_blocked_shots', 'home_skater5_blocked_shots', 'home_skater6_blocked_shots']].mean(axis=1)
            home_top6_avg_faceoff_win_pct = matchup_data[['home_skater1_faceoff_win_pct', 'home_skater2_faceoff_win_pct', 'home_skater3_faceoff_win_pct', 'home_skater4_faceoff_win_pct', 'home_skater5_faceoff_win_pct', 'home_skater6_faceoff_win_pct']].mean(axis=1)
            home_top6_total_takeaways = matchup_data[['home_skater1_takeaway', 'home_skater2_takeaway', 'home_skater3_takeaway', 'home_skater4_takeaway', 'home_skater5_takeaway', 'home_skater6_takeaway']].sum(axis=1)
            home_top6_total_giveaways = matchup_data[['home_skater1_giveaway', 'home_skater2_giveaway', 'home_skater3_giveaway', 'home_skater4_giveaway', 'home_skater5_giveaway', 'home_skater6_giveaway']].sum(axis=1)
            home_top6_takeaway_giveaway_ratio = home_top6_total_takeaways / (home_top6_total_giveaways + 1)
            
            away_top3_avg_goals = matchup_data[['away_skater1_goals', 'away_skater2_goals', 'away_skater3_goals']].mean(axis=1)
            away_top6_avg_goals = matchup_data[['away_skater1_goals', 'away_skater2_goals', 'away_skater3_goals', 'away_skater4_goals', 'away_skater5_goals', 'away_skater6_goals']].mean(axis=1)
            away_top3_avg_assists = matchup_data[['away_skater1_assists', 'away_skater2_assists', 'away_skater3_assists']].mean(axis=1)
            away_top6_avg_assists = matchup_data[['away_skater1_assists', 'away_skater2_assists', 'away_skater3_assists', 'away_skater4_assists', 'away_skater5_assists', 'away_skater6_assists']].mean(axis=1)
            away_top3_avg_points = matchup_data[['away_skater1_points', 'away_skater2_points', 'away_skater3_points']].mean(axis=1)
            away_top6_avg_points = matchup_data[['away_skater1_points', 'away_skater2_points', 'away_skater3_points', 'away_skater4_points', 'away_skater5_points', 'away_skater6_points']].mean(axis=1)
            away_top6_total_plusminus = matchup_data[['away_skater1_plus_minus', 'away_skater2_plus_minus', 'away_skater3_plus_minus', 'away_skater4_plus_minus', 'away_skater5_plus_minus', 'away_skater6_plus_minus']].sum(axis=1)
            away_top6_avg_shots = matchup_data[['away_skater1_shots', 'away_skater2_shots', 'away_skater3_shots', 'away_skater4_shots', 'away_skater5_shots', 'away_skater6_shots']].mean(axis=1)
            away_top6_avg_hits = matchup_data[['away_skater1_hits', 'away_skater2_hits', 'away_skater3_hits', 'away_skater4_hits', 'away_skater5_hits', 'away_skater6_hits']].mean(axis=1)
            away_top6_avg_blocked_shots = matchup_data[['away_skater1_blocked_shots', 'away_skater2_blocked_shots', 'away_skater3_blocked_shots', 'away_skater4_blocked_shots', 'away_skater5_blocked_shots', 'away_skater6_blocked_shots']].mean(axis=1)
            away_top6_avg_faceoff_win_pct = matchup_data[['away_skater1_faceoff_win_pct', 'away_skater2_faceoff_win_pct', 'away_skater3_faceoff_win_pct', 'away_skater4_faceoff_win_pct', 'away_skater5_faceoff_win_pct', 'away_skater6_faceoff_win_pct']].mean(axis=1)
            away_top6_total_takeaways = matchup_data[['away_skater1_takeaway', 'away_skater2_takeaway', 'away_skater3_takeaway', 'away_skater4_takeaway', 'away_skater5_takeaway', 'away_skater6_takeaway']].sum(axis=1)
            away_top6_total_giveaways = matchup_data[['away_skater1_giveaway', 'away_skater2_giveaway', 'away_skater3_giveaway', 'away_skater4_giveaway', 'away_skater5_giveaway', 'away_skater6_giveaway']].sum(axis=1)
            away_top6_takeaway_giveaway_ratio = away_top6_total_takeaways / (away_top6_total_giveaways + 1)
            
            # Goalie aggregations (primary goalie)
            home_goalie_save_pct = matchup_data['home_goalie1_save_pct']
            home_goalie_goals_against = matchup_data['home_goalie1_goals_against']
            home_goalie_saves = matchup_data['home_goalie1_saves']
            home_goalie_shots_against = matchup_data['home_goalie1_shots_against']
            
            away_goalie_save_pct = matchup_data['away_goalie1_save_pct']
            away_goalie_goals_against = matchup_data['away_goalie1_goals_against']
            away_goalie_saves = matchup_data['away_goalie1_saves']
            away_goalie_shots_against = matchup_data['away_goalie1_shots_against']
            
            # Goalie matchup differentials
            goalie_save_pct_diff = home_goalie_save_pct - away_goalie_save_pct
            goalie_goals_against_diff = home_goalie_goals_against - away_goalie_goals_against
        
            # Add aggregated features to training dict
            matchup_data['home_top3_avg_goals'] = home_top3_avg_goals
            matchup_data['home_top6_avg_goals'] = home_top6_avg_goals
            matchup_data['home_top3_avg_assists'] = home_top3_avg_assists
            matchup_data['home_top6_avg_assists'] = home_top6_avg_assists
            matchup_data['home_top3_avg_points'] = home_top3_avg_points
            matchup_data['home_top6_avg_points'] = home_top6_avg_points
            matchup_data['home_top6_total_plusminus'] = home_top6_total_plusminus
            matchup_data['home_top6_avg_shots'] = home_top6_avg_shots
            matchup_data['home_top6_avg_hits'] = home_top6_avg_hits
            matchup_data['home_top6_avg_blocked_shots'] = home_top6_avg_blocked_shots
            matchup_data['home_top6_avg_faceoff_win_pct'] = home_top6_avg_faceoff_win_pct
            matchup_data['home_top6_total_takeaways'] = home_top6_total_takeaways
            matchup_data['home_top6_total_giveaways'] = home_top6_total_giveaways
            matchup_data['home_top6_takeaway_giveaway_ratio'] = home_top6_takeaway_giveaway_ratio
            
            matchup_data['away_top3_avg_goals'] = away_top3_avg_goals
            matchup_data['away_top6_avg_goals'] = away_top6_avg_goals
            matchup_data['away_top3_avg_assists'] = away_top3_avg_assists
            matchup_data['away_top6_avg_assists'] = away_top6_avg_assists
            matchup_data['away_top3_avg_points'] = away_top3_avg_points
            matchup_data['away_top6_avg_points'] = away_top6_avg_points
            matchup_data['away_top6_total_plusminus'] = away_top6_total_plusminus
            matchup_data['away_top6_avg_shots'] = away_top6_avg_shots
            matchup_data['away_top6_avg_hits'] = away_top6_avg_hits
            matchup_data['away_top6_avg_blocked_shots'] = away_top6_avg_blocked_shots
            matchup_data['away_top6_avg_faceoff_win_pct'] = away_top6_avg_faceoff_win_pct
            matchup_data['away_top6_total_takeaways'] = away_top6_total_takeaways
            matchup_data['away_top6_total_giveaways'] = away_top6_total_giveaways
            matchup_data['away_top6_takeaway_giveaway_ratio'] = away_top6_takeaway_giveaway_ratio
            
            matchup_data['home_goalie_save_pct'] = home_goalie_save_pct
            matchup_data['home_goalie_goals_against'] = home_goalie_goals_against
            matchup_data['home_goalie_saves'] = home_goalie_saves
            matchup_data['home_goalie_shots_against'] = home_goalie_shots_against
            
            matchup_data['away_goalie_save_pct'] = away_goalie_save_pct
            matchup_data['away_goalie_goals_against'] = away_goalie_goals_against
            matchup_data['away_goalie_saves'] = away_goalie_saves
            matchup_data['away_goalie_shots_against'] = away_goalie_shots_against
            
            matchup_data['goalie_save_pct_diff'] = goalie_save_pct_diff
            matchup_data['goalie_goals_against_diff'] = goalie_goals_against_diff
        
        training_data_dict = {
            'game_id': matchup_data['GAME_ID'],
            'date': matchup_data['GAME_DATE_home'],
            'season': season,
            
            'home_team': matchup_data['TEAM_ABBREVIATION_home'],
            'away_team': matchup_data['TEAM_ABBREVIATION_away'],
            
            'home_score': matchup_data['PTS_home'],
            'away_score': matchup_data['PTS_away'],
            'total_score': matchup_data['PTS_home'] + matchup_data['PTS_away'],
            'goal_diff': matchup_data['PTS_home'] - matchup_data['PTS_away'],
            'home_won': (matchup_data['WL_home'] == 'W').astype(int),
            
            'home_rest_days': matchup_data['rest_days_home'],
            'away_rest_days': matchup_data['rest_days_away'],
            'rest_days_diff': matchup_data['rest_days_home'] - matchup_data['rest_days_away'],
            'is_back_to_back_home': matchup_data['is_back_to_back_home'],
            'is_back_to_back_away': matchup_data['is_back_to_back_away'],
            
            'home_streak': matchup_data['current_streak_home'],
            'away_streak': matchup_data['current_streak_away'],
            'streak_diff': matchup_data['current_streak_home'] - matchup_data['current_streak_away'],
        }
        
        for window in window_sizes:
            training_data_dict.update({
                f'home_wins_l{window}': matchup_data[f'wins_l{window}_home'],
                f'away_wins_l{window}': matchup_data[f'wins_l{window}_away'],
                f'home_goals_l{window}': matchup_data[f'goals_l{window}_home'],
                f'away_goals_l{window}': matchup_data[f'goals_l{window}_away'],
                f'goals_diff_l{window}': matchup_data[f'goals_l{window}_home'] - matchup_data[f'goals_l{window}_away'],
                f'home_goals_against_l{window}': matchup_data[f'goals_against_l{window}_home'],
                f'away_goals_against_l{window}': matchup_data[f'goals_against_l{window}_away'],
                f'goals_against_diff_l{window}': matchup_data[f'goals_against_l{window}_home'] - matchup_data[f'goals_against_l{window}_away'],
                f'home_total_goals_l{window}': matchup_data[f'total_goals_l{window}_home'],
                f'away_total_goals_l{window}': matchup_data[f'total_goals_l{window}_away'],
                f'home_shots_l{window}': matchup_data[f'shots_l{window}_home'],
                f'away_shots_l{window}': matchup_data[f'shots_l{window}_away'],
                f'home_shots_against_l{window}': matchup_data[f'shots_against_l{window}_home'],
                f'away_shots_against_l{window}': matchup_data[f'shots_against_l{window}_away'],
                f'home_shooting_pct_l{window}': matchup_data[f'shooting_pct_l{window}_home'],
                f'away_shooting_pct_l{window}': matchup_data[f'shooting_pct_l{window}_away'],
                f'home_save_pct_l{window}': matchup_data[f'save_pct_l{window}_home'],
                f'away_save_pct_l{window}': matchup_data[f'save_pct_l{window}_away'],
                f'home_pp_goals_l{window}': matchup_data[f'pp_goals_l{window}_home'],
                f'away_pp_goals_l{window}': matchup_data[f'pp_goals_l{window}_away'],
                f'home_pp_goals_against_l{window}': matchup_data[f'pp_goals_against_l{window}_home'],
                f'away_pp_goals_against_l{window}': matchup_data[f'pp_goals_against_l{window}_away'],
                f'home_hits_l{window}': matchup_data[f'hits_l{window}_home'],
                f'away_hits_l{window}': matchup_data[f'hits_l{window}_away'],
                f'home_pim_l{window}': matchup_data[f'pim_l{window}_home'],
                f'away_pim_l{window}': matchup_data[f'pim_l{window}_away'],
                f'home_blocked_shots_l{window}': matchup_data[f'blocked_shots_l{window}_home'],
                f'away_blocked_shots_l{window}': matchup_data[f'blocked_shots_l{window}_away'],
                f'home_takeaways_l{window}': matchup_data[f'takeaways_l{window}_home'],
                f'away_takeaways_l{window}': matchup_data[f'takeaways_l{window}_away'],
                f'home_giveaways_l{window}': matchup_data[f'giveaways_l{window}_home'],
                f'away_giveaways_l{window}': matchup_data[f'giveaways_l{window}_away'],
                
                # Home/Away splits
                f'home_home_wins_l{window}': matchup_data[f'home_wins_l{window}_home'],
                f'away_away_wins_l{window}': matchup_data[f'away_wins_l{window}_away'],
                f'home_home_games_l{window}': matchup_data[f'home_games_l{window}_home'],
                f'away_home_games_l{window}': matchup_data[f'home_games_l{window}_away'],
                
                # Consistency metrics
                f'home_goals_std_l{window}': matchup_data[f'goals_std_l{window}_home'],
                f'away_goals_std_l{window}': matchup_data[f'goals_std_l{window}_away'],
                f'home_goals_against_std_l{window}': matchup_data[f'goals_against_std_l{window}_home'],
                f'away_goals_against_std_l{window}': matchup_data[f'goals_against_std_l{window}_away'],
            })
            
            # Goals trends (only for windows >= 7)
            if window >= 7:
                training_data_dict.update({
                    f'home_goals_trend_l{window}': matchup_data[f'goals_trend_l{window}_home'],
                    f'away_goals_trend_l{window}': matchup_data[f'goals_trend_l{window}_away'],
                    f'home_goals_against_trend_l{window}': matchup_data[f'goals_against_trend_l{window}_home'],
                    f'away_goals_against_trend_l{window}': matchup_data[f'goals_against_trend_l{window}_away'],
                })
        
        if not player_features.empty:
            training_data_dict.update({
                'home_top3_avg_goals': home_top3_avg_goals,
                'away_top3_avg_goals': away_top3_avg_goals,
                'home_top6_avg_goals': home_top6_avg_goals,
                'away_top6_avg_goals': away_top6_avg_goals,
                'home_top3_avg_assists': home_top3_avg_assists,
                'away_top3_avg_assists': away_top3_avg_assists,
                'home_top6_avg_assists': home_top6_avg_assists,
                'away_top6_avg_assists': away_top6_avg_assists,
                'home_top3_avg_points': home_top3_avg_points,
                'away_top3_avg_points': away_top3_avg_points,
                'home_top6_avg_points': home_top6_avg_points,
                'away_top6_avg_points': away_top6_avg_points,
                'home_top6_total_plusminus': home_top6_total_plusminus,
                'away_top6_total_plusminus': away_top6_total_plusminus,
                
                'home_goalie_save_pct': home_goalie_save_pct,
                'home_goalie_goals_against': home_goalie_goals_against,
                'home_goalie_saves': home_goalie_saves,
                'home_goalie_shots_against': home_goalie_shots_against,
                'away_goalie_save_pct': away_goalie_save_pct,
                'away_goalie_goals_against': away_goalie_goals_against,
                'away_goalie_saves': away_goalie_saves,
                'away_goalie_shots_against': away_goalie_shots_against,
                'goalie_save_pct_diff': goalie_save_pct_diff,
                'goalie_goals_against_diff': goalie_goals_against_diff,
            })
        
        training_data = pd.DataFrame(training_data_dict)
        training_data = training_data.sort_values('date').reset_index(drop=True)
        
        if training_data.empty:
            raise ValueError(f"createGameMatchupData returned empty dataframe for season {season}")
 
        return training_data
    
    def getCurrentSeason(self):
        current_date = datetime.now()
        if current_date.month >= 10:
            return f"{current_date.year}-{current_date.year + 1}"
        else:
            return f"{current_date.year - 1}-{current_date.year}"
    
    def createUpcomingMatchupData(self, upcoming_games_file=None, window_sizes=[10]):
        if upcoming_games_file is None:
            upcoming_games_file = self.data_dir / 'upcoming_games.csv'
        
        if not upcoming_games_file.exists():
            raise FileNotFoundError(f"Upcoming games file not found: {upcoming_games_file}")
        
        upcoming_df = pd.read_csv(upcoming_games_file)
        upcoming_df['GAME_DATE'] = pd.to_datetime(upcoming_df['GAME_DATE'])
        
        if upcoming_df.empty:
            print("No upcoming games found.")
            return pd.DataFrame()
        
        print(f"Processing {len(upcoming_df)} upcoming games...")
        
        current_season = self.getCurrentSeason()
        print(f"Current season: {current_season}")
        
        team_file = self.team_data_dir / f'{current_season}_team_stats.csv'
        if not team_file.exists():
            raise FileNotFoundError(f"Team data file not found: {team_file}")
        
        team_df = pd.read_csv(team_file)
        team_df['GAME_DATE'] = pd.to_datetime(team_df['GAME_DATE'])
        
        print(f"Calculating rolling stats for {current_season}...")
        rolling_stats = self.calculateTeamRollingStats(current_season, [10])
        
        print(f"Calculating rest days for {current_season}...")
        team_rest = self.calculateRestDays(team_df[['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID']].copy())
        
        team_features = rolling_stats.merge(
            team_rest[['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID', 'rest_days', 'is_back_to_back']],
            on=['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID'],
            how='left'
        )
        
        latest_team_stats = team_features.sort_values('GAME_DATE').groupby('TEAM_ABBREVIATION').last().reset_index()
        
        matchup_rows = []
        
        for _, game in upcoming_df.iterrows():
            game_id = game['GAME_ID']
            game_date = game['GAME_DATE']
            home_team = game['HOME_TEAM_ABBR']
            away_team = game['AWAY_TEAM_ABBR']
            
            home_stats = latest_team_stats[latest_team_stats['TEAM_ABBREVIATION'] == home_team]
            if home_stats.empty:
                print(f"Warning: No stats found for home team {home_team}, skipping game {game_id}")
                continue
            home_stats = home_stats.iloc[0]
            
            away_stats = latest_team_stats[latest_team_stats['TEAM_ABBREVIATION'] == away_team]
            if away_stats.empty:
                print(f"Warning: No stats found for away team {away_team}, skipping game {game_id}")
                continue
            away_stats = away_stats.iloc[0]
            
            game_date_naive = game_date.tz_localize(None) if game_date.tz is not None else game_date
            
            home_last_game = team_df[team_df['TEAM_ABBREVIATION'] == home_team]['GAME_DATE'].max()
            away_last_game = team_df[team_df['TEAM_ABBREVIATION'] == away_team]['GAME_DATE'].max()
            
            home_rest = (game_date_naive - home_last_game).days - 1 if pd.notna(home_last_game) else 3
            away_rest = (game_date_naive - away_last_game).days - 1 if pd.notna(away_last_game) else 3
            
            matchup_row = {
                'GAME_ID': game_id,
                'GAME_DATE_home': game_date,
                'TEAM_ABBREVIATION_home': home_team,
                'TEAM_ABBREVIATION_away': away_team,
                'rest_days_home': home_rest,
                'rest_days_away': away_rest,
                'is_back_to_back_home': 1 if home_rest == 0 else 0,
                'is_back_to_back_away': 1 if away_rest == 0 else 0,
                'current_streak_home': home_stats['current_streak'],
                'current_streak_away': away_stats['current_streak'],
            }
            
            for window in window_sizes:
                matchup_row.update({
                    f'wins_l{window}_home': home_stats[f'wins_l{window}'],
                    f'wins_l{window}_away': away_stats[f'wins_l{window}'],
                    f'goals_l{window}_home': home_stats[f'goals_l{window}'],
                    f'goals_l{window}_away': away_stats[f'goals_l{window}'],
                    f'goals_against_l{window}_home': home_stats[f'goals_against_l{window}'],
                    f'goals_against_l{window}_away': away_stats[f'goals_against_l{window}'],
                    f'total_goals_l{window}_home': home_stats[f'total_goals_l{window}'],
                    f'total_goals_l{window}_away': away_stats[f'total_goals_l{window}'],
                    f'shots_l{window}_home': home_stats[f'shots_l{window}'],
                    f'shots_l{window}_away': away_stats[f'shots_l{window}'],
                    f'shots_against_l{window}_home': home_stats[f'shots_against_l{window}'],
                    f'shots_against_l{window}_away': away_stats[f'shots_against_l{window}'],
                    f'shooting_pct_l{window}_home': home_stats[f'shooting_pct_l{window}'],
                    f'shooting_pct_l{window}_away': away_stats[f'shooting_pct_l{window}'],
                    f'save_pct_l{window}_home': home_stats[f'save_pct_l{window}'],
                    f'save_pct_l{window}_away': away_stats[f'save_pct_l{window}'],
                    f'pp_goals_l{window}_home': home_stats[f'pp_goals_l{window}'],
                    f'pp_goals_l{window}_away': away_stats[f'pp_goals_l{window}'],
                    f'pp_goals_against_l{window}_home': home_stats[f'pp_goals_against_l{window}'],
                    f'pp_goals_against_l{window}_away': away_stats[f'pp_goals_against_l{window}'],
                    f'hits_l{window}_home': home_stats[f'hits_l{window}'],
                    f'hits_l{window}_away': away_stats[f'hits_l{window}'],
                    f'pim_l{window}_home': home_stats[f'pim_l{window}'],
                    f'pim_l{window}_away': away_stats[f'pim_l{window}'],
                    f'blocked_shots_l{window}_home': home_stats[f'blocked_shots_l{window}'],
                    f'blocked_shots_l{window}_away': away_stats[f'blocked_shots_l{window}'],
                    f'takeaways_l{window}_home': home_stats[f'takeaways_l{window}'],
                    f'takeaways_l{window}_away': away_stats[f'takeaways_l{window}'],
                    f'giveaways_l{window}_home': home_stats[f'giveaways_l{window}'],
                    f'giveaways_l{window}_away': away_stats[f'giveaways_l{window}'],
                    
                    # Home/Away splits
                    f'home_wins_l{window}_home': home_stats[f'home_wins_l{window}'],
                    f'away_wins_l{window}_away': away_stats[f'away_wins_l{window}'],
                    f'home_games_l{window}_home': home_stats[f'home_games_l{window}'],
                    f'home_games_l{window}_away': away_stats[f'home_games_l{window}'],
                    
                    # Consistency metrics
                    f'goals_std_l{window}_home': home_stats[f'goals_std_l{window}'],
                    f'goals_std_l{window}_away': away_stats[f'goals_std_l{window}'],
                    f'goals_against_std_l{window}_home': home_stats[f'goals_against_std_l{window}'],
                    f'goals_against_std_l{window}_away': away_stats[f'goals_against_std_l{window}'],
                })
                
                # Goals trends (only for windows >= 7)
                if window >= 7:
                    matchup_row.update({
                        f'goals_trend_l{window}_home': home_stats[f'goals_trend_l{window}'],
                        f'goals_trend_l{window}_away': away_stats[f'goals_trend_l{window}'],
                        f'goals_against_trend_l{window}_home': home_stats[f'goals_against_trend_l{window}'],
                        f'goals_against_trend_l{window}_away': away_stats[f'goals_against_trend_l{window}'],
                    })
            
            matchup_rows.append(matchup_row)
        
        matchup_data = pd.DataFrame(matchup_rows)
        
        if matchup_data.empty:
            print("No matchup data created.")
            return pd.DataFrame()
        
        player_features = self.addPlayerFeatures(matchup_data, current_season)
        if not player_features.empty:
            matchup_data = matchup_data.merge(player_features, left_on='GAME_ID', right_on='game_id', how='left')
            
            player_cols = [col for col in matchup_data.columns if col.startswith(('home_skater', 'away_skater', 'home_goalie', 'away_goalie'))]
            for col in player_cols:
                matchup_data[col] = pd.to_numeric(matchup_data[col], errors='coerce').fillna(0)
            
            # Skater aggregations (same as createGameMatchupData)
            home_top3_avg_goals = matchup_data[['home_skater1_goals', 'home_skater2_goals', 'home_skater3_goals']].mean(axis=1)
            home_top6_avg_goals = matchup_data[['home_skater1_goals', 'home_skater2_goals', 'home_skater3_goals', 'home_skater4_goals', 'home_skater5_goals', 'home_skater6_goals']].mean(axis=1)
            home_top3_avg_assists = matchup_data[['home_skater1_assists', 'home_skater2_assists', 'home_skater3_assists']].mean(axis=1)
            home_top6_avg_assists = matchup_data[['home_skater1_assists', 'home_skater2_assists', 'home_skater3_assists', 'home_skater4_assists', 'home_skater5_assists', 'home_skater6_assists']].mean(axis=1)
            home_top3_avg_points = matchup_data[['home_skater1_points', 'home_skater2_points', 'home_skater3_points']].mean(axis=1)
            home_top6_avg_points = matchup_data[['home_skater1_points', 'home_skater2_points', 'home_skater3_points', 'home_skater4_points', 'home_skater5_points', 'home_skater6_points']].mean(axis=1)
            home_top6_total_plusminus = matchup_data[['home_skater1_plus_minus', 'home_skater2_plus_minus', 'home_skater3_plus_minus', 'home_skater4_plus_minus', 'home_skater5_plus_minus', 'home_skater6_plus_minus']].sum(axis=1)
            home_top6_avg_shots = matchup_data[['home_skater1_shots', 'home_skater2_shots', 'home_skater3_shots', 'home_skater4_shots', 'home_skater5_shots', 'home_skater6_shots']].mean(axis=1)
            home_top6_avg_hits = matchup_data[['home_skater1_hits', 'home_skater2_hits', 'home_skater3_hits', 'home_skater4_hits', 'home_skater5_hits', 'home_skater6_hits']].mean(axis=1)
            home_top6_avg_blocked_shots = matchup_data[['home_skater1_blocked_shots', 'home_skater2_blocked_shots', 'home_skater3_blocked_shots', 'home_skater4_blocked_shots', 'home_skater5_blocked_shots', 'home_skater6_blocked_shots']].mean(axis=1)
            home_top6_avg_faceoff_win_pct = matchup_data[['home_skater1_faceoff_win_pct', 'home_skater2_faceoff_win_pct', 'home_skater3_faceoff_win_pct', 'home_skater4_faceoff_win_pct', 'home_skater5_faceoff_win_pct', 'home_skater6_faceoff_win_pct']].mean(axis=1)
            home_top6_total_takeaways = matchup_data[['home_skater1_takeaway', 'home_skater2_takeaway', 'home_skater3_takeaway', 'home_skater4_takeaway', 'home_skater5_takeaway', 'home_skater6_takeaway']].sum(axis=1)
            home_top6_total_giveaways = matchup_data[['home_skater1_giveaway', 'home_skater2_giveaway', 'home_skater3_giveaway', 'home_skater4_giveaway', 'home_skater5_giveaway', 'home_skater6_giveaway']].sum(axis=1)
            home_top6_takeaway_giveaway_ratio = home_top6_total_takeaways / (home_top6_total_giveaways + 1)
            
            away_top3_avg_goals = matchup_data[['away_skater1_goals', 'away_skater2_goals', 'away_skater3_goals']].mean(axis=1)
            away_top6_avg_goals = matchup_data[['away_skater1_goals', 'away_skater2_goals', 'away_skater3_goals', 'away_skater4_goals', 'away_skater5_goals', 'away_skater6_goals']].mean(axis=1)
            away_top3_avg_assists = matchup_data[['away_skater1_assists', 'away_skater2_assists', 'away_skater3_assists']].mean(axis=1)
            away_top6_avg_assists = matchup_data[['away_skater1_assists', 'away_skater2_assists', 'away_skater3_assists', 'away_skater4_assists', 'away_skater5_assists', 'away_skater6_assists']].mean(axis=1)
            away_top3_avg_points = matchup_data[['away_skater1_points', 'away_skater2_points', 'away_skater3_points']].mean(axis=1)
            away_top6_avg_points = matchup_data[['away_skater1_points', 'away_skater2_points', 'away_skater3_points', 'away_skater4_points', 'away_skater5_points', 'away_skater6_points']].mean(axis=1)
            away_top6_total_plusminus = matchup_data[['away_skater1_plus_minus', 'away_skater2_plus_minus', 'away_skater3_plus_minus', 'away_skater4_plus_minus', 'away_skater5_plus_minus', 'away_skater6_plus_minus']].sum(axis=1)
            away_top6_avg_shots = matchup_data[['away_skater1_shots', 'away_skater2_shots', 'away_skater3_shots', 'away_skater4_shots', 'away_skater5_shots', 'away_skater6_shots']].mean(axis=1)
            away_top6_avg_hits = matchup_data[['away_skater1_hits', 'away_skater2_hits', 'away_skater3_hits', 'away_skater4_hits', 'away_skater5_hits', 'away_skater6_hits']].mean(axis=1)
            away_top6_avg_blocked_shots = matchup_data[['away_skater1_blocked_shots', 'away_skater2_blocked_shots', 'away_skater3_blocked_shots', 'away_skater4_blocked_shots', 'away_skater5_blocked_shots', 'away_skater6_blocked_shots']].mean(axis=1)
            away_top6_avg_faceoff_win_pct = matchup_data[['away_skater1_faceoff_win_pct', 'away_skater2_faceoff_win_pct', 'away_skater3_faceoff_win_pct', 'away_skater4_faceoff_win_pct', 'away_skater5_faceoff_win_pct', 'away_skater6_faceoff_win_pct']].mean(axis=1)
            away_top6_total_takeaways = matchup_data[['away_skater1_takeaway', 'away_skater2_takeaway', 'away_skater3_takeaway', 'away_skater4_takeaway', 'away_skater5_takeaway', 'away_skater6_takeaway']].sum(axis=1)
            away_top6_total_giveaways = matchup_data[['away_skater1_giveaway', 'away_skater2_giveaway', 'away_skater3_giveaway', 'away_skater4_giveaway', 'away_skater5_giveaway', 'away_skater6_giveaway']].sum(axis=1)
            away_top6_takeaway_giveaway_ratio = away_top6_total_takeaways / (away_top6_total_giveaways + 1)
            
            # Goalie aggregations
            home_goalie_save_pct = matchup_data['home_goalie1_save_pct']
            home_goalie_goals_against = matchup_data['home_goalie1_goals_against']
            home_goalie_saves = matchup_data['home_goalie1_saves']
            home_goalie_shots_against = matchup_data['home_goalie1_shots_against']
            
            away_goalie_save_pct = matchup_data['away_goalie1_save_pct']
            away_goalie_goals_against = matchup_data['away_goalie1_goals_against']
            away_goalie_saves = matchup_data['away_goalie1_saves']
            away_goalie_shots_against = matchup_data['away_goalie1_shots_against']
            
            goalie_save_pct_diff = home_goalie_save_pct - away_goalie_save_pct
            goalie_goals_against_diff = home_goalie_goals_against - away_goalie_goals_against
            
            # Add all aggregated features at once to avoid fragmentation
            aggregated_features = pd.DataFrame({
                'home_top3_avg_goals': home_top3_avg_goals,
                'home_top6_avg_goals': home_top6_avg_goals,
                'home_top3_avg_assists': home_top3_avg_assists,
                'home_top6_avg_assists': home_top6_avg_assists,
                'home_top3_avg_points': home_top3_avg_points,
                'home_top6_avg_points': home_top6_avg_points,
                'home_top6_total_plusminus': home_top6_total_plusminus,
                'home_top6_avg_shots': home_top6_avg_shots,
                'home_top6_avg_hits': home_top6_avg_hits,
                'home_top6_avg_blocked_shots': home_top6_avg_blocked_shots,
                'home_top6_avg_faceoff_win_pct': home_top6_avg_faceoff_win_pct,
                'home_top6_total_takeaways': home_top6_total_takeaways,
                'home_top6_total_giveaways': home_top6_total_giveaways,
                'home_top6_takeaway_giveaway_ratio': home_top6_takeaway_giveaway_ratio,
                'away_top3_avg_goals': away_top3_avg_goals,
                'away_top6_avg_goals': away_top6_avg_goals,
                'away_top3_avg_assists': away_top3_avg_assists,
                'away_top6_avg_assists': away_top6_avg_assists,
                'away_top3_avg_points': away_top3_avg_points,
                'away_top6_avg_points': away_top6_avg_points,
                'away_top6_total_plusminus': away_top6_total_plusminus,
                'away_top6_avg_shots': away_top6_avg_shots,
                'away_top6_avg_hits': away_top6_avg_hits,
                'away_top6_avg_blocked_shots': away_top6_avg_blocked_shots,
                'away_top6_avg_faceoff_win_pct': away_top6_avg_faceoff_win_pct,
                'away_top6_total_takeaways': away_top6_total_takeaways,
                'away_top6_total_giveaways': away_top6_total_giveaways,
                'away_top6_takeaway_giveaway_ratio': away_top6_takeaway_giveaway_ratio,
                'home_goalie_save_pct': home_goalie_save_pct,
                'home_goalie_goals_against': home_goalie_goals_against,
                'home_goalie_saves': home_goalie_saves,
                'home_goalie_shots_against': home_goalie_shots_against,
                'away_goalie_save_pct': away_goalie_save_pct,
                'away_goalie_goals_against': away_goalie_goals_against,
                'away_goalie_saves': away_goalie_saves,
                'away_goalie_shots_against': away_goalie_shots_against,
                'goalie_save_pct_diff': goalie_save_pct_diff,
                'goalie_goals_against_diff': goalie_goals_against_diff
            }, index=matchup_data.index)
            
            matchup_data = pd.concat([matchup_data, aggregated_features], axis=1)
        
        prediction_data_dict = {
            'game_id': matchup_data['GAME_ID'],
            'date': matchup_data['GAME_DATE_home'],
            'season': current_season,
            'home_team': matchup_data['TEAM_ABBREVIATION_home'],
            'away_team': matchup_data['TEAM_ABBREVIATION_away'],
            'home_rest_days': matchup_data['rest_days_home'],
            'away_rest_days': matchup_data['rest_days_away'],
            'rest_days_diff': matchup_data['rest_days_home'] - matchup_data['rest_days_away'],
            'is_back_to_back_home': matchup_data['is_back_to_back_home'],
            'is_back_to_back_away': matchup_data['is_back_to_back_away'],
            
            'home_streak': matchup_data['current_streak_home'],
            'away_streak': matchup_data['current_streak_away'],
            'streak_diff': matchup_data['current_streak_home'] - matchup_data['current_streak_away'],
        }
        
        for window in window_sizes:
            prediction_data_dict.update({
                f'home_wins_l{window}': matchup_data[f'wins_l{window}_home'],
                f'away_wins_l{window}': matchup_data[f'wins_l{window}_away'],
                f'home_goals_l{window}': matchup_data[f'goals_l{window}_home'],
                f'away_goals_l{window}': matchup_data[f'goals_l{window}_away'],
                f'goals_diff_l{window}': matchup_data[f'goals_l{window}_home'] - matchup_data[f'goals_l{window}_away'],
                f'home_goals_against_l{window}': matchup_data[f'goals_against_l{window}_home'],
                f'away_goals_against_l{window}': matchup_data[f'goals_against_l{window}_away'],
                f'goals_against_diff_l{window}': matchup_data[f'goals_against_l{window}_home'] - matchup_data[f'goals_against_l{window}_away'],
                f'home_total_goals_l{window}': matchup_data[f'total_goals_l{window}_home'],
                f'away_total_goals_l{window}': matchup_data[f'total_goals_l{window}_away'],
                f'home_shots_l{window}': matchup_data[f'shots_l{window}_home'],
                f'away_shots_l{window}': matchup_data[f'shots_l{window}_away'],
                f'home_shots_against_l{window}': matchup_data[f'shots_against_l{window}_home'],
                f'away_shots_against_l{window}': matchup_data[f'shots_against_l{window}_away'],
                f'home_shooting_pct_l{window}': matchup_data[f'shooting_pct_l{window}_home'],
                f'away_shooting_pct_l{window}': matchup_data[f'shooting_pct_l{window}_away'],
                f'home_save_pct_l{window}': matchup_data[f'save_pct_l{window}_home'],
                f'away_save_pct_l{window}': matchup_data[f'save_pct_l{window}_away'],
                f'home_pp_goals_l{window}': matchup_data[f'pp_goals_l{window}_home'],
                f'away_pp_goals_l{window}': matchup_data[f'pp_goals_l{window}_away'],
                f'home_pp_goals_against_l{window}': matchup_data[f'pp_goals_against_l{window}_home'],
                f'away_pp_goals_against_l{window}': matchup_data[f'pp_goals_against_l{window}_away'],
                f'home_hits_l{window}': matchup_data[f'hits_l{window}_home'],
                f'away_hits_l{window}': matchup_data[f'hits_l{window}_away'],
                f'home_pim_l{window}': matchup_data[f'pim_l{window}_home'],
                f'away_pim_l{window}': matchup_data[f'pim_l{window}_away'],
                f'home_blocked_shots_l{window}': matchup_data[f'blocked_shots_l{window}_home'],
                f'away_blocked_shots_l{window}': matchup_data[f'blocked_shots_l{window}_away'],
                f'home_takeaways_l{window}': matchup_data[f'takeaways_l{window}_home'],
                f'away_takeaways_l{window}': matchup_data[f'takeaways_l{window}_away'],
                f'home_giveaways_l{window}': matchup_data[f'giveaways_l{window}_home'],
                f'away_giveaways_l{window}': matchup_data[f'giveaways_l{window}_away'],
                
                # Home/Away splits
                f'home_home_wins_l{window}': matchup_data[f'home_wins_l{window}_home'],
                f'away_away_wins_l{window}': matchup_data[f'away_wins_l{window}_away'],
                f'home_home_games_l{window}': matchup_data[f'home_games_l{window}_home'],
                f'away_home_games_l{window}': matchup_data[f'home_games_l{window}_away'],
                
                # Consistency metrics
                f'home_goals_std_l{window}': matchup_data[f'goals_std_l{window}_home'],
                f'away_goals_std_l{window}': matchup_data[f'goals_std_l{window}_away'],
                f'home_goals_against_std_l{window}': matchup_data[f'goals_against_std_l{window}_home'],
                f'away_goals_against_std_l{window}': matchup_data[f'goals_against_std_l{window}_away'],
            })
            
            # Goals trends (only for windows >= 7)
            if window >= 7:
                prediction_data_dict.update({
                    f'home_goals_trend_l{window}': matchup_data[f'goals_trend_l{window}_home'],
                    f'away_goals_trend_l{window}': matchup_data[f'goals_trend_l{window}_away'],
                    f'home_goals_against_trend_l{window}': matchup_data[f'goals_against_trend_l{window}_home'],
                    f'away_goals_against_trend_l{window}': matchup_data[f'goals_against_trend_l{window}_away'],
                })
        
        if not player_features.empty:
            prediction_data_dict.update({
                'home_top3_avg_goals': matchup_data['home_top3_avg_goals'],
                'away_top3_avg_goals': matchup_data['away_top3_avg_goals'],
                'home_top6_avg_goals': matchup_data['home_top6_avg_goals'],
                'away_top6_avg_goals': matchup_data['away_top6_avg_goals'],
                'home_top3_avg_assists': matchup_data['home_top3_avg_assists'],
                'away_top3_avg_assists': matchup_data['away_top3_avg_assists'],
                'home_top6_avg_assists': matchup_data['home_top6_avg_assists'],
                'away_top6_avg_assists': matchup_data['away_top6_avg_assists'],
                'home_top3_avg_points': matchup_data['home_top3_avg_points'],
                'away_top3_avg_points': matchup_data['away_top3_avg_points'],
                'home_top6_avg_points': matchup_data['home_top6_avg_points'],
                'away_top6_avg_points': matchup_data['away_top6_avg_points'],
                'home_top6_total_plusminus': matchup_data['home_top6_total_plusminus'],
                'away_top6_total_plusminus': matchup_data['away_top6_total_plusminus'],
                
                'home_goalie_save_pct': matchup_data['home_goalie_save_pct'],
                'home_goalie_goals_against': matchup_data['home_goalie_goals_against'],
                'home_goalie_saves': matchup_data['home_goalie_saves'],
                'home_goalie_shots_against': matchup_data['home_goalie_shots_against'],
                'away_goalie_save_pct': matchup_data['away_goalie_save_pct'],
                'away_goalie_goals_against': matchup_data['away_goalie_goals_against'],
                'away_goalie_saves': matchup_data['away_goalie_saves'],
                'away_goalie_shots_against': matchup_data['away_goalie_shots_against'],
                'goalie_save_pct_diff': matchup_data['goalie_save_pct_diff'],
                'goalie_goals_against_diff': matchup_data['goalie_goals_against_diff'],
            })
        
        prediction_data = pd.DataFrame(prediction_data_dict)
        
        return prediction_data
    
    def prepareMultipleSeasons(self, seasons=None, window_sizes=[10], save_individual=True, save_combined=True):
        all_data = []
        current_season = self.getCurrentSeason()
        
        if seasons is None:
            seasons = ['2010-2011', '2011-2012', '2012-2013', '2013-2014', '2014-2015', '2015-2016', '2016-2017', '2017-2018', '2018-2019', '2019-2020', '2020-2021', '2021-2022', '2022-2023', '2023-2024', '2024-2025', '2025-2026']
        
        # Create separated_seasons directory if it doesn't exist
        separated_seasons_dir = self.data_dir / 'separated_seasons'
        separated_seasons_dir.mkdir(parents=True, exist_ok=True)
        
        # Get list of already processed seasons
        existing_files = [f.stem.replace('_training_data', '') for f in separated_seasons_dir.glob('*_training_data.csv')]
        
        for season in seasons:
            # Skip if already processed and not current season
            if season in existing_files and season != current_season:
                print(f"Skipping {season} as it already exists")
                all_data.append(pd.read_csv(separated_seasons_dir / f'{season}_training_data.csv'))
                continue
            
            print(f"\n{'='*60}")
            print(f"Processing season: {season}")
            print(f"{'='*60}")
            
            try:
                season_data = self.createGameMatchupData(season, window_sizes)
                all_data.append(season_data)
                print(f"Successfully processed {len(season_data)} games for {season}")
                
                if save_individual:
                    output_path = separated_seasons_dir / f'{season}_training_data.csv'
                    season_data.to_csv(output_path, index=False)
                    print(f"Saved to {output_path}")
            except Exception as e:
                print(f"Error processing season {season}: {e}")
                continue
        
        if not all_data:
            raise ValueError("No data was successfully processed")
        
        combined_data = pd.concat(all_data, ignore_index=True)
        
        if save_combined:
            output_path = self.data_dir / 'all_seasons_training_data.csv'
            combined_data.to_csv(output_path, index=False)
            print(f"\nSaved combined data to {output_path}")
            print(f"Total games: {len(combined_data)}")
        
        return combined_data