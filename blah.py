import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

h2h = pd.read_csv('./logs/basketball/betting/archive/h2h_bets.csv')
spread = pd.read_csv('./logs/basketball/betting/archive/spread_bets.csv')

h2h_wl = {
            'ATL': 0, 'BOS': 0, 'CLE': 0, 'NOP': 0, 'CHI': 0, 'DAL': 0, 'DEN': 0, 'GSW': 0, 'HOU': 0, 'LAC': 0,
            'LAL': 0, 'MIA': 0, 'MIL': 0, 'MIN': 0, 'BKN': 0, 'NYK': 0, 'ORL': 0, 'IND': 0, 'PHI': 0, 'PHX': 0,
            'POR': 0, 'SAC': 0, 'SAS': 0, 'OKC': 0, 'TOR': 0, 'UTA': 0, 'MEM': 0, 'WAS': 0, 'DET': 0, 'CHA': 0,
        }

spread_wl = h2h_wl.copy()
total_games = h2h_wl.copy()

RECENT_WINDOW = 5
h2h_recent = {team: [] for team in h2h_wl}
spread_recent = {team: [] for team in h2h_wl}

for i in range(len(h2h)):
    team = h2h.at[i, 'bet_team']
    result = 1 if h2h.at[i, 'result'] == 'W' else -1
    h2h_wl[team] += result
    total_games[team] += 1
    h2h_recent[team].append(result)
    if len(h2h_recent[team]) > RECENT_WINDOW:
        h2h_recent[team].pop(0)

for i in range(len(spread)):
    team = spread.at[i, 'bet_team']
    result = 1 if spread.at[i, 'result'] == 'W' else -1
    spread_wl[team] += result
    total_games[team] += 1
    spread_recent[team].append(result)
    if len(spread_recent[team]) > RECENT_WINDOW:
        spread_recent[team].pop(0)

def calc_recent_weight(recent_list):
    """Calculate weight from recent results. More recent games weighted higher."""
    if not recent_list:
        return 0
    weights = np.linspace(0.5, 1.0, len(recent_list))
    return np.dot(recent_list, weights) / len(recent_list)

h2h_weights = {team: calc_recent_weight(results) for team, results in h2h_recent.items()}
spread_weights = {team: calc_recent_weight(results) for team, results in spread_recent.items()}

h2h_wl_sorted = sorted(h2h_wl.items(), key=lambda x: x[1], reverse=False)
spread_wl_sorted = sorted(spread_wl.items(), key=lambda x: x[1], reverse=False)

print('total', total_games)
print('h2h', h2h_wl_sorted)
print('spread', spread_wl_sorted)

fig, axes = plt.subplots(2, 1, figsize=(14, 10))

teams_h2h = [t[0] for t in h2h_wl_sorted]
values_h2h = [t[1] for t in h2h_wl_sorted]
weights_h2h = [h2h_weights[t] for t, _ in h2h_wl_sorted]
colors_h2h = plt.cm.RdYlGn((np.array(weights_h2h) + 1) / 2)

axes[0].barh(teams_h2h, values_h2h, color=colors_h2h)
axes[0].axvline(x=0, color='black', linewidth=0.5)
axes[0].set_xlabel('W/L Differential')
axes[0].set_title(f'H2H Betting Performance (color = recent {RECENT_WINDOW}-game momentum)')
for i, (team, val) in enumerate(h2h_wl_sorted):
    weight = h2h_weights[team]
    axes[0].annotate(f'{weight:+.2f}', xy=(val, i), ha='left' if val >= 0 else 'right', va='center', fontsize=7)

teams_spread = [t[0] for t in spread_wl_sorted]
values_spread = [t[1] for t in spread_wl_sorted]
weights_spread = [spread_weights[t] for t, _ in spread_wl_sorted]
colors_spread = plt.cm.RdYlGn((np.array(weights_spread) + 1) / 2)

axes[1].barh(teams_spread, values_spread, color=colors_spread)
axes[1].axvline(x=0, color='black', linewidth=0.5)
axes[1].set_xlabel('W/L Differential')
axes[1].set_title(f'Spread Betting Performance (color = recent {RECENT_WINDOW}-game momentum)')
for i, (team, val) in enumerate(spread_wl_sorted):
    weight = spread_weights[team]
    axes[1].annotate(f'{weight:+.2f}', xy=(val, i), ha='left' if val >= 0 else 'right', va='center', fontsize=7)

plt.tight_layout()
plt.savefig('./logs/basketball/betting/archive/betting_performance.png', dpi=150)
plt.show()