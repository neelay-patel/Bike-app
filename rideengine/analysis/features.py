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
from .repeats import Track

VERSION = 1


def extract(ride: Ride) -> dict:
    s = summary(ride)
    f = {"v": VERSION, "ride_id": str(int(ride.start)), "start": ride.start, "end": ride.end,
         "indoor": ride.indoor, "km": s["km"] or 0.0, "moving_s": round((s["moving_h"] or 0) * 3600),
         "ascent_m": s["ascent_m"], "kmh": s["avg_kmh"], "avg_hr": s["avg_hr"],
         # Only measured power reaches a Ride (simulated power never does).
         "power": s["avg_power"] if ride.provenance.get("channel:power") else None,
         "cells": [], "first": None, "last": None, "bbox": None, "track_km": 0.0, "climbs": []}
    if ride.indoor:
        return f
    t = Track.of(ride)
    if len(t.lat) < 10:
        return f
    f.update(cells=sorted([list(c) for c in t.cells]), first=[t.lat[0], t.lon[0]], last=[t.lat[-1], t.lon[-1]],
             bbox=[min(t.lat), min(t.lon), max(t.lat), max(t.lon)], track_km=round(t.km, 2),
             climbs=[{"start": list(c["start"]), "end": list(c["end"]), "gain_m": c["gain_m"],
                      "length_m": c["length_m"]} for c in find_climbs(ride)])
    return f


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
