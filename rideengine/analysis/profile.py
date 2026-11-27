"""A ride's profiles for the ride page: every channel in 30-second steps (stdlib only).

    p = profile(ride)   # {"step_s": 30, "t": [...], "km": [...], "s": [...], "h": [...], ...}

Each step averages its samples: speed (km/h), heart rate, power and cadence (pedalling only, zeros left out,
as averages are), elevation, and the last position (for the dot on the card's map). Outdoors the stopped
steps are left out, so the profile runs on moving time. "cu" is the climbing so far: the ride's ups added
with a 1 m dead band, then scaled so it ends on the ride's own total (the Edge's barometric figure, or the
ride game's), so dragging across elevation counts toward the number on the card. "km" ends on the
ride's total distance the same way. Values are None where a channel has no reading (27 Nov 2026).
"""
from __future__ import annotations

from ..model import haversine
from .basics import summary

STEP_S = 30
STOPPED_KMH = 2.0   # outdoors, a step slower than this on average is a stop, left out
DEAD_BAND_M = 1.0   # elevation wobble ignored when adding up the climbing (outdoors)


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def profile(ride, step_s: int = STEP_S) -> dict:
    s = summary(ride)
    samples = [x for x in ride.samples if x.t is not None]
    if not samples:
        return {"step_s": step_s, "t": [], "km": [], "s": [], "h": [], "p": [], "c": [], "e": [], "cu": [],
                "lat": [], "lon": []}
    t0 = ride.start
    band = 0.0 if ride.indoor else DEAD_BAND_M
    # Running distance and climbing, sample by sample.
    dist, climb, ref, prev = 0.0, 0.0, None, None
    run_d, run_c = [], []
    for x in samples:
        if prev is not None and x.lat is not None and prev.lat is not None:
            dist += haversine(prev.lat, prev.lon, x.lat, x.lon)
        elif prev is not None and x.speed is not None and x.lat is None:
            dist += x.speed * max(0.0, x.t - prev.t)       # indoors without a track: the trainer's speed
        if x.ele is not None:
            if ref is None:
                ref = x.ele
            elif x.ele - ref > band:
                climb += x.ele - ref
                ref = x.ele
            elif x.ele < ref:
                ref = x.ele
        run_d.append(dist)
        run_c.append(climb)
        prev = x
    # Group into steps.
    groups: dict[int, list[int]] = {}
    for i, x in enumerate(samples):
        groups.setdefault(int((x.t - t0) // step_s), []).append(i)
    out = {k: [] for k in ("t", "km", "s", "h", "p", "c", "e", "cu", "lat", "lon")}
    for k in sorted(groups):
        idx = groups[k]
        g = [samples[i] for i in idx]
        sp = _avg([x.speed for x in g])
        kmh = None if sp is None else sp * 3.6
        if not ride.indoor and (kmh is None or kmh < STOPPED_KMH):
            continue
        pos = next(((x.lat, x.lon) for x in reversed(g) if x.lat is not None and x.lon is not None), (None, None))
        out["t"].append(k * step_s)
        out["km"].append(run_d[idx[-1]] / 1000)
        out["s"].append(kmh)
        out["h"].append(_avg([x.hr for x in g if x.hr]))
        out["p"].append(_avg([x.power for x in g if x.power]))
        out["c"].append(_avg([x.cadence for x in g if x.cadence]))
        out["e"].append(_avg([x.ele for x in g]))
        out["cu"].append(run_c[idx[-1]])
        out["lat"].append(pos[0])
        out["lon"].append(pos[1])
    # End on the ride's own totals.
    if out["km"] and out["km"][-1] and s.get("km"):
        f = s["km"] / out["km"][-1]
        out["km"] = [v * f for v in out["km"]]
    if out["cu"] and out["cu"][-1] and s.get("ascent_m"):
        f = s["ascent_m"] / out["cu"][-1]
        out["cu"] = [v * f for v in out["cu"]]
    r = lambda v, d=0: None if v is None else (round(v, d) if d else round(v))
    return {"step_s": step_s, "t": out["t"], "km": [r(v, 2) for v in out["km"]], "s": [r(v, 1) for v in out["s"]],
            "h": [r(v) for v in out["h"]], "p": [r(v) for v in out["p"]], "c": [r(v) for v in out["c"]],
            "e": [r(v) for v in out["e"]], "cu": [r(v) for v in out["cu"]],
            "lat": [r(v, 5) for v in out["lat"]], "lon": [r(v, 5) for v in out["lon"]]}


def index_at(t_list: list, seconds: float) -> int:
    """The step nearest `seconds` after the start (steps can be missing where the ride stopped)."""
    if not t_list:
        return 0
    return min(range(len(t_list)), key=lambda i: abs(t_list[i] - seconds))
