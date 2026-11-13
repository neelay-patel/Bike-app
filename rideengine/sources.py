"""Which source wins for each channel and each total.

Rule of thumb: a measured value beats an estimate, and a dedicated sensor beats a
wrist. Calories are the exception (Neelay's call): the wearable wins.

Sources are the `Recording.source` keys produced by the importers. Unknown sources
rank after every listed one.
"""

CHANNEL_PRIORITY = {
    # Route, elevation, speed: the bike computer (barometric altimeter, better GPS mount).
    "lat": ["garmin", "wahoo", "apple_watch", "iphone", "gpx"],
    "lon": ["garmin", "wahoo", "apple_watch", "iphone", "gpx"],
    "ele": ["garmin", "wahoo", "apple_watch", "iphone", "gpx"],
    "speed": ["garmin", "wahoo", "kickr", "apple_watch", "iphone", "gpx"],
    # Heart rate: the wearable (any wearable for other riders).
    "hr": ["apple_watch", "whoop", "garmin", "wahoo", "gpx"],
    # Power and cadence: whatever device actually measured them. Never estimated here.
    "power": ["kickr", "wahoo", "garmin", "gpx"],
    "cadence": ["kickr", "wahoo", "garmin", "gpx"],
    "temp": ["garmin", "wahoo", "gpx"],
}

TOTAL_PRIORITY = {
    "distance_m": ["garmin", "wahoo", "kickr", "@track", "apple_watch", "iphone"],
    "ascent_m": ["garmin", "wahoo", "@elevation", "apple_watch", "iphone"],
    "descent_m": ["garmin", "wahoo", "apple_watch"],
    "moving_s": ["garmin", "wahoo", "kickr"],
    "elapsed_s": ["garmin", "wahoo", "kickr", "apple_watch"],
    "max_speed_ms": ["garmin", "wahoo", "apple_watch"],
    # "@track" / "@elevation": worked out from the merged route, used when the winning
    # route source (e.g. a plain GPX) carries no totals of its own.
    # Calories: wearable first; then energy from measured power; then the head unit's guess.
    "calories": ["apple_watch", "whoop", "@power", "garmin", "wahoo", "kickr"],
}

# How far apart (seconds) two samples may be and still be treated as the same moment.
ALIGN_TOLERANCE = {"hr": 15, "power": 3, "cadence": 3, "temp": 30}
DEFAULT_TOLERANCE = 5


def rank(priority: list[str], source: str) -> int:
    return priority.index(source) if source in priority else len(priority)
