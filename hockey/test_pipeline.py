"""
Test script for hockey data pipeline
Demonstrates the usage of all hockey data pipeline components
"""

from data_pipeline.hockey_data import HockeyData
from data_pipeline.injury_data import HockeyInjuryData
from data_pipeline.odd_scraping import HockeyOddScraping
from data_pipeline.live_data_updater import HockeyLiveDataUpdater

def test_hockey_data():
    """Test basic hockey data fetching"""
    print("\n" + "="*80)
    print("TESTING HOCKEY DATA MODULE")
    print("="*80)
    
    hockey = HockeyData(data_dir='../data/hockey')
    
    # Test getting upcoming games
    print("\n1. Testing getUpcomingGames()...")
    games = hockey.getUpcomingGames()
    if not games.empty:
        print(f"   ✓ Found {len(games)} games")
    else:
        print("   ℹ No games today")
    
    # Test current season
    print("\n2. Testing getCurrentSeason()...")
    season = hockey.getCurrentSeason()
    print(f"   ✓ Current season: {season}")
    
    return True

def test_injury_data():
    """Test injury data module"""
    print("\n" + "="*80)
    print("TESTING INJURY DATA MODULE")
    print("="*80)
    
    injuries = HockeyInjuryData(data_dir='../data/hockey')
    
    # Test fetching injuries from ESPN
    print("\n1. Testing fetchInjuriesFromESPN()...")
    print("   (This may take a minute...)")
    success = injuries.fetchInjuriesFromESPN()
    if success:
        print("   ✓ Successfully fetched injuries")
    else:
        print("   ℹ No injuries found or error occurred")
    
    # Test getting injury report
    print("\n2. Testing getInjuryReport()...")
    report = injuries.getInjuryReport()
    print(report)
    
    return True

def test_odds_scraping():
    """Test odds scraping module"""
    print("\n" + "="*80)
    print("TESTING ODDS SCRAPING MODULE")
    print("="*80)
    
    odds = HockeyOddScraping(data_dir='../data/hockey/odds_data')
    
    print("\n1. Testing getH2hOdds()...")
    print("   (This will use API credits)")
    try:
        h2h_data = odds.getH2hOdds()
        if h2h_data is not None and not h2h_data.empty:
            print(f"   ✓ Retrieved H2H odds for {len(h2h_data)} entries")
        else:
            print("   ℹ No H2H odds available")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    return True

def test_live_updater():
    """Test live data updater"""
    print("\n" + "="*80)
    print("TESTING LIVE DATA UPDATER MODULE")
    print("="*80)
    
    updater = HockeyLiveDataUpdater(data_dir='../data/hockey')
    
    # Test fetching today's games
    print("\n1. Testing fetchTodaysGames()...")
    games = updater.fetchTodaysGames()
    if not games.empty:
        print(f"   ✓ Found {len(games)} games")
        print("\n   Games:")
        for _, game in games.iterrows():
            print(f"     • {game['AWAY_TEAM']} @ {game['HOME_TEAM']}")
    else:
        print("   ℹ No games today")
    
    # Test injury update
    print("\n2. Testing updateInjuryData()...")
    success = updater.updateInjuryData()
    if success:
        print("   ✓ Injury data updated")
    else:
        print("   ℹ No injury updates")
    
    return True

def run_all_tests():
    """Run all tests"""
    print("\n" + "="*80)
    print("HOCKEY DATA PIPELINE TEST SUITE")
    print("="*80)
    
    tests = [
        ("Hockey Data", test_hockey_data),
        ("Injury Data", test_injury_data),
        ("Odds Scraping", test_odds_scraping),
        ("Live Updater", test_live_updater),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"\n✗ {name} test failed with error: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Print summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    for name, success in results:
        status = "✓ PASSED" if success else "✗ FAILED"
        print(f"{name}: {status}")
    
    print("\n" + "="*80)

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        test_name = sys.argv[1].lower()
        if test_name == "data":
            test_hockey_data()
        elif test_name == "injury":
            test_injury_data()
        elif test_name == "odds":
            test_odds_scraping()
        elif test_name == "updater":
            test_live_updater()
        else:
            print(f"Unknown test: {test_name}")
            print("Available tests: data, injury, odds, updater")
    else:
        # Run all tests
        run_all_tests()
