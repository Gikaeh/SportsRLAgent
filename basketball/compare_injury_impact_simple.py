import pandas as pd
from pathlib import Path
from datetime import datetime


def get_current_season():
    today = datetime.now()
    year = today.year
    month = today.month
    
    if month < 7:
        return f"{year-1}-{str(year)[-2:]}"
    else:
        return f"{year}-{str(year+1)[-2:]}"


def compare_top_players():
    print("\n" + "="*80)
    print("TOP 5 PLAYER STATS COMPARISON - WITH vs WITHOUT INJURED PLAYERS")
    print("="*80 + "\n")
    
    # Load injury data
    injury_file = Path('./data/basketball/injury_data/current_injuries.csv')
    if not injury_file.exists():
        print("No injury file found")
        return
    
    injury_df = pd.read_csv(injury_file)
    injured_players = set(injury_df[injury_df['status'].isin(['OUT', 'DOUBTFUL', 'QUESTIONABLE'])]['player_id'].values)
    
    # Filter out player_id = 0 (unmatched players)
    injured_players = {pid for pid in injured_players if pid != 0}
    
    if not injured_players:
        print("No injured players found (OUT, DOUBTFUL, or QUESTIONABLE status)")
        return
    
    print(f"Found {len(injured_players)} injured players (OUT, DOUBTFUL, or QUESTIONABLE)\n")
    
    # Load upcoming games
    upcoming_file = Path('./data/basketball/upcoming_games.csv')
    if not upcoming_file.exists():
        print(f"No upcoming games file found")
        return
    
    upcoming_df = pd.read_csv(upcoming_file)
    
    # Load player data
    current_season = get_current_season()
    player_file = Path(f'./data/basketball/player_data/{current_season}_player_stats.csv')
    
    if not player_file.exists():
        print(f"No player data found for {current_season}")
        return
    
    print(f"Loading player data from {current_season}...")
    player_df = pd.read_csv(player_file)
    player_df['GAME_DATE'] = pd.to_datetime(player_df['GAME_DATE'])
    
    # Calculate rolling averages for each player
    print("Calculating rolling averages...")
    player_df = player_df.sort_values(['PLAYER_ID', 'GAME_DATE'])
    
    rolling_stats = []
    for player_id, player_games in player_df.groupby('PLAYER_ID'):
        player_games = player_games.reset_index(drop=True)
        
        player_games['ppg_rolling'] = player_games['PTS'].expanding().mean().shift(1).fillna(0)
        player_games['mpg_rolling'] = player_games['MIN'].expanding().mean().shift(1).fillna(0)
        player_games['apg_rolling'] = player_games['AST'].expanding().mean().shift(1).fillna(0)
        player_games['rpg_rolling'] = player_games['REB'].expanding().mean().shift(1).fillna(0)
        player_games['fg_pct_rolling'] = player_games['FG_PCT'].expanding().mean().shift(1).fillna(0)
        
        rolling_stats.append(player_games)
    
    player_df = pd.concat(rolling_stats, ignore_index=True)
    
    # Get latest stats for each player
    latest_player_stats = player_df.sort_values('GAME_DATE').groupby('PLAYER_ID').last().reset_index()
    
    # Create player name map
    player_name_map = dict(zip(latest_player_stats['PLAYER_ID'], latest_player_stats['PLAYER_NAME']))
    
    print(f"\nProcessing {len(upcoming_df)} upcoming games...\n")
    
    # Process each game
    for idx, game in upcoming_df.iterrows():
        home_team = game['TEAM_ABB_HOME']
        away_team = game['TEAM_ABB_AWAY']
        
        print("="*80)
        print(f"GAME: {away_team} @ {home_team}")
        print("="*80 + "\n")
        
        # Process home team
        print(f"--- {home_team} (HOME) ---\n")
        compare_team_players(latest_player_stats, home_team, injured_players, player_name_map)
        
        print()
        
        # Process away team
        print(f"--- {away_team} (AWAY) ---\n")
        compare_team_players(latest_player_stats, away_team, injured_players, player_name_map)
        
        print("\n")


def compare_team_players(latest_player_stats, team_abbr, injured_players, player_name_map):
    team_players = latest_player_stats[latest_player_stats['TEAM_ABBREVIATION'] == team_abbr].copy()
    
    if team_players.empty:
        print(f"  No player data found for {team_abbr}")
        return
    
    # Sort by minutes and get top 5 WITHOUT filtering
    team_players_sorted = team_players.sort_values('mpg_rolling', ascending=False)
    top5_before = team_players_sorted.head(5).copy()
    
    # Get top 5 WITH filtering (remove injured)
    team_players_healthy = team_players[~team_players['PLAYER_ID'].isin(injured_players)].copy()
    team_players_healthy_sorted = team_players_healthy.sort_values('mpg_rolling', ascending=False)
    top5_after = team_players_healthy_sorted.head(5).copy()
    
    # Check if any top 5 players were injured
    injured_in_top5 = top5_before[top5_before['PLAYER_ID'].isin(injured_players)]
    
    if injured_in_top5.empty:
        print(f"No injured players in top 5 - stats unchanged")
        print_top5_stats(top5_before, player_name_map, "  ")
        return
    
    # Show injured players that were removed
    print(f"{len(injured_in_top5)} INJURED PLAYER(S) REMOVED FROM TOP 5:")
    for _, player in injured_in_top5.iterrows():
        player_name = player_name_map.get(player['PLAYER_ID'], f"ID {player['PLAYER_ID']}")
        print(f"     - {player_name}: {player['ppg_rolling']:.1f} PPG, {player['mpg_rolling']:.1f} MPG")
    
    print()
    
    # Show before stats
    print("TOP 5 BEFORE (with injured):")
    print_top5_stats(top5_before, player_name_map, "    ")
    
    print()
    
    # Show after stats
    print("TOP 5 AFTER (injured removed):")
    print_top5_stats(top5_after, player_name_map, "    ")
    
    # Calculate and show the difference
    print()
    print("IMPACT ON AVERAGES:")
    
    stats_to_compare = [
        ('ppg_rolling', 'PPG'),
        ('mpg_rolling', 'MPG'),
        ('apg_rolling', 'APG'),
        ('rpg_rolling', 'RPG'),
        ('fg_pct_rolling', 'FG%'),
    ]
    
    for stat_col, stat_name in stats_to_compare:
        before_avg = top5_before[stat_col].mean()
        after_avg = top5_after[stat_col].mean()
        diff = after_avg - before_avg
        
        if stat_name == 'FG%':
            print(f"    {stat_name}: {before_avg:.3f} → {after_avg:.3f} ({diff:+.3f})")
        else:
            print(f"    {stat_name}: {before_avg:.1f} → {after_avg:.1f} ({diff:+.1f})")


def print_top5_stats(top5_df, player_name_map, indent=""):
    """Print top 5 player stats in a formatted table."""
    if top5_df.empty:
        print(f"{indent}No players found")
        return
    
    print(f"{indent}{'Player':<25} {'PPG':>6} {'MPG':>6} {'APG':>6} {'RPG':>6} {'FG%':>6}")
    print(f"{indent}{'-'*60}")
    
    for i, (_, player) in enumerate(top5_df.iterrows(), 1):
        player_name = player_name_map.get(player['PLAYER_ID'], f"ID {player['PLAYER_ID']}")
        # Truncate long names
        if len(player_name) > 24:
            player_name = player_name[:21] + "..."
        
        print(f"{indent}{player_name:<25} "
              f"{player['ppg_rolling']:>6.1f} "
              f"{player['mpg_rolling']:>6.1f} "
              f"{player['apg_rolling']:>6.1f} "
              f"{player['rpg_rolling']:>6.1f} "
              f"{player['fg_pct_rolling']:>6.3f}")
    
    # Print averages
    print(f"{indent}{'-'*60}")
    print(f"{indent}{'AVERAGE':<25} "
          f"{top5_df['ppg_rolling'].mean():>6.1f} "
          f"{top5_df['mpg_rolling'].mean():>6.1f} "
          f"{top5_df['apg_rolling'].mean():>6.1f} "
          f"{top5_df['rpg_rolling'].mean():>6.1f} "
          f"{top5_df['fg_pct_rolling'].mean():>6.3f}")


if __name__ == "__main__":
    try:
        compare_top_players()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
