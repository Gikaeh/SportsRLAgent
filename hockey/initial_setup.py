"""
Initial setup script for hockey data pipeline
Run this to initialize your hockey data collection
"""

from data_pipeline.hockey_data import HockeyData
from data_pipeline.injury_data import HockeyInjuryData
from data_pipeline.live_data_updater import HockeyLiveDataUpdater
from pathlib import Path

def setup_directories():
    """Create necessary data directories"""
    print("\n" + "="*80)
    print("SETTING UP DIRECTORIES")
    print("="*80)
    
    data_dir = Path('../data/hockey')
    directories = [
        data_dir / 'game_data',
        data_dir / 'player_data',
        data_dir / 'team_data',
        data_dir / 'injury_data',
        data_dir / 'odds_data',
    ]
    
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        print(f"✓ Created: {directory}")
    
    print("\n✅ All directories created successfully!")
    return True

def fetch_current_season():
    """Fetch current season data"""
    print("\n" + "="*80)
    print("FETCHING CURRENT SEASON DATA")
    print("="*80)
    
    hockey = HockeyData(data_dir='../data/hockey')
    current_season = hockey.getCurrentSeason()
    season_year = int(current_season[:4])
    
    print(f"\nCurrent Season: {current_season}")
    print(f"Season Year: {season_year}")
    
    try:
        print("\n1. Fetching game data...")
        hockey.scrape_season_games(season_year)
        
        print("\n2. Fetching player data...")
        print("   (This may take several minutes...)")
        hockey.scrape_season_player_data(season_year)
        
        print("\n3. Fetching team data...")
        hockey.scrape_season_team_data(season_year)
        
        print("\n✅ Current season data fetched successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ Error fetching season data: {e}")
        import traceback
        traceback.print_exc()
        return False

def fetch_injuries():
    """Fetch current injury data"""
    print("\n" + "="*80)
    print("FETCHING INJURY DATA")
    print("="*80)
    
    injuries = HockeyInjuryData(data_dir='../data/hockey')
    
    try:
        print("\n1. Fetching injuries from ESPN...")
        success = injuries.fetchInjuriesFromESPN()
        
        if success:
            print("\n2. Matching player IDs...")
            injuries.matchPlayerIDs()
            
            print("\n3. Generating injury report...")
            print(injuries.getInjuryReport())
            
            print("\n✅ Injury data fetched successfully!")
            return True
        else:
            print("\n⚠️ No injuries found or error occurred")
            return False
            
    except Exception as e:
        print(f"\n❌ Error fetching injuries: {e}")
        import traceback
        traceback.print_exc()
        return False

def get_todays_games():
    """Fetch today's games"""
    print("\n" + "="*80)
    print("FETCHING TODAY'S GAMES")
    print("="*80)
    
    hockey = HockeyData(data_dir='../data/hockey')
    
    try:
        games = hockey.getUpcomingGames()
        
        if not games.empty:
            print(f"\n✅ Found {len(games)} games today:")
            for _, game in games.iterrows():
                print(f"   • {game['AWAY_TEAM']} @ {game['HOME_TEAM']}")
            return True
        else:
            print("\n⚠️ No games scheduled for today")
            return False
            
    except Exception as e:
        print(f"\n❌ Error fetching games: {e}")
        import traceback
        traceback.print_exc()
        return False

def full_setup():
    """Run complete initial setup"""
    print("\n" + "="*80)
    print("🏒 HOCKEY DATA PIPELINE - INITIAL SETUP")
    print("="*80)
    print("\nThis will:")
    print("  1. Create necessary directories")
    print("  2. Fetch current season data (games, players, teams)")
    print("  3. Fetch current injury data")
    print("  4. Fetch today's games")
    print("\n⚠️  This may take 10-15 minutes for player data")
    
    response = input("\nProceed with full setup? (y/n): ")
    if response.lower() != 'y':
        print("\nSetup cancelled.")
        return
    
    results = []
    
    # Step 1: Setup directories
    results.append(("Directories", setup_directories()))
    
    # Step 2: Fetch current season
    results.append(("Current Season", fetch_current_season()))
    
    # Step 3: Fetch injuries
    results.append(("Injuries", fetch_injuries()))
    
    # Step 4: Get today's games
    results.append(("Today's Games", get_todays_games()))
    
    # Print summary
    print("\n" + "="*80)
    print("SETUP SUMMARY")
    print("="*80)
    for name, success in results:
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"{name}: {status}")
    
    print("\n" + "="*80)
    print("🎉 SETUP COMPLETE!")
    print("="*80)
    print("\nNext steps:")
    print("  • Run tests: python test_pipeline.py")
    print("  • Use live updater: from data_pipeline.live_data_updater import HockeyLiveDataUpdater")
    print("  • Check documentation: README.md and QUICK_START.md")

def quick_setup():
    """Quick setup - just directories and today's games"""
    print("\n" + "="*80)
    print("🏒 HOCKEY DATA PIPELINE - QUICK SETUP")
    print("="*80)
    
    setup_directories()
    get_todays_games()
    fetch_injuries()
    
    print("\n" + "="*80)
    print("✅ QUICK SETUP COMPLETE!")
    print("="*80)
    print("\nTo fetch historical data, run:")
    print("  python initial_setup.py --full")

def main():
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--full':
        full_setup()
    elif len(sys.argv) > 1 and sys.argv[1] == '--dirs':
        setup_directories()
    elif len(sys.argv) > 1 and sys.argv[1] == '--season':
        fetch_current_season()
    elif len(sys.argv) > 1 and sys.argv[1] == '--injuries':
        fetch_injuries()
    elif len(sys.argv) > 1 and sys.argv[1] == '--games':
        get_todays_games()
    else:
        print("\n" + "="*80)
        print("🏒 HOCKEY DATA PIPELINE - SETUP OPTIONS")
        print("="*80)
        print("\nUsage:")
        print("  python initial_setup.py              # Quick setup (dirs + today's games)")
        print("  python initial_setup.py --full       # Full setup (includes season data)")
        print("  python initial_setup.py --dirs       # Create directories only")
        print("  python initial_setup.py --season     # Fetch current season data")
        print("  python initial_setup.py --injuries   # Fetch injury data")
        print("  python initial_setup.py --games      # Fetch today's games")
        print("\nRecommended: Start with quick setup, then run --season when ready")
        print("="*80)
        
        response = input("\nRun quick setup now? (y/n): ")
        if response.lower() == 'y':
            quick_setup()

if __name__ == "__main__":
    main()
