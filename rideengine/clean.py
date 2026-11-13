"""Find parts of a recording that weren't riding, so they don't count as the ride.

Today: vehicle stretches, when a bike computer kept recording in a car (e.g. 30 Jul 2026: a
146.9 km "ride" with a 115 km/h top speed). The rule:

1. A *vehicle core* is a run of samples faster than VEHICLE_KMH lasting at least VEHICLE_MIN_S,
   that either peaks above VEHICLE_PEAK_KMH or lasts VEHICLE_LONG_S. A fast descent on a bike
   is short and rarely holds 65+ km/h for a minute, let alone peaks at 80.
2. The cut grows from the core back to the end of the last long stop (loading the bike) and
   forward to the start of the next long stop (unloading), or to the end of the recording.
   A long stop is LONG_STOP_S still (red lights are shorter). With no long stop before the core,
   the cut starts at the recording's start only if the core is near it, otherwise at the core.

City driving that never reaches the threshold and has no long stop around it can't be told apart
from fast riding, so it stays. Thresholds are tuned on Neelay's rides; revisit for mountains.
"""
from __future__ import annotations

from typing import Optional

from .model import Sample, haversine

VEHICLE_KMH = 65.0
VEHICLE_PEAK_KMH = 80.0
VEHICLE_MIN_S = 60
VEHICLE_LONG_S = 180
FAST_GAP_S = 30        # fast samples this close together belong to the same run
STOP_MS = 1.0          # below this speed (m/s) counts as stopped
LONG_STOP_S = 120
NEAR_EDGE_S = 600      # a core this close to the recording's start/end extends to it


def speeds(samples: list[Sample]) -> list[Optional[float]]:
    """Speed (m/s) at each sample: the device's, else from the position change."""
    out: list[Optional[float]] = []
    prev: Optional[Sample] = None
    for s in samples:
        v = s.speed
        if v is None and s.lat is not None and prev is not None and s.t > prev.t:
            v = haversine(prev.lat, prev.lon, s.lat, s.lon) / (s.t - prev.t)
        out.append(v)
        if s.lat is not None:
            prev = s
    return out


def long_stops(samples: list[Sample], v: list[Optional[float]]) -> list[tuple[float, float]]:
    """(start, end) times of stops lasting LONG_STOP_S or more, including recording gaps."""
    out, still_from = [], None
    for i, s in enumerate(samples):
        if i and s.t - samples[i - 1].t >= LONG_STOP_S:  # auto-pause or a gap in recording
            out.append((samples[i - 1].t, s.t))
        stopped = v[i] is not None and v[i] < STOP_MS
        if stopped and still_from is None:
            still_from = s.t
        elif not stopped and still_from is not None:
            if samples[i - 1].t - still_from >= LONG_STOP_S:
                out.append((still_from, samples[i - 1].t))
            still_from = None
    if still_from is not None and samples[-1].t - still_from >= LONG_STOP_S:
        out.append((still_from, samples[-1].t))
    return sorted(out)


def vehicle_segments(samples: list[Sample]) -> list[dict]:
    """Time ranges recorded in a vehicle: [{"start", "end", "peak_kmh"}], merged and sorted."""
    if len(samples) < 2:
        return []
    v = speeds(samples)
    fast = VEHICLE_KMH / 3.6
    runs, cur = [], None
    for i, s in enumerate(samples):
        if v[i] is not None and v[i] > fast:
            if cur is not None and s.t - samples[cur[1]].t <= FAST_GAP_S:
                cur[1] = i
            else:
                if cur is not None:
                    runs.append(cur)
                cur = [i, i]
    if cur is not None:
        runs.append(cur)

    cores = []
    for a, b in runs:
        dur = samples[b].t - samples[a].t
        peak = max(v[i] for i in range(a, b + 1) if v[i] is not None) * 3.6
        if dur >= VEHICLE_MIN_S and (peak >= VEHICLE_PEAK_KMH or dur >= VEHICLE_LONG_S):
            cores.append((samples[a].t, samples[b].t, peak))
    if not cores:
        return []

    first, last = samples[0].t, samples[-1].t
    stops = long_stops(samples, v)
    segs = []
    for ta, tb, peak in cores:
        before = [t1 for t0, t1 in stops if t1 <= ta]
        after = [t0 for t0, t1 in stops if t0 >= tb]
        start = max(before) if before else (first if ta - first <= NEAR_EDGE_S else ta)
        end = min(after) if after else (last if last - tb <= NEAR_EDGE_S else tb)
        segs.append({"start": start, "end": end, "peak_kmh": round(peak, 1)})
    segs.sort(key=lambda s: s["start"])
    merged = [segs[0]]
    for s in segs[1:]:
        if s["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], s["end"])
            merged[-1]["peak_kmh"] = max(merged[-1]["peak_kmh"], s["peak_kmh"])
        else:
            merged.append(s)
    return merged


def moving_seconds(samples: list[Sample], v: Optional[list] = None, max_gap: float = 30) -> float:
    v = v if v is not None else speeds(samples)
    total = 0.0
    for i in range(1, len(samples)):
        dt = samples[i].t - samples[i - 1].t
        if 0 < dt <= max_gap and v[i] is not None and v[i] > STOP_MS:
            total += dt
    return total


def pieces(samples: list[Sample], cuts: list[dict]) -> list[list[Sample]]:
    """The samples outside the cuts, as contiguous pieces (so no distance is counted across a cut)."""
    out, cur = [], []
    for s in samples:
        if any(c["start"] <= s.t <= c["end"] for c in cuts):
            if cur:
                out.append(cur)
                cur = []
        else:
            cur.append(s)
    if cur:
        out.append(cur)
    return out
