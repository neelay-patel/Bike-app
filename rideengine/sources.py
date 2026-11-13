"""Which source wins for each channel and each total, and what each source's data may be used for.

Rule of thumb: a measured value beats an estimate, and a dedicated sensor beats a
wrist. Calories are the exception (Neelay's call): the wearable wins.

Sources are the `Recording.source` keys produced by the importers and backend connectors.
Unknown sources rank after every listed one.
"""

# Head units (bike computers) in order: they carry the best route, elevation and speed.
_HEAD_UNITS = ["garmin", "wahoo", "hammerhead"]

CHANNEL_PRIORITY = {
    # Route, elevation, speed: the bike computer (barometric altimeter, better GPS mount).
    "lat": _HEAD_UNITS + ["apple_watch", "fitbit", "iphone", "gpx"],
    "lon": _HEAD_UNITS + ["apple_watch", "fitbit", "iphone", "gpx"],
    "ele": _HEAD_UNITS + ["apple_watch", "fitbit", "iphone", "gpx"],
    "speed": _HEAD_UNITS + ["kickr", "apple_watch", "fitbit", "iphone", "gpx"],
    # Heart rate: the wearable (any wearable for other riders). Whoop has no HR stream in its API,
    # so in practice it only supplies totals; Oura's ring HR ranks after wrist wearables.
    "hr": ["apple_watch", "fitbit", "whoop", "oura"] + _HEAD_UNITS + ["gpx"],
    # Power and cadence: whatever device actually measured them. Never estimated here.
    "power": ["kickr"] + _HEAD_UNITS + ["gpx"],
    "cadence": ["kickr"] + _HEAD_UNITS + ["gpx"],
    "temp": _HEAD_UNITS + ["gpx"],
}

TOTAL_PRIORITY = {
    "distance_m": _HEAD_UNITS + ["kickr", "@track", "apple_watch", "fitbit", "whoop", "oura", "iphone"],
    "ascent_m": _HEAD_UNITS + ["@elevation", "apple_watch", "fitbit", "whoop", "iphone"],
    "descent_m": _HEAD_UNITS + ["apple_watch"],
    "moving_s": _HEAD_UNITS + ["kickr"],
    "elapsed_s": _HEAD_UNITS + ["kickr", "apple_watch"],
    "max_speed_ms": _HEAD_UNITS + ["apple_watch"],
    # "@track" / "@elevation": worked out from the merged route, used when the winning
    # route source (e.g. a plain GPX) carries no totals of its own.
    # Calories: wearable first; then energy from measured power; then the head unit's guess.
    "calories": ["apple_watch", "whoop", "fitbit", "oura", "@power"] + _HEAD_UNITS + ["kickr"],
    # Used only when no recording has a heart-rate stream (e.g. Whoop, which gives totals only);
    # otherwise merge() recomputes these from the merged channel.
    "avg_hr": ["apple_watch", "fitbit", "whoop", "oura"] + _HEAD_UNITS,
    "max_hr": ["apple_watch", "fitbit", "whoop", "oura"] + _HEAD_UNITS,
}

# How far apart (seconds) two samples may be and still be treated as the same moment.
ALIGN_TOLERANCE = {"hr": 15, "power": 3, "cadence": 3, "temp": 30}
DEFAULT_TOLERANCE = 5


def rank(priority: list[str], source: str) -> int:
    return priority.index(source) if source in priority else len(priority)


# What each source's data may be used for, per its provider's terms:
#   "ai":    fed to AI models (coach, generated headlines, ...)
#   "share": shown to people other than the rider (share cards, group features)
# True = allowed, False = barred, None = terms not reviewed yet. Only True counts as allowed.
# Review the full agreements before launch (docs/connectors.md) and update this table.
SOURCE_POLICY = {
    # Rider's own HealthKit data, read with their permission. Apple: no advertising, no selling.
    "apple_watch": {"ai": True, "share": True},
    "iphone": {"ai": True, "share": True},
    # A GPX file the rider supplies themselves.
    "gpx": {"ai": True, "share": True},
    # A quoted Garmin clause bars building AI models from its data, and passing data on needs
    # permission. Not yet read in full.
    "garmin": {"ai": None, "share": None},
    "wahoo": {"ai": None, "share": None},
    "kickr": {"ai": None, "share": None},
    "hammerhead": {"ai": None, "share": None},
    "whoop": {"ai": None, "share": None},
    # Oura's June 2026 API agreement appears to bar using its data to prompt or supply AI models.
    "oura": {"ai": False, "share": None},
    "fitbit": {"ai": None, "share": None},
}


def sources_used(provenance: dict) -> set[str]:
    """Every source that contributed a channel or a total to a merged ride.

    Derived values ("derived:hr", "derived:power", "derived:garmin") come from channels that are
    already counted, or name the source they were derived from.
    """
    out = set()
    for key, val in provenance.items():
        src = val.split(":", 1)[1] if val.startswith("derived:") else val
        if key.startswith("channel:") or src not in ("hr", "power"):
            out.add(src)
    return out


def blocked_sources(provenance: dict, use: str) -> set[str]:
    """Sources in this ride whose data may not (or not yet) be used for `use` ("ai" or "share")."""
    return {s for s in sources_used(provenance) if SOURCE_POLICY.get(s, {}).get(use) is not True}


def allowed(provenance: dict, use: str) -> bool:
    return not blocked_sources(provenance, use)
