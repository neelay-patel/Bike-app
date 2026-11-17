"""What each ride contributes to insights, worked out once when the ride arrives.

extract(ride) reads the ride's samples once (the slow part) and keeps a small JSON-able summary:
totals for tallies and bests, the ~300 m grid cells the route visits (route matching), where it
starts and ends (home), and the climbs detected in it (climb discovery). Everything after that
(routes, climbs, notes, tallies) works from these, without loading samples again, except timing
a ride on a newly found climb.

Bump VERSION when what's extracted changes; stored features with an older version are redone.
"""
from __future__ import annotations

from ..model import Ride
from .basics import summary
from .climbs import find_climbs
from .fitness import efficiency
from .goals import power_curve
from .headline import hold, watts_per_beat
from .repeats import Track

VERSION = 8  # 2 HR recovery; 3 route shape; 4 indoor time; 5 power curve; 6 max HR; 7 avg power while pedalling;
             # 8 efficiency and durability (headline.py)


def extract(ride: Ride) -> dict:
    s = summary(ride)
    f = {"v": VERSION, "ride_id": str(int(ride.start)), "start": ride.start, "end": ride.end,
         "indoor": ride.indoor, "km": s["km"] or 0.0, "moving_s": round((s["moving_h"] or 0) * 3600),
         "ascent_m": s["ascent_m"], "kmh": s["avg_kmh"], "avg_hr": s["avg_hr"],
         # Only measured power reaches a Ride (simulated power never does).
         "power": s["avg_power"] if ride.provenance.get("channel:power") else None,
         "hr_drop_60s": s["hr_drop_60s"], "max_hr": s["max_hr"],
         "power_curve": power_curve(ride.samples) if ride.provenance.get("channel:power") else {},
         "w_per_beat": watts_per_beat(ride) if ride.provenance.get("channel:power") else None,
         "m_per_beat": None, "hold": hold(ride),
         "cells": [], "first": None, "last": None, "bbox": None, "track_km": 0.0, "climbs": []}
    if ride.indoor:
        return f
    t = Track.of(ride)
    if len(t.lat) < 10:
        return f
    f["m_per_beat"] = None if f["w_per_beat"] else efficiency(ride)
    f.update(cells=sorted([list(c) for c in t.cells]), first=[t.lat[0], t.lon[0]], last=[t.lat[-1], t.lon[-1]],
             bbox=[min(t.lat), min(t.lon), max(t.lat), max(t.lon)], track_km=round(t.km, 2),
             climbs=[{"start": list(c["start"]), "end": list(c["end"]), "gain_m": c["gain_m"],
                      "length_m": c["length_m"]} for c in find_climbs(ride)],
             shape=shape(t))
    return f


def shape(t: Track, points: int = 48) -> list[list[float]]:
    """The route's outline for thumbnails: ~`points` points evenly along it, x east and y south,
    scaled into a unit square (aspect kept, centred). Only ever shown to the rider."""
    import math
    if len(t.lat) < 2 or t.d[-1] <= 0:
        return []
    k = math.cos(math.radians(sum(t.lat) / len(t.lat)))
    picks, j = [], 0
    for i in range(points + 1):
        target = t.d[-1] * i / points
        while j < len(t.d) - 1 and t.d[j] < target:
            j += 1
        picks.append((t.lon[j] * k, -t.lat[j]))
    xs, ys = [p[0] for p in picks], [p[1] for p in picks]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1e-9
    ox = (span - (max(xs) - min(xs))) / 2
    oy = (span - (max(ys) - min(ys))) / 2
    return [[round((x - min(xs) + ox) / span, 3), round((y - min(ys) + oy) / span, 3)] for x, y in picks]


class Brief:
    """Just enough of a ride for clean.hidden_reasons(), from its features."""

    def __init__(self, f: dict):
        self.start, self.end, self.indoor = f["start"], f["end"], f["indoor"]
        self.totals = {"distance_m": f["km"] * 1000, "moving_s": f["moving_s"]}
        self.samples: list = []


def visible_ids(feats: list[dict]) -> set[str]:
    """Rides that count: not false starts or empty recordings (clean.hidden_reasons)."""
    from ..clean import hidden_reasons
    hide = hidden_reasons([Brief(f) for f in feats])
    return {f["ride_id"] for i, f in enumerate(feats) if i not in hide}
