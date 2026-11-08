import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from abc import ABC, abstractmethod

class BaseTrainingDataPreparer(ABC):
    def __init__(self, data_dir, sport_name):
        self.data_dir = Path(data_dir)
        self.sport_name = sport_name
        self.team_data_dir = self.data_dir / 'team_data'
        self.game_data_dir = self.data_dir / 'game_data'
        self.player_data_dir = self.data_dir / 'player_data'
        self.cache_dir = self.data_dir / 'cache'
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def calculateRestDays(self, df):
        df = df.sort_values(['TEAM_ABBREVIATION', 'GAME_DATE'])
        df['prev_game_date'] = df.groupby('TEAM_ABBREVIATION')['GAME_DATE'].shift(1)
        df['rest_days'] = (df['GAME_DATE'] - df['prev_game_date']).dt.days - 1
        df['is_back_to_back'] = (df['rest_days'] == 0).astype(int)
        return df
    
    def computeRollingStatsVectorized(self, df, group_col, stat_cols, window=None, min_periods=1):
        df = df.copy()
        
        for source_col, new_col in stat_cols.items():
            if source_col not in df.columns:
                continue
                
            if window is None:
                # Expanding mean, shifted to avoid leakage
                df[new_col] = df.groupby(group_col)[source_col].transform(
                    lambda x: x.expanding(min_periods=min_periods).mean().shift(1)
                ).fillna(0)
            else:
                # Rolling mean, shifted to avoid leakage
                df[new_col] = df.groupby(group_col)[source_col].transform(
                    lambda x: x.rolling(window=window, min_periods=min_periods).mean().shift(1)
                ).fillna(0)
        
        return df
    
    def computeRollingStdVectorized(self, df, group_col, stat_cols, window=10, min_periods=2):
        df = df.copy()
        
        for source_col, new_col in stat_cols.items():
            if source_col not in df.columns:
                continue
            
            df[new_col] = df.groupby(group_col)[source_col].transform(
                lambda x: x.rolling(window=window, min_periods=min_periods).std().shift(1)
            ).fillna(0)
        
        return df
    
    def aggregatePlayerStats(self, df, prefix, stat, top_n_list):
        result = {}
        
        for top_n in top_n_list:
            cols = [f'{prefix}_p{i}_{stat}' for i in range(1, top_n + 1)]
            existing_cols = [c for c in cols if c in df.columns]
            
            if existing_cols:
                result[f'{prefix}_top{top_n}_avg_{stat}'] = df[existing_cols].mean(axis=1)
        
        return result
    
    def aggregatePlayerStatsSum(self, df, prefix, stat, top_n):
        cols = [f'{prefix}_p{i}_{stat}' for i in range(1, top_n + 1)]
        existing_cols = [c for c in cols if c in df.columns]
        
        if existing_cols:
            return df[existing_cols].sum(axis=1)
        return pd.Series(0, index=df.index)
    
    def aggregatePlayerStatsStd(self, df, prefix, stat, top_n):
        cols = [f'{prefix}_p{i}_{stat}' for i in range(1, top_n + 1)]
        existing_cols = [c for c in cols if c in df.columns]
        
        if existing_cols:
            return df[existing_cols].std(axis=1)
        return pd.Series(0, index=df.index)
    
    def getCachedData(self, cache_name, season, source_file=None):
        cache_file = self.cache_dir / f'{season}_{cache_name}.parquet'
        
        if cache_file.exists():
            # If source file provided, check if cache is stale
            if source_file is not None and Path(source_file).exists():
                source_mtime = Path(source_file).stat().st_mtime
                cache_mtime = cache_file.stat().st_mtime
                
                if source_mtime > cache_mtime:
                    print(f"Cache stale for {cache_name} ({season}), source data is newer. Regenerating...")
                    return None
            
            try:
                return pd.read_parquet(cache_file)
            except Exception:
                return None
        return None
    
    def saveCachedData(self, df, cache_name, season):
        cache_file = self.cache_dir / f'{season}_{cache_name}.parquet'
        try:
            df.to_parquet(cache_file, index=False)
        except Exception as e:
            print(f"Warning: Could not save cache: {e}")
    
    def clearCache(self, season=None):
        if season:
            for f in self.cache_dir.glob(f'{season}_*.parquet'):
                f.unlink()
        else:
            for f in self.cache_dir.glob('*.parquet'):
                f.unlink()
    
    @abstractmethod
    def getCurrentSeason(self):
        """Get the current season string. Must be implemented by subclass."""
        pass
    
    @abstractmethod
    def precomputePlayerRollingAverages(self, season):
        """Precompute player rolling averages. Must be implemented by subclass."""
        pass
    
    @abstractmethod
    def createGameMatchupData(self, season):
        """Create game matchup training data. Must be implemented by subclass."""
        pass
    
    @abstractmethod
    def createUpcomingMatchupData(self, upcoming_games_file=None):
        """Create upcoming game prediction data. Must be implemented by subclass."""
        pass
