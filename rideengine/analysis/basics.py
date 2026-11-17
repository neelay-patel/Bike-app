"""Per-ride basics computed from a merged Ride's samples."""
from __future__ import annotations

from ..model import Ride, haversine

MOVING_MS = 1.0  # below this speed (m/s) the rider counts as stopped
MAX_GAP_S = 30   # gaps longer than this are pauses, not riding


def distances(ride: Ride) -> list[float]:
    """Cumulative distance (m) at each sample, from the merged track."""
    out, d, prev = [], 0.0, None
    for s in ride.samples:
        if s.lat is not None and prev is not None:
            d += haversine(prev.lat, prev.lon, s.lat, s.lon)
        if s.lat is not None:
            prev = s
        out.append(d)
    return out


def moving_time(ride: Ride) -> float:
    cum = distances(ride)
    t = 0.0
    for i in range(1, len(ride.samples)):
        dt = ride.samples[i].t - ride.samples[i - 1].t
        if 0 < dt <= MAX_GAP_S and (cum[i] - cum[i - 1]) / dt > MOVING_MS:
            t += dt
    return t


def stops(ride: Ride, min_s: float = 120) -> list[dict]:
    """Stops of at least `min_s` seconds: where, when, how long, how far into the ride."""
    cum = distances(ride)
    out, cur = [], None
    for i in range(1, len(ride.samples)):
        a, b = ride.samples[i - 1], ride.samples[i]
        dt = b.t - a.t
        slow = dt > 0 and ((cum[i] - cum[i - 1]) / dt < MOVING_MS or dt >= MAX_GAP_S)
        if slow:
            if cur is None:
                cur = {"t": a.t, "km": cum[i] / 1000, "lat": a.lat, "lon": a.lon, "seconds": 0.0}
            cur["seconds"] += dt
        else:
            if cur and cur["seconds"] >= min_s:
                out.append(cur)
            cur = None
    if cur and cur["seconds"] >= min_s:
        out.append(cur)
    return out


def summary(ride: Ride) -> dict:
    """One flat dict per ride, preferring device totals over our own derivations."""
    tot = ride.totals
    km = (tot.get("distance_m") or (distances(ride)[-1] if ride.samples else 0.0)) / 1000
    mv = tot.get("moving_s") or moving_time(ride)
    if not mv and (ride.indoor or km < 0.05):
        # Indoors (or no GPS) there's no speed to tell moving from stopped: the workout's own length.
        mv = tot.get("elapsed_s") or (ride.end - ride.start)
    return {
        "start": ride.start,
        "km": round(km, 2),
        "moving_h": round(mv / 3600, 3),
        "avg_kmh": round(km / (mv / 3600), 2) if mv and km >= 0.05 else None,
        "ascent_m": tot.get("ascent_m"),
        "avg_hr": tot.get("avg_hr"),
        "max_hr": tot.get("max_hr"),
        "avg_power": tot.get("avg_power"),
        "max_power": tot.get("max_power"),
        "power_60s": tot.get("power_60s"),        # best 1 minute
        "power_1200s": tot.get("power_1200s"),    # best 20 minutes
        "avg_cadence": tot.get("avg_cadence"),
        "calories": tot.get("calories"),
        "hr_drop_60s": tot.get("hr_drop_60s"),   # heart-rate recovery: bpm fallen 1 min after the end
        "indoor": ride.indoor,
    }
