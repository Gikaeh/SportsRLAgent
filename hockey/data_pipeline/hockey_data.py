from nhlpy import NHLClient
import hockey_scraper
import pandas as pd

# client = NHLClient()

# print(client.stats.team_summary(
#     start_season="20232024", 
#     end_season="20232024"
# ))

scraped_data = hockey_scraper.scrape_seasons(
    [2023, 2024], 
    True,  # include shifts
    data_format='Pandas'
)

scraped_data.to_csv(f'test.csv', index=False)