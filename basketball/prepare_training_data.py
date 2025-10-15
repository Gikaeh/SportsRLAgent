import pandas as pd
from pathlib import Path
from tqdm import tqdm


class NBATrainingDataPreparer:
    def __init__(self, data_dir='./data/basketball'):
        self.data_dir = Path(data_dir)
        self.team_data_dir = self.data_dir / 'team_data'
        self.game_data_dir = self.data_dir / 'game_data'
        self.player_data_dir = self.data_dir / 'player_data'
        # self.season_data_dir = self.data_dir / 'season_data'
        self.season_averages_cache = {}  # Cache for team season averages
        
    def calculateTeamL10Stats(self, season):
        # Load team game logs
        team_file = self.team_data_dir / f'{season}_team_stats.csv'
        if not team_file.exists():
            raise FileNotFoundError(f"Team data file not found: {team_file}")
        
        df = pd.read_csv(team_file)
        df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])
        df = df.sort_values(['TEAM_ABBREVIATION', 'GAME_DATE'])
        
        df['OPP_PTS'] = df['PTS'] - df['PLUS_MINUS']
        
        # Initialize result columns
        l10_stats = []
        
        # Group by team and calculate rolling stats
        for team, team_df in df.groupby('TEAM_ABBREVIATION'):
            team_df = team_df.reset_index(drop=True)
            
            # Calculate rolling 10-game statistics (shifted by 1 to exclude current game)
            # This prevents data leakage by only using previous games
            team_df['wins_l10'] = team_df['WL'].apply(lambda x: 1 if x == 'W' else 0).rolling(window=10, min_periods=1).sum().shift(1)
            team_df['ppg_l10'] = team_df['PTS'].rolling(window=10, min_periods=1).mean().shift(1)
            team_df['opp_ppg_l10'] = team_df['OPP_PTS'].rolling(window=10, min_periods=1).mean().shift(1)
            team_df['fg_pct_l10'] = team_df['FG_PCT'].rolling(window=10, min_periods=1).mean().shift(1)
            team_df['fg3_pct_l10'] = team_df['FG3_PCT'].rolling(window=10, min_periods=1).mean().shift(1)
            # team_df['reb_l10'] = team_df['REB'].rolling(window=10, min_periods=1).mean().shift(1)
            # team_df['ast_l10'] = team_df['AST'].rolling(window=10, min_periods=1).mean().shift(1)
            # team_df['tov_l10'] = team_df['TOV'].rolling(window=10, min_periods=1).mean().shift(1)
            team_df['plus_minus_l10'] = team_df['PLUS_MINUS'].rolling(window=10, min_periods=1).mean().shift(1)
            
            # Calculate net rating (simplified: point differential per game)
            team_df['net_rating_l10'] = team_df['plus_minus_l10']
            
            # Fill NaN values for first game (no previous games available)
            # Use 0 as default for first game statistics
            team_df['wins_l10'] = team_df['wins_l10'].fillna(0)
            team_df['ppg_l10'] = team_df['ppg_l10'].fillna(0)
            team_df['opp_ppg_l10'] = team_df['opp_ppg_l10'].fillna(0)
            team_df['fg_pct_l10'] = team_df['fg_pct_l10'].fillna(0)
            team_df['fg3_pct_l10'] = team_df['fg3_pct_l10'].fillna(0)
            team_df['plus_minus_l10'] = team_df['plus_minus_l10'].fillna(0)
            team_df['net_rating_l10'] = team_df['net_rating_l10'].fillna(0)
            
            # Select relevant columns
            team_l10 = team_df[[
                'TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID',
                'wins_l10', 'ppg_l10', 'opp_ppg_l10', 
                'fg_pct_l10', 'fg3_pct_l10', 
                # 'reb_l10', 'ast_l10', 'tov_l10', 
                'net_rating_l10'
            ]]
            
            l10_stats.append(team_l10)
        
        return pd.concat(l10_stats, ignore_index=True)
    
    def calculateRestDays(self, df):
        df = df.sort_values(['TEAM_ABBREVIATION', 'GAME_DATE'])
        df['prev_game_date'] = df.groupby('TEAM_ABBREVIATION')['GAME_DATE'].shift(1)
        df['rest_days'] = (df['GAME_DATE'] - df['prev_game_date']).dt.days - 1
        df['rest_days'] = df['rest_days'].fillna(3)  # First game of season, assume 3 days rest
        df['is_back_to_back'] = (df['rest_days'] == 0).astype(int)
        return df
    
    
    def precomputePlayerRollingAverages(self, season):
        player_file = self.player_data_dir / f'{season}_player_stats.csv'
        if not player_file.exists():
            return pd.DataFrame()
        
        df = pd.read_csv(player_file)
        df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'])
        df = df.sort_values(['PLAYER_ID', 'GAME_DATE'])
        
        # Calculate rolling averages for each player (shifted to exclude current game)
        rolling_stats = []
        for player_id, player_df in df.groupby('PLAYER_ID'):
            player_df = player_df.reset_index(drop=True)
            
            # Calculate rolling averages (shift by 1 to prevent data leakage)
            player_df['ppg_rolling'] = player_df['PTS'].expanding().mean().shift(1)
            player_df['fg_pct_rolling'] = player_df['FG_PCT'].expanding().mean().shift(1)
            player_df['mpg_rolling'] = player_df['MIN'].expanding().mean().shift(1)
            player_df['plus_minus_rolling'] = player_df['PLUS_MINUS'].expanding().mean().shift(1)
            
            # Fill NaN for first game with 0
            player_df['ppg_rolling'] = player_df['ppg_rolling'].fillna(0)
            player_df['fg_pct_rolling'] = player_df['fg_pct_rolling'].fillna(0)
            player_df['mpg_rolling'] = player_df['mpg_rolling'].fillna(0)
            player_df['plus_minus_rolling'] = player_df['plus_minus_rolling'].fillna(0)
            
            rolling_stats.append(player_df)
        
        return pd.concat(rolling_stats, ignore_index=True)
    
    def getTopPlayersWithStats(self, player_df, game_id, team_abbr, top_n=6):
        """Get top N players for a game with their precomputed rolling averages."""
        # Filter for specific game and team
        game_players = player_df[(player_df['GAME_ID'] == game_id) & 
                                  (player_df['TEAM_ABBREVIATION'] == team_abbr)].copy()
        
        if game_players.empty:
            return pd.DataFrame()
        
        # Sort by minutes played and get top N
        game_players = game_players.sort_values('MIN', ascending=False).head(top_n)
        
        return game_players[['PLAYER_ID', 'ppg_rolling', 'fg_pct_rolling', 
                            'mpg_rolling', 'plus_minus_rolling']]
    
    def addPlayerFeatures(self, matchup_data, season):
        print(f"Adding player features for {season}...")
        print(f"Precomputing player rolling averages...")
        
        # Load and precompute all player rolling averages once
        player_df = self.precomputePlayerRollingAverages(season)
        
        if player_df.empty:
            print(f"No player data found for {season}")
            # Return empty features with zeros
            return self.createEmptyPlayerFeatures(matchup_data)
        
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
                    game_features[f'{prefix}plus_minus'] = player['plus_minus_rolling']
                else:
                    # No player data available
                    game_features[f'{prefix}ppg'] = 0
                    game_features[f'{prefix}fg_pct'] = 0
                    game_features[f'{prefix}mpg'] = 0
                    game_features[f'{prefix}plus_minus'] = 0
            
            # Get top 6 players for away team with precomputed stats
            away_players = self.getTopPlayersWithStats(player_df, game_id, away_team, top_n=6)
            for i in range(6):
                prefix = f'away_p{i+1}_'
                if i < len(away_players):
                    player = away_players.iloc[i]
                    game_features[f'{prefix}ppg'] = player['ppg_rolling']
                    game_features[f'{prefix}fg_pct'] = player['fg_pct_rolling']
                    game_features[f'{prefix}mpg'] = player['mpg_rolling']
                    game_features[f'{prefix}plus_minus'] = player['plus_minus_rolling']
                else:
                    # No player data available
                    game_features[f'{prefix}ppg'] = 0
                    game_features[f'{prefix}fg_pct'] = 0
                    game_features[f'{prefix}mpg'] = 0
                    game_features[f'{prefix}plus_minus'] = 0
            
            player_features.append(game_features)
        
        return pd.DataFrame(player_features)
    
    def createEmptyPlayerFeatures(self, matchup_data):
        features = {'game_id': matchup_data['GAME_ID'].values}
        
        for team in ['home', 'away']:
            for i in range(1, 7):
                prefix = f'{team}_p{i}_'
                features[f'{prefix}ppg'] = 0
                features[f'{prefix}fg_pct'] = 0
                features[f'{prefix}mpg'] = 0
                features[f'{prefix}plus_minus'] = 0
        
        return pd.DataFrame(features)
    
    def createGameMatchupData(self, season):
        # Load game data
        game_file = self.game_data_dir / f'{season}_game_stats.csv'
        if not game_file.exists():
            raise FileNotFoundError(f"Game data file not found: {game_file}")
        
        games_df = pd.read_csv(game_file)
        games_df['GAME_DATE'] = pd.to_datetime(games_df['GAME_DATE'])
        
        # Calculate L10 stats for all teams
        print(f"Calculating L10 stats for {season}...")
        l10_stats = self.calculateTeamL10Stats(season)
        
        # Calculate rest days
        print(f"Calculating rest days for {season}...")
        team_rest = self.calculateRestDays(games_df[['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID']].copy())
        
        # Merge L10 stats with rest days
        team_features = l10_stats.merge(
            team_rest[['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID', 'rest_days', 'is_back_to_back']],
            on=['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID'],
            how='left'
        )
        
        # Identify home and away teams from MATCHUP column
        games_df['is_home'] = ~games_df['MATCHUP'].str.contains('@')
        
        # Split into home and away dataframes
        home_games = games_df[games_df['is_home']].copy()
        away_games = games_df[~games_df['is_home']].copy()
        
        # Merge with team features
        home_features = home_games.merge(
            team_features,
            on=['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID'],
            how='left',
            suffixes=('', '_home')
        )
        
        away_features = away_games.merge(
            team_features,
            on=['TEAM_ABBREVIATION', 'GAME_DATE', 'GAME_ID'],
            how='left',
            suffixes=('', '_away')
        )
        
        # Merge home and away on GAME_ID
        matchup_data = home_features.merge(
            away_features,
            on='GAME_ID',
            suffixes=('_home', '_away')
        )
        
        # Add player features
        player_features = self.addPlayerFeatures(matchup_data, season)
        matchup_data = matchup_data.merge(player_features, left_on='GAME_ID', right_on='game_id', how='left')
        
        # Calculate aggregated player features
        print(f"Calculating aggregated player features for {season}...")
        
        # Home team aggregates
        home_top3_avg_ppg = matchup_data[['home_p1_ppg', 'home_p2_ppg', 'home_p3_ppg']].mean(axis=1)
        home_top5_avg_mpg = matchup_data[['home_p1_mpg', 'home_p2_mpg', 'home_p3_mpg', 'home_p4_mpg', 'home_p5_mpg']].mean(axis=1)
        home_top6_total_plusminus = matchup_data[['home_p1_plus_minus', 'home_p2_plus_minus', 'home_p3_plus_minus', 
                                                    'home_p4_plus_minus', 'home_p5_plus_minus', 'home_p6_plus_minus']].sum(axis=1)
        home_star_ppg = matchup_data['home_p1_ppg']
        home_6thman_quality = matchup_data['home_p6_ppg']
        home_depth_variance = matchup_data[['home_p1_ppg', 'home_p2_ppg', 'home_p3_ppg', 
                                             'home_p4_ppg', 'home_p5_ppg', 'home_p6_ppg']].std(axis=1)
        
        # Away team aggregates
        away_top3_avg_ppg = matchup_data[['away_p1_ppg', 'away_p2_ppg', 'away_p3_ppg']].mean(axis=1)
        away_top5_avg_mpg = matchup_data[['away_p1_mpg', 'away_p2_mpg', 'away_p3_mpg', 'away_p4_mpg', 'away_p5_mpg']].mean(axis=1)
        away_top6_total_plusminus = matchup_data[['away_p1_plus_minus', 'away_p2_plus_minus', 'away_p3_plus_minus',
                                                    'away_p4_plus_minus', 'away_p5_plus_minus', 'away_p6_plus_minus']].sum(axis=1)
        away_star_ppg = matchup_data['away_p1_ppg']
        away_6thman_quality = matchup_data['away_p6_ppg']
        away_depth_variance = matchup_data[['away_p1_ppg', 'away_p2_ppg', 'away_p3_ppg',
                                             'away_p4_ppg', 'away_p5_ppg', 'away_p6_ppg']].std(axis=1)
        
        # Create final training features (28 features as per Phase 1 roadmap)
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
            'home_won': (matchup_data['WL_home'] == 'W').astype(int),
            
            # Team Performance (8 features)
            'home_wins_l10': matchup_data['wins_l10_home'],
            'away_wins_l10': matchup_data['wins_l10_away'],
            'home_net_rating_l10': matchup_data['net_rating_l10_home'],
            'away_net_rating_l10': matchup_data['net_rating_l10_away'],
            'home_ppg_l10': matchup_data['ppg_l10_home'],
            'away_ppg_l10': matchup_data['ppg_l10_away'],
            'home_opp_ppg_l10': matchup_data['opp_ppg_l10_home'],
            'away_opp_ppg_l10': matchup_data['opp_ppg_l10_away'],
            
            # Game Context (4 features)
            'home_rest_days': matchup_data['rest_days_home'],
            'away_rest_days': matchup_data['rest_days_away'],
            'is_back_to_back_home': matchup_data['is_back_to_back_home'],
            'is_back_to_back_away': matchup_data['is_back_to_back_away'],
            
            # Player Aggregates (12 features)
            'home_top3_avg_ppg': home_top3_avg_ppg,
            'away_top3_avg_ppg': away_top3_avg_ppg,
            'home_top5_avg_mpg': home_top5_avg_mpg,
            'away_top5_avg_mpg': away_top5_avg_mpg,
            'home_top6_total_plusminus': home_top6_total_plusminus,
            'away_top6_total_plusminus': away_top6_total_plusminus,
            'home_star_ppg': home_star_ppg,
            'away_star_ppg': away_star_ppg,
            'home_6thman_quality': home_6thman_quality,
            'away_6thman_quality': away_6thman_quality,
            'home_depth_variance': home_depth_variance,
            'away_depth_variance': away_depth_variance,
            
            # Shooting Efficiency (4 features)
            'home_fg_pct_l10': matchup_data['fg_pct_l10_home'],
            'away_fg_pct_l10': matchup_data['fg_pct_l10_away'],
            'home_fg3_pct_l10': matchup_data['fg3_pct_l10_home'],
            'away_fg3_pct_l10': matchup_data['fg3_pct_l10_away'],
        })
        
        # Sort by date
        training_data = training_data.sort_values('date').reset_index(drop=True)
        
        return training_data
    
    def prepareAllSeasons(self, seasons=None, output_dir='./data/training_data/basketball/phase1'):
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        files = [f.stem.replace('_training_data', '') for f in output_path.glob('separated_seasons/*_training_data.csv')]
        seasons = [f.stem.replace('_game_stats', '') for f in self.game_data_dir.glob('*_game_stats.csv')]
        seasons.sort()
        
        all_training_data = []
        
        for season in seasons:
            if season in files:
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
            print(f"  Master file created: {master_file}")
            print(f"  Total games: {len(master_df)}")
            print(f"  Seasons: {', '.join(seasons)}")
            print(f"  Date range: {master_df['date'].min()} to {master_df['date'].max()}")
            print(f"{'='*60}")
            
            return master_df
        else:
            print("No training data generated.")
            return None