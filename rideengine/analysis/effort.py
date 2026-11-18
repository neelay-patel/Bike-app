"""Efforts: what a session was, not just what was recorded.

A recording is one device's start and stop. An effort is what the rider did: the real session with its
false starts folded in (and other rides of the same kind in the same outing), split into phases worked
out from the samples:

- pause:       stopped pedalling for PAUSE_S or more
- warm_up:     the easy opening, until power (or heart rate) reaches the session's working level
- structured:  steady blocks held to within a few watts, back to back: a workout with the trainer
               setting the power (ERG), as a Zwift or plan workout does
- riding:      the rider's own riding; harder pushes inside it are listed (indoors these are usually
               the climbs: the trainer adds resistance and cadence drops)
- cool_down:   the easy finish

Power leads when the ride has measured power; otherwise heart rate does (no structured blocks then:
heart rate can't show them). Everything is calculated here; `lines` are rule-based words. An AI may
retell them, but only from these numbers.

    group(rides) -> [{"main": index, "parts": [indexes], "folded": [indexes]}]
    phases(ride) -> {"basis", "phases", "pushes", "drift", "lines", "series"}
"""
from __future__ import annotations

import math
from statistics import median

from ..clean import SESSION_GAP_S, hidden_reasons

PAUSE_S = 20             # stopped this long (or longer) is a pause
STEADY_WINDOW_S = 30     # steadiness is judged over this window
STEADY_SD_W = 5.0        # ... power within this many watts (or 4%, whichever is more) is "held"
BLOCK_MIN_S = 45         # a steady block lasts at least this long
CHAIN_GAP_S = 180        # blocks this close are one workout (a free minute inside a workout stays in it)
PAUSE_PHASE_S = 60       # pauses this long are a phase of their own; shorter ones are counted, not cut out
STRUCTURED_MIN_S = 8 * 60
STRUCTURED_MIN_BLOCKS = 3
WARM_LEVEL = 0.8         # warm-up ends when 2-min power reaches this share of the working level
COOL_LEVEL = 0.7
PUSH_SHARE = 1.12        # a push: 30 s power (or torque: same watts, lower cadence) this far above the riding's median ...
PUSH_MIN_S = 45          # ... for at least this long
SERIES_STEP_S = 15


# --- grouping ---------------------------------------------------------------------------------------

def group(rides: list) -> list[dict]:
    """Efforts, oldest first. Rides of the same kind (indoor or outdoor) within SESSION_GAP_S of each other
    are one effort; false starts and empty recordings fold into the effort they sit next to. `main` is the
    longest part, whose id the effort takes."""
    hide = hidden_reasons(rides)
    order = sorted(range(len(rides)), key=lambda i: rides[i].start)
    efforts: list[dict] = []
    for i in order:
        if i in hide:
            continue
        last = efforts[-1] if efforts else None
        if last and rides[last["parts"][0]].indoor == rides[i].indoor \
                and rides[i].start - rides[last["parts"][-1]].end <= SESSION_GAP_S:
            last["parts"].append(i)
        else:
            efforts.append({"parts": [i], "folded": []})
    alone = []
    for i in order:
        if i not in hide:
            continue
        r = rides[i]
        near = [e for e in efforts
                if min(abs(r.start - rides[e["parts"][-1]].end), abs(rides[e["parts"][0]].start - r.end)) <= SESSION_GAP_S]
        near.sort(key=lambda e: (rides[e["parts"][0]].indoor != r.indoor,
                                 min(abs(r.start - rides[e["parts"][-1]].end), abs(rides[e["parts"][0]].start - r.end))))
        if near:
            near[0]["folded"].append(i)
        else:
            alone.append({"parts": [i], "folded": []})
    out = efforts + alone
    for e in out:
        e["main"] = max(e["parts"], key=lambda k: rides[k].end - rides[k].start)
        e["hidden"] = all(k in hide for k in e["parts"])
        e["reasons"] = {k: hide[k] for k in e["parts"] + e["folded"] if k in hide}
    return sorted(out, key=lambda e: rides[e["parts"][0]].start)


# --- per-second series --------------------------------------------------------------------------------

def _per_second(ride, attr: str, fill_s: int) -> list:
    t0 = ride.start
    n = max(1, int(ride.end - t0) + 1)
    total, count = [0.0] * n, [0] * n
    for s in ride.samples:
        v = getattr(s, attr)
        if v is None:
            continue
        k = int(s.t - t0)
        if 0 <= k < n:
            total[k] += v
            count[k] += 1
    out: list = [None] * n
    last, since = None, fill_s + 1
    for k in range(n):
        if count[k]:
            last, since = total[k] / count[k], 0
            out[k] = last
        else:
            since += 1
            out[k] = last if since <= fill_s else None
    return out


class _Sums:
    """Window means and standard deviations over a series with gaps (None)."""

    def __init__(self, xs: list):
        self.s, self.q, self.c = [0.0], [0.0], [0]
        for x in xs:
            v = x if x is not None else 0.0
            self.s.append(self.s[-1] + v)
            self.q.append(self.q[-1] + v * v)
            self.c.append(self.c[-1] + (x is not None))

    def mean(self, a: int, b: int):
        a, b = max(a, 0), min(b, len(self.c) - 1)
        n = self.c[b] - self.c[a] if b > a else 0
        return (self.s[b] - self.s[a]) / n if n else None

    def sd(self, a: int, b: int):
        a, b = max(a, 0), min(b, len(self.c) - 1)
        n = self.c[b] - self.c[a] if b > a else 0
        if n < 2:
            return None
        m = (self.s[b] - self.s[a]) / n
        return math.sqrt(max(0.0, (self.q[b] - self.q[a]) / n - m * m))


def _runs(flags: list[bool], min_len: int) -> list[tuple[int, int]]:
    out, start = [], None
    for k, f in enumerate(flags + [False]):
        if f and start is None:
            start = k
        elif not f and start is not None:
            if k - start >= min_len:
                out.append((start, k))
            start = None
    return out


def _avg(xs, lo, hi, positive=False):
    v = [x for x in xs[lo:hi] if x is not None and (x > 0 or not positive)]
    return sum(v) / len(v) if v else None


# --- phases -----------------------------------------------------------------------------------------

def phases(ride) -> dict:
    power = _per_second(ride, "power", 5)
    cad = _per_second(ride, "cadence", 5)
    hr = _per_second(ride, "hr", 20)
    speed = _per_second(ride, "speed", 5)
    n = len(power)
    with_power = bool(ride.provenance.get("channel:power")) and sum(p is not None for p in power) > n / 2
    basis = "power" if with_power else "heart_rate"
    sig = power if with_power else hr

    # Pauses: not pedalling (power) or not moving (outdoors without power).
    if with_power:
        stopped = [p is None or p < 20 for p in power]
    elif not ride.indoor and any(s is not None for s in speed):
        stopped = [s is None or s < 0.6 for s in speed]
    else:
        stopped = [c is not None and c < 10 for c in cad]
    pauses = _runs(stopped, PAUSE_S if with_power else 60)
    paused = [False] * n
    for a, b in pauses:
        for k in range(a, b):
            paused[k] = True
    working = [sig[k] for k in range(n) if not paused[k] and sig[k] is not None]
    if len(working) < 120:
        return {"basis": basis, "phases": [], "pushes": [], "drift": None, "lines": [], "series": []}
    level = median(working)
    sums = _Sums([None if paused[k] else sig[k] for k in range(n)])
    first = next(k for k in range(n) if not paused[k] and sig[k] is not None)
    last = max(k for k in range(n) if not paused[k] and sig[k] is not None) + 1

    # Warm-up: until the 2-minute level reaches WARM_LEVEL of the working level (heart rate: 93%).
    warm_share = WARM_LEVEL if with_power else 0.93
    warm_end = first
    for k in range(first, min(last, first + 25 * 60)):
        m = sums.mean(k, k + 120)
        if m is not None and m >= warm_share * level:
            warm_end = k
            break
    short_ride = last - first < 30 * 60    # a short ride (an errand, a commute) has no warm-up or cool-down
    if warm_end - first < 3 * 60 or short_ride:
        warm_end = first
    cool_share = COOL_LEVEL if with_power else 0.9
    cool_start = last
    for k in range(last, max(warm_end, last - 20 * 60), -1):
        m = sums.mean(k - 120, k)
        if m is not None and m >= cool_share * level:
            cool_start = k
            break
    if last - cool_start < 2 * 60 or short_ride:
        cool_start = last

    # Structured blocks (power only): steady over STEADY_WINDOW_S, between the warm-up and cool-down.
    blocks: list[dict] = []
    if with_power:
        raw = _Sums([None if paused[k] else power[k] for k in range(n)])
        h = STEADY_WINDOW_S // 2
        steady = [False] * n
        for k in range(warm_end, cool_start):
            m, sd = raw.mean(k - h, k + h), raw.sd(k - h, k + h)
            steady[k] = m is not None and sd is not None and m >= 40 and sd <= max(STEADY_SD_W, 0.04 * m)
        for a, b in _runs(steady, max(1, BLOCK_MIN_S - 2 * h)):
            a, b = max(warm_end, a - h), min(cool_start, b + h)
            if b - a < BLOCK_MIN_S:
                continue
            w = raw.mean(a, b)
            if blocks and a - blocks[-1]["end"] <= 10 and abs(w - blocks[-1]["power"]) <= 5:
                blocks[-1]["end"] = b
                blocks[-1]["power"] = raw.mean(blocks[-1]["start"], b)
            else:
                blocks.append({"start": max(a, blocks[-1]["end"]) if blocks else a, "end": b, "power": w})
    stretches: list[list[dict]] = []
    for b in blocks:
        if stretches and b["start"] - stretches[-1][-1]["end"] <= CHAIN_GAP_S:
            stretches[-1].append(b)
        else:
            stretches.append([b])
    structured = []
    for st in stretches:
        span = st[-1]["end"] - st[0]["start"]
        held = sum(b["end"] - b["start"] for b in st)
        if len(st) >= STRUCTURED_MIN_BLOCKS and span >= STRUCTURED_MIN_S and held >= 0.6 * span:
            structured.append(st)

    # Label every second, then cut into phases.
    label = ["riding"] * n
    for k in range(n):
        if k < first or k >= last:
            label[k] = "none"
        elif k < warm_end:
            label[k] = "warm_up"
        elif k >= cool_start:
            label[k] = "cool_down"
    for st in structured:
        for k in range(st[0]["start"], st[-1]["end"]):
            label[k] = "structured"
    for a, b in pauses:
        if b - a < PAUSE_PHASE_S:
            continue
        for k in range(a, b):
            if label[k] != "none":
                label[k] = "pause"
    segs: list[list] = []
    for k in range(n):
        if label[k] == "none":
            continue
        if segs and segs[-1][0] == label[k] and segs[-1][2] == k:
            segs[-1][2] = k + 1
        else:
            segs.append([label[k], k, k + 1])
    # Bits of riding under a minute between other phases belong to them.
    tidy: list[list] = []
    for s in segs:
        if s[0] == "riding" and s[2] - s[1] < 60 and tidy:
            tidy[-1][2] = s[2]
        elif tidy and tidy[-1][0] == s[0]:
            tidy[-1][2] = s[2]
        else:
            tidy.append(s)

    def stats(kind, a, b):
        p = _avg(power, a, b, positive=True)
        c = _avg(cad, a, b, positive=True)
        hv = [x for x in hr[a:b] if x is not None]
        out = {"kind": kind, "start_s": a, "end_s": b, "minutes": round((b - a) / 60, 1),
               "power": round(p) if p is not None and with_power else None,
               "cadence": round(c) if c is not None else None,
               "hr": round(sum(hv) / len(hv)) if hv else None, "hr_max": round(max(hv)) if hv else None,
               "torque_nm": round(p / (c * 2 * math.pi / 60), 1) if with_power and p and c else None}
        if kind == "structured":
            out["blocks"] = [{"start_s": b_["start"], "seconds": b_["end"] - b_["start"], "power": round(b_["power"])}
                             for st in structured for b_ in st if a <= b_["start"] < b]
        return out

    found = [stats(k, a, b) for k, a, b in tidy]

    # Pushes inside the rider's own riding (power only).
    pushes = []
    if with_power:
        own = [k for k in range(n) if label[k] == "riding" and power[k] is not None and not paused[k]]
        if len(own) >= 5 * 60:
            torque = [power[k] / (cad[k] * 2 * math.pi / 60) if label[k] == "riding" and power[k] and cad[k] and cad[k] >= 40
                      else None for k in range(n)]
            base = median(power[k] for k in own)
            tq = [x for x in torque if x is not None]
            base_t = median(tq) if len(tq) >= 5 * 60 else None
            raw = _Sums([power[k] if label[k] == "riding" and not paused[k] else None for k in range(n)])
            rt = _Sums(torque)
            hard = [label[k] == "riding" and ((raw.mean(k - 15, k + 15) or 0) >= PUSH_SHARE * base or
                                              (base_t is not None and (rt.mean(k - 15, k + 15) or 0) >= PUSH_SHARE * base_t))
                    for k in range(n)]
            for a, b in _runs(hard, PUSH_MIN_S):
                if pushes and a - pushes[-1]["end_s"] <= 30:
                    a = pushes.pop()["start_s"]
                pushes.append({"start_s": a, "end_s": b})
            pushes = [{**stats("push", x["start_s"], x["end_s"]), "seconds": x["end_s"] - x["start_s"]} for x in pushes]

    drift = _drift(found, power, hr) if with_power else None
    short = [(a, b) for a, b in pauses if b - a < PAUSE_PHASE_S and first <= a < last]
    series = []
    for a in range(0, n, SERIES_STEP_S):
        p, hv = _avg(power, a, a + SERIES_STEP_S), _avg(hr, a, a + SERIES_STEP_S)
        series.append([a, round(p) if p is not None and with_power else None, round(hv) if hv is not None else None])
    climbs = []
    if sum(1 for x in ride.samples if x.lat is not None and x.ele is not None) >= 10:
        from .climbs import find_climbs
        climbs = [{k: c[k] for k in ("km_into_ride", "length_m", "gain_m", "grade", "seconds", "avg_hr", "avg_power")}
                  | {"start_s": round(c["date_t"] - ride.start)} for c in find_climbs(ride)]
    out = {"basis": basis, "indoor": ride.indoor, "phases": found, "pushes": pushes, "drift": drift, "series": series,
           "climbs": climbs, "short_pauses": {"count": len(short), "seconds": sum(b - a for a, b in short)}}
    out["lines"] = lines(out)
    return out


def _drift(found: list[dict], power: list, hr: list):
    """Heart rate at the same power, early against late: the first and last working phases of 8 min or more,
    compared minute by minute in 10 W bands both share (skipping each phase's first 3 minutes, while heart
    rate catches up)."""
    work = [f for f in found if f["kind"] in ("structured", "riding") and f["minutes"] >= 8]
    if len(work) < 2:
        return None

    def bands(f):
        out: dict[int, list[float]] = {}
        for a in range(f["start_s"] + 180, f["end_s"] - 59, 60):
            p, h = _avg(power, a, a + 60, positive=True), _avg(hr, a, a + 60)
            ctx = _avg(power, a - 120, a + 60, positive=True)
            # Only minutes after two steady ones: heart rate lags, so a minute after a hard push reads high.
            if p and h and ctx and abs(ctx - p) <= 0.08 * p:
                out.setdefault(int(p // 10), []).append(h)
        return out

    early, late = bands(work[0]), bands(work[-1])
    shared = [b for b in early if b in late]
    if len(shared) < 2:
        return None
    diff = sum(sum(late[b]) / len(late[b]) - sum(early[b]) / len(early[b]) for b in shared) / len(shared)
    return {"bpm": round(diff), "bands_w": [b * 10 for b in sorted(shared)],
            "early": work[0]["kind"], "late": work[-1]["kind"]}


# --- words ------------------------------------------------------------------------------------------

def _min(m: float) -> str:
    m = round(m)
    return f"{m // 60}:{m % 60:02d}" if m >= 60 else f"{m} min"


def _joined(found: list[dict]) -> list[dict]:
    """Phases for the words: the same kind either side of a stop is one phase (minutes added, averages
    weighted by time); the stops are told separately."""
    out: list[dict] = []
    for f in found:
        if f["kind"] == "pause":
            continue
        if out and out[-1]["kind"] == f["kind"]:
            a, m1, m2 = out[-1], out[-1]["minutes"], f["minutes"]
            merged = dict(a, end_s=f["end_s"], minutes=round(m1 + m2, 1))
            for k in ("power", "cadence", "hr", "torque_nm"):
                if a.get(k) is not None and f.get(k) is not None:
                    v = (a[k] * m1 + f[k] * m2) / (m1 + m2)
                    merged[k] = round(v, 1) if k == "torque_nm" else round(v)
            merged["hr_max"] = max(x for x in (a.get("hr_max"), f.get("hr_max"), 0) if x is not None) or None
            if "blocks" in a:
                merged["blocks"] = a["blocks"] + f.get("blocks", [])
            out[-1] = merged
        else:
            out.append(dict(f))
    return out


def _range(xs: list, unit: str) -> str:
    lo, hi = min(xs), max(xs)
    return f"{lo} {unit}" if lo == hi else f"{lo}–{hi} {unit}"


def _length(seconds: list) -> str:
    if max(seconds) < 90:
        return _range(seconds, "s")
    return _range([round(x / 60) for x in seconds], "min")


def lines(p: dict) -> list[str]:
    """What happened, in order, rule-based."""
    out: list[str] = []
    found = _joined(p["phases"])
    watts = p["basis"] == "power"
    work = [f for f in found if f["kind"] in ("structured", "riding")]
    for f in found:
        k = f["kind"]
        if k == "warm_up":
            out.append(f"Warm-up, {_min(f['minutes'])}" + (f", at about {f['power']} W." if watts and f["power"]
                                                            else f", heart rate rising to {f['hr_max']}." if f["hr_max"] else "."))
        elif k == "structured":
            bl = f["blocks"]
            ws = [b["power"] for b in bl]
            text = f"A structured workout, {_min(f['minutes'])}: "
            mid = (min(ws) + max(ws)) / 2
            hard = [b for b in bl if b["power"] >= mid]
            easy = [b for b in bl if b["power"] < mid]
            if easy and max(ws) - min(ws) >= 0.2 * max(ws):
                text += (f"{len(hard)} work block{'s' if len(hard) > 1 else ''} of {_length([b['seconds'] for b in hard])} "
                         f"at {_range([b['power'] for b in hard], 'W')}, with easier {_length([b['seconds'] for b in easy])} "
                         f"at {_range([b['power'] for b in easy], 'W')} between")
            else:
                text += f"{len(bl)} steady blocks of {_length([b['seconds'] for b in bl])} at {_range(ws, 'W')}"
            out.append(text + f", each held within a few watts (the trainer setting the power), at {f['cadence']} rpm. "
                              f"Heart rate {f['hr']} on average, up to {f['hr_max']}.")
        elif k == "riding" and f["minutes"] >= 2:
            after = any(w["kind"] == "structured" and w["end_s"] <= f["start_s"] for w in work)
            head = "Then your own riding" if after else "Riding"
            if watts and f["power"]:
                text = f"{head}, {_min(f['minutes'])} at {f['power']} W, {f['cadence']} rpm, heart rate {f['hr']}"
                before = [w for w in work if w["kind"] == "structured" and w["end_s"] <= f["start_s"]]
                if before and before[-1]["power"]:
                    d = f["power"] - before[-1]["power"]
                    if abs(d) >= 5:
                        text += f": {abs(d)} W {'harder' if d > 0 else 'easier'} than the workout"
                out.append(text + ".")
                inside = [x for x in p["pushes"] if f["start_s"] <= x["start_s"] < f["end_s"]]
                if inside:
                    ws = [x["power"] for x in inside]
                    cs = [x["cadence"] for x in inside if x["cadence"]]
                    held = f["power"] and max(ws) < PUSH_SHARE * f["power"]   # harder by torque, not watts
                    noun = "heavier stretch" if held else "harder push"
                    text = (f"{len(inside)} {noun}{'es' if len(inside) > 1 else ''} of {_length([x['seconds'] for x in inside])} "
                            f"at {_range(ws, 'W')}")
                    if cs and f["cadence"] and f["cadence"] - min(cs) >= 3:
                        text += f", cadence down to {min(cs)} rpm"
                    if held:
                        text += " (power held, more force on the pedals)"
                    out.append(text + (": likely the climbs." if p.get("indoor") else "."))
            else:
                out.append(f"{head}, {_min(f['minutes'])} at heart rate {f['hr']}" +
                           (f", up to {f['hr_max']}." if f["hr_max"] else "."))
        elif k == "cool_down":
            out.append(f"Cool-down, {_min(f['minutes'])}.")
    cl = p.get("climbs") or []
    if cl:
        big = max(cl, key=lambda c: c["gain_m"])
        what = "virtual climb" if p.get("indoor") else "climb"
        text = (f"{len(cl)} {what}s, the biggest {big['gain_m']} m over {big['length_m'] / 1000:.1f} km ({big['grade']}%)"
                if len(cl) > 1 else f"One {what}: {big['gain_m']} m over {big['length_m'] / 1000:.1f} km ({big['grade']}%)")
        if big.get("avg_power") and watts:
            text += f", at {big['avg_power']} W"
        elif big.get("avg_hr"):
            text += f", heart rate {big['avg_hr']}"
        out.append(text + ".")
    stops = [f for f in p["phases"] if f["kind"] == "pause"]
    short = p.get("short_pauses") or {"count": 0, "seconds": 0}
    count = len(stops) + short["count"]
    if count:
        total = sum(f["minutes"] for f in stops) + short["seconds"] / 60
        words = _min(total) if total >= 1 else "under a minute"
        out.append(f"{count} pauses, {words} in all." if count > 1 else f"One pause, {words}.")
    d = p.get("drift")
    if d and d["bpm"] >= 3:
        out.append(f"Late on, the same power cost more heart rate: about {d['bpm']} beats higher at "
                   f"{d['bands_w'][0]}–{d['bands_w'][-1] + 10} W than earlier, the usual sign of tiring (or a warm room).")
    elif d and d["bpm"] <= -3:
        out.append(f"Heart rate was about {-d['bpm']} beats lower at the same power late on: you settled in.")
    return out
