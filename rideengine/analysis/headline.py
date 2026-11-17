"""The four headline numbers: the one card a rider checks to see they're getting better.

1. Sustained power (FTP): holding the group's pace.
2. Punch (best minute): closing a gap, getting over a rise.
3. Efficiency (watts, or metres, per heartbeat at a steady effort): the aerobic engine underneath.
4. Durability (how well output per heartbeat holds late in long rides): legs when the group splits.

Each has its current value, a history (one value per ride), and a target from the rider's goal. Targets
are fixed when first worked out (from a baseline), so progress is measured against something that
doesn't move as the rider improves. Read from ordinary riding, never tests; rule-based and stdlib only.
Simulated power never reaches a Ride, so every watt here was measured.
"""
from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta

from ..model import Ride, power_series
from .fitness import efficiency_windows

POWER_DAYS = 120          # power bests (and the FTP estimate) come from this recent a window
EFF_DAYS = 56             # efficiency from power when there are power rides this recent, else from speed
WARMUP_S = 600            # heart rate lags at the start: leave out the first 10 minutes
WINDOW_S = 300            # steady 5-minute windows for efficiency
HOLD_MIN_S = 2 * 3600     # durability needs a ride of two hours or more
HR_HOLD_S = 10            # a heart-rate reading holds for up to this long

IDS = ["sustained", "punch", "efficiency", "durability"]

# Which of the four each goal leans on (the "focus"); their targets stretch further.
FOCUS = {"keep_up_group": ["sustained", "punch"], "sprint": ["punch"], "more_power": ["sustained", "punch"],
         "beat_my_roads": ["sustained", "efficiency"], "climb_faster": ["sustained"], "own_climbs": ["sustained"],
         "first_distance": ["durability", "efficiency"], "all_day": ["durability", "efficiency"],
         "event": ["durability", "sustained"]}

ACTION = {
    "sustained": "Long steady efforts just under your limit: 2 x 20 minutes, or tempo on the rollers.",
    "punch": "Short, hard efforts, 30 seconds to 2 minutes, again and again, with easy riding between.",
    "efficiency": "Easy, steady hours: most of your riding at a pace you could hold a conversation at.",
    "durability": "One longer ride each week, eating and drinking from the first hour.",
}


# --- per ride (features.extract calls these once, with the samples) ----------------------------
def _hr_per_second(samples, t0: int, n: int) -> list[float | None]:
    pts = sorted((s.t, s.hr) for s in samples if s.hr is not None)
    out: list[float | None] = [None] * n
    for (t, hr), nxt in zip(pts, pts[1:] + [(pts[-1][0] + HR_HOLD_S, None)] if pts else []):
        a = max(0, int(t) - t0)
        b = min(n, int(t) - t0 + HR_HOLD_S, int(nxt[0]) - t0 if nxt[1] is not None else n)
        for i in range(a, max(b, a + 1)):
            if i < n:
                out[i] = hr
    return out


def _power_windows(ride: Ride) -> list[tuple[float, float]]:
    """(seconds in, watts per heartbeat-per-minute) for steady 5-minute stretches (power varying under
    20%, pedalling throughout) after a 10-minute warm-up, every minute."""
    t0, p = power_series(ride.samples)
    if len(p) < WARMUP_S + WINDOW_S:
        return []
    hr = _hr_per_second(ride.samples, t0, len(p))
    vals = []
    for i in range(WARMUP_S, len(p) - WINDOW_S + 1, 60):
        w = p[i:i + WINDOW_S]
        h = [x for x in hr[i:i + WINDOW_S] if x]
        if sum(1 for x in w if x > 0) < 0.95 * WINDOW_S or len(h) < 0.8 * WINDOW_S:
            continue
        mean = sum(w) / len(w)
        if mean < 60 or statistics.pstdev(w) > 0.2 * mean:
            continue
        vals.append((float(i), mean / (sum(h) / len(h))))
    return vals


def watts_per_beat(ride: Ride) -> float | None:
    """Median watts per heartbeat-per-minute over steady stretches. Needs measured power and heart rate."""
    vals = [v for _, v in _power_windows(ride)]
    return round(statistics.median(vals), 3) if len(vals) >= 3 else None


def hold(ride: Ride) -> float | None:
    """Durability: efficiency (output per heartbeat on steady stretches: flat and steady outdoors, steady
    power on the trainer) in the last quarter of the ride, as a percentage of the first half's, after a
    warm-up. 100 = no fade. Rides of 90 minutes or more, with enough steady stretches at both ends."""
    if ride.end - ride.start < HOLD_MIN_S:
        return None
    wins = _power_windows(ride) if ride.provenance.get("channel:power") else efficiency_windows(ride)
    if not wins:
        return None
    span = ride.end - ride.start
    early = [v for t, v in wins if WARMUP_S <= t <= span / 2]
    late = [v for t, v in wins if t >= span * 0.75]
    if len(early) < 5 or len(late) < 5:
        return None
    ratio = statistics.median(late) / statistics.median(early)
    return round(max(70.0, min(115.0, 100 * ratio)), 1)


# --- the four ---------------------------------------------------------------------------------
def _day(t: float) -> str:
    return datetime.fromtimestamp(t).date().isoformat()


def _metric(mid: str, label: str, plain: str, unit: str, decimals: int, current, history, pending: str | None,
            detail: str | None = None) -> dict:
    return {"id": mid, "label": label, "plain": plain, "unit": unit, "decimals": decimals,
            "current": current, "history": history[-20:], "better": "higher", "pending": None if current else pending,
            "detail": detail, "how": detail, "action": ACTION[mid]}


def current(feats: list[dict], today: date, ftp_own: float | None = None) -> list[dict]:
    """The four as they stand, from stored ride features (oldest first), without targets."""
    feats = sorted(feats, key=lambda f: f["start"])
    recent_cut = datetime.combine(today - timedelta(days=POWER_DAYS), datetime.min.time()).timestamp()
    pc = [f for f in feats if f.get("power_curve")]
    best = {}
    for f in pc:
        if f["start"] >= recent_cut:
            for k, v in f["power_curve"].items():
                best[k] = max(best.get(k, 0), v or 0)
    b20, b60 = best.get("1200"), best.get("60")
    ftp = round(ftp_own) if ftp_own else round(b20 * 0.95) if b20 else None
    sustained = _metric(
        "sustained", "Sustained power", "The power you could hold for about an hour: what keeps you with the group.",
        "W", 0, ftp, [{"date": _day(f["start"]), "value": round(f["power_curve"]["1200"] * 0.95)}
                      for f in pc if f["power_curve"].get("1200")],
        "Ride with the KICKR (or a power meter) for 20 minutes or more to measure this.",
        ("Your FTP, as you set it." if ftp_own else
         f"FTP estimated as 95% of your best 20 minutes ({b20} W)." if b20 else None))
    punch = _metric(
        "punch", "Punch", "Your best minute: closing a gap, getting over a rise.", "W", 0, b60,
        [{"date": _day(f["start"]), "value": f["power_curve"]["60"]} for f in pc if f["power_curve"].get("60")],
        "Ride with the KICKR (or a power meter) to measure this.",
        f"Best minute in the last {POWER_DAYS} days." if b60 else None)

    eff_cut = datetime.combine(today - timedelta(days=EFF_DAYS), datetime.min.time()).timestamp()
    by_power = [f for f in feats if f.get("w_per_beat")]
    by_speed = [f for f in feats if f.get("m_per_beat")]
    if by_power and by_power[-1]["start"] >= eff_cut:
        hist = [{"date": _day(f["start"]), "value": f["w_per_beat"]} for f in by_power]
        unit, how = "W/beat", "Watts for each heartbeat a minute, on steady stretches."
    else:
        hist = [{"date": _day(f["start"]), "value": f["m_per_beat"]} for f in by_speed]
        unit, how = "m/beat", "Metres travelled for each heartbeat, on flat, steady stretches."
    eff_now = round(statistics.median(h["value"] for h in hist[-5:]), 2) if hist else None
    efficiency = _metric(
        "efficiency", "Efficiency", "What you get from each heartbeat at a steady effort. It rises as your "
        "aerobic engine grows.", unit, 2, eff_now, hist,
        "Needs steady riding with heart rate: 20 minutes or more.", how if hist else None)

    holds = [f for f in feats if f.get("hold")]
    # Single rides are noisy outdoors (wind, a long climb late on): the median of the last five, and
    # gaining speed late (a tailwind home) counts as no fade, not better than none.
    hold_now = min(100, round(statistics.median(f["hold"] for f in holds[-5:]))) if holds else None
    durability = _metric(
        "durability", "Durability", "How well you hold your pace late in long rides. 100% means no fade.", "%", 0,
        hold_now, [{"date": _day(f["start"]), "value": f["hold"]} for f in holds],
        "Needs a ride of two hours or more.",
        "Your last five long rides: the last quarter against the first half, for the same heart rate."
        if holds else None)
    return [sustained, punch, efficiency, durability]


def targets(metrics: list[dict], aspiration: str | None) -> dict[str, dict]:
    """A target for each metric that has a value: {id: {"baseline", "target", "unit"}}. The goal's focus
    metrics stretch further. Worked out once and kept with the goal."""
    focus = set(FOCUS.get(aspiration or "", []))
    out = {}
    for m in metrics:
        v = m["current"]
        if not v:
            continue
        f = m["id"] in focus
        if m["id"] in ("sustained", "punch"):
            t = round(v * (1.10 if f else 1.05))
        elif m["id"] == "efficiency":
            t = round(v * (1.06 if f else 1.03), 2)
        else:
            t = min(100, round(v + (5 if f else 2)))
            t = max(t, round(v) + 1) if v < 100 else t
        out[m["id"]] = {"baseline": v, "target": t, "unit": m["unit"]}
    return out


def four(feats: list[dict], today: date, goal: dict | None = None, ftp_own: float | None = None) -> dict:
    """The headline card: the four with targets (from the goal's stored targets, new ones for metrics
    that have gained a value since), progress towards each, and one line on what to work on next.
    `stored_targets` in the result is what the goal should keep (changed only when new targets appeared)."""
    ms = current(feats, today, ftp_own)
    asp = (goal or {}).get("aspiration")
    stored = dict((goal or {}).get("targets") or {})
    fresh = targets(ms, asp)
    for mid, t in fresh.items():
        # A new target when there's none yet, or the unit changed (efficiency switched from speed to power).
        if mid not in stored or stored[mid].get("unit") != t["unit"]:
            stored[mid] = t
    focus = FOCUS.get(asp or "", [])
    for m in ms:
        t = stored.get(m["id"]) if goal else fresh.get(m["id"])
        m["focus"] = m["id"] in focus
        m["baseline"] = t["baseline"] if t else None
        m["target"] = t["target"] if t else None
        m["progress"] = None
        if t and m["current"] is not None:
            span = t["target"] - t["baseline"]
            m["progress"] = 1.0 if m["current"] >= t["target"] else \
                round(max(0.0, min(1.0, (m["current"] - t["baseline"]) / span)), 2) if span > 0 else 0.0
    have = [m for m in ms if m["progress"] is not None and m["progress"] < 1]
    nxt = None
    if have:
        pick = min(have, key=lambda m: (not m["focus"], m["progress"]))
        nxt = {"id": pick["id"], "text": f"{pick['label']} is furthest from its target. {pick['action']}"}
    elif all(m["progress"] == 1 for m in ms if m["progress"] is not None) and any(m["progress"] for m in ms):
        nxt = {"id": None, "text": "Every number with a target has reached it. Time for a bigger goal."}
    return {"metrics": ms, "next": nxt, "targets": stored if goal else None,
            "targets_changed": bool(goal) and stored != ((goal or {}).get("targets") or {})}
