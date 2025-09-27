import json
import pandas as pd
 
with open('output.json', 'r') as f:
    data = json.load(f)
    
print(data[0])
df = pd.json_normalize(
    data,
    record_path=['bookmakers','markets','outcomes'],
    meta=['commence_time', 'home_team', 'away_team', ['bookmakers','key'],['bookmakers', 'markets', 'key']],
    sep='_'
)
print(df)
df.to_csv('output.csv')