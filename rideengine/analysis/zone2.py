"""Zone 2 (docs/train-method.md, "Zone 2"): the easy, aerobic riding most of a week should be.

Zone 2 is the hardest you can ride while still below your first threshold, where breathing and lactate first start
to rise (a 2025 expert consensus); the talk test, full sentences, is its everyday check. We start from heart rate
reserve, 60-70% (Karvonen, as Apple's zones appear to), and the rider can type their own range (a lab test, their
Watch or Edge). It's checked from normal riding: a steady ride whose heart rate barely drifts was inside zone 2.

hist(ride)          -> per ride, stored in its features: moving seconds at each heart rate (whole bpm), and the
                       pedalling seconds and watts at each, when power is measured. Zones change; this doesn't.
steady(ride)        -> per ride, stored: a steady ride's heart-rate drift (Pa:HR, first half against second).
zone2_range(...)    -> the rider's range and where it came from.
split(hists, rng)   -> % of moving time in zone 2, above and below.
watts(hists, rng)   -> average watts while heart rate was in zone 2 (the proof it's working, when it rises).
trend(feats, rng)   -> watts at zone 2, month by month.
check(feats, rng)   -> what the latest steady ride says about the range.
ride_line(...)      -> after a ride: one line, only where zone 2 was the point.
week_line(...)      -> the week's share.
"""
from __future__ import annotations

from datetime import datetime

HRR = (0.60, 0.70)     # zone 2 as a share of heart rate reserve
DRIFT_OK = 5.0         # % heart-rate drift at steady power: under this, the ride stayed aerobic (Friel's decoupling)
STEADY_MIN = 40        # minutes of steady pedalling after the warm-up, for a drift check
WARMUP_S = 600
NEAR = 6               # bpm above the range a steady ride can still say "your zone 2 may reach higher"
EASY_SHARE = 80        # % of a week's riding at zone 2 or easier that polarized training points to (`easy-most`)


# --- per ride, stored in features -------------------------------------------------------------------------

def _moving(ride) -> list[bool]:
    """Each second of the ride: moving or not. Outdoors from GPS speed; indoors (no speed) every second counts."""
    n = max(1, int(ride.end - ride.start) + 1)
    if ride.indoor or not any(s.lat is not None for s in ride.samples):
        return [True] * n
    from .basics import MAX_GAP_S, MOVING_MS, distances
    cum = distances(ride)
    out = [False] * n
    for i in range(1, len(ride.samples)):
        a, b = ride.samples[i - 1], ride.samples[i]
        dt = b.t - a.t
        if 0 < dt <= MAX_GAP_S and (cum[i] - cum[i - 1]) / dt > MOVING_MS:
            for k in range(max(0, int(a.t - ride.start)), min(n, int(b.t - ride.start))):
                out[k] = True
    return out


def hist(ride) -> dict | None:
    """{"lo": lowest bpm, "s": [moving seconds at lo, lo+1, ...], "ps": [pedalling seconds with power],
    "w": [watt-seconds]}. None without heart rate."""
    from .effort import _per_second
    hr = _per_second(ride, "hr", 20)
    if sum(h is not None for h in hr) < 300:
        return None
    power = _per_second(ride, "power", 5) if ride.provenance.get("channel:power") else [None] * len(hr)
    moving = _moving(ride)
    vals = [round(h) for h in hr if h is not None and 40 <= h <= 230]
    if not vals:
        return None
    lo, hi = min(vals), max(vals)
    s, ps, w = [0] * (hi - lo + 1), [0] * (hi - lo + 1), [0.0] * (hi - lo + 1)
    for k, h in enumerate(hr):
        if h is None or not 40 <= h <= 230 or not (moving[k] if k < len(moving) else False):
            continue
        i = round(h) - lo
        s[i] += 1
        p = power[k] if k < len(power) else None
        if p is not None and p > 0:          # pedalling only, as Zwift shows average power
            ps[i] += 1
            w[i] += p
    out = {"lo": lo, "s": s}
    if any(ps):
        out |= {"ps": ps, "w": [round(x) for x in w]}
    return out


def steady(ride) -> dict | None:
    """A steady ride's heart-rate drift: watts per beat in the first half of the steady riding against the
    second (after a 10-minute warm-up). {"pct", "hr", "watts", "minutes"}; None unless 40+ minutes of steady
    pedalling with power and heart rate."""
    if not ride.provenance.get("channel:power"):
        return None
    from .effort import _per_second
    power, hr = _per_second(ride, "power", 5), _per_second(ride, "hr", 20)
    pts = [(k, power[k], hr[k]) for k in range(WARMUP_S, min(len(power), len(hr)))
           if power[k] is not None and power[k] > 0 and hr[k] is not None]
    if len(pts) < STEADY_MIN * 60:
        return None
    # Steady: most minutes within 15% of the ride's typical power.
    mins = [sum(p for _, p, _ in pts[i:i + 60]) / 60 for i in range(0, len(pts) - 59, 60)]
    med = sorted(mins)[len(mins) // 2]
    if med < 50 or sum(abs(m - med) <= 0.15 * med for m in mins) < 0.75 * len(mins):
        return None
    half = len(pts) // 2

    def ratio(xs):
        return (sum(p for _, p, _ in xs) / len(xs)) / (sum(h for _, _, h in xs) / len(xs))
    r1, r2 = ratio(pts[:half]), ratio(pts[half:])
    return {"pct": round((r1 - r2) / r1 * 100, 1), "hr": round(sum(h for _, _, h in pts) / len(pts)),
            "watts": round(sum(p for _, p, _ in pts) / len(pts)), "minutes": round(len(pts) / 60)}


# --- the rider's range -------------------------------------------------------------------------------------

def zone2_range(max_hr: float | None, resting: float | None, own: list | None = None) -> dict | None:
    """{"bpm": [lo, hi], "source": "yours" | "estimated", "how"}. The rider's own range wins."""
    if own and len(own) == 2 and 60 <= own[0] < own[1] <= 220:
        return {"bpm": [int(own[0]), int(own[1])], "source": "yours", "how": "the range you set"}
    if not max_hr or not resting or max_hr <= resting + 30:
        return None
    r = max_hr - resting
    return {"bpm": [round(resting + HRR[0] * r), round(resting + HRR[1] * r)], "source": "estimated",
            "how": f"60–70% of your heart rate reserve (resting {round(resting)}, max {round(max_hr)})"}


def parse_own(text: str | None) -> list | None:
    """ "126-138" or "126–138" -> [126, 138]; None for empty or invalid."""
    import re
    m = re.fullmatch(r"\s*(\d{2,3})\s*[-–]\s*(\d{2,3})\s*", text or "")
    if not m:
        return None
    lo, hi = int(m[1]), int(m[2])
    return [lo, hi] if 60 <= lo < hi <= 220 and hi - lo >= 5 else None


# --- reading rides against it ----------------------------------------------------------------------------

def split(hists: list[dict | None], rng: list) -> dict | None:
    """% of moving time in zone 2, above and below (adds to 100), and the minutes."""
    lo, hi = rng
    below = inside = above = 0
    for h in hists:
        for i, sec in enumerate((h or {}).get("s", [])):
            bpm = h["lo"] + i
            if bpm < lo:
                below += sec
            elif bpm <= hi:
                inside += sec
            else:
                above += sec
    total = below + inside + above
    if total < 300:
        return None
    pin, pab = round(inside / total * 100), round(above / total * 100)
    return {"in": pin, "above": pab, "below": 100 - pin - pab, "minutes": round(total / 60),
            "in_min": round(inside / 60)}


def watts(hists: list[dict | None], rng: list, min_s: int = 15 * 60) -> dict | None:
    """Average watts while heart rate was in zone 2, over pedalling seconds with power."""
    lo, hi = rng
    sec = ws = 0
    for h in hists:
        if not h or "ps" not in h:
            continue
        for i, n in enumerate(h["ps"]):
            if lo <= h["lo"] + i <= hi:
                sec += n
                ws += h["w"][i]
    return {"watts": round(ws / sec), "minutes": round(sec / 60)} if sec >= min_s else None


def trend(feats: list[dict], rng: list, tz=None, months: int = 6) -> list[dict]:
    """Watts at zone 2, month by month (rides with power), the last `months` months that have any."""
    by: dict[str, list] = {}
    for f in feats:
        h = f.get("hr_hist")
        if h and "ps" in h:
            by.setdefault(datetime.fromtimestamp(f["start"], tz).strftime("%Y-%m"), []).append(h)
    out = []
    for m in sorted(by):
        w = watts(by[m], rng)
        if w:
            out.append({"month": m, **w})
    return out[-months:]


def check(feats: list[dict], rng: list, tz=None) -> dict | None:
    """What the latest steady ride says about the range: {"ride_id", "date", "verdict", "line"}. A steady ride
    whose heart rate drifted under 5% stayed aerobic, so its heart rate is zone 2 or below."""
    lo, hi = rng
    # Only rides ridden near the range: drift is a test of aerobic riding, and a threshold workout can hold steady
    # for 45 minutes without saying anything about zone 2.
    ok = [f for f in feats if f.get("z2_drift") and lo <= f["z2_drift"]["hr"] <= hi + NEAR]
    if not ok:
        return None
    f = max(ok, key=lambda x: x["start"])
    d = f["z2_drift"]
    day = datetime.fromtimestamp(f["start"], tz)
    when = f"{day.day} {day.strftime('%b')}"
    ride = f"On {when}: {d['minutes']} min steady at {d['watts']} W, heart rate {d['hr']} on average"
    if d["hr"] <= hi and d["pct"] <= DRIFT_OK:
        verdict, line = "fits", f"{ride}, drifting {max(0, d['pct']):g}%: inside zone 2, as your range says."
    elif d["hr"] <= hi:
        verdict = "lower"
        line = (f"{ride}, drifting {d['pct']:g}%. Over 5% for that long means it wasn't all aerobic: if that "
                f"keeps happening, your zone 2 may top out below {hi}." +
                (" Indoors, heat adds drift too: a fan helps." if f.get("indoor") else ""))
    elif d["pct"] <= DRIFT_OK:
        verdict = "higher"
        line = (f"{ride}, above your range, and it drifted only {max(0, d['pct']):g}%: your zone 2 may reach "
                f"higher than {hi}. Set your own range if you know it.")
    else:
        verdict, line = "above", f"{ride}, above your range, drifting {d['pct']:g}%: that was above zone 2."
    return {"ride_id": f["ride_id"], "date": day.date().isoformat(), "verdict": verdict, "line": line}


ZONE2_KINDS = {"endurance", "long", "easy"}


def ride_line(s: dict | None, rng: list, point: str | None, indoor: bool = False) -> str | None:
    """After a ride, only where zone 2 was the point (`point`: "endurance", "long" or "easy", the recovery spin):
    one line, earned praise or one thing to change. Hard days: the split is shown, nothing said."""
    if not s or point not in ZONE2_KINDS:
        return None
    lo, hi = rng
    what = {"endurance": "zone 2 ride", "long": "long ride", "easy": "easy ride"}[point]
    if s["above"] >= 25:
        how = "ease the trainer down when you pass it" if indoor else "spin the climbs in a low gear to stay there"
        return f"{s['above']}% above zone 2. Easy riding works best kept under {hi}: {how}, and the hard days stay hard."
    if point == "easy":
        return f"{s['in'] + s['below']}% at zone 2 or easier: a proper recovery ride." if s["above"] < 10 else None
    if s["below"] >= 50:
        how = f"raise the trainer until your heart rate sits at {lo}–{hi}" if indoor else f"{lo}–{hi} builds more of the base"
        return f"Mostly below zone 2 ({s['below']}% under {lo}): easier than it needs to be. Next time, {how}."
    if s["in"] >= 70:
        return f"{s['in']}% in zone 2: a textbook {what}."
    return None


def week_line(s: dict | None) -> str | None:
    """The week's time above zone 2, against what polarized training points to (about a fifth, or less)."""
    if not s or s["minutes"] < 60:
        return None
    hard = 100 - EASY_SHARE
    if s["above"] <= hard + 5:
        return f"{s['above']}% of this week was above zone 2: right where it should be."
    return (f"{s['above']}% of this week was above zone 2. Most riders get faster with about {hard}%: keep the easy "
            f"rides easy, and the hard ones hard.")
