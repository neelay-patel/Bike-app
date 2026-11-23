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
# Interval sets: hard efforts repeated with easy riding between ("5 x 1 min hard, 2 min easy"), ridden freely
# or set by the trainer. Found without knowing the rider's FTP, by contrast with the riding around each effort.
SET_CAND = 1.15          # a candidate effort: 10 s power at least this share of the ride's 40th percentile ...
SET_MIN_S = 12           # ... for at least this long
SET_CONTRAST = 1.3       # ... and this much harder than the riding either side of it
SET_REP_MAX_S = 20 * 60
NICE_S = [10, 15, 20, 30, 45, 60, 90, 120, 150, 180, 240, 300, 360, 480, 600, 720, 900, 1200]


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


# --- interval sets ----------------------------------------------------------------------------------

def nice(seconds: float) -> int:
    """The planned-looking length nearest to a measured one (64 s -> 60 s, 33 s -> 30 s)."""
    return min(NICE_S, key=lambda x: abs(math.log(max(seconds, 1) / x)))


def find_sets(power: list, paused: list, cad: list | None = None, hr: list | None = None) -> list[dict]:
    """Interval sets in per-second power: at least three hard efforts of about the same length with about the
    same easy riding between (two will do for efforts of 5 minutes or more). Each set:
    {"start_s", "end_s", "repeat", "seconds", "rest_s" (both rounded to a planned-looking length), "power"
    (the efforts' average), "rest_power", "reps": [{"start_s", "seconds", "power", "cadence", "hr_max"}]}."""
    n = len(power)
    ped = [None if paused[k] or power[k] is None or power[k] < 20 else power[k] for k in range(n)]
    vals = sorted(v for v in ped if v is not None)
    if len(vals) < 600:
        return []
    base = vals[int(len(vals) * 0.4)]
    S = _Sums(ped)
    s10 = [S.mean(k - 5, k + 5) for k in range(n)]
    s3 = [S.mean(k - 1, k + 2) for k in range(n)]
    runs = _runs([v is not None and v >= SET_CAND * base for v in s10], SET_MIN_S)
    merged: list[list[int]] = []
    for a, b in runs:
        if merged and a - merged[-1][1] <= 4:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    efforts = []
    for i, (a, b) in enumerate(merged):
        if b - a > SET_REP_MAX_S:
            continue
        lo = merged[i - 1][1] if i else 0
        hi = merged[i + 1][0] if i + 1 < len(merged) else n
        around = [x for x in (S.mean(max(lo, a - 120), a) if a - max(lo, a - 120) >= 10 else None,
                              S.mean(b, min(hi, b + 120)) if min(hi, b + 120) - b >= 10 else None) if x is not None]
        core = S.mean(a, b)
        if not around or core is None or core < SET_CONTRAST * (sum(around) / len(around)):
            continue
        # Sharpen the edges: where 3 s power crosses halfway between the effort and the riding around it.
        mid = (core + sum(around) / len(around)) / 2
        o = max(lo, a - 15)
        span = _runs([s3[k] is not None and s3[k] >= mid for k in range(o, min(hi, b + 15))], 1)
        if span:
            x, y = max(span, key=lambda r: r[1] - r[0])
            a, b = o + x, o + y
        efforts.append({"a": a, "b": b, "power": S.mean(a, b)})

    def close(st, out):
        secs = sorted(e["b"] - e["a"] for e in st)
        med = secs[len(secs) // 2]
        if len(st) >= 3 or (len(st) == 2 and med >= 300):
            out.append(st)

    groups: list[list[dict]] = []
    cur: list[dict] = []
    for e in efforts:
        if cur:
            secs = sorted(x["b"] - x["a"] for x in cur)
            med = secs[len(secs) // 2]
            gaps = [cur[j + 1]["a"] - cur[j]["b"] for j in range(len(cur) - 1)]
            gap = e["a"] - cur[-1]["b"]
            avg_w = sum(x["power"] for x in cur) / len(cur)
            same = (abs((e["b"] - e["a"]) - med) <= 0.35 * med + 8 and gap <= min(max(3.5 * med, 60), 600)
                    and (not gaps or abs(gap - sorted(gaps)[len(gaps) // 2]) <= 0.5 * sorted(gaps)[len(gaps) // 2] + 10)
                    and 0.75 * avg_w <= e["power"] <= 1.33 * avg_w)
            if same:
                cur.append(e)
                continue
            close(cur, groups)
        cur = [e]
    if cur:
        close(cur, groups)

    def avg(xs, a, b):
        v = [x for x in (xs or [])[a:b] if x is not None and x > 0]
        return sum(v) / len(v) if v else None

    out = []
    for st in groups:
        secs = sorted(e["b"] - e["a"] for e in st)
        gaps = sorted(st[j + 1]["a"] - st[j]["b"] for j in range(len(st) - 1))
        rest_w = [S.mean(st[j]["b"], st[j + 1]["a"]) for j in range(len(st) - 1)]
        reps = [{"start_s": e["a"], "seconds": e["b"] - e["a"], "power": round(e["power"]),
                 "cadence": round(c) if (c := avg(cad, e["a"], e["b"])) else None,
                 "hr_max": round(max(h)) if (h := [x for x in (hr or [])[e["a"]:e["b"] + 30] if x]) else None}
                for e in st]
        # Harder with the cadence well down is the trainer's climbs on a virtual course, not intervals.
        rc = [c for j in range(len(st) - 1) if (c := avg(cad, st[j]["b"], st[j + 1]["a"]))]
        ec = [r["cadence"] for r in reps if r["cadence"]]
        if rc and ec and sum(ec) / len(ec) < sum(rc) / len(rc) - 10:
            continue
        inner = [S.sd(e["a"] + 8, e["b"] - 8) for e in st if e["b"] - e["a"] >= 40]
        held = bool(inner) and all(x is not None and x <= max(STEADY_SD_W, 0.04 * e["power"]) * 1.5
                                   for x, e in zip(inner, st))
        out.append({"start_s": st[0]["a"], "end_s": st[-1]["b"], "repeat": len(st), "held": held,
                    "seconds": nice(secs[len(secs) // 2]), "rest_s": nice(gaps[len(gaps) // 2]),
                    "power": round(sum(r["power"] * r["seconds"] for r in reps) / sum(r["seconds"] for r in reps)),
                    "rest_power": round(sum(w for w in rest_w if w) / max(1, sum(1 for w in rest_w if w))),
                    "reps": reps})
    return out


def say_length(seconds: int) -> str:
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min" if seconds % 60 == 0 else f"{seconds / 60:g} min"


def say_set(s: dict, hard_word: str = "hard") -> str:
    """'5 × 1 min hard at 188–229 W (211 on average), 2 min easy between'."""
    ws = [r["power"] for r in s["reps"]]
    watts = f"at {min(ws)}–{max(ws)} W ({s['power']} on average)" if max(ws) - min(ws) >= 5 else f"at {s['power']} W"
    if s["seconds"] >= 300:
        hard_word = "steady"
    return (f"{s['repeat']} × {say_length(s['seconds'])} {hard_word} {watts}, "
            f"{say_length(s['rest_s'])} easy between")


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
        return {"basis": basis, "phases": [], "pushes": [], "drift": None, "lines": [], "series": [], "sets": []}
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

    # Interval sets (power only), ridden freely or set by the trainer: where one overlaps a workout of steady
    # blocks, the set tells it better ("5 x 1 min hard, 2 min easy between").
    sets = find_sets(power, paused, cad, hr) if with_power else []
    free_sets = [x for x in sets if x["start_s"] >= warm_end - 60 and x["end_s"] <= cool_start + 60]
    structured = [st for st in structured
                  if not any(x["start_s"] < st[-1]["end"] and st[0]["start"] < x["end_s"] for x in free_sets)]
    if free_sets and free_sets[0]["start_s"] - first <= 25 * 60 and warm_end > first:
        warm_end = free_sets[0]["start_s"]      # the easy riding before the first set is the warm-up

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
    for x in free_sets:
        for k in range(x["start_s"], x["end_s"]):
            label[k] = "intervals"
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
        if kind == "intervals":
            out["sets"] = [x for x in free_sets if a <= x["start_s"] < b]
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
           "sets": sets,
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
            if "sets" in a:
                merged["sets"] = a["sets"] + f.get("sets", [])
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
    for i, f in enumerate(found):
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
        elif k == "intervals":
            for x in f.get("sets", []):
                cs = [r["cadence"] for r in x["reps"] if r["cadence"]]
                out.append(say_set(x) + (", each held within a few watts (the trainer setting the power)" if x["held"] else "")
                           + (f", at {round(sum(cs) / len(cs))} rpm." if cs else "."))
        elif k == "riding" and f["minutes"] >= 2 and i + 1 < len(found) and found[i + 1]["kind"] == "intervals" \
                and i and found[i - 1]["kind"] == "intervals":
            out.append(f"Easy between the sets, {_min(f['minutes'])}" +
                       (f" at {f['power']} W." if watts and f["power"] else "."))
        elif k == "riding" and f["minutes"] >= 2:
            after = any(w["kind"] in ("structured", "intervals") and w["end_s"] <= f["start_s"] for w in found)
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
