import pandas as pd
from pathlib import Path
from datetime import datetime

class UnifiedBankroll:
    STARTING_BANKROLL = 80.0  # Unified starting bankroll in dollars
    
    # Log directories for all sports
    SPORT_LOG_DIRS = {
        'basketball': './logs/basketball/betting',
        'hockey': './logs/hockey/betting'
    }
    
    BET_LOG_FILES = ['h2h_bets.csv', 'spread_bets.csv', 'total_bets.csv']
    
    @classmethod
    def calculateUnifiedBankroll(cls):
        """Calculate unified bankroll across all sports by summing profits/losses from all bet logs"""
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
