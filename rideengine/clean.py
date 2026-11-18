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


# --- Rides that aren't really rides -----------------------------------------------------------------
# A false start: the bike computer started, stopped, started again before the real ride (or ran on
# for a minute after it). Seen on Neelay's Garmin: 0.0-2.6 km, under 11 min, within an hour of a ride.
# They stay stored; lists and trends just leave them out.

EMPTY_KM = 0.1
EMPTY_MOVING_S = 60
TINY_KM = 3.0
TINY_MOVING_S = 15 * 60
SESSION_GAP_S = 90 * 60   # rides this close together are one outing
# Indoors there's no distance to judge by: a trainer session under INDOOR_TINY_S (e.g. the Watch started,
# then the Zwift ride changed, twice, before the real one) is a false start next to a longer session;
# under INDOOR_EMPTY_S on its own, it's empty.
INDOOR_TINY_S = 5 * 60
INDOOR_EMPTY_S = 60


def _size(ride) -> tuple[float, float]:
    """(km, moving seconds), preferring the ride's totals like the summary does."""
    km = (ride.totals.get("distance_m") or sum(
        haversine(a.lat, a.lon, b.lat, b.lon) for a, b in zip(ride.samples, ride.samples[1:])
        if a.lat is not None and b.lat is not None)) / 1000
    moving = ride.totals.get("moving_s")
    if moving is None:
        moving = moving_seconds(ride.samples)
    return km, moving


def hidden_reasons(rides: list) -> dict[int, str]:
    """{index: "empty" | "false_start"} for rides to leave out of lists and trends.

    empty: under EMPTY_KM or EMPTY_MOVING_S of riding.
    false_start: under TINY_KM and TINY_MOVING_S, in the same outing (gaps <= SESSION_GAP_S)
    as a ride that isn't tiny. A tiny ride on its own is a real (short) ride and stays.
    """
    order = sorted(range(len(rides)), key=lambda i: rides[i].start)
    size = {i: _size(rides[i]) for i in order}
    reasons: dict[int, str] = {}
    for i in order:
        if rides[i].indoor:
            if rides[i].end - rides[i].start < INDOOR_EMPTY_S:
                reasons[i] = "empty"
            continue  # trainer sessions have no distance to judge by: length in time instead
        km, moving = size[i]
        if km < EMPTY_KM or moving < EMPTY_MOVING_S:
            reasons[i] = "empty"
    # Outings: consecutive rides with short gaps between them.
    outing, outings = [], []
    for i in order:
        if outing and rides[i].start - rides[outing[-1]].end > SESSION_GAP_S:
            outings.append(outing)
            outing = []
        outing.append(i)
    if outing:
        outings.append(outing)

    def tiny(i):
        if rides[i].indoor:
            return rides[i].end - rides[i].start < INDOOR_TINY_S
        km, moving = size[i]
        return km < TINY_KM and moving < TINY_MOVING_S

    for o in outings:
        for i in o:
            if not tiny(i) or i in reasons:
                continue
            # Folded into a real session of the same kind (indoor with indoor, outdoor with outdoor).
            if any(not tiny(j) and j not in reasons and rides[j].indoor == rides[i].indoor for j in o):
                reasons[i] = "false_start"
    return reasons


def visible(rides: list) -> list:
    hide = hidden_reasons(rides)
    return [r for i, r in enumerate(rides) if i not in hide]
