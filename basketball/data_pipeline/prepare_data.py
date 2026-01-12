import pandas as pd
import numpy as np
from pathlib import Path
from tqdm import tqdm
from datetime import datetime
# from .injury_data import InjuryData
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.base_data_preparer import BaseTrainingDataPreparer

class NBATrainingDataPreparer(BaseTrainingDataPreparer):
    def __init__(self, data_dir='././data/basketball'):
        super().__init__(data_dir, 'basketball')
        self.season_averages_cache = {}
        # self.injury_data = InjuryData(data_dir=data_dir)  

    def calculateTeamL10Stats(self, season):
        team_file = self.team_data_dir / f'{season}_team_stats.csv'
        if not team_file.exists():
            raise FileNotFoundError(f"Team data file not found: {team_file}")
        
        df = pd.read_csv(team_file)
        
        if df.empty:
            raise ValueError(f"Team data file for {season} is empty: {team_file}")
        
        df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])
        df = df.sort_values(['TEAM_ABBREVIATION', 'GAME_DATE'])
        
        df['OPP_PTS'] = df['PTS'] - df['PLUS_MINUS']
        df['TOT_PTS'] = df['PTS'] + df['OPP_PTS']
        df['win_flag'] = (df['WL'] == 'W').astype(int)
        
        # Vectorized rolling stats using base class method
        rolling_stats = {
            'TOT_PTS': 'total_l10',
            'PTS': 'ppg_l10',
            'OPP_PTS': 'opp_ppg_l10',
            'FG_PCT': 'fg_pct_l10',
            'FG3_PCT': 'fg3_pct_l10',
            'REB': 'reb_l10',
            'AST': 'ast_l10',
            'TOV': 'tov_l10',
            'BLK': 'blk_l10',
            'STL': 'stl_l10',
            'PLUS_MINUS': 'plus_minus_l10',
        }
        
        df = self.computeRollingStatsVectorized(df, 'TEAM_ABBREVIATION', rolling_stats, window=10, min_periods=1)
        
        # Wins need sum, not mean
        df['wins_l10'] = df.groupby('TEAM_ABBREVIATION')['win_flag'].transform(
            lambda x: x.rolling(window=10, min_periods=1).sum().shift(1)
        ).fillna(0)
        
        # Drop first 10 games per team
        df['game_num'] = df.groupby('TEAM_ABBREVIATION').cumcount()
        df = df[df['game_num'] >= 10].drop(columns=['game_num'])
        
        result = df[['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID', 'wins_l10', 'ppg_l10', 'opp_ppg_l10', 
                     'fg_pct_l10', 'fg3_pct_l10', 'reb_l10', 'ast_l10', 'tov_l10', 'blk_l10', 
                     'stl_l10', 'plus_minus_l10', 'total_l10']].copy()
        
        current_season = self.getCurrentSeason()
        if result.empty:
            if season == current_season:
                max_games_per_team = df.groupby('TEAM_ABBREVIATION').size().max()
                if max_games_per_team < 11:
                    raise ValueError(f"Current season {season} has insufficient games (max {max_games_per_team} per team, need 11+) to calculate L10 stats")
            raise ValueError(f"calculateTeamL10Stats returned empty dataframe for season {season}. Data may be corrupted.")
        
        stat_cols = ['ppg_l10', 'opp_ppg_l10', 'fg_pct_l10', 'reb_l10', 'ast_l10', 'tov_l10', 'blk_l10', 'stl_l10', 'total_l10']
        if (result[stat_cols] == 0).all().all():
            raise ValueError(f"calculateTeamL10Stats returned all-zero stats for season {season}. Data may be corrupted.")
        
        return result
    
    def precomputePlayerRollingAverages(self, season):
        player_file = self.player_data_dir / f'{season}_player_stats.csv'
        if not player_file.exists():
            return pd.DataFrame()
        
        # Check cache first (with source file freshness check)
        cached = self.getCachedData('player_rolling', season, source_file=player_file)
        if cached is not None:
            return cached
        
        df = pd.read_csv(player_file)
        
        if df.empty:
            raise ValueError(f"Player data file for {season} is empty: {player_file}")
        
        df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])
        df = df.sort_values(['PLAYER_ID', 'GAME_DATE'])
        
        # Vectorized rolling stats using base class method
        rolling_stats = {
            'PTS': 'ppg_rolling',
            'FG_PCT': 'fg_pct_rolling',
            'MIN': 'mpg_rolling',
            'AST': 'apg_rolling',
            'REB': 'rpg_rolling',
            'BLK': 'blk_rolling',
            'STL': 'stl_rolling',
            'TOV': 'tov_rolling',
            'PLUS_MINUS': 'plus_minus_rolling',
        }
        
        df = self.computeRollingStatsVectorized(df, 'PLAYER_ID', rolling_stats, window=None, min_periods=1)
        
        if len(df) > 0:
            # Validation check
            player_game_counts = df.groupby('PLAYER_ID').size()
            players_with_multiple_games = player_game_counts[player_game_counts > 1].index
            
            if len(players_with_multiple_games) > 0:
                multi_game_data = df[df['PLAYER_ID'].isin(players_with_multiple_games)].copy()
                multi_game_data['game_num'] = multi_game_data.groupby('PLAYER_ID').cumcount() + 1
                non_first_games = multi_game_data[multi_game_data['game_num'] > 1]
                
                if len(non_first_games) > 0:
                    stat_cols = ['ppg_rolling', 'mpg_rolling', 'apg_rolling', 'rpg_rolling', 'blk_rolling', 'stl_rolling', 'tov_rolling']
                    if (non_first_games[stat_cols] == 0).all().all():
                        raise ValueError(f"precomputePlayerRollingAverages returned all-zero rolling stats for non-first games in season {season}. Data may be corrupted.")
        
        # Save to cache
        self.saveCachedData(df, 'player_rolling', season)
        
        return df
    
    def getTopPlayersWithStats(self, player_df, game_id, team_abbr, top_n=6):
        game_players = player_df[(player_df['GAME_ID'] == game_id) & (player_df['TEAM_ABBREVIATION'] == team_abbr)].copy()
        
        if game_players.empty or len(game_players) < top_n:
            return pd.DataFrame()
        
        game_players = game_players.sort_values('MIN', ascending=False).head(top_n)
        
        return game_players[['PLAYER_ID', 'ppg_rolling', 'fg_pct_rolling', 'mpg_rolling', 'plus_minus_rolling', 'apg_rolling', 'rpg_rolling', 'blk_rolling', 'stl_rolling', 'tov_rolling']]
    
    def addPlayerFeatures(self, matchup_data, season):
        print(f"Adding player features for {season}...")
        print(f"Precomputing player rolling averages...")
        
        player_df = self.precomputePlayerRollingAverages(season)
        
        if player_df.empty:
            raise ValueError(f"No player data found for {season}. Cannot add player features without player data.")
        
        player_features = []
        
        for idx, row in tqdm(matchup_data.iterrows(), total=len(matchup_data)):
            game_id = row['GAME_ID']
            home_team = row['TEAM_ABBREVIATION_home']
            away_team = row['TEAM_ABBREVIATION_away']
            
            game_features = {'game_id': game_id}

            # Get top 6 players for home team with precomputed stats
            home_players = self.getTopPlayersWithStats(player_df, game_id, home_team, top_n=6)
            for i in range(6):
                prefix = f'home_p{i+1}_'
                if i < len(home_players):
                    player = home_players.iloc[i]
                    game_features[f'{prefix}ppg'] = player['ppg_rolling']
                    game_features[f'{prefix}fg_pct'] = player['fg_pct_rolling']
                    game_features[f'{prefix}mpg'] = player['mpg_rolling']
                    game_features[f'{prefix}apg'] = player['apg_rolling']
                    game_features[f'{prefix}rpg'] = player['rpg_rolling']
                    game_features[f'{prefix}blk'] = player['blk_rolling']
                    game_features[f'{prefix}stl'] = player['stl_rolling']
                    game_features[f'{prefix}tov'] = player['tov_rolling']
                    game_features[f'{prefix}plus_minus'] = player['plus_minus_rolling']
                else:
                    print(f"No player data available for {home_team} in game {game_id}")
            
            # Get top 6 players for away team with precomputed stats
            away_players = self.getTopPlayersWithStats(player_df, game_id, away_team, top_n=6)
            for i in range(6):
                prefix = f'away_p{i+1}_'
                if i < len(away_players):
                    player = away_players.iloc[i]
                    game_features[f'{prefix}ppg'] = player['ppg_rolling']
                    game_features[f'{prefix}fg_pct'] = player['fg_pct_rolling']
                    game_features[f'{prefix}mpg'] = player['mpg_rolling']
                    game_features[f'{prefix}apg'] = player['apg_rolling']
                    game_features[f'{prefix}rpg'] = player['rpg_rolling']
                    game_features[f'{prefix}blk'] = player['blk_rolling']
                    game_features[f'{prefix}stl'] = player['stl_rolling']
                    game_features[f'{prefix}tov'] = player['tov_rolling']
                    game_features[f'{prefix}plus_minus'] = player['plus_minus_rolling']
                else:
                    print(f"No player data available for {away_team} in game {game_id}")
            
            player_features.append(game_features)
        
        return pd.DataFrame(player_features)
    
    def createGameMatchupData(self, season):
        game_file = self.game_data_dir / f'{season}_game_stats.csv'
        if not game_file.exists():
            raise FileNotFoundError(f"Game data file not found: {game_file}")
        
        games_df = pd.read_csv(game_file)
        games_df['GAME_DATE'] = pd.to_datetime(games_df['GAME_DATE'])
        
        print(f"Calculating L10 stats for {season}...")
        l10_stats = self.calculateTeamL10Stats(season)
        
        print(f"Calculating rest days for {season}...")
        team_rest = self.calculateRestDays(games_df[['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID']].copy())
        
        team_features = l10_stats.merge(
            team_rest[['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID', 'rest_days', 'is_back_to_back']],
            on=['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID'],
            how='left'
        )

        games_df.dropna(subset=['MATCHUP'], inplace=True)
        
        games_df['is_home'] = ~games_df['MATCHUP'].str.contains('@')
        
        home_games = games_df[games_df['is_home']].copy()
        away_games = games_df[~games_df['is_home']].copy()
        
        # This automatically drops the first 10 games for each team
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
        matchup_data = matchup_data.merge(player_features, left_on='GAME_ID', right_on='game_id', how='left')
        
        print(f"Calculating aggregated player features for {season}...")
        
        home_star_ppg = matchup_data['home_p1_ppg']
        home_top3_avg_ppg = matchup_data[['home_p1_ppg', 'home_p2_ppg', 'home_p3_ppg']].mean(axis=1)
        home_top5_avg_ppg = matchup_data[['home_p1_ppg', 'home_p2_ppg', 'home_p3_ppg', 'home_p4_ppg', 'home_p5_ppg']].mean(axis=1)
        home_top6_avg_ppg = matchup_data[['home_p1_ppg', 'home_p2_ppg', 'home_p3_ppg', 'home_p4_ppg', 'home_p5_ppg', 'home_p6_ppg']].mean(axis=1)
        
        home_top5_avg_mpg = matchup_data[['home_p1_mpg', 'home_p2_mpg', 'home_p3_mpg', 'home_p4_mpg', 'home_p5_mpg']].mean(axis=1)
        home_top6_avg_mpg = matchup_data[['home_p1_mpg', 'home_p2_mpg', 'home_p3_mpg', 'home_p4_mpg', 'home_p5_mpg', 'home_p6_mpg']].mean(axis=1)
        
        home_star_apg = matchup_data['home_p1_apg']
        home_top3_avg_apg = matchup_data[['home_p1_apg', 'home_p2_apg', 'home_p3_apg']].mean(axis=1)
        home_top5_avg_apg = matchup_data[['home_p1_apg', 'home_p2_apg', 'home_p3_apg', 'home_p4_apg', 'home_p5_apg']].mean(axis=1)
        home_top6_avg_apg = matchup_data[['home_p1_apg', 'home_p2_apg', 'home_p3_apg', 'home_p4_apg', 'home_p5_apg', 'home_p6_apg']].mean(axis=1)

        home_star_rpg = matchup_data['home_p1_rpg']
        home_top3_avg_rpg = matchup_data[['home_p1_rpg', 'home_p2_rpg', 'home_p3_rpg']].mean(axis=1)
        home_top5_avg_rpg = matchup_data[['home_p1_rpg', 'home_p2_rpg', 'home_p3_rpg', 'home_p4_rpg', 'home_p5_rpg']].mean(axis=1)
        home_top6_avg_rpg = matchup_data[['home_p1_rpg', 'home_p2_rpg', 'home_p3_rpg', 'home_p4_rpg', 'home_p5_rpg', 'home_p6_rpg']].mean(axis=1)
        
        home_star_blk = matchup_data['home_p1_blk']
        home_top3_avg_blk = matchup_data[['home_p1_blk', 'home_p2_blk', 'home_p3_blk']].mean(axis=1)
        home_top5_avg_blk = matchup_data[['home_p1_blk', 'home_p2_blk', 'home_p3_blk', 'home_p4_blk', 'home_p5_blk']].mean(axis=1)
        home_top6_avg_blk = matchup_data[['home_p1_blk', 'home_p2_blk', 'home_p3_blk', 'home_p4_blk', 'home_p5_blk', 'home_p6_blk']].mean(axis=1)
        
        home_star_stl = matchup_data['home_p1_stl']
        home_top3_avg_stl = matchup_data[['home_p1_stl', 'home_p2_stl', 'home_p3_stl']].mean(axis=1)
        home_top5_avg_stl = matchup_data[['home_p1_stl', 'home_p2_stl', 'home_p3_stl', 'home_p4_stl', 'home_p5_stl']].mean(axis=1)
        home_top6_avg_stl = matchup_data[['home_p1_stl', 'home_p2_stl', 'home_p3_stl', 'home_p4_stl', 'home_p5_stl', 'home_p6_stl']].mean(axis=1)
        
        home_star_tov = matchup_data['home_p1_tov']
        home_top3_avg_tov = matchup_data[['home_p1_tov', 'home_p2_tov', 'home_p3_tov']].mean(axis=1)
        home_top5_avg_tov = matchup_data[['home_p1_tov', 'home_p2_tov', 'home_p3_tov', 'home_p4_tov', 'home_p5_tov']].mean(axis=1)
        home_top6_avg_tov = matchup_data[['home_p1_tov', 'home_p2_tov', 'home_p3_tov', 'home_p4_tov', 'home_p5_tov', 'home_p6_tov']].mean(axis=1)
        
        home_top6_total_plusminus = matchup_data[['home_p1_plus_minus', 'home_p2_plus_minus', 'home_p3_plus_minus', 'home_p4_plus_minus', 'home_p5_plus_minus', 'home_p6_plus_minus']].sum(axis=1)
        home_depth_variance = matchup_data[['home_p1_ppg', 'home_p2_ppg', 'home_p3_ppg', 'home_p4_ppg', 'home_p5_ppg', 'home_p6_ppg']].std(axis=1)
        
        away_star_ppg = matchup_data['away_p1_ppg']
        away_top3_avg_ppg = matchup_data[['away_p1_ppg', 'away_p2_ppg', 'away_p3_ppg']].mean(axis=1)
        away_top5_avg_ppg = matchup_data[['away_p1_ppg', 'away_p2_ppg', 'away_p3_ppg', 'away_p4_ppg', 'away_p5_ppg']].mean(axis=1)
        away_top6_avg_ppg = matchup_data[['away_p1_ppg', 'away_p2_ppg', 'away_p3_ppg', 'away_p4_ppg', 'away_p5_ppg', 'away_p6_ppg']].mean(axis=1)
        
        away_top5_avg_mpg = matchup_data[['away_p1_mpg', 'away_p2_mpg', 'away_p3_mpg', 'away_p4_mpg', 'away_p5_mpg']].mean(axis=1)
        away_top6_avg_mpg = matchup_data[['away_p1_mpg', 'away_p2_mpg', 'away_p3_mpg', 'away_p4_mpg', 'away_p5_mpg', 'away_p6_mpg']].mean(axis=1)
        
        away_star_apg = matchup_data['away_p1_apg']
        away_top3_avg_apg = matchup_data[['away_p1_apg', 'away_p2_apg', 'away_p3_apg']].mean(axis=1)
        away_top5_avg_apg = matchup_data[['away_p1_apg', 'away_p2_apg', 'away_p3_apg', 'away_p4_apg', 'away_p5_apg']].mean(axis=1)
        away_top6_avg_apg = matchup_data[['away_p1_apg', 'away_p2_apg', 'away_p3_apg', 'away_p4_apg', 'away_p5_apg', 'away_p6_apg']].mean(axis=1)
        
        away_star_rpg = matchup_data['away_p1_rpg']
        away_top3_avg_rpg = matchup_data[['away_p1_rpg', 'away_p2_rpg', 'away_p3_rpg']].mean(axis=1)
        away_top5_avg_rpg = matchup_data[['away_p1_rpg', 'away_p2_rpg', 'away_p3_rpg', 'away_p4_rpg', 'away_p5_rpg']].mean(axis=1)
        away_top6_avg_rpg = matchup_data[['away_p1_rpg', 'away_p2_rpg', 'away_p3_rpg', 'away_p4_rpg', 'away_p5_rpg', 'away_p6_rpg']].mean(axis=1)

        away_star_blk = matchup_data['away_p1_blk']
        away_top3_avg_blk = matchup_data[['away_p1_blk', 'away_p2_blk', 'away_p3_blk']].mean(axis=1)
        away_top5_avg_blk = matchup_data[['away_p1_blk', 'away_p2_blk', 'away_p3_blk', 'away_p4_blk', 'away_p5_blk']].mean(axis=1)
        away_top6_avg_blk = matchup_data[['away_p1_blk', 'away_p2_blk', 'away_p3_blk', 'away_p4_blk', 'away_p5_blk', 'away_p6_blk']].mean(axis=1)
        
        away_star_stl = matchup_data['away_p1_stl']
        away_top3_avg_stl = matchup_data[['away_p1_stl', 'away_p2_stl', 'away_p3_stl']].mean(axis=1)
        away_top5_avg_stl = matchup_data[['away_p1_stl', 'away_p2_stl', 'away_p3_stl', 'away_p4_stl', 'away_p5_stl']].mean(axis=1)
        away_top6_avg_stl = matchup_data[['away_p1_stl', 'away_p2_stl', 'away_p3_stl', 'away_p4_stl', 'away_p5_stl', 'away_p6_stl']].mean(axis=1)
        
        away_star_tov = matchup_data['away_p1_tov']
        away_top3_avg_tov = matchup_data[['away_p1_tov', 'away_p2_tov', 'away_p3_tov']].mean(axis=1)
        away_top5_avg_tov = matchup_data[['away_p1_tov', 'away_p2_tov', 'away_p3_tov', 'away_p4_tov', 'away_p5_tov']].mean(axis=1)
        away_top6_avg_tov = matchup_data[['away_p1_tov', 'away_p2_tov', 'away_p3_tov', 'away_p4_tov', 'away_p5_tov', 'away_p6_tov']].mean(axis=1)
        
        away_top6_total_plusminus = matchup_data[['away_p1_plus_minus', 'away_p2_plus_minus', 'away_p3_plus_minus', 'away_p4_plus_minus', 'away_p5_plus_minus', 'away_p6_plus_minus']].sum(axis=1)
        away_depth_variance = matchup_data[['away_p1_ppg', 'away_p2_ppg', 'away_p3_ppg', 'away_p4_ppg', 'away_p5_ppg', 'away_p6_ppg']].std(axis=1)
        
        training_data = pd.DataFrame({
            'game_id': matchup_data['GAME_ID'],
            'date': matchup_data['GAME_DATE_home'],
            'season': season,
            
            # Team identifiers
            'home_team': matchup_data['TEAM_ABBREVIATION_home'],
            'away_team': matchup_data['TEAM_ABBREVIATION_away'],
            
            # Game outcome
            'home_score': matchup_data['PTS_home'],
            'away_score': matchup_data['PTS_away'],
            'total_score': matchup_data['PTS_home'] + matchup_data['PTS_away'],
            'point_diff': matchup_data['PLUS_MINUS_home'],
            'home_won': (matchup_data['WL_home'] == 'W').astype(int),
            
            # Team Performance
            'home_wins_l10': matchup_data['wins_l10_home'],
            'away_wins_l10': matchup_data['wins_l10_away'],
            'home_total_l10': matchup_data['total_l10_home'],
            'away_total_l10': matchup_data['total_l10_away'],
            'home_plus_minus_l10': matchup_data['plus_minus_l10_home'],
            'away_plus_minus_l10': matchup_data['plus_minus_l10_away'],
            'plus_minus_diff': matchup_data['plus_minus_l10_home'] - matchup_data['plus_minus_l10_away'],
            'home_ppg_l10': matchup_data['ppg_l10_home'],
            'away_ppg_l10': matchup_data['ppg_l10_away'],
            'ppg_diff': matchup_data['ppg_l10_home'] - matchup_data['ppg_l10_away'],
            'home_opp_ppg_l10': matchup_data['opp_ppg_l10_home'],
            'away_opp_ppg_l10': matchup_data['opp_ppg_l10_away'],
            'opp_ppg_diff': matchup_data['opp_ppg_l10_home'] - matchup_data['opp_ppg_l10_away'],
            'home_apg_l10': matchup_data['ast_l10_home'],
            'away_apg_l10': matchup_data['ast_l10_away'],
            'home_tov_l10': matchup_data['tov_l10_home'],
            'away_tov_l10': matchup_data['tov_l10_away'],
            'home_rpg_l10': matchup_data['reb_l10_home'],
            'away_rpg_l10': matchup_data['reb_l10_away'],
            'home_blk_l10': matchup_data['blk_l10_home'],
            'away_blk_l10': matchup_data['blk_l10_away'],
            'home_stl_l10': matchup_data['stl_l10_home'],
            'away_stl_l10': matchup_data['stl_l10_away'],
            
            # Game Context
            'home_rest_days': matchup_data['rest_days_home'],
            'away_rest_days': matchup_data['rest_days_away'],
            'rest_days_diff': matchup_data['rest_days_home'] - matchup_data['rest_days_away'],
            'is_back_to_back_home': matchup_data['is_back_to_back_home'],
            'is_back_to_back_away': matchup_data['is_back_to_back_away'],

            # Player Aggregates
            # 'home_star_ppg': home_star_ppg,
            # 'away_star_ppg': away_star_ppg,
            'home_top3_avg_ppg': home_top3_avg_ppg,
            'away_top3_avg_ppg': away_top3_avg_ppg,
            'home_top5_avg_ppg': home_top5_avg_ppg,
            'away_top5_avg_ppg': away_top5_avg_ppg,
            'home_top6_avg_ppg': home_top6_avg_ppg,
            'away_top6_avg_ppg': away_top6_avg_ppg,
            
            'home_top5_avg_mpg': home_top5_avg_mpg,
            'away_top5_avg_mpg': away_top5_avg_mpg,
            'home_top6_avg_mpg': home_top6_avg_mpg,
            'away_top6_avg_mpg': away_top6_avg_mpg,
            
            # 'home_star_apg': home_star_apg,
            # 'away_star_apg': away_star_apg,
            'home_top3_avg_apg': home_top3_avg_apg,
            'away_top3_avg_apg': away_top3_avg_apg,
            'home_top5_avg_apg': home_top5_avg_apg,
            'away_top5_avg_apg': away_top5_avg_apg,
            'home_top6_avg_apg': home_top6_avg_apg,
            'away_top6_avg_apg': away_top6_avg_apg,

            # 'home_star_rpg': home_star_rpg,
            # 'away_star_rpg': away_star_rpg,
            'home_top3_avg_rpg': home_top3_avg_rpg,
            'away_top3_avg_rpg': away_top3_avg_rpg,
            'home_top5_avg_rpg': home_top5_avg_rpg,
            'away_top5_avg_rpg': away_top5_avg_rpg,
            'home_top6_avg_rpg': home_top6_avg_rpg,
            'away_top6_avg_rpg': away_top6_avg_rpg,
            
            # 'home_star_blk': home_star_blk,
            # 'away_star_blk': away_star_blk,
            'home_top3_avg_blk': home_top3_avg_blk,
            'away_top3_avg_blk': away_top3_avg_blk,
            'home_top5_avg_blk': home_top5_avg_blk,
            'away_top5_avg_blk': away_top5_avg_blk,
            'home_top6_avg_blk': home_top6_avg_blk,
            'away_top6_avg_blk': away_top6_avg_blk,
            
            # 'home_star_stl': home_star_stl,
            # 'away_star_stl': away_star_stl,
            'home_top3_avg_stl': home_top3_avg_stl,
            'away_top3_avg_stl': away_top3_avg_stl,
            'home_top5_avg_stl': home_top5_avg_stl,
            'away_top5_avg_stl': away_top5_avg_stl,
            'home_top6_avg_stl': home_top6_avg_stl,
            'away_top6_avg_stl': away_top6_avg_stl,
            
            # 'home_star_tov': home_star_tov,
            # 'away_star_tov': away_star_tov,
            'home_top3_avg_tov': home_top3_avg_tov,
            'away_top3_avg_tov': away_top3_avg_tov,
            'home_top5_avg_tov': home_top5_avg_tov,
            'away_top5_avg_tov': away_top5_avg_tov,
            'home_top6_avg_tov': home_top6_avg_tov,
            'away_top6_avg_tov': away_top6_avg_tov,
            
            'home_top6_total_plusminus': home_top6_total_plusminus,
            'away_top6_total_plusminus': away_top6_total_plusminus,
            
            'home_depth_variance': home_depth_variance,
            'away_depth_variance': away_depth_variance,
            
            # Individual Home Player
            'home_player1_ppg': matchup_data['home_p1_ppg'],
            'home_player1_apg': matchup_data['home_p1_apg'],
            'home_player1_rpg': matchup_data['home_p1_rpg'],
            'home_player1_blk': matchup_data['home_p1_blk'],
            'home_player1_stl': matchup_data['home_p1_stl'],
            'home_player1_tov': matchup_data['home_p1_tov'],
            'home_player2_ppg': matchup_data['home_p2_ppg'],
            'home_player2_apg': matchup_data['home_p2_apg'],
            'home_player2_rpg': matchup_data['home_p2_rpg'],
            'home_player2_blk': matchup_data['home_p2_blk'],
            'home_player2_stl': matchup_data['home_p2_stl'],
            'home_player2_tov': matchup_data['home_p2_tov'],
            'home_player3_ppg': matchup_data['home_p3_ppg'],
            'home_player3_apg': matchup_data['home_p3_apg'],
            'home_player3_rpg': matchup_data['home_p3_rpg'],
            'home_player3_blk': matchup_data['home_p3_blk'],
            'home_player3_stl': matchup_data['home_p3_stl'],
            'home_player3_tov': matchup_data['home_p3_tov'],
            'home_player4_ppg': matchup_data['home_p4_ppg'],
            'home_player4_apg': matchup_data['home_p4_apg'],
            'home_player4_rpg': matchup_data['home_p4_rpg'],
            'home_player4_blk': matchup_data['home_p4_blk'],
            'home_player4_stl': matchup_data['home_p4_stl'],
            'home_player4_tov': matchup_data['home_p4_tov'],
            'home_player5_ppg': matchup_data['home_p5_ppg'],
            'home_player5_apg': matchup_data['home_p5_apg'],
            'home_player5_rpg': matchup_data['home_p5_rpg'],
            'home_player5_blk': matchup_data['home_p5_blk'],
            'home_player5_stl': matchup_data['home_p5_stl'],
            'home_player5_tov': matchup_data['home_p5_tov'],

            # Individual Away Player
            'away_player1_ppg': matchup_data['away_p1_ppg'],
            'away_player1_apg': matchup_data['away_p1_apg'],
            'away_player1_rpg': matchup_data['away_p1_rpg'],
            'away_player1_blk': matchup_data['away_p1_blk'],
            'away_player1_stl': matchup_data['away_p1_stl'],
            'away_player1_tov': matchup_data['away_p1_tov'],
            'away_player2_ppg': matchup_data['away_p2_ppg'],
            'away_player2_apg': matchup_data['away_p2_apg'],
            'away_player2_rpg': matchup_data['away_p2_rpg'],
            'away_player2_blk': matchup_data['away_p2_blk'],
            'away_player2_stl': matchup_data['away_p2_stl'],
            'away_player2_tov': matchup_data['away_p2_tov'],
            'away_player3_ppg': matchup_data['away_p3_ppg'],
            'away_player3_apg': matchup_data['away_p3_apg'],
            'away_player3_rpg': matchup_data['away_p3_rpg'],
            'away_player3_blk': matchup_data['away_p3_blk'],
            'away_player3_stl': matchup_data['away_p3_stl'],
            'away_player3_tov': matchup_data['away_p3_tov'],
            'away_player4_ppg': matchup_data['away_p4_ppg'],
            'away_player4_apg': matchup_data['away_p4_apg'],
            'away_player4_rpg': matchup_data['away_p4_rpg'],
            'away_player4_blk': matchup_data['away_p4_blk'],
            'away_player4_stl': matchup_data['away_p4_stl'],
            'away_player4_tov': matchup_data['away_p4_tov'],
            'away_player5_ppg': matchup_data['away_p5_ppg'],
            'away_player5_apg': matchup_data['away_p5_apg'],
            'away_player5_rpg': matchup_data['away_p5_rpg'],
            'away_player5_blk': matchup_data['away_p5_blk'],
            'away_player5_stl': matchup_data['away_p5_stl'],
            'away_player5_tov': matchup_data['away_p5_tov'],

            # Shooting Efficiency
            'home_fg_pct_l10': matchup_data['fg_pct_l10_home'],
            'away_fg_pct_l10': matchup_data['fg_pct_l10_away'],
            'home_fg3_pct_l10': matchup_data['fg3_pct_l10_home'],
            'away_fg3_pct_l10': matchup_data['fg3_pct_l10_away'],
        })
        
        training_data = training_data.sort_values('date').reset_index(drop=True)
        
        if training_data.empty:
            raise ValueError(f"createGameMatchupData returned empty dataframe for season {season}. This likely means insufficient games (<11 per team) or data corruption.")
 
        return training_data
    
    def createUpcomingMatchupData(self, upcoming_games_file=None):
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
        
        print(f"Calculating L10 stats for {current_season}...")
        l10_stats = self.calculateTeamL10Stats(current_season)
        
        print(f"Calculating rest days for {current_season}...")
        team_rest = self.calculateRestDays(team_df[['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID']].copy())
        
        team_features = l10_stats.merge(
            team_rest[['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID', 'rest_days', 'is_back_to_back']],
            on=['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID'],
            how='left'
        )
        
        latest_team_stats = team_features.sort_values('GAME_DATE').groupby('TEAM_ABBREVIATION').last().reset_index()
        
        matchup_rows = []
        
        for _, game in upcoming_df.iterrows():
            game_id = game['GAME_ID']
            game_date = game['GAME_DATE']
            home_team = game['TEAM_ABB_HOME']
            away_team = game['TEAM_ABB_AWAY']
            
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
                
                # Home team L10 stats
                'wins_l10_home': home_stats['wins_l10'],
                'wins_l10_away': away_stats['wins_l10'],
                'total_l10_home': home_stats['total_l10'],
                'total_l10_away': away_stats['total_l10'],
                'ppg_l10_home': home_stats['ppg_l10'],
                'ppg_l10_away': away_stats['ppg_l10'],
                'opp_ppg_l10_home': home_stats['opp_ppg_l10'],
                'opp_ppg_l10_away': away_stats['opp_ppg_l10'],
                'fg_pct_l10_home': home_stats['fg_pct_l10'],
                'fg_pct_l10_away': away_stats['fg_pct_l10'],
                'fg3_pct_l10_home': home_stats['fg3_pct_l10'],
                'fg3_pct_l10_away': away_stats['fg3_pct_l10'],
                'home_rpg_l10': home_stats['reb_l10'],
                'away_rpg_l10': away_stats['reb_l10'],
                'home_apg_l10': home_stats['ast_l10'],
                'away_apg_l10': away_stats['ast_l10'],
                'blk_l10_home': home_stats['blk_l10'],
                'blk_l10_away': away_stats['blk_l10'],
                'stl_l10_home': home_stats['stl_l10'],
                'stl_l10_away': away_stats['stl_l10'],
                'tov_l10_home': home_stats['tov_l10'],
                'tov_l10_away': away_stats['tov_l10'],
                'plus_minus_l10_home': home_stats['plus_minus_l10'],
                'plus_minus_l10_away': away_stats['plus_minus_l10'],
                
                'rest_days_home': home_rest,
                'rest_days_away': away_rest,
                'is_back_to_back_home': 1 if home_rest == 0 else 0,
                'is_back_to_back_away': 1 if away_rest == 0 else 0,
            }
            
            matchup_rows.append(matchup_row)
        
        matchup_data = pd.DataFrame(matchup_rows)
        
        if matchup_data.empty:
            print("No matchup data created.")
            return pd.DataFrame()
        
        player_features = self.addUpcomingPlayerFeatures(matchup_data, current_season)
        matchup_data = matchup_data.merge(player_features, left_on='GAME_ID', right_on='game_id', how='left')
        
        print(f"Calculating aggregated player features...")
        
        home_star_ppg = matchup_data['home_p1_ppg']
        home_top3_avg_ppg = matchup_data[['home_p1_ppg', 'home_p2_ppg', 'home_p3_ppg']].mean(axis=1)
        home_top5_avg_ppg = matchup_data[['home_p1_ppg', 'home_p2_ppg', 'home_p3_ppg', 'home_p4_ppg', 'home_p5_ppg']].mean(axis=1)
        home_top6_avg_ppg = matchup_data[['home_p1_ppg', 'home_p2_ppg', 'home_p3_ppg', 'home_p4_ppg', 'home_p5_ppg', 'home_p6_ppg']].mean(axis=1)
        
        home_top5_avg_mpg = matchup_data[['home_p1_mpg', 'home_p2_mpg', 'home_p3_mpg', 'home_p4_mpg', 'home_p5_mpg']].mean(axis=1)
        home_top6_avg_mpg = matchup_data[['home_p1_mpg', 'home_p2_mpg', 'home_p3_mpg', 'home_p4_mpg', 'home_p5_mpg', 'home_p6_mpg']].mean(axis=1)
        
        home_star_apg = matchup_data['home_p1_apg']
        home_top3_avg_apg = matchup_data[['home_p1_apg', 'home_p2_apg', 'home_p3_apg']].mean(axis=1)
        home_top5_avg_apg = matchup_data[['home_p1_apg', 'home_p2_apg', 'home_p3_apg', 'home_p4_apg', 'home_p5_apg']].mean(axis=1)
        home_top6_avg_apg = matchup_data[['home_p1_apg', 'home_p2_apg', 'home_p3_apg', 'home_p4_apg', 'home_p5_apg', 'home_p6_apg']].mean(axis=1)

        home_star_rpg = matchup_data['home_p1_rpg']
        home_top3_avg_rpg = matchup_data[['home_p1_rpg', 'home_p2_rpg', 'home_p3_rpg']].mean(axis=1)
        home_top5_avg_rpg = matchup_data[['home_p1_rpg', 'home_p2_rpg', 'home_p3_rpg', 'home_p4_rpg', 'home_p5_rpg']].mean(axis=1)
        home_top6_avg_rpg = matchup_data[['home_p1_rpg', 'home_p2_rpg', 'home_p3_rpg', 'home_p4_rpg', 'home_p5_rpg', 'home_p6_rpg']].mean(axis=1)
        
        home_star_blk = matchup_data['home_p1_blk']
        home_top3_avg_blk = matchup_data[['home_p1_blk', 'home_p2_blk', 'home_p3_blk']].mean(axis=1)
        home_top5_avg_blk = matchup_data[['home_p1_blk', 'home_p2_blk', 'home_p3_blk', 'home_p4_blk', 'home_p5_blk']].mean(axis=1)
        home_top6_avg_blk = matchup_data[['home_p1_blk', 'home_p2_blk', 'home_p3_blk', 'home_p4_blk', 'home_p5_blk', 'home_p6_blk']].mean(axis=1)
        
        home_star_stl = matchup_data['home_p1_stl']
        home_top3_avg_stl = matchup_data[['home_p1_stl', 'home_p2_stl', 'home_p3_stl']].mean(axis=1)
        home_top5_avg_stl = matchup_data[['home_p1_stl', 'home_p2_stl', 'home_p3_stl', 'home_p4_stl', 'home_p5_stl']].mean(axis=1)
        home_top6_avg_stl = matchup_data[['home_p1_stl', 'home_p2_stl', 'home_p3_stl', 'home_p4_stl', 'home_p5_stl', 'home_p6_stl']].mean(axis=1)
        
        home_star_tov = matchup_data['home_p1_tov']
        home_top3_avg_tov = matchup_data[['home_p1_tov', 'home_p2_tov', 'home_p3_tov']].mean(axis=1)
        home_top5_avg_tov = matchup_data[['home_p1_tov', 'home_p2_tov', 'home_p3_tov', 'home_p4_tov', 'home_p5_tov']].mean(axis=1)
        home_top6_avg_tov = matchup_data[['home_p1_tov', 'home_p2_tov', 'home_p3_tov', 'home_p4_tov', 'home_p5_tov', 'home_p6_tov']].mean(axis=1)
        
        home_top6_total_plusminus = matchup_data[['home_p1_plus_minus', 'home_p2_plus_minus', 'home_p3_plus_minus', 'home_p4_plus_minus', 'home_p5_plus_minus', 'home_p6_plus_minus']].sum(axis=1)
        home_depth_variance = matchup_data[['home_p1_ppg', 'home_p2_ppg', 'home_p3_ppg', 'home_p4_ppg', 'home_p5_ppg', 'home_p6_ppg']].std(axis=1)
        
        away_star_ppg = matchup_data['away_p1_ppg']
        away_top3_avg_ppg = matchup_data[['away_p1_ppg', 'away_p2_ppg', 'away_p3_ppg']].mean(axis=1)
        away_top5_avg_ppg = matchup_data[['away_p1_ppg', 'away_p2_ppg', 'away_p3_ppg', 'away_p4_ppg', 'away_p5_ppg']].mean(axis=1)
        away_top6_avg_ppg = matchup_data[['away_p1_ppg', 'away_p2_ppg', 'away_p3_ppg', 'away_p4_ppg', 'away_p5_ppg', 'away_p6_ppg']].mean(axis=1)
        
        away_top5_avg_mpg = matchup_data[['away_p1_mpg', 'away_p2_mpg', 'away_p3_mpg', 'away_p4_mpg', 'away_p5_mpg']].mean(axis=1)
        away_top6_avg_mpg = matchup_data[['away_p1_mpg', 'away_p2_mpg', 'away_p3_mpg', 'away_p4_mpg', 'away_p5_mpg', 'away_p6_mpg']].mean(axis=1)
        
        away_star_apg = matchup_data['away_p1_apg']
        away_top3_avg_apg = matchup_data[['away_p1_apg', 'away_p2_apg', 'away_p3_apg']].mean(axis=1)
        away_top5_avg_apg = matchup_data[['away_p1_apg', 'away_p2_apg', 'away_p3_apg', 'away_p4_apg', 'away_p5_apg']].mean(axis=1)
        away_top6_avg_apg = matchup_data[['away_p1_apg', 'away_p2_apg', 'away_p3_apg', 'away_p4_apg', 'away_p5_apg', 'away_p6_apg']].mean(axis=1)
        
        away_star_rpg = matchup_data['away_p1_rpg']
        away_top3_avg_rpg = matchup_data[['away_p1_rpg', 'away_p2_rpg', 'away_p3_rpg']].mean(axis=1)
        away_top5_avg_rpg = matchup_data[['away_p1_rpg', 'away_p2_rpg', 'away_p3_rpg', 'away_p4_rpg', 'away_p5_rpg']].mean(axis=1)
        away_top6_avg_rpg = matchup_data[['away_p1_rpg', 'away_p2_rpg', 'away_p3_rpg', 'away_p4_rpg', 'away_p5_rpg', 'away_p6_rpg']].mean(axis=1)

        away_star_blk = matchup_data['away_p1_blk']
        away_top3_avg_blk = matchup_data[['away_p1_blk', 'away_p2_blk', 'away_p3_blk']].mean(axis=1)
        away_top5_avg_blk = matchup_data[['away_p1_blk', 'away_p2_blk', 'away_p3_blk', 'away_p4_blk', 'away_p5_blk']].mean(axis=1)
        away_top6_avg_blk = matchup_data[['away_p1_blk', 'away_p2_blk', 'away_p3_blk', 'away_p4_blk', 'away_p5_blk', 'away_p6_blk']].mean(axis=1)
        
        away_star_stl = matchup_data['away_p1_stl']
        away_top3_avg_stl = matchup_data[['away_p1_stl', 'away_p2_stl', 'away_p3_stl']].mean(axis=1)
        away_top5_avg_stl = matchup_data[['away_p1_stl', 'away_p2_stl', 'away_p3_stl', 'away_p4_stl', 'away_p5_stl']].mean(axis=1)
        away_top6_avg_stl = matchup_data[['away_p1_stl', 'away_p2_stl', 'away_p3_stl', 'away_p4_stl', 'away_p5_stl', 'away_p6_stl']].mean(axis=1)
        
        away_star_tov = matchup_data['away_p1_tov']
        away_top3_avg_tov = matchup_data[['away_p1_tov', 'away_p2_tov', 'away_p3_tov']].mean(axis=1)
        away_top5_avg_tov = matchup_data[['away_p1_tov', 'away_p2_tov', 'away_p3_tov', 'away_p4_tov', 'away_p5_tov']].mean(axis=1)
        away_top6_avg_tov = matchup_data[['away_p1_tov', 'away_p2_tov', 'away_p3_tov', 'away_p4_tov', 'away_p5_tov', 'away_p6_tov']].mean(axis=1)
        
        away_top6_total_plusminus = matchup_data[['away_p1_plus_minus', 'away_p2_plus_minus', 'away_p3_plus_minus', 'away_p4_plus_minus', 'away_p5_plus_minus', 'away_p6_plus_minus']].sum(axis=1)
        away_depth_variance = matchup_data[['away_p1_ppg', 'away_p2_ppg', 'away_p3_ppg', 'away_p4_ppg', 'away_p5_ppg', 'away_p6_ppg']].std(axis=1)
        
        # Create final prediction features (same structure as training data but without outcome columns)
        prediction_data = pd.DataFrame({
            'game_id': matchup_data['GAME_ID'],
            'date': matchup_data['GAME_DATE_home'],
            'season': current_season,
            
            # Team identifiers
            'home_team': matchup_data['TEAM_ABBREVIATION_home'],
            'away_team': matchup_data['TEAM_ABBREVIATION_away'],
            
            # Team Performance
            'home_wins_l10': matchup_data['wins_l10_home'],
            'away_wins_l10': matchup_data['wins_l10_away'],
            'home_total_l10': matchup_data['total_l10_home'],
            'away_total_l10': matchup_data['total_l10_away'],
            'home_plus_minus_l10': matchup_data['plus_minus_l10_home'],
            'away_plus_minus_l10': matchup_data['plus_minus_l10_away'],
            'plus_minus_diff': matchup_data['plus_minus_l10_home'] - matchup_data['plus_minus_l10_away'],
            'home_ppg_l10': matchup_data['ppg_l10_home'],
            'away_ppg_l10': matchup_data['ppg_l10_away'],
            'ppg_diff': matchup_data['ppg_l10_home'] - matchup_data['ppg_l10_away'],
            'home_opp_ppg_l10': matchup_data['opp_ppg_l10_home'],
            'away_opp_ppg_l10': matchup_data['opp_ppg_l10_away'],
            'opp_ppg_diff': matchup_data['opp_ppg_l10_home'] - matchup_data['opp_ppg_l10_away'],
            # 'home_apg_l10': matchup_data['ast_l10_home'],
            # 'away_apg_l10': matchup_data['ast_l10_away'],
            'home_tov_l10': matchup_data['tov_l10_home'],
            'away_tov_l10': matchup_data['tov_l10_away'],
            'home_blk_l10': matchup_data['blk_l10_home'],
            'away_blk_l10': matchup_data['blk_l10_away'],
            'home_stl_l10': matchup_data['stl_l10_home'],
            'away_stl_l10': matchup_data['stl_l10_away'],
            
            # Game Context
            'home_rest_days': matchup_data['rest_days_home'],
            'away_rest_days': matchup_data['rest_days_away'],
            'rest_days_diff': matchup_data['rest_days_home'] - matchup_data['rest_days_away'],
            'is_back_to_back_home': matchup_data['is_back_to_back_home'],
            'is_back_to_back_away': matchup_data['is_back_to_back_away'],

            # Player Aggregates
            # 'home_star_ppg': home_star_ppg,
            # 'away_star_ppg': away_star_ppg,
            'home_top3_avg_ppg': home_top3_avg_ppg,
            'away_top3_avg_ppg': away_top3_avg_ppg,
            'home_top5_avg_ppg': home_top5_avg_ppg,
            'away_top5_avg_ppg': away_top5_avg_ppg,
            'home_top6_avg_ppg': home_top6_avg_ppg,
            'away_top6_avg_ppg': away_top6_avg_ppg,
            
            'home_top5_avg_mpg': home_top5_avg_mpg,
            'away_top5_avg_mpg': away_top5_avg_mpg,
            'home_top6_avg_mpg': home_top6_avg_mpg,
            'away_top6_avg_mpg': away_top6_avg_mpg,
            
            # 'home_star_apg': home_star_apg,
            # 'away_star_apg': away_star_apg,
            'home_top3_avg_apg': home_top3_avg_apg,
            'away_top3_avg_apg': away_top3_avg_apg,
            'home_top5_avg_apg': home_top5_avg_apg,
            'away_top5_avg_apg': away_top5_avg_apg,
            'home_top6_avg_apg': home_top6_avg_apg,
            'away_top6_avg_apg': away_top6_avg_apg,

            # 'home_star_rpg': home_star_rpg,
            # 'away_star_rpg': away_star_rpg,
            'home_top3_avg_rpg': home_top3_avg_rpg,
            'away_top3_avg_rpg': away_top3_avg_rpg,
            'home_top5_avg_rpg': home_top5_avg_rpg,
            'away_top5_avg_rpg': away_top5_avg_rpg,
            'home_top6_avg_rpg': home_top6_avg_rpg,
            'away_top6_avg_rpg': away_top6_avg_rpg,
            
            # 'home_star_blk': home_star_blk,
            # 'away_star_blk': away_star_blk,
            'home_top3_avg_blk': home_top3_avg_blk,
            'away_top3_avg_blk': away_top3_avg_blk,
            'home_top5_avg_blk': home_top5_avg_blk,
            'away_top5_avg_blk': away_top5_avg_blk,
            'home_top6_avg_blk': home_top6_avg_blk,
            'away_top6_avg_blk': away_top6_avg_blk,
            
            # 'home_star_stl': home_star_stl,
            # 'away_star_stl': away_star_stl,
            'home_top3_avg_stl': home_top3_avg_stl,
            'away_top3_avg_stl': away_top3_avg_stl,
            'home_top5_avg_stl': home_top5_avg_stl,
            'away_top5_avg_stl': away_top5_avg_stl,
            'home_top6_avg_stl': home_top6_avg_stl,
            'away_top6_avg_stl': away_top6_avg_stl,
            
            # 'home_star_tov': home_star_tov,
            # 'away_star_tov': away_star_tov,
            'home_top3_avg_tov': home_top3_avg_tov,
            'away_top3_avg_tov': away_top3_avg_tov,
            'home_top5_avg_tov': home_top5_avg_tov,
            'away_top5_avg_tov': away_top5_avg_tov,
            'home_top6_avg_tov': home_top6_avg_tov,
            'away_top6_avg_tov': away_top6_avg_tov,
            
            'home_top6_total_plusminus': home_top6_total_plusminus,
            'away_top6_total_plusminus': away_top6_total_plusminus,
            
            'home_depth_variance': home_depth_variance,
            'away_depth_variance': away_depth_variance,

            # Individual Home Player
            'home_player1_ppg': matchup_data['home_p1_ppg'],
            'home_player1_apg': matchup_data['home_p1_apg'],
            'home_player1_rpg': matchup_data['home_p1_rpg'],
            'home_player1_blk': matchup_data['home_p1_blk'],
            'home_player1_stl': matchup_data['home_p1_stl'],
            'home_player1_tov': matchup_data['home_p1_tov'],
            'home_player2_ppg': matchup_data['home_p2_ppg'],
            'home_player2_apg': matchup_data['home_p2_apg'],
            'home_player2_rpg': matchup_data['home_p2_rpg'],
            'home_player2_blk': matchup_data['home_p2_blk'],
            'home_player2_stl': matchup_data['home_p2_stl'],
            'home_player2_tov': matchup_data['home_p2_tov'],
            'home_player3_ppg': matchup_data['home_p3_ppg'],
            'home_player3_apg': matchup_data['home_p3_apg'],
            'home_player3_rpg': matchup_data['home_p3_rpg'],
            'home_player3_blk': matchup_data['home_p3_blk'],
            'home_player3_stl': matchup_data['home_p3_stl'],
            'home_player3_tov': matchup_data['home_p3_tov'],
            'home_player4_ppg': matchup_data['home_p4_ppg'],
            'home_player4_apg': matchup_data['home_p4_apg'],
            'home_player4_rpg': matchup_data['home_p4_rpg'],
            'home_player4_blk': matchup_data['home_p4_blk'],
            'home_player4_stl': matchup_data['home_p4_stl'],
            'home_player4_tov': matchup_data['home_p4_tov'],
            'home_player5_ppg': matchup_data['home_p5_ppg'],
            'home_player5_apg': matchup_data['home_p5_apg'],
            'home_player5_rpg': matchup_data['home_p5_rpg'],
            'home_player5_blk': matchup_data['home_p5_blk'],
            'home_player5_stl': matchup_data['home_p5_stl'],
            'home_player5_tov': matchup_data['home_p5_tov'],

            # Individual Away Player
            'away_player1_ppg': matchup_data['away_p1_ppg'],
            'away_player1_apg': matchup_data['away_p1_apg'],
            'away_player1_rpg': matchup_data['away_p1_rpg'],
            'away_player1_blk': matchup_data['away_p1_blk'],
            'away_player1_stl': matchup_data['away_p1_stl'],
            'away_player1_tov': matchup_data['away_p1_tov'],
            'away_player2_ppg': matchup_data['away_p2_ppg'],
            'away_player2_apg': matchup_data['away_p2_apg'],
            'away_player2_rpg': matchup_data['away_p2_rpg'],
            'away_player2_blk': matchup_data['away_p2_blk'],
            'away_player2_stl': matchup_data['away_p2_stl'],
            'away_player2_tov': matchup_data['away_p2_tov'],
            'away_player3_ppg': matchup_data['away_p3_ppg'],
            'away_player3_apg': matchup_data['away_p3_apg'],
            'away_player3_rpg': matchup_data['away_p3_rpg'],
            'away_player3_blk': matchup_data['away_p3_blk'],
            'away_player3_stl': matchup_data['away_p3_stl'],
            'away_player3_tov': matchup_data['away_p3_tov'],
            'away_player4_ppg': matchup_data['away_p4_ppg'],
            'away_player4_apg': matchup_data['away_p4_apg'],
            'away_player4_rpg': matchup_data['away_p4_rpg'],
            'away_player4_blk': matchup_data['away_p4_blk'],
            'away_player4_stl': matchup_data['away_p4_stl'],
            'away_player4_tov': matchup_data['away_p4_tov'],
            'away_player5_ppg': matchup_data['away_p5_ppg'],
            'away_player5_apg': matchup_data['away_p5_apg'],
            'away_player5_rpg': matchup_data['away_p5_rpg'],
            'away_player5_blk': matchup_data['away_p5_blk'],
            'away_player5_stl': matchup_data['away_p5_stl'],
            'away_player5_tov': matchup_data['away_p5_tov'],
            
            # Shooting Efficiency
            'home_fg_pct_l10': matchup_data['fg_pct_l10_home'],
            'away_fg_pct_l10': matchup_data['fg_pct_l10_away'],
            'home_fg3_pct_l10': matchup_data['fg3_pct_l10_home'],
            'away_fg3_pct_l10': matchup_data['fg3_pct_l10_away'],
        })
        
        if prediction_data.empty:
            if team_df.groupby('TEAM_ABBREVIATION').size().max() < 11:
                raise ValueError(f"Current season {current_season} has insufficient games (need 11+ per team) to generate predictions")
            raise ValueError(f"createUpcomingMatchupData returned empty dataframe. Data may be corrupted or no upcoming games found.")
        
        feature_cols = ['home_wins_l10', 'away_wins_l10', 'home_opp_ppg_l10', 'away_opp_ppg_l10']
        if (prediction_data[feature_cols] == 0).all().all():
            raise ValueError(f"createUpcomingMatchupData returned all-zero features. Data may be corrupted.")
        
        print(f"Created prediction data for {len(prediction_data)} upcoming games")
        return prediction_data
    
    def getCurrentSeason(self):
        today = datetime.now()
        year = today.year
        month = today.month
        
        if month < 7:
            return f"{year-1}-{str(year)[-2:]}"
        else:
            return f"{year}-{str(year+1)[-2:]}"
    
    def addUpcomingPlayerFeatures(self, matchup_data, season, debug=False):
        print(f"Adding player features for upcoming games...")
        print(f"Precomputing player rolling averages...")
        
        player_df = self.precomputePlayerRollingAverages(season)
        
        if player_df.empty:
            raise ValueError(f"No player data found for {season}. Cannot generate predictions without player data.")
        
        latest_player_stats = player_df.sort_values('GAME_DATE').groupby('PLAYER_ID').last().reset_index()
        
        # Get injured players (OUT/DOUBTFUL only - removed from selection)
        # injured_players = self.injury_data.getInjuredPlayers()
        # if injured_players:
        #     print(f"Found {len(injured_players)} OUT/DOUBTFUL players to exclude from top player selection")
        
        # Get all questionable players (kept in selection but stats weighted at 50%)
        # questionable_weight = self.injury_data.INJURY_WEIGHTS.get('QUESTIONABLE', 0.5)
        
        # if debug:
        #     print("\n" + "="*80)
        #     print("DEBUG: INJURY DATA LOADED")
        #     print("="*80)
            # Show injured player IDs
            # print(f"Injured player IDs: {sorted(injured_players) if injured_players else 'None'}")
        
        # if verify_injury_filtering:
        #     print("\n" + "="*80)
        #     print("INJURY FILTERING VERIFICATION MODE ENABLED")
        #     print("="*80)
        
        player_features = []
        
        for idx, row in tqdm(matchup_data.iterrows(), total=len(matchup_data)):
            game_id = row['GAME_ID']
            home_team = row['TEAM_ABBREVIATION_home']
            away_team = row['TEAM_ABBREVIATION_away']
            
            game_features = {'game_id': game_id}
            
            # Add injury impact features
            # injury_impact = self.injury_data.getInjuryImpactForGame(home_team, away_team, latest_player_stats)
            # game_features.update(injury_impact)
            
            # Home team: Get top 6 healthy players by minutes
            home_players = latest_player_stats[latest_player_stats['TEAM_ABBREVIATION'] == home_team].copy()
            
            # if debug:
            #     print(f"\n{'='*80}")
            #     print(f"DEBUG: {home_team} @ {away_team} - PLAYER SELECTION")
            #     print(f"{'='*80}")
            #     print(f"\n{home_team} (HOME) - All players before filtering: {len(home_players)}")
            #     if 'PLAYER_NAME' in home_players.columns:
            #         top_by_ppg = home_players.nlargest(8, 'ppg_rolling')[['PLAYER_ID', 'PLAYER_NAME', 'ppg_rolling', 'mpg_rolling']]
            #         print(f"  Top 8 by PPG (before injury filter):")
                    # for _, p in top_by_ppg.iterrows():
                    #     is_injured = p['PLAYER_ID'] in injured_players if injured_players else False
                    #     status = " [INJURED]" if is_injured else ""
                    #     print(f"    {p['PLAYER_NAME']}: {p['ppg_rolling']:.1f} PPG, {p['mpg_rolling']:.1f} MPG{status}")
            
            # Filter out injured players
            # if injured_players:
            #     original_count = len(home_players)
            #     injured_in_team = home_players[home_players['PLAYER_ID'].isin(injured_players)]
                
            #     if not injured_in_team.empty:
            #         if debug or verify_injury_filtering:
            #             print(f"\n  {home_team} (Home) - Dropping {len(injured_in_team)} injured player(s):")
            #             for _, player in injured_in_team.iterrows():
            #                 name = player.get('PLAYER_NAME', f"ID:{player['PLAYER_ID']}")
            #                 print(f"    - {name}: {player['ppg_rolling']:.1f} PPG, {player['mpg_rolling']:.1f} MPG")
                
            #     home_players = home_players[~home_players['PLAYER_ID'].isin(injured_players)]
                
            #     if (debug or verify_injury_filtering) and len(injured_in_team) > 0:
            #         print(f"    Players remaining: {len(home_players)} (was {original_count})")
            
            home_players = home_players.sort_values('mpg_rolling', ascending=False).head(6)
            
            # Get questionable players for this team
            # home_questionable = self.injury_data.getQuestionablePlayersByTeam(home_team)
            
            if debug:
                print(f"\n  {home_team} - FINAL TOP 6 (sent to model):")
                for i, (_, p) in enumerate(home_players.iterrows()):
                    name = p.get('PLAYER_NAME', f"ID:{p['PLAYER_ID']}")
                    is_questionable = p['PLAYER_ID'] in home_questionable
                    q_tag = f" [Q - {questionable_weight:.0%} weight]" if is_questionable else ""
                    print(f"    P{i+1}: {name}: {p['ppg_rolling']:.1f} PPG, {p['mpg_rolling']:.1f} MPG{q_tag}")
            
            for i in range(6):
                prefix = f'home_p{i+1}_'
                if i < len(home_players):
                    player = home_players.iloc[i]
                    # Apply weight for questionable players (50% of their stats)
                    # weight = questionable_weight if player['PLAYER_ID'] in home_questionable else 1.0
                    weight = 1
                    game_features[f'{prefix}ppg'] = player['ppg_rolling'] * weight
                    game_features[f'{prefix}fg_pct'] = player['fg_pct_rolling']  # Don't weight percentages
                    game_features[f'{prefix}mpg'] = player['mpg_rolling'] * weight
                    game_features[f'{prefix}apg'] = player['apg_rolling'] * weight
                    game_features[f'{prefix}rpg'] = player['rpg_rolling'] * weight
                    game_features[f'{prefix}blk'] = player['blk_rolling'] * weight
                    game_features[f'{prefix}stl'] = player['stl_rolling'] * weight
                    game_features[f'{prefix}tov'] = player['tov_rolling'] * weight
                    game_features[f'{prefix}plus_minus'] = player['plus_minus_rolling'] * weight
                else:
                    game_features[f'{prefix}ppg'] = 0
                    game_features[f'{prefix}fg_pct'] = 0
                    game_features[f'{prefix}mpg'] = 0
                    game_features[f'{prefix}apg'] = 0
                    game_features[f'{prefix}rpg'] = 0
                    game_features[f'{prefix}blk'] = 0
                    game_features[f'{prefix}stl'] = 0
                    game_features[f'{prefix}tov'] = 0
                    game_features[f'{prefix}plus_minus'] = 0
            
            # Away team: Get top 6 healthy players by minutes
            away_players = latest_player_stats[latest_player_stats['TEAM_ABBREVIATION'] == away_team].copy()
            
            # if debug:
            #     print(f"\n{away_team} (AWAY) - All players before filtering: {len(away_players)}")
            #     if 'PLAYER_NAME' in away_players.columns:
            #         top_by_ppg = away_players.nlargest(8, 'ppg_rolling')[['PLAYER_ID', 'PLAYER_NAME', 'ppg_rolling', 'mpg_rolling']]
                    # print(f"  Top 8 by PPG (before injury filter):")
                    # for _, p in top_by_ppg.iterrows():
                    #     is_injured = p['PLAYER_ID'] in injured_players if injured_players else False
                    #     status = " [INJURED]" if is_injured else ""
                    #     print(f"    {p['PLAYER_NAME']}: {p['ppg_rolling']:.1f} PPG, {p['mpg_rolling']:.1f} MPG{status}")
            
            # Filter out injured players
            # if injured_players:
            #     original_count = len(away_players)
            #     injured_in_team = away_players[away_players['PLAYER_ID'].isin(injured_players)]
                
            #     if not injured_in_team.empty:
            #         if debug or verify_injury_filtering:
            #             print(f"\n  {away_team} (Away) - Dropping {len(injured_in_team)} injured player(s):")
            #             for _, player in injured_in_team.iterrows():
            #                 name = player.get('PLAYER_NAME', f"ID:{player['PLAYER_ID']}")
            #                 print(f"    - {name}: {player['ppg_rolling']:.1f} PPG, {player['mpg_rolling']:.1f} MPG")
                
            #     away_players = away_players[~away_players['PLAYER_ID'].isin(injured_players)]
                
            #     if (debug or verify_injury_filtering) and len(injured_in_team) > 0:
            #         print(f"    Players remaining: {len(away_players)} (was {original_count})")
            
            away_players = away_players.sort_values('mpg_rolling', ascending=False).head(6)
            
            # Get questionable players for this team
            # away_questionable = self.injury_data.getQuestionablePlayersByTeam(away_team)
            
            # if debug:
            #     print(f"\n  {away_team} - FINAL TOP 6 (sent to model):")
            #     for i, (_, p) in enumerate(away_players.iterrows()):
            #         name = p.get('PLAYER_NAME', f"ID:{p['PLAYER_ID']}")
            #         is_questionable = p['PLAYER_ID'] in away_questionable
            #         q_tag = f" [Q - {questionable_weight:.0%} weight]" if is_questionable else ""
            #         print(f"    P{i+1}: {name}: {p['ppg_rolling']:.1f} PPG, {p['mpg_rolling']:.1f} MPG{q_tag}")
            
            for i in range(6):
                prefix = f'away_p{i+1}_'
                if i < len(away_players):
                    player = away_players.iloc[i]
                    # Apply weight for questionable players (50% of their stats)
                    # weight = questionable_weight if player['PLAYER_ID'] in away_questionable else 1.0
                    weight = 1
                    game_features[f'{prefix}ppg'] = player['ppg_rolling'] * weight
                    game_features[f'{prefix}fg_pct'] = player['fg_pct_rolling']  # Don't weight percentages
                    game_features[f'{prefix}mpg'] = player['mpg_rolling'] * weight
                    game_features[f'{prefix}apg'] = player['apg_rolling'] * weight
                    game_features[f'{prefix}rpg'] = player['rpg_rolling'] * weight
                    game_features[f'{prefix}blk'] = player['blk_rolling'] * weight
                    game_features[f'{prefix}stl'] = player['stl_rolling'] * weight
                    game_features[f'{prefix}tov'] = player['tov_rolling'] * weight
                    game_features[f'{prefix}plus_minus'] = player['plus_minus_rolling'] * weight
                else:
                    game_features[f'{prefix}ppg'] = 0
                    game_features[f'{prefix}fg_pct'] = 0
                    game_features[f'{prefix}mpg'] = 0
                    game_features[f'{prefix}apg'] = 0
                    game_features[f'{prefix}rpg'] = 0
                    game_features[f'{prefix}blk'] = 0
                    game_features[f'{prefix}stl'] = 0
                    game_features[f'{prefix}tov'] = 0
                    game_features[f'{prefix}plus_minus'] = 0
            
            player_features.append(game_features)
        
        # if verify_injury_filtering:
        #     print("\n" + "="*80)
        #     print("INJURY FILTERING VERIFICATION COMPLETE")
        #     print("="*80 + "\n")
        
        return pd.DataFrame(player_features)
    
    def prepareAllSeasons(self, seasons=None, output_dir='././data/training_data/basketball/phase1'):
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        current_season = self.getCurrentSeason()

        files = [f.stem.replace('_training_data', '') for f in output_path.glob('separated_seasons/*_training_data.csv')]
        seasons = [f.stem.replace('_game_stats', '') for f in self.game_data_dir.glob('*_game_stats.csv')]
        seasons.sort()
        
        all_training_data = []
        
        for season in seasons:
            if season in files and season != current_season:
                print(f"Skipping {season} as it already exists")
                all_training_data.append(pd.read_csv(output_path / f'separated_seasons/{season}_training_data.csv'))
                continue
            
            print(f"\n{'='*60}")
            print(f"Processing season: {season}")
            print(f"{'='*60}")
            
            try:
                training_data = self.createGameMatchupData(season)
                
                season_file = output_path / f'separated_seasons/{season}_training_data.csv'
                training_data.to_csv(season_file, index=False)
                print(f"Saved {len(training_data)} games to {season_file}")
                
                all_training_data.append(training_data)
                
            except Exception as e:
                print(f"Error processing {season}: {e}")
                continue
        
        if all_training_data:
            master_df = pd.concat(all_training_data, ignore_index=True)
            master_file = output_path / 'all_seasons_training_data.csv'
            master_df.to_csv(master_file, index=False)
            print(f"\n{'='*60}")
            print(f"Master file created: {master_file}")
            print(f"Total games: {len(master_df)}")
            print(f"Seasons: {', '.join(seasons)}")
            # print(f"Date range: {master_df['date'].min()} to {master_df['date'].max()}")
            print(f"{'='*60}")
            
            return master_df
        else:
            print("No training data generated.")
            return None