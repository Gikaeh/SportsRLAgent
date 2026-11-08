"""Static venue-city coordinates for travel distance (`team_game_context.travel_km`).

Keyed by `games.venue_city` exactly as ESPN writes it. Covers the 30 NBA home cities (plus
Inglewood for the Clippers' Intuit Dome) and the neutral/alternate sites seen in the raw
scoreboards for 2021-22 onward. A city missing here gives a NULL travel_km, never a guess.
Coordinates are the arena's, to about 1 km.
"""

VENUE_CITIES: dict[str, tuple[float, float]] = {
    # NBA home cities
    "Atlanta": (33.7573, -84.3963),
    "Boston": (42.3662, -71.0621),
    "Brooklyn": (40.6826, -73.9754),
    "Charlotte": (35.2251, -80.8392),
    "Chicago": (41.8807, -87.6742),
    "Cleveland": (41.4965, -81.6882),
    "Dallas": (32.7905, -96.8103),
    "Denver": (39.7487, -105.0077),
    "Detroit": (42.3410, -83.0552),
    "San Francisco": (37.7680, -122.3877),
    "Houston": (29.7508, -95.3621),
    "Indianapolis": (39.7640, -86.1555),
    "Los Angeles": (34.0430, -118.2673),
    "Inglewood": (33.9450, -118.3430),
    "Memphis": (35.1382, -90.0506),
    "Miami": (25.7814, -80.1870),
    "Milwaukee": (43.0451, -87.9172),
    "Minneapolis": (44.9795, -93.2761),
    "New Orleans": (29.9490, -90.0821),
    "New York": (40.7505, -73.9934),
    "Oklahoma City": (35.4634, -97.5151),
    "Orlando": (28.5392, -81.3839),
    "Philadelphia": (39.9012, -75.1720),
    "Phoenix": (33.4457, -112.0712),
    "Portland": (45.5316, -122.6668),
    "Sacramento": (38.5802, -121.4997),
    "San Antonio": (29.4270, -98.4375),
    "Toronto": (43.6435, -79.3791),
    "Salt Lake City": (40.7683, -111.9011),
    "Washington": (38.8981, -77.0209),
    # alternate and neutral sites
    "Austin": (30.2820, -97.7320),
    "Las Vegas": (36.1029, -115.1784),
    "Mexico City": (19.4887, -99.1715),
    "Paris": (48.8386, 2.3785),
    "Berlin": (52.5079, 13.4433),
    "London": (51.5030, 0.0032),
}
