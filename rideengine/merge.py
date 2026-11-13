"""Turn many recordings into rides.

1. group(): recordings that overlap in time are the same activity
   (e.g. Garmin + Apple Watch both recording one ride).
2. merge(): pick a base timeline, then fill each channel and total from the source
   that wins for it (see sources.py), recording where each value came from.
"""
from __future__ import annotations

import bisect
from dataclasses import replace

from .model import CHANNELS, Recording, Ride, Sample, haversine
from .sources import ALIGN_TOLERANCE, CHANNEL_PRIORITY, DEFAULT_TOLERANCE, TOTAL_PRIORITY, rank

MIN_OVERLAP = 0.5  # share of the shorter recording that must overlap


def overlap_share(a: Recording, b: Recording) -> float:
    o = min(a.end, b.end) - max(a.start, b.start)
    shorter = min(a.duration, b.duration) or 1
    return max(0.0, o) / shorter


def group(recordings: list[Recording]) -> list[list[Recording]]:
    """Union-find over time overlap. Returns groups sorted by start time."""
    recs = sorted(recordings, key=lambda r: r.start)
    parent = list(range(len(recs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(recs)):
        for j in range(i + 1, len(recs)):
            if recs[j].start > recs[i].end:
                break
            if recs[i].sport == recs[j].sport and overlap_share(recs[i], recs[j]) >= MIN_OVERLAP:
                parent[find(j)] = find(i)
    groups: dict[int, list[Recording]] = {}
    for i, r in enumerate(recs):
        groups.setdefault(find(i), []).append(r)
    return sorted(groups.values(), key=lambda g: g[0].start)


def _pick(priority: list[str], candidates: list[Recording]) -> Recording | None:
    if not candidates:
        return None
    return min(candidates, key=lambda r: (rank(priority, r.source), -len(r.samples)))


def _values(rec: Recording, channel: str) -> tuple[list[float], list[float]]:
    pts = [(s.t, getattr(s, channel)) for s in rec.samples if getattr(s, channel) is not None]
    return [p[0] for p in pts], [p[1] for p in pts]


def merge(group_: list[Recording]) -> Ride:
    # Base timeline: the recording that wins for position; else for power; else the longest.
    with_pos = [r for r in group_ if "lat" in r.channels()]
    with_pow = [r for r in group_ if "power" in r.channels()]
    base = (_pick(CHANNEL_PRIORITY["lat"], with_pos) or _pick(CHANNEL_PRIORITY["power"], with_pow)
            or max(group_, key=lambda r: r.duration))
    base_samples = [s for s in base.samples if any(getattr(s, c) is not None for c in CHANNELS if c != "hr")] \
        or base.samples
    samples = [replace(s) for s in base_samples]
    provenance: dict[str, str] = {}

    for ch in CHANNELS:
        having = [r for r in group_ if ch in r.channels()]
        winner = _pick(CHANNEL_PRIORITY.get(ch, []), having)
        if winner is None:
            for s in samples:
                setattr(s, ch, None)
            continue
        provenance[f"channel:{ch}"] = winner.source
        # Always align from the winner's own samples, even when it is the base: some sources
        # (Apple Health) store heart rate as separate samples between the route points.
        ts, vs = _values(winner, ch)
        tol = ALIGN_TOLERANCE.get(ch, DEFAULT_TOLERANCE)
        for s in samples:
            k = bisect.bisect_left(ts, s.t)
            best = None
            for j in (k - 1, k):
                if 0 <= j < len(ts) and abs(ts[j] - s.t) <= tol:
                    if best is None or abs(ts[j] - s.t) < abs(ts[best] - s.t):
                        best = j
            setattr(s, ch, vs[best] if best is not None else None)

    totals: dict = {}
    for key, prio in TOTAL_PRIORITY.items():
        for src in prio:
            if src in ("@track", "@elevation"):
                pos_src = provenance.get("channel:lat")
                if pos_src and not any(r.source == pos_src and key in r.totals for r in group_) \
                        and rank(TOTAL_PRIORITY[key], pos_src) < prio.index(src):
                    val = track_distance(samples) if src == "@track" else elevation_gain(samples)
                    if val:
                        totals[key] = round(val, 1)
                        provenance[f"total:{key}"] = f"derived:{pos_src}"
                        break
                continue
            if src == "@power":
                if "channel:power" in provenance:
                    kj = _energy_kj(samples)
                    if kj:
                        totals[key] = round(kj)  # ~1 kJ of work ≈ 1 kcal burned (≈ 22% efficiency)
                        provenance[f"total:{key}"] = "derived:power"
                        break
                continue
            # Same source twice (e.g. a Garmin .FIT and the copy Garmin Connect wrote to Apple
            # Health): trust the fuller recording.
            rec = max((r for r in group_ if r.source == src and key in r.totals),
                      key=lambda r: len(r.samples), default=None)
            if rec is not None:
                totals[key] = rec.totals[key]
                provenance[f"total:{key}"] = src
                break
        else:
            rec = next((r for r in group_ if key in r.totals), None)
            if rec is not None:
                totals[key] = rec.totals[key]
                provenance[f"total:{key}"] = rec.source

    # Heart-rate and power summaries come from the merged channels, over the base window.
    hr = [s.hr for s in samples if s.hr is not None]
    if hr:
        totals["avg_hr"] = round(sum(hr) / len(hr), 1)
        totals["max_hr"] = max(hr)
        provenance["total:avg_hr"] = provenance["total:max_hr"] = "derived:hr"
    pw = [s.power for s in samples if s.power is not None]
    if pw:
        totals["avg_power"] = round(sum(pw) / len(pw), 1)
        totals["max_power"] = max(pw)
        provenance["total:avg_power"] = provenance["total:max_power"] = "derived:power"

    return Ride(start=samples[0].t, end=samples[-1].t, sport=base.sport,
                indoor=all(r.indoor for r in group_), samples=samples, totals=totals,
                provenance=provenance, recordings=[r.origin for r in group_])


def track_distance(samples: list[Sample]) -> float:
    d, prev = 0.0, None
    for s in samples:
        if s.lat is None:
            continue
        if prev is not None:
            d += haversine(prev.lat, prev.lon, s.lat, s.lon)
        prev = s
    return d


def elevation_gain(samples: list[Sample], hysteresis: float = 3.0) -> float:
    """Climbing with a small dead band so GPS/baro noise isn't counted."""
    gain, ref = 0.0, None
    for s in samples:
        if s.ele is None:
            continue
        if ref is None:
            ref = s.ele
        elif s.ele - ref > hysteresis:
            gain += s.ele - ref
            ref = s.ele
        elif ref - s.ele > hysteresis:
            ref = s.ele
    return gain


def _energy_kj(samples: list[Sample]) -> float:
    kj = 0.0
    for a, b in zip(samples, samples[1:]):
        if a.power is not None:
            kj += a.power * min(b.t - a.t, 10) / 1000
    return kj


def build_rides(recordings: list[Recording]) -> list[Ride]:
    return [merge(g) for g in group(recordings)]
