import pandas as pd
from pathlib import Path
from datetime import datetime

class UnifiedBankroll:
    STARTING_BANKROLL = 90.0  # Unified starting bankroll in dollars
    
    # Log directories for all sports
    SPORT_LOG_DIRS = {
        'basketball': './logs/basketball/betting',
        'hockey': './logs/hockey/betting'
    }
    
    BET_LOG_FILES = ['h2h_bets.csv', 'spread_bets.csv', 'total_bets.csv']
    
    @classmethod
    def _getHockeySeason(cls):
        """Get current NHL season string"""
        now = datetime.now()
        if now.month >= 10:
            return f"{now.year}-{now.year + 1}"
        else:
            return f"{now.year - 1}-{now.year}"
    
    @classmethod
    def _getBasketballSeason(cls):
        """Get current NBA season string"""
        now = datetime.now()
        if now.month >= 10:
            return f"{now.year}-{str(now.year + 1)[-2:]}"
        else:
            return f"{now.year - 1}-{str(now.year)[-2:]}"
    
    @classmethod
    def _updateSportBetResults(cls, sport, log_dir, game_data_path):
        """Update bet results for a single sport"""
        if not Path(game_data_path).exists():
            return
        
        game_data = pd.read_csv(game_data_path)
        log_path = Path(log_dir)
        
        for log_file in cls.BET_LOG_FILES:
            file_path = log_path / log_file
            
            if not file_path.exists():
                continue
                
            df = pd.read_csv(file_path)
            modified = False
            
            for idx, row in df.iterrows():
                if pd.notna(row.get('result')) and row.get('result') != '':
                    continue
                    
                game_id = int(row['game_id'])
                
                if str(row['date']).split(' ')[0] == datetime.now().strftime('%Y-%m-%d'):
                    continue
                
                if game_id not in game_data['GAME_ID'].values.astype(int):
                    continue
                
                bet_type = row.get('type', log_file.replace('_bets.csv', ''))
                
                if bet_type == 'h2h':
                    game_data_row = game_data[(game_data['GAME_ID'] == game_id) & (game_data['TEAM_ABBREVIATION'] == row['bet_team'])]
                    if len(game_data_row) > 0:
                        if game_data_row['WL'].values[0] == 'W':
                            df.at[idx, 'result'] = 'W'
                            modified = True
                        elif game_data_row['WL'].values[0] == 'L':
                            df.at[idx, 'result'] = 'L'
                            modified = True
                            
                elif bet_type == 'spread':
                    home_data = game_data[(game_data['GAME_ID'] == game_id) & (game_data['TEAM_ABBREVIATION'] == row['matchup'].split(' ')[2])]
                    away_data = game_data[(game_data['GAME_ID'] == game_id) & (game_data['TEAM_ABBREVIATION'] == row['matchup'].split(' ')[0])]
                    
                    if len(home_data) > 0 and len(away_data) > 0:
                        home_score = home_data['PTS'].values[0]
                        away_score = away_data['PTS'].values[0]
                        
                        if row['bet_side'] == 'home':
                            spread = row['home_spread']
                            home_score += spread
                            if home_score > away_score:
                                df.at[idx, 'result'] = 'W'
                            elif home_score < away_score:
                                df.at[idx, 'result'] = 'L'
                            else:
                                df.at[idx, 'result'] = 'D'
                            modified = True
                        elif row['bet_side'] == 'away':
                            spread = row['away_spread']
                            away_score += spread
                            if away_score > home_score:
                                df.at[idx, 'result'] = 'W'
                            elif away_score < home_score:
                                df.at[idx, 'result'] = 'L'
                            else:
                                df.at[idx, 'result'] = 'D'
                            modified = True
                            
                elif bet_type == 'total':
                    home_data = game_data[(game_data['GAME_ID'] == game_id) & (game_data['TEAM_ABBREVIATION'] == row['matchup'].split(' ')[2])]
                    away_data = game_data[(game_data['GAME_ID'] == game_id) & (game_data['TEAM_ABBREVIATION'] == row['matchup'].split(' ')[0])]
                    
                    if len(home_data) > 0 and len(away_data) > 0:
                        total_score = home_data['PTS'].values[0] + away_data['PTS'].values[0]
                        
                        if str(row['bet_side']).lower() == 'over':
                            if total_score > row['total_line']:
                                df.at[idx, 'result'] = 'W'
                            elif total_score < row['total_line']:
                                df.at[idx, 'result'] = 'L'
                            else:
                                df.at[idx, 'result'] = 'D'
                            modified = True
                        elif str(row['bet_side']).lower() == 'under':
                            if total_score < row['total_line']:
                                df.at[idx, 'result'] = 'W'
                            elif total_score > row['total_line']:
                                df.at[idx, 'result'] = 'L'
                            else:
                                df.at[idx, 'result'] = 'D'
                            modified = True
            
            if modified:
                df.to_csv(file_path, index=False)
    
    @classmethod
    def updateAllBetResults(cls):
        """Update bet results for all sports before calculating bankroll"""
        # Update hockey bet results
        try:
            hockey_season = cls._getHockeySeason()
            hockey_game_data = f'./data/hockey/game_data/{hockey_season}_game_stats.csv'
            cls._updateSportBetResults('hockey', cls.SPORT_LOG_DIRS['hockey'], hockey_game_data)
        except Exception as e:
            print(f"Error updating hockey bet results: {e}")
        
        # Update basketball bet results
        try:
            basketball_season = cls._getBasketballSeason()
            basketball_game_data = f'./data/basketball/game_data/{basketball_season}_game_stats.csv'
            cls._updateSportBetResults('basketball', cls.SPORT_LOG_DIRS['basketball'], basketball_game_data)
        except Exception as e:
            print(f"Error updating basketball bet results: {e}")
    
    @classmethod
    def calculateUnifiedBankroll(cls):
        """Calculate unified bankroll across all sports by summing profits/losses from all bet logs"""
        cls.updateAllBetResults()
        
        bankroll = cls.STARTING_BANKROLL
        
        for sport, log_dir in cls.SPORT_LOG_DIRS.items():
            log_path = Path(log_dir)
            
            for log_file in cls.BET_LOG_FILES:
                file_path = log_path / log_file
                
                if file_path.exists():
                    try:
                        df = pd.read_csv(file_path)
                        
                        for _, row in df.iterrows():
                            if row.get('result') == 'W':
                                bankroll += row.get('potential_profit', 0)
                            elif row.get('result') == 'L':
                                bankroll -= row.get('bet_amount', 0)
                    except Exception as e:
                        print(f"Error reading {file_path}: {e}")
        
        return bankroll
    
    @classmethod
    def getUnifiedBankroll(cls):
        """Get the current unified bankroll"""
        return cls.calculateUnifiedBankroll()
    
    @classmethod
    def displayBankrollBreakdown(cls):
        """Display bankroll breakdown by sport"""
        print("\n" + "="*60)
        print("UNIFIED BANKROLL BREAKDOWN")
        print("="*60)
        print(f"Starting Bankroll: ${cls.STARTING_BANKROLL:,.2f}")
        print("-"*60)
        
        total_profit = 0
        
        for sport, log_dir in cls.SPORT_LOG_DIRS.items():
            log_path = Path(log_dir)
            sport_profit = 0
            sport_wins = 0
            sport_losses = 0
            
            for log_file in cls.BET_LOG_FILES:
                file_path = log_path / log_file
                
                if file_path.exists():
                    try:
                        df = pd.read_csv(file_path)
                        
                        for _, row in df.iterrows():
                            if row.get('result') == 'W':
                                sport_profit += row.get('potential_profit', 0)
                                sport_wins += 1
                            elif row.get('result') == 'L':
                                sport_profit -= row.get('bet_amount', 0)
                                sport_losses += 1
                    except Exception:
                        pass
            
            total_profit += sport_profit
            print(f"{sport.upper()}: ${sport_profit:+,.2f} ({sport_wins}W - {sport_losses}L)")
        
        print("-"*60)
        print(f"Total Profit/Loss: ${total_profit:+,.2f}")
        print(f"Current Bankroll: ${cls.STARTING_BANKROLL + total_profit:,.2f}")
        print("="*60)
        
        return cls.STARTING_BANKROLL + total_profit
