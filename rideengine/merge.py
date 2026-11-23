"""Turn many recordings into rides.

1. group(): recordings that overlap in time are the same activity
   (e.g. Garmin + Apple Watch both recording one ride).
2. merge(): pick a base timeline, then fill each channel and total from the source
   that wins for it (see sources.py), recording where each value came from.

The ride runs from the first device's riding to the last's: where the base recording hadn't started yet (a Watch
started before a Zwift course) or had already stopped, another device's samples carry it. At every moment each
channel comes from the best source recording at that moment, and a total from the source that wins it, plus the
next best for the stretches that source didn't record. No device names in here: sources.py ranks them.
"""
from __future__ import annotations

import bisect
from dataclasses import replace

from . import clean
from .analysis.wellness import ride_recovery
from .model import CHANNELS, Recording, Ride, Sample, haversine, power_series
from .sources import ALIGN_TOLERANCE, CHANNEL_PRIORITY, DEFAULT_TOLERANCE, TOTAL_PRIORITY, rank

MIN_OVERLAP = 0.5  # share of the shorter recording that must overlap
MIN_ADDED_S = 60   # a stretch before or after the base recording with less riding than this isn't added
RIDING_W = 10      # riding, for an added stretch: power at least this, or cadence at least RIDING_RPM, or speed
RIDING_RPM = 30    # over 30 s at least RIDING_MS (walking about with the bike, or fiddling with a head unit,
RIDING_MS = 2.5    # isn't riding)
MAX_STOP_S = 120   # an added stretch is the riding right up to the base recording: a longer stop ends it (waiting
                   # at the car, the drive there, a false start before)


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
    # A heart rate of 0 is no reading (a head unit with no strap paired writes zeros: Zwift via Garmin).
    pts = [(s.t, v) for s in rec.samples if (v := getattr(s, channel)) is not None and (v > 0 or channel != "hr")]
    return [p[0] for p in pts], [p[1] for p in pts]


def merge(group_: list[Recording]) -> Ride:
    # Base timeline: the recording that wins for position; else for power; else the longest.
    with_pos = [r for r in group_ if "lat" in r.channels()]
    with_pow = [r for r in group_ if "power" in r.channels()]
    base = (_pick(CHANNEL_PRIORITY["lat"], with_pos) or _pick(CHANNEL_PRIORITY["power"], with_pow)
            or max(group_, key=lambda r: r.duration))
    base_samples = _riding_samples(base) or base.samples
    samples = [replace(s) for s in base_samples]
    provenance: dict[str, str] = {}

    # The riding other devices recorded before the base started or after it stopped.
    added = []
    for where in ("before", "after"):
        stretch = _stretch(group_, base, samples[0].t, samples[-1].t, where)
        if stretch:
            rec, extra = stretch
            samples = [replace(s) for s in extra] + samples if where == "before" else samples + [replace(s) for s in extra]
            added.append({"where": where, "source": rec.source, "start": extra[0].t, "end": extra[-1].t,
                          "minutes": round((extra[-1].t - extra[0].t) / 60, 1)})

    for ch in CHANNELS:
        having = sorted((r for r in group_ if ch in r.channels()),
                        key=lambda r: (rank(CHANNEL_PRIORITY.get(ch, []), r.source), -len(r.samples)))
        if not having:
            for s in samples:
                setattr(s, ch, None)
            continue
        provenance[f"channel:{ch}"] = having[0].source
        # Always align from each source's own samples, even the base's: some sources (Apple Health) store
        # heart rate as separate samples between the route points. At each moment, the best source that
        # recorded it; the next best fills where it didn't (it hadn't started, had stopped, or dropped out).
        tol = ALIGN_TOLERANCE.get(ch, DEFAULT_TOLERANCE)
        series = [(r.source, *_values(r, ch)) for r in having]
        filled: dict[str, int] = {}
        for s in samples:
            value = None
            for src, ts, vs in series:
                k = bisect.bisect_left(ts, s.t)
                best = None
                for j in (k - 1, k):
                    if 0 <= j < len(ts) and abs(ts[j] - s.t) <= tol:
                        if best is None or abs(ts[j] - s.t) < abs(ts[best] - s.t):
                            best = j
                if best is not None:
                    value = vs[best]
                    if src != having[0].source:
                        filled[src] = filled.get(src, 0) + 1
                    break
            setattr(s, ch, value)
        for src in filled:
            provenance[f"fill:{ch}:{src}"] = src

    # Leave out stretches that weren't riding (a bike computer left on in a car).
    full = samples
    cuts = clean.vehicle_segments(samples)
    kept = [x for p in clean.pieces(samples, cuts) for x in p] if cuts else samples
    excluded = []
    if cuts and len(kept) >= 0.1 * len(samples):  # if nearly everything is "vehicle", leave it alone
        for c in cuts:
            inside = [x for x in samples if c["start"] <= x.t <= c["end"]]
            excluded.append({"reason": "vehicle", "start": c["start"], "end": c["end"],
                             "km": round(track_distance(inside) / 1000, 1),
                             "minutes": round((c["end"] - c["start"]) / 60), "peak_kmh": c["peak_kmh"]})
        samples = kept

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

    if excluded:
        _totals_without_cuts(totals, provenance, full, samples, cuts)
    elif added:
        _totals_for_added(totals, provenance, samples, added, group_, all(r.indoor for r in group_))

    # Heart-rate and power summaries come from the merged channels, over the base window; a ride
    # that is one recording keeps that device's own heart-rate figures (they leave out pauses).
    hr = [s.hr for s in samples if s.hr is not None]
    own = group_[0].totals if len(group_) == 1 and not excluded else {}
    if hr and "avg_hr" in own and "max_hr" in own:
        totals["avg_hr"], totals["max_hr"] = round(own["avg_hr"], 1), own["max_hr"]
        provenance["total:avg_hr"] = provenance["total:max_hr"] = group_[0].source
    elif hr:
        totals["avg_hr"] = round(sum(hr) / len(hr), 1)
        totals["max_hr"] = max(hr)
        provenance["total:avg_hr"] = provenance["total:max_hr"] = "derived:hr"
    stats = power_stats(samples)
    if stats:
        totals.update(stats)
        for key in stats:
            provenance[f"total:{key}"] = "derived:power" if key != "avg_cadence" else "derived:cadence"

    # Heart-rate recovery after the ride, from the wearable that kept measuring once it ended.
    for rec in sorted((r for r in group_ if r.after), key=lambda r: rank(CHANNEL_PRIORITY["hr"], r.source)):
        rr = ride_recovery(rec)
        if rr:
            for key in ("hr_drop_60s", "hr_drop_120s"):
                if key in rr:
                    totals[key] = rr[key]
                    provenance[f"total:{key}"] = rec.source
            break

    return Ride(start=samples[0].t, end=samples[-1].t, sport=base.sport,
                indoor=all(r.indoor for r in group_), samples=samples, totals=totals,
                provenance=provenance, recordings=[r.origin for r in group_], excluded=excluded, added=added)


def _riding_samples(rec: Recording) -> list[Sample]:
    """A recording's samples that carry more than heart rate (a wearable stores heart rate between them)."""
    return [s for s in rec.samples if any(getattr(s, c) is not None for c in CHANNELS if c != "hr")]


def _riding_flags(samples: list[Sample]) -> list[bool]:
    """Whether each sample is riding: pedalling (power or cadence), or 30 s of speed at a riding pace."""
    ts = [s.t for s in samples if s.speed is not None]
    cs = [0.0]
    for s in samples:
        if s.speed is not None:
            cs.append(cs[-1] + s.speed)
    out = []
    for s in samples:
        if (s.power or 0) >= RIDING_W or (s.cadence or 0) >= RIDING_RPM:
            out.append(True)
            continue
        a, b = bisect.bisect_left(ts, s.t - 15), bisect.bisect_right(ts, s.t + 15)
        out.append(b - a >= 3 and (cs[b] - cs[a]) / (b - a) >= RIDING_MS)
    return out


def _stretch(group_: list[Recording], base: Recording, t0: float, t1: float, where: str):
    """(recording, samples) of the riding another device recorded before t0 or after t1: the one that reaches
    furthest out, from its first (or to its last) moment of moving. None if there's under MIN_ADDED_S of it."""
    best = None
    for r in group_:
        if r is base:
            continue
        own = [s for s in _riding_samples(r) if (s.t < t0 - 1 if where == "before" else s.t > t1 + 1)]
        once: dict[int, Sample] = {}
        for x in own:                       # one moment a second (a wearable stores each channel apart)
            once.setdefault(int(x.t), x)
        own = list(once.values())
        flags = _riding_flags(own)
        riding = [i for i, f in enumerate(flags) if f]
        # Walk out from the base recording while the riding carries on without a long stop.
        order = riding[::-1] if where == "before" else riding
        edge, last = None, t0 if where == "before" else t1
        for i in order:
            if abs(last - own[i].t) > MAX_STOP_S:
                break
            edge, last = i, own[i].t
        if edge is None:
            continue
        lo, hi = (edge, len(own)) if where == "before" else (0, edge + 1)
        own, flags = own[lo:hi], flags[lo:hi]
        ridden = sum(min(b.t - a.t, 5) for a, b, f in zip(own, own[1:], flags) if f)
        if ridden < MIN_ADDED_S:
            continue
        reach = t0 - own[0].t if where == "before" else own[-1].t - t1
        if best is None or reach > best[0]:
            best = (reach, r, own)
    return (best[1], best[2]) if best else None


def _covers(group_: list[Recording], source: str, a: float, b: float) -> bool:
    return any(r.source == source and r.start <= a + 5 and r.end >= b - 5 for r in group_)


def _speed_distance(samples: list[Sample]) -> float:
    return sum(a.speed * min(b.t - a.t, 5) for a, b in zip(samples, samples[1:]) if a.speed is not None)


def _totals_for_added(totals: dict, provenance: dict, samples: list[Sample], added: list[dict],
                      group_: list[Recording], indoor: bool) -> None:
    """A total from a device that didn't record an added stretch gets that stretch's share, worked out from the
    merged samples there (the next best source's): distance, moving and elapsed time, climbing outdoors (indoors
    only a ride game's climbing counts), and energy from power for calories. Recorded as "extra:<total>"."""
    for a in added:
        seg = [s for s in samples if a["start"] <= s.t <= a["end"]]
        if len(seg) < 2:
            continue
        gap = (seg[0].t if a["where"] == "after" else samples[samples.index(seg[-1]) + 1].t) - \
              (samples[samples.index(seg[0]) - 1].t if a["where"] == "after" else seg[-1].t)
        with_pos = sum(s.lat is not None for s in seg) > len(seg) / 2
        dist = track_distance(seg) if with_pos else _speed_distance(seg)
        a["km"] = round(dist / 1000, 1)
        extra = {"distance_m": dist, "moving_s": clean.moving_seconds(seg), "elapsed_s": seg[-1].t - seg[0].t + gap}
        if not indoor and any(s.ele is not None for s in seg):
            extra["ascent_m"] = elevation_gain(seg)
        if any(s.power is not None for s in seg):
            extra["calories"] = _energy_kj(seg)
        for key, value in extra.items():
            src = provenance.get(f"total:{key}", "")
            if key not in totals or src.startswith("derived") or _covers(group_, src, a["start"], a["end"]):
                continue
            if value:
                totals[key] = round(totals[key] + value, 1 if key.endswith("_m") else 0)
                provenance[f"extra:{key}"] = a["source"]


def power_stats(samples: list[Sample]) -> dict:
    """Average and best power from measured power, on 1 s steps (model.power_series). The average is
    over the seconds you were pedalling (zeros left out), as Zwift shows it."""
    _, series = power_series(samples)
    if not series:
        return {}
    riding = [p for p in series if p > 0]
    out = {"avg_power": round(sum(riding) / len(riding), 1) if riding else 0.0, "max_power": max(series)}
    csum = [0.0]
    for p in series:
        csum.append(csum[-1] + p)
    for d in (60, 1200):
        if d <= len(series):
            out[f"power_{d}s"] = round(max(csum[i + d] - csum[i] for i in range(len(series) - d + 1)) / d)
    cad = [s.cadence for s in samples if s.cadence]
    if cad:
        out["avg_cadence"] = round(sum(cad) / len(cad))
    return out


# Head units whose totals cover the whole recording, vehicle stretch included.
_HEAD_UNIT_TOTALS = ("distance_m", "ascent_m", "descent_m", "moving_s", "elapsed_s", "max_speed_ms")


def _totals_without_cuts(totals: dict, provenance: dict, full: list[Sample], kept: list[Sample],
                         cuts: list[dict]) -> None:
    """Device totals include the cut stretch, so work these out again from what was kept."""
    route = provenance.get("channel:lat")
    pieces = clean.pieces(full, cuts)
    device_ascent = totals.get("ascent_m") if not provenance.get("total:ascent_m", "").startswith("derived") else None
    for key in _HEAD_UNIT_TOTALS:
        totals.pop(key, None)
        provenance.pop(f"total:{key}", None)
    if route:
        totals["distance_m"] = round(sum(track_distance(p) for p in pieces), 1)
        provenance["total:distance_m"] = f"derived:{route}"
    if provenance.get("channel:ele"):
        kept_gain = sum(elevation_gain(p) for p in pieces)
        full_gain = elevation_gain(full)
        # Keep the device's barometric calibration: its total, scaled by the share of climbing kept.
        totals["ascent_m"] = round(device_ascent * kept_gain / full_gain if device_ascent and full_gain
                                   else kept_gain, 1)
        provenance["total:ascent_m"] = f"derived:{provenance['channel:ele']}"
    totals["elapsed_s"] = round(sum(p[-1].t - p[0].t for p in pieces))
    provenance["total:elapsed_s"] = "derived:" + (route or provenance.get("channel:speed", "hr"))
    v = [x for x in clean.speeds(kept) if x is not None]
    if v and provenance.get("channel:speed"):
        totals["max_speed_ms"] = round(max(v), 2)
        provenance["total:max_speed_ms"] = f"derived:{provenance['channel:speed']}"
    # A head unit's calorie estimate also ran in the car: keep the share for the moving time kept.
    # A wearable's calories are the wearable's own workout, so they stay as they are.
    cal_src = provenance.get("total:calories", "")
    if cal_src in ("garmin", "wahoo", "hammerhead", "kickr") and "calories" in totals:
        before, after = clean.moving_seconds(full), clean.moving_seconds(kept)
        if before:
            totals["calories"] = round(totals["calories"] * after / before)


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
