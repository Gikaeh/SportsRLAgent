import pandas as pd
import numpy as np
from pathlib import Path
from tqdm import tqdm
from datetime import datetime

class NBATrainingDataPreparer:
    def __init__(self, data_dir='././data/basketball'):
        self.data_dir = Path(data_dir)
        self.team_data_dir = self.data_dir / 'team_data'
        self.game_data_dir = self.data_dir / 'game_data'
        self.player_data_dir = self.data_dir / 'player_data'
        # self.season_data_dir = self.data_dir / 'season_data'
        self.season_averages_cache = {}  

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
        
        l10_stats = []
        
        for team, team_df in df.groupby('TEAM_ABBREVIATION'):
            team_df = team_df.reset_index(drop=True)
            
            team_df['win_flag'] = (team_df['WL'] == 'W').astype(int)
            
            # Using min_periods=1 allows calculation to start, but we'll drop first 10 games later
            team_df['wins_l10'] = team_df['win_flag'].rolling(window=10, min_periods=1).sum().shift(1)
            team_df['total_l10'] = team_df['TOT_PTS'].rolling(window=10, min_periods=1).mean().shift(1)
            team_df['ppg_l10'] = team_df['PTS'].rolling(window=10, min_periods=1).mean().shift(1)
            team_df['opp_ppg_l10'] = team_df['OPP_PTS'].rolling(window=10, min_periods=1).mean().shift(1)
            team_df['fg_pct_l10'] = team_df['FG_PCT'].rolling(window=10, min_periods=1).mean().shift(1)
            team_df['fg3_pct_l10'] = team_df['FG3_PCT'].rolling(window=10, min_periods=1).mean().shift(1)
            team_df['reb_l10'] = team_df['REB'].rolling(window=10, min_periods=1).mean().shift(1)
            team_df['ast_l10'] = team_df['AST'].rolling(window=10, min_periods=1).mean().shift(1)
            team_df['tov_l10'] = team_df['TOV'].rolling(window=10, min_periods=1).mean().shift(1)
            team_df['blk_l10'] = team_df['BLK'].rolling(window=10, min_periods=1).mean().shift(1)
            team_df['stl_l10'] = team_df['STL'].rolling(window=10, min_periods=1).mean().shift(1)
            team_df['plus_minus_l10'] = team_df['PLUS_MINUS'].rolling(window=10, min_periods=1).mean().shift(1)
            
            # After shift(1), game 11 will have stats from games 1-10
            team_df = team_df.iloc[10:].copy()
            
            team_l10 = team_df[['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID', 'wins_l10', 'ppg_l10', 'opp_ppg_l10', 'fg_pct_l10', 'fg3_pct_l10', 'reb_l10', 'ast_l10', 'tov_l10', 'blk_l10', 'stl_l10', 'plus_minus_l10', 'total_l10']]
            
            l10_stats.append(team_l10)
        
        result = pd.concat(l10_stats, ignore_index=True)
        
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
    
    def calculateRestDays(self, df):
        df = df.sort_values(['TEAM_ABBREVIATION', 'GAME_DATE'])
        df['prev_game_date'] = df.groupby('TEAM_ABBREVIATION')['GAME_DATE'].shift(1)
        df['rest_days'] = (df['GAME_DATE'] - df['prev_game_date']).dt.days - 1
        df['is_back_to_back'] = (df['rest_days'] == 0).astype(int)
        
        return df
    
    def precomputePlayerRollingAverages(self, season):
        player_file = self.player_data_dir / f'{season}_player_stats.csv'
        if not player_file.exists():
            return pd.DataFrame()
        
        df = pd.read_csv(player_file)
        
        if df.empty:
            raise ValueError(f"Player data file for {season} is empty: {player_file}")
        
        df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])
        df = df.sort_values(['PLAYER_ID', 'GAME_DATE'])
        
        # Calculate rolling averages for each player (shifted to exclude current game)
        rolling_stats = []
        for player_id, player_df in df.groupby('PLAYER_ID'):
            player_df = player_df.reset_index(drop=True)
            
            player_df['ppg_rolling'] = player_df['PTS'].expanding().mean().shift(1)
            player_df['fg_pct_rolling'] = player_df['FG_PCT'].expanding().mean().shift(1)
            player_df['mpg_rolling'] = player_df['MIN'].expanding().mean().shift(1)
            player_df['apg_rolling'] = player_df['AST'].expanding().mean().shift(1)
            player_df['rpg_rolling'] = player_df['REB'].expanding().mean().shift(1)
            player_df['blk_rolling'] = player_df['BLK'].expanding().mean().shift(1)
            player_df['stl_rolling'] = player_df['STL'].expanding().mean().shift(1)
            player_df['tov_rolling'] = player_df['TOV'].expanding().mean().shift(1)
            player_df['plus_minus_rolling'] = player_df['PLUS_MINUS'].expanding().mean().shift(1)
            
            player_df['ppg_rolling'] = player_df['ppg_rolling'].fillna(0)
            player_df['fg_pct_rolling'] = player_df['fg_pct_rolling'].fillna(0)
            player_df['mpg_rolling'] = player_df['mpg_rolling'].fillna(0)
            player_df['apg_rolling'] = player_df['apg_rolling'].fillna(0)
            player_df['rpg_rolling'] = player_df['rpg_rolling'].fillna(0)
            player_df['blk_rolling'] = player_df['blk_rolling'].fillna(0)
            player_df['stl_rolling'] = player_df['stl_rolling'].fillna(0)
            player_df['tov_rolling'] = player_df['tov_rolling'].fillna(0)
            player_df['plus_minus_rolling'] = player_df['plus_minus_rolling'].fillna(0)
            
            rolling_stats.append(player_df)
        
        result = pd.concat(rolling_stats, ignore_index=True)
        
        if len(result) > 0:
            # Group by player and check if any player has games beyond their first
            player_game_counts = result.groupby('PLAYER_ID').size()
            players_with_multiple_games = player_game_counts[player_game_counts > 1].index
            
            if len(players_with_multiple_games) > 0:
                # For players with multiple games, check if all their non-first-game stats are zero
                multi_game_data = result[result['PLAYER_ID'].isin(players_with_multiple_games)].copy()
                multi_game_data['game_num'] = multi_game_data.groupby('PLAYER_ID').cumcount() + 1
                non_first_games = multi_game_data[multi_game_data['game_num'] > 1]
                
                if len(non_first_games) > 0:
                    stat_cols = ['ppg_rolling', 'mpg_rolling', 'apg_rolling', 'rpg_rolling', 'blk_rolling', 'stl_rolling', 'tov_rolling']
                    # Check if all non-first-game rolling stats are zero
                    if (non_first_games[stat_cols] == 0).all().all():
                        raise ValueError(f"precomputePlayerRollingAverages returned all-zero rolling stats for non-first games in season {season}. Data may be corrupted.")
        
        return result
    
    def getTopPlayersAsOf(self, player_df, game_date, team_abbr, top_n=6):
        """Top players by PRE-GAME rolling mpg as of game_date.

        Leak fix (NOTES.md A1): selection must not depend on who actually
        played this game or their in-game minutes. Uses each player's latest
        row strictly BEFORE the game date — identical semantics to the
        prediction path's latest_player_stats ranking.
        """
        candidates = player_df[
            (player_df['TEAM_ABBREVIATION'] == team_abbr) &
            (player_df['GAME_DATE'] < game_date)
        ]
        if candidates.empty:
            return pd.DataFrame()

        latest = (
            candidates.sort_values(['PLAYER_ID', 'GAME_DATE'])
            .groupby('PLAYER_ID', as_index=False)
            .tail(1)
        )
        latest = latest.sort_values(
            ['mpg_rolling', 'PLAYER_ID'], ascending=[False, True]
        ).head(top_n)

        return latest[['PLAYER_ID', 'ppg_rolling', 'fg_pct_rolling', 'mpg_rolling', 'plus_minus_rolling', 'apg_rolling', 'rpg_rolling', 'blk_rolling', 'stl_rolling', 'tov_rolling']].reset_index(drop=True)

    def addPlayerFeatures(self, matchup_data, season):
        print(f"Adding player features for {season}...")
        print(f"Precomputing player rolling averages...")

        player_df = self.precomputePlayerRollingAverages(season)

        if player_df.empty:
            raise ValueError(f"No player data found for {season}. Cannot add player features without player data.")

        player_features = []

        for idx, row in tqdm(matchup_data.iterrows(), total=len(matchup_data)):
            game_id = row['GAME_ID']
            game_date = pd.to_datetime(row['GAME_DATE_home'])
            home_team = row['TEAM_ABBREVIATION_home']
            away_team = row['TEAM_ABBREVIATION_away']

            game_features = {'game_id': game_id}

            # Get top 6 players for home team as of game date (pre-game only)
            home_players = self.getTopPlayersAsOf(player_df, game_date, home_team, top_n=6)
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
                    game_features[f'{prefix}ppg'] = 0
                    game_features[f'{prefix}fg_pct'] = 0
                    game_features[f'{prefix}mpg'] = 0
                    game_features[f'{prefix}apg'] = 0
                    game_features[f'{prefix}rpg'] = 0
                    game_features[f'{prefix}blk'] = 0
                    game_features[f'{prefix}stl'] = 0
                    game_features[f'{prefix}tov'] = 0
                    game_features[f'{prefix}plus_minus'] = 0

            # Get top 6 players for away team as of game date (pre-game only)
            away_players = self.getTopPlayersAsOf(player_df, game_date, away_team, top_n=6)
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
                # 'home_rpg_l10': home_stats['reb_l10'],
                # 'away_rpg_l10': away_stats['reb_l10'],
                # 'home_apg_l10': home_stats['ast_l10'],
                # 'away_apg_l10': away_stats['ast_l10'],
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
    
    def addUpcomingPlayerFeatures(self, matchup_data, season):
        print(f"Adding player features for upcoming games...")
        print(f"Precomputing player rolling averages...")
        
        player_df = self.precomputePlayerRollingAverages(season)
        
        if player_df.empty:
            raise ValueError(f"No player data found for {season}. Cannot generate predictions without player data.")
        
        latest_player_stats = player_df.sort_values('GAME_DATE').groupby('PLAYER_ID').last().reset_index()
        
        player_features = []
        
        for idx, row in tqdm(matchup_data.iterrows(), total=len(matchup_data)):
            game_id = row['GAME_ID']
            home_team = row['TEAM_ABBREVIATION_home']
            away_team = row['TEAM_ABBREVIATION_away']
            
            game_features = {'game_id': game_id}
            
            home_players = latest_player_stats[latest_player_stats['TEAM_ABBREVIATION'] == home_team].copy()
            home_players = home_players.sort_values('mpg_rolling', ascending=False).head(6)
            
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
                    game_features[f'{prefix}ppg'] = 0
                    game_features[f'{prefix}fg_pct'] = 0
                    game_features[f'{prefix}mpg'] = 0
                    game_features[f'{prefix}apg'] = 0
                    game_features[f'{prefix}rpg'] = 0
                    game_features[f'{prefix}blk'] = 0
                    game_features[f'{prefix}stl'] = 0
                    game_features[f'{prefix}tov'] = 0
                    game_features[f'{prefix}plus_minus'] = 0
            
            away_players = latest_player_stats[latest_player_stats['TEAM_ABBREVIATION'] == away_team].copy()
            away_players = away_players.sort_values('mpg_rolling', ascending=False).head(6)
            
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
        
        return pd.DataFrame(player_features)
    
    def prepareAllSeasons(self, seasons=None, output_dir='././data/training_data/basketball/phase1'):
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / 'separated_seasons').mkdir(parents=True, exist_ok=True)
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