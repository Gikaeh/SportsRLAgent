import requests
import time
import random
from pathlib import Path
from datetime import datetime
from abc import ABC, abstractmethod
from requests.exceptions import ReadTimeout, ConnectionError, Timeout

class BaseDataFetcher(ABC):
    """Base class for sports data fetching with shared retry logic and file tracking."""
    
    def __init__(self, data_dir, max_retries=3, base_delay=2):
        self.data_dir = Path(data_dir)
        self.max_retries = max_retries
        self.base_delay = base_delay
        
        # Ensure directories exist
        (self.data_dir / 'game_data').mkdir(parents=True, exist_ok=True)
        (self.data_dir / 'team_data').mkdir(parents=True, exist_ok=True)
        (self.data_dir / 'player_data').mkdir(parents=True, exist_ok=True)
        
        # Track existing files
        self.game_files = self._getExistingFiles('game_data', '_game_stats')
        self.team_files = self._getExistingFiles('team_data', '_team_stats')
        self.player_files = self._getExistingFiles('player_data', '_player_stats')
    
    def _getExistingFiles(self, subdir, suffix):
        """Get list of existing season files in a subdirectory."""
        return [f.stem.replace(suffix, '') for f in (self.data_dir / subdir).glob(f'*{suffix}.csv')]
    
    def retryApiCall(self, func, *args, **kwargs):
        """Execute a function with exponential backoff retry logic."""
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except (ReadTimeout, ConnectionError, Timeout) as e:
                if attempt < self.max_retries - 1:
                    delay = self.base_delay * (2 ** attempt) + random.uniform(0, 1)
                    print(f"\nAPI timeout/connection error (attempt {attempt + 1}/{self.max_retries})")
                    print(f"Retrying in {delay:.1f} seconds...")
                    time.sleep(delay)
                else:
                    print(f"\nFailed after {self.max_retries} attempts")
                    raise
            except Exception as e:
                print(f"\nUnexpected error: {type(e).__name__}: {e}")
                raise
    
    def makeRequest(self, url, max_retries=None):
        """Make an HTTP GET request with retry logic."""
        max_retries = max_retries or self.max_retries
        
        for attempt in range(max_retries):
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 404:
                    return None
                time.sleep(1)
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"Error after {max_retries} attempts: {e}")
                    return None
                time.sleep(2 ** attempt)
        return None
    
    @abstractmethod
    def getCurrentSeason(self):
        """Get the current season string. Must be implemented by subclass."""
        pass
    
    @abstractmethod
    def getAllSeasonData(self, season=None):
        """Fetch all data for a season or all seasons. Must be implemented by subclass."""
        pass
    
    @abstractmethod
    def getUpcomingGames(self):
        """Fetch upcoming games. Must be implemented by subclass."""
        pass
