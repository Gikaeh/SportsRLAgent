"""
Quick test script for the rewritten hockey_data.py module
Tests the NHL Stats API integration
"""

import sys
sys.path.insert(0, '..')

from data_pipeline.hockey_data import HockeyData
import pandas as pd

def test_basic_functionality():
    """Test basic API connectivity and data fetching"""
    print("\n" + "="*80)
    print("TESTING REWRITTEN HOCKEY DATA MODULE")
    print("="*80)
    
    hockey = HockeyData(data_dir='../data/hockey')
    
    # Test 1: Get current season
    print("\n1. Testing getCurrentSeason()...")
    current_season = hockey.getCurrentSeason()
    print(f"   ✓ Current season: {current_season}")
    
    # Test 2: Get today's games
    print("\n2. Testing getUpcomingGames()...")
    try:
        games = hockey.getUpcomingGames()
        if not games.empty:
            print(f"   ✓ Found {len(games)} games today")
            print("\n   Games:")
            for _, game in games.iterrows():
                print(f"     • {game['AWAY_TEAM']} @ {game['HOME_TEAM']}")
        else:
            print("   ℹ No games scheduled today")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    # Test 3: Fetch a recent season's game data (fast)
    print("\n3. Testing scrape_season_games(2023)...")
    try:
        df = hockey.scrape_season_games(2023)
        if not df.empty:
            print(f"   ✓ Fetched {len(df)} game records")
            print(f"   ✓ Columns: {list(df.columns)}")
            print(f"\n   Sample data:")
            print(df.head(3).to_string(index=False))
        else:
            print("   ✗ No data returned")
    except Exception as e:
        print(f"   ✗ Error: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 4: Fetch team stats (fast)
    print("\n4. Testing scrape_season_team_data(2023)...")
    try:
        df = hockey.scrape_season_team_data(2023)
        if not df.empty:
            print(f"   ✓ Fetched {len(df)} team records")
            print(f"   ✓ Columns: {list(df.columns)}")
            print(f"\n   Sample data:")
            print(df.head(3).to_string(index=False))
        else:
            print("   ✗ No data returned")
    except Exception as e:
        print(f"   ✗ Error: {e}")
        import traceback
        traceback.print_exc()
    
    # Test 5: Get season summary
    print("\n5. Testing get_season_summary(2023)...")
    try:
        summary = hockey.get_season_summary(2023)
        print(f"   ✓ Season: {summary['season']}")
        print(f"   ✓ Games: {summary['games']}")
        print(f"   ✓ Player records: {summary['player_records']}")
        print(f"   ✓ Team records: {summary['team_records']}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    print("\n" + "="*80)
    print("BASIC TESTS COMPLETE")
    print("="*80)
    print("\nNote: Player data scraping is SLOW (requires fetching each game's boxscore)")
    print("To test player data: hockey.scrape_season_player_data(2023)")
    print("This will take 10-30 minutes depending on the season.")

def test_player_data_single_game():
    """Test player data extraction from a single game"""
    print("\n" + "="*80)
    print("TESTING PLAYER DATA EXTRACTION (SINGLE GAME)")
    print("="*80)
    
    hockey = HockeyData(data_dir='../data/hockey')
    
    # Get a recent game
    print("\n1. Fetching recent games...")
    games = hockey.get_season_schedule(2023)
    
    if not games:
        print("   ✗ No games found")
        return
    
    # Find a completed game
    completed_game = None
    for game in games[:50]:  # Check first 50 games
        if game.get('status', {}).get('detailedState') == 'Final':
            completed_game = game
            break
    
    if not completed_game:
        print("   ✗ No completed games found")
        return
    
    game_id = completed_game.get('gamePk')
    print(f"   ✓ Found completed game: {game_id}")
    
    # Fetch game details
    print(f"\n2. Fetching boxscore for game {game_id}...")
    game_url = f"{hockey.stats_api}/game/{game_id}/feed/live"
    game_data = hockey._make_request(game_url)
    
    if not game_data:
        print("   ✗ Could not fetch game data")
        return
    
    print("   ✓ Game data fetched successfully")
    
    # Extract player stats
    boxscore = game_data.get('liveData', {}).get('boxscore', {})
    teams = boxscore.get('teams', {})
    
    player_count = 0
    for side in ['home', 'away']:
        players = teams.get(side, {}).get('players', {})
        player_count += len(players)
    
    print(f"   ✓ Found {player_count} players in game")
    
    # Show sample player
    home_players = teams.get('home', {}).get('players', {})
    if home_players:
        sample_player_key = list(home_players.keys())[0]
        sample_player = home_players[sample_player_key]
        print(f"\n   Sample player data:")
        print(f"     Name: {sample_player.get('person', {}).get('fullName')}")
        print(f"     Position: {sample_player.get('position', {}).get('abbreviation')}")
        stats = sample_player.get('stats', {}).get('skaterStats', {})
        if stats:
            print(f"     Goals: {stats.get('goals', 0)}")
            print(f"     Assists: {stats.get('assists', 0)}")
            print(f"     Shots: {stats.get('shots', 0)}")
    
    print("\n   ✓ Player data extraction working correctly")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--player-test':
        test_player_data_single_game()
    else:
        test_basic_functionality()
        
        print("\n" + "="*80)
        print("To test player data extraction from a single game:")
        print("  python test_hockey_data.py --player-test")
        print("="*80)
