"""Train, step 1 (docs/train-tab.md): what kind of training each ride was, and which planned session it counts as.

Three parts:

    work(ride)                       -> compact facts stored with the ride's features (no FTP needed): 30 s
                                        power every 10 s, the trainer's steady blocks, heart rate every 10 s
    classify(work, ftp, max_hr, rest)-> {"kind", "confidence", "reason", "facts"}: surges, steady (sweet spot),
                                        threshold, vo2, endurance, long, easy or mixed, with the reason in plain
                                        words (docs/train-words.md: no jargon, "what you could hold for an hour")
    match_week(sessions, rides)      -> each planned session's ride, by what the ride contained, whatever the day

Power leads when the ride has it; heart rate can only tell easy from hard, so those rides classify with lower
confidence. Everything here is calculated; an AI may retell the reasons, never change them.
"""
from __future__ import annotations

from .effort import _per_second, say_length

STEP_S = 10              # one value every 10 seconds
ROLL_S = 30              # of 30-second rolling power (or heart rate)

# Shares of FTP (what the rider could hold for about an hour).
HARD = 1.18              # a hard effort's 30 s power reaches this ...
HARD_HOLD = 1.05         # ... and it lasts while 30 s power stays above this
SURGE_S = (20, 180)      # surges: hard efforts this long
VO2_S = (150, 480)       # longer hard efforts (3-5 minutes and so)
VO2_LEVEL = 1.06
SS = (0.84, 0.97)        # sweet spot band, judged on 5-minute rolling power
THR = (0.97, 1.08)       # threshold band
BLOCK_SS = (0.80, 0.97)  # the trainer's steady blocks (ERG) count as sweet spot in this band ...
BLOCK_THR = (0.97, 1.08)  # ... and threshold in this one
EASY_AP = 0.65
ENDURANCE_AP = 0.86
LONG_MIN = 150
MIN_MINUTES = 15         # shorter rides don't count as a session
HR_SS = (0.76, 0.86)     # heart-rate reserve bands for steady work on rides without power ...
HR_THR = (0.86, 0.93)
HR_STEADY_MIN = 20       # ... held for at least this long

TITLES = {"surges": "Surges", "steady": "Sweet spot", "threshold": "Threshold", "vo2": "VO2 max",
          "sprint": "Sprints", "over_unders": "Over-unders", "group": "Group ride", "endurance": "Zone 2",
          "long": "Long ride", "easy": "Easy spin", "mixed": "Mixed riding"}

# How well a ride of one kind (rows) does the job of a planned session (columns). Same kind: 1.0.
COMPAT = {
    "surges": {"group": 0.7, "vo2": 0.6, "over_unders": 0.6, "sprint": 0.5},
    "steady": {"threshold": 0.8, "endurance": 0.6, "group": 0.5, "long": 0.5},
    "threshold": {"steady": 0.85, "over_unders": 0.7, "group": 0.6},
    "vo2": {"surges": 0.7, "threshold": 0.5, "group": 0.5, "over_unders": 0.6},
    "endurance": {"long": 0.8, "easy": 0.6, "group": 0.3},
    "long": {"endurance": 1.0, "group": 0.3},
    "easy": {"endurance": 0.5},
    # Hard riding without power to show its pattern (mostly outdoor rides with heart rate only): it can stand in
    # for the group ride or the surges, since indoors or out is the rider's choice.
    "mixed": {"group": 0.8, "surges": 0.6, "endurance": 0.4, "long": 0.4},
}
COUNTS = 0.4             # below this a ride doesn't count as the session


# --- facts stored with each ride ---------------------------------------------------------------------

def _rolling(xs: list, half: int) -> list:
    """Centred rolling mean of a per-second series, skipping gaps."""
    n = len(xs)
    total = [0.0] * (n + 1)
    count = [0] * (n + 1)
    for k, v in enumerate(xs):
        total[k + 1] = total[k] + (v or 0.0)
        count[k + 1] = count[k] + (v is not None)
    out = []
    for k in range(n):
        a, b = max(0, k - half), min(n, k + half)
        c = count[b] - count[a]
        out.append((total[b] - total[a]) / c if c >= half else None)
    return out


def work(ride) -> dict:
    """What the ride contained, independent of the rider's FTP, so it's stored once and judged later."""
    power = _per_second(ride, "power", 5)
    hr = _per_second(ride, "hr", 20)
    n = len(power)
    with_power = bool(ride.provenance.get("channel:power")) and sum(p is not None for p in power) > n / 2
    out: dict = {"basis": None, "p30": [], "h30": [], "c30": [], "blocks": [], "pushes": [], "drift": None,
                 "minutes": 0, "sets": []}
    cad = _per_second(ride, "cadence", 5)
    if sum(c is not None and c >= 20 for c in cad) >= 300:     # five minutes of cadence or more
        r = _rolling([c if c is not None and c >= 20 else None for c in cad], ROLL_S // 2)
        out["c30"] = [None if v is None else round(v) for v in r[::STEP_S]]
    if with_power:
        pedal = [p if p is not None and p >= 20 else None for p in power]
        r = _rolling(pedal, ROLL_S // 2)
        out["p30"] = [None if v is None else round(v) for v in r[::STEP_S]]
        out["minutes"] = round(sum(p is not None for p in pedal) / 60)
        out["basis"] = "power"
        from .effort import phases
        ph = phases(ride)
        out["blocks"] = [[b["seconds"], b["power"]] for p_ in ph["phases"] if p_["kind"] == "structured"
                         for b in p_.get("blocks", [])]
        # The harder pushes inside the rider's own riding (indoors, mostly the climbs): [start s, seconds, W, rpm].
        out["pushes"] = [[x["start_s"], x["seconds"], x["power"], x["cadence"]] for x in ph["pushes"]]
        out["drift"] = ph["drift"]["bpm"] if ph.get("drift") else None
        # Interval sets, the same ones the ride's own page describes (effort.find_sets).
        out["sets"] = [{k: x[k] for k in ("start_s", "end_s", "repeat", "seconds", "rest_s", "power", "rest_power")}
                       | {"reps": [[r["seconds"], r["power"]] for r in x["reps"]]} for x in ph.get("sets", [])]
    if not with_power and any(h is not None for h in hr):     # heart rate only matters when there's no power
        r = _rolling(hr, ROLL_S // 2)
        out["h30"] = [None if v is None else round(v) for v in r[::STEP_S]]
        out["basis"] = "heart_rate"
        out["minutes"] = round(sum(h is not None for h in hr) / 60)
    return out


# --- what kind of training it was ---------------------------------------------------------------------

def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    out, a = [], None
    for k, f in enumerate(flags + [False]):
        if f and a is None:
            a = k
        elif not f and a is not None:
            out.append((a, k))
            a = None
    return out


def _efforts(p30: list, ftp: float) -> list[dict]:
    """Hard efforts: 30 s power reaches HARD x FTP, lasting while it stays above HARD_HOLD x FTP.
    Each {"start_s", "seconds", "watts"}."""
    out = []
    k, n = 0, len(p30)
    while k < n:
        if p30[k] is not None and p30[k] >= HARD * ftp:
            a = k
            while a > 0 and p30[a - 1] is not None and p30[a - 1] >= HARD_HOLD * ftp:
                a -= 1
            b = k
            while b < n and p30[b] is not None and p30[b] >= HARD_HOLD * ftp:
                b += 1
            vals = [v for v in p30[a:b] if v is not None]
            out.append({"start_s": a * STEP_S, "seconds": (b - a) * STEP_S, "watts": round(sum(vals) / len(vals))})
            k = b
        else:
            k += 1
    return out


def say_sets(xs: list[dict]) -> str:
    """'5 × 1 min at about 219 W and 5 × 30 s at about 255 W'."""
    parts = [f"{x['repeat']} × {say_length(x['seconds'])} at about {x['power']} W" for x in xs]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _span(seconds: list[int]) -> str:
    def one(s):
        return f"{s} s" if s < 90 else f"{round(s / 60)} min"
    lo, hi = min(seconds), max(seconds)
    if hi < 90:
        return f"{lo}–{hi} s" if lo != hi else f"{lo} s"
    return one(lo) + " to " + one(hi) if one(lo) != one(hi) else one(hi)


def classify(w: dict, ftp: float | None, max_hr: float | None = None, rest_hr: float | None = None) -> dict:
    """The ride's kind of training, how sure, and why in plain words. FTP in watts (what the rider could hold
    for about an hour); heart rate is used when there's no power."""
    minutes = w.get("minutes") or 0
    if minutes < MIN_MINUTES:
        return {"kind": None, "confidence": 0.0, "reason": "Too short to count as a session.", "facts": {}}
    if w.get("basis") == "power" and ftp:
        return _by_power(w, ftp, minutes)
    return _by_heart_rate(w, max_hr, rest_hr, minutes)


def _by_power(w: dict, ftp: float, minutes: int) -> dict:
    p30 = w["p30"]
    vals = [v for v in p30 if v is not None]
    ap = sum(vals) / len(vals)
    np_ = (sum(v ** 4 for v in vals) / len(vals)) ** 0.25
    efforts = _efforts(p30, ftp)
    surges = [e for e in efforts if SURGE_S[0] <= e["seconds"] <= SURGE_S[1]]
    longer = [e for e in efforts if VO2_S[0] <= e["seconds"] <= VO2_S[1] and e["watts"] >= VO2_LEVEL * ftp]
    # Minutes of 5-minute rolling power in the sweet spot and threshold bands.
    r5 = _rolling(p30, 15)
    ss_min = sum(1 for v in r5 if v is not None and SS[0] * ftp <= v < SS[1] * ftp) * STEP_S / 60
    thr_min = sum(1 for v in r5 if v is not None and THR[0] * ftp <= v < THR[1] * ftp) * STEP_S / 60
    blocks_ss = [b for b in w.get("blocks", []) if BLOCK_SS[0] * ftp <= b[1] < BLOCK_SS[1] * ftp]
    blocks_thr = [b for b in w.get("blocks", []) if BLOCK_THR[0] * ftp <= b[1] < BLOCK_THR[1] * ftp]
    ss_block_min = sum(b[0] for b in blocks_ss) / 60
    thr_block_min = sum(b[0] for b in blocks_thr) / 60

    def watts(bs):
        return round(sum(b[0] * b[1] for b in bs) / sum(b[0] for b in bs))

    def held(lo, hi):
        vs = [v for v in r5 if v is not None and lo * ftp <= v < hi * ftp]
        return round(sum(vs) / len(vs)) if vs else round(ap)

    cand: dict[str, tuple[float, str]] = {}
    if len(surges) >= 4:
        cand["surges"] = (min(0.95, 0.55 + 0.05 * len(surges)),
                          f"{len(surges)} hard efforts of {_span([e['seconds'] for e in surges])}, "
                          f"at {min(e['watts'] for e in surges)}–{max(e['watts'] for e in surges)} W, "
                          f"with easier riding between.")
    if len(longer) >= 3:
        cand["vo2"] = (0.9, f"{len(longer)} hard efforts of {_span([e['seconds'] for e in longer])} "
                            f"at about {round(sum(e['watts'] for e in longer) / len(longer))} W.")
    if ss_block_min >= 12:
        cand["steady"] = (min(0.97, 0.7 + ss_block_min / 100),
                          f"{len(blocks_ss)} steady blocks, {round(ss_block_min)} minutes in all, at about "
                          f"{watts(blocks_ss)} W: just below what you could hold for an hour.")
    elif ss_min >= 15:
        cand["steady"] = (min(0.9, 0.45 + ss_min / 60),
                          f"{round(ss_min)} minutes of steady work at about {held(*SS)} W: just below what you "
                          f"could hold for an hour.")
    if thr_block_min >= 12:
        cand["threshold"] = (min(0.97, 0.7 + thr_block_min / 100),
                             f"{len(blocks_thr)} steady blocks, {round(thr_block_min)} minutes in all, at about "
                             f"{watts(blocks_thr)} W: right at what you could hold for an hour.")
    elif thr_min >= 15:
        cand["threshold"] = (min(0.95, 0.5 + thr_min / 60),
                             f"{round(thr_min)} minutes held at about {held(*THR)} W: right around what you could "
                             f"hold for an hour.")
    if ap <= EASY_AP * ftp and minutes < 75:
        cand["easy"] = (0.8, f"{minutes} minutes, light all the way, at about {round(ap)} W.")
    if ap <= ENDURANCE_AP * ftp and len(surges) <= 3:
        extra = (" with a few harder efforts" if surges else "")
        if minutes >= LONG_MIN:
            cand["long"] = (0.85, f"{minutes} minutes of steady riding at about {round(ap)} W{extra}.")
        if minutes >= 40:
            cand.setdefault("endurance", (0.75, f"{minutes} minutes of steady riding at about {round(ap)} W, "
                                                f"mostly comfortable{extra}."))
    # Interval sets found in the ride (effort.find_sets) say it best, in the same words as the ride's own page.
    sets = w.get("sets") or []
    if sets:
        hard_sets = [x for x in sets if x["power"] >= HARD_HOLD * ftp]
        short = [x for x in hard_sets if SURGE_S[0] <= x["seconds"] <= SURGE_S[1]]
        mid = [x for x in hard_sets if VO2_S[0] <= x["seconds"] <= VO2_S[1] and x["power"] >= VO2_LEVEL * ftp]
        if sum(x["repeat"] for x in short) >= 4:
            cand["surges"] = (min(0.97, 0.65 + 0.04 * sum(x["repeat"] for x in short)),
                              f"Hard efforts: {say_sets(short)}, with easy riding between.")
        if sum(x["repeat"] for x in mid) >= 3:
            cand["vo2"] = (0.93, f"Hard efforts: {say_sets(mid)}, with easy riding between.")
        for kind, band, words in (("steady", SS, "just below"), ("threshold", THR, "right at")):
            held_sets = [x for x in sets if x["seconds"] >= 300 and band[0] * ftp <= x["power"] < band[1] * ftp]
            by_blocks = (ss_block_min if kind == "steady" else thr_block_min) >= 12   # the trainer's blocks say it
            if sum(x["repeat"] * x["seconds"] for x in held_sets) >= 12 * 60 and not by_blocks:
                cand[kind] = (0.95, f"{say_sets(held_sets)}: {words} what you could hold for an hour.")
    if not cand:
        cand["mixed"] = (0.5, f"{minutes} minutes of varied riding at about {round(ap)} W, hard and easy mixed "
                              f"with no set pattern.")
    kind = max(cand, key=lambda k: cand[k][0])
    conf, reason = cand[kind]
    return {"kind": kind, "confidence": round(conf, 2), "reason": reason,
            "facts": {"minutes": minutes, "sets": [{k: x[k] for k in ("repeat", "seconds", "rest_s", "power")}
                                                   for x in sets], "avg_w": round(ap), "np_w": round(np_), "ftp_w": round(ftp),
                      "surges": len(surges), "longer_efforts": len(longer), "sweet_spot_min": round(ss_min),
                      "threshold_min": round(thr_min), "steady_blocks": len(w.get("blocks", []))}}


def _by_heart_rate(w: dict, max_hr: float | None, rest_hr: float | None, minutes: int) -> dict:
    hs = [v for v in w.get("h30", []) if v is not None]
    if not hs:
        return {"kind": "mixed", "confidence": 0.3, "reason": f"{minutes} minutes of riding; no power or heart rate "
                                                             f"to tell what kind.", "facts": {"minutes": minutes}}
    avg = sum(hs) / len(hs)
    facts = {"minutes": minutes, "avg_hr": round(avg)}
    if not max_hr or not rest_hr or max_hr <= rest_hr:
        return {"kind": "mixed", "confidence": 0.3, "reason": f"{minutes} minutes at heart rate {round(avg)}.",
                "facts": facts}
    share = (avg - rest_hr) / (max_hr - rest_hr)        # heart-rate reserve
    hard = sum(1 for v in hs if (v - rest_hr) / (max_hr - rest_hr) >= 0.8) * STEP_S / 60
    facts |= {"hr_reserve": round(share, 2), "hard_min": round(hard)}
    if share < 0.5 and minutes < 75:
        return {"kind": "easy", "confidence": 0.6, "facts": facts,
                "reason": f"{minutes} minutes at an easy heart rate, {round(avg)} on average."}
    # Steady work by heart rate: 5-minute rolling heart-rate reserve in the sweet spot or threshold band. Heart
    # rate lags short efforts, so only long steady stretches are judged this way.
    hs5 = _rolling(w.get("h30", []), 15)
    def band(lo, hi):
        return sum(1 for v in hs5 if v is not None and lo <= (v - rest_hr) / (max_hr - rest_hr) < hi) * STEP_S / 60
    ss_min, thr_min = band(*HR_SS), band(*HR_THR)
    facts |= {"sweet_spot_min": round(ss_min), "threshold_min": round(thr_min)}
    if minutes < LONG_MIN and thr_min >= HR_STEADY_MIN:
        return {"kind": "threshold", "confidence": 0.5, "facts": facts,
                "reason": f"{round(thr_min)} minutes at a hard, steady heart rate, close to what you could hold for "
                          f"an hour (judged by heart rate: no power on this ride)."}
    if minutes < LONG_MIN and ss_min >= HR_STEADY_MIN:
        return {"kind": "steady", "confidence": 0.5, "facts": facts,
                "reason": f"{round(ss_min)} minutes at a steady, comfortably hard heart rate: sweet spot by feel "
                          f"(judged by heart rate: no power on this ride)."}
    if minutes >= LONG_MIN and share < 0.85:
        return {"kind": "long", "confidence": 0.7, "facts": facts,
                "reason": f"{minutes} minutes in the saddle, heart rate {round(avg)} on average."}
    if share < 0.75 and hard < 15:
        return {"kind": "endurance", "confidence": 0.55, "facts": facts,
                "reason": f"{minutes} minutes at a steady heart rate, {round(avg)} on average."}
    return {"kind": "mixed", "confidence": 0.45, "facts": facts,
            "reason": f"{minutes} minutes of harder riding by heart rate ({round(hard)} minutes near your limit); "
                      f"without power the efforts themselves can't be seen."}


# --- which jobs a ride did (docs/train-method.md) -------------------------------------------------------
# A week is a set of jobs, and any ride that fits can do one. This reads which jobs a ride did and how much of
# each, from what it contained; the week's plan (step 2) says how much of each job it wants.

JOBS = ("punch", "top_end", "hold", "long", "easy")
JOB_TITLES = {"punch": "Punch", "top_end": "Top end", "hold": "Hold", "long": "Long", "easy": "Easy"}
# What each job builds, in the rider's words (docs/train-method.md, the jobs table).
JOB_BUILDS = {"punch": "answering accelerations and closing gaps",
              "top_end": "the hardest few minutes: a long climb, a breakaway",
              "hold": "the power you can keep for the whole ride",
              "long": "endurance for long rides",
              "easy": "the base everything sits on, and recovery"}
JOB_WANT_MIN = {"punch": 5, "top_end": 10, "hold": 20}   # minutes of the job's work that make it done
PUNCH_S = (10, 149)      # punch: hard efforts this long (sprints too) ...
TOP_END_S = (150, 480)   # ... top end: these, at VO2_LEVEL or more
HOLD = (0.84, 1.08)      # hold: steady work in this band of FTP (sweet spot to threshold) ...
HOLD_STEADY = (0.75, 1.15)  # ... with 30 s power staying in this one (steady, not surging) ...
HOLD_RUN_S = 180         # ... for at least this long at a time
LONG_SHARE = 0.8         # a ride of 80% of the week's long-ride time does the long job
LONG_DEFAULT_MIN = 150   # the long ride's time when there's no plan to say
LONG_FLOOR_MIN = 90      # and never less than this: an hour's ride isn't a long one
TWO_HARD_MIN = 90        # a ride does a second hard job only when it's this long and the second is done in full
EASY_MIN = 20
SHOW = 0.2               # less of a job than this isn't mentioned
MORE = 1.5               # this much of a job or more: "and then some"
HR_PUNCH = 0.85          # rides with heart rate only: rises to this share of heart-rate reserve count as punch ...
HR_TOP_END = 0.9         # ... and long ones at this share as top end


def _hm(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m} min" if m < 60 else f"{m // 60} h" + (f" {m % 60:02d}" if m % 60 else "")


def _mins(seconds: float) -> str:
    """Minutes of work, to the half minute: '7.5 min', '12 min', '45 s'."""
    s = round(seconds / 30) * 30
    return say_length(int(s)) if s >= 60 else f"{round(seconds)} s"


def _and(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _in_sets(t: int, sets: list[dict]) -> bool:
    return any(x["start_s"] - STEP_S <= t <= x["end_s"] + STEP_S for x in sets)


def _hard_work(w: dict, ftp: float) -> dict:
    """Seconds of punch and top-end work, with what they were: the ride's interval sets (effort.find_sets), then
    hard efforts outside them."""
    sets = w.get("sets") or []
    out = {"punch": {"s": 0.0, "parts": []}, "top_end": {"s": 0.0, "parts": []}}
    for x in sets:
        reps = [r for r in x["reps"] if r[1] >= HARD_HOLD * ftp]
        if not reps or _over_unders(x, ftp):
            continue
        job = ("punch" if x["seconds"] <= PUNCH_S[1] else
               "top_end" if x["seconds"] <= TOP_END_S[1] and x["power"] >= VO2_LEVEL * ftp else None)
        if job:
            out[job]["s"] += sum(r[0] for r in reps)
            out[job]["parts"].append(f"{len(reps)} × {say_length(x['seconds'])}")
    loose = {"punch": [], "top_end": []}
    for e in _efforts(w.get("p30") or [], ftp):
        if _in_sets(e["start_s"], sets):
            continue
        if PUNCH_S[0] <= e["seconds"] <= PUNCH_S[1]:
            loose["punch"].append(e)
        elif TOP_END_S[0] <= e["seconds"] <= TOP_END_S[1] and e["watts"] >= VO2_LEVEL * ftp:
            loose["top_end"].append(e)
    for job, es in loose.items():
        if es:
            out[job]["s"] += sum(e["seconds"] for e in es)
            out[job]["parts"].append(f"{len(es)} hard effort{'s' if len(es) > 1 else ''} of "
                                     f"{_span([e['seconds'] for e in es])}")
            out[job]["loose"] = True
    return out


def _over_unders(x: dict, ftp: float) -> bool:
    """A set whose easy part is still at sweet spot: over-unders, hold work all the way through."""
    return x.get("rest_power") is not None and x["rest_power"] >= HOLD[0] * ftp


def _hold_work(w: dict, ftp: float) -> dict:
    """Seconds of steady work just below or at what the rider could hold for an hour: held sets, the trainer's
    steady blocks, and steady stretches of the rider's own riding (at least 3 minutes each)."""
    sets = w.get("sets") or []
    held = [x for x in sets if x["seconds"] >= 300 and HOLD[0] * ftp <= x["power"] < HOLD[1] * ftp]
    ou = [x for x in sets if _over_unders(x, ftp) and x not in held]
    set_s = sum(x["repeat"] * x["seconds"] for x in held) + sum(x["repeat"] * (x["seconds"] + x["rest_s"]) for x in ou)
    blocks = [b for b in w.get("blocks") or [] if BLOCK_SS[0] * ftp <= b[1] < BLOCK_THR[1] * ftp]
    block_s = sum(b[0] for b in blocks)
    p30 = w.get("p30") or []
    r5 = _rolling(p30, 15)
    flags = [p is not None and r is not None and HOLD[0] * ftp <= r < HOLD[1] * ftp
             and HOLD_STEADY[0] * ftp <= p < HOLD_STEADY[1] * ftp and not _in_sets(k * STEP_S, sets)
             for k, (p, r) in enumerate(zip(p30, r5))]
    runs = [(a, b) for a, b in _runs(flags) if (b - a) * STEP_S >= HOLD_RUN_S]
    free_s = sum(b - a for a, b in runs) * STEP_S
    free_w = [p30[k] for a, b in runs for k in range(a, b)]
    parts, ws = [], []          # ws: (seconds, watts) for the average
    if held:
        parts.append(say_sets(held))
        ws += [(x["repeat"] * x["seconds"], x["power"]) for x in held]
    for x in ou:
        parts.append(f"{x['repeat']} × {say_length(x['seconds'])} over, {say_length(x['rest_s'])} under")
        ws += [(x["repeat"] * x["seconds"], x["power"]), (x["repeat"] * x["rest_s"], x["rest_power"])]
    if max(block_s, free_s) > 0:
        if block_s >= free_s:
            bw = round(sum(b[0] * b[1] for b in blocks) / block_s)
            parts.append(f"{len(blocks)} steady block{'s' if len(blocks) > 1 else ''} on the trainer, "
                         f"{_mins(block_s)} at about {bw} W")
            ws += [(b[0], b[1]) for b in blocks]
        else:
            fw = round(sum(free_w) / len(free_w))
            parts.append(f"{_mins(free_s)} of steady riding at about {fw} W")
            ws += [(STEP_S, v) for v in free_w]
    total = sum(t for t, _ in ws)
    return {"s": set_s + max(block_s, free_s), "parts": parts,
            "watts": round(sum(t * v for t, v in ws) / total) if total else None}


def _hr_work(w: dict, max_hr: float | None, rest_hr: float | None) -> dict:
    """Rides with heart rate only: a rough read. Rises to near the limit stand in for hard efforts (heart rate
    lags, so it can't see their shape); steady stretches in the sweet-spot-to-threshold band for hold."""
    out = {"punch": {"s": 0.0, "parts": []}, "top_end": {"s": 0.0, "parts": []}, "hold": {"s": 0.0, "parts": []}}
    h30 = w.get("h30") or []
    if not h30 or not max_hr or not rest_hr or max_hr <= rest_hr:
        return out
    def res(v):
        return None if v is None else (v - rest_hr) / (max_hr - rest_hr)
    for a, b in _runs([res(v) is not None and res(v) >= HR_PUNCH for v in h30]):
        s = (b - a) * STEP_S
        vals = [res(v) for v in h30[a:b]]
        if s >= TOP_END_S[0] and sum(vals) / len(vals) >= HR_TOP_END:
            out["top_end"]["s"] += min(s, TOP_END_S[1])
        elif s >= PUNCH_S[0]:
            out["punch"]["s"] += min(s, PUNCH_S[1])
    # Heart rate drifts up over long rides, so steady work is only read from it on shorter ones.
    if len(h30) * STEP_S < LONG_MIN * 60:
        hs5 = _rolling(h30, 15)
        flags = [v is not None and HR_SS[0] <= res(v) < HR_THR[1] for v in hs5]
        out["hold"]["s"] = sum(b - a for a, b in _runs(flags) if (b - a) * STEP_S >= 300) * STEP_S
    return out


def jobs_done(w: dict, ftp: float | None, max_hr: float | None = None, rest_hr: float | None = None,
              minutes: float | None = None, long_min: float | None = None, want: dict | None = None) -> dict:
    """Which jobs a ride did, and how much of each. w: the ride's stored work; minutes: its moving time (default:
    the work's own minutes); long_min: the week's long-ride time; want: minutes of each hard job that make it
    done (default JOB_WANT_MIN; the week's plan sets them as the rider grows).
    {"jobs": [{"job", "title", "status": done|more|part, "have_min", "want_min", "left_min", "line", "basis"}],
     "also": [jobs also done in full that a short ride doesn't count], "summary", "basis"}. One ride does at most two hard jobs (the second only on a long ride, in full), plus the
    long job; easy only when it did nothing hard."""
    want = {**JOB_WANT_MIN, **(want or {})}
    minutes = minutes if minutes is not None else (w.get("minutes") or 0)
    out = {"jobs": [], "also": [], "summary": None, "basis": w.get("basis")}
    if minutes < MIN_MINUTES:
        return out
    basis = w.get("basis")
    if basis == "power" and ftp:
        work = _hard_work(w, ftp) | {"hold": _hold_work(w, ftp)}
        vals = [v for v in w.get("p30") or [] if v is not None]
        easy_ride = bool(vals) and sum(vals) / len(vals) <= ENDURANCE_AP * ftp
    else:
        work = _hr_work(w, max_hr, rest_hr)
        hs = [v for v in w.get("h30") or [] if v is not None]
        easy_ride = (not hs or not max_hr or not rest_hr or max_hr <= rest_hr or
                     (sum(hs) / len(hs) - rest_hr) / (max_hr - rest_hr) < 0.75)
    by = " (judged by heart rate: a rough read without power)" if basis != "power" else ""

    def entry(job, have, target, detail):
        frac = have / target if target else 0
        left = max(0.0, target - have)
        if frac >= MORE:
            t = _mins(target * 60)
            line = f"{JOB_TITLES[job]}, and then some: {detail}, where the week asked for {t[:-4] if t.endswith(' min') else t}."
            status = "more"
        elif frac >= 1:
            line = f"{JOB_TITLES[job]}: done. {detail}."
            status = "done"
        else:
            a, b = _mins(have * 60), _mins(target * 60)
            if a.endswith(" min") and b.endswith(" min"):
                a = a[:-4]
            line = f"{JOB_TITLES[job]}: {a} of {b} done. {_mins(left * 60)} more finishes it."
            status = "part"
        return {"job": job, "title": JOB_TITLES[job], "status": status, "have_min": round(have, 1),
                "want_min": target, "left_min": round(left, 1), "line": line + (by if job != "long" else ""),
                "basis": basis, "detail": detail}

    hard = []
    for job in ("punch", "top_end", "hold"):
        have = work[job]["s"] / 60
        if have / want[job] < SHOW:
            continue
        parts = work[job]["parts"]
        total = _mins(have * 60)
        if job == "hold":
            watts = work[job].get("watts")
            detail = ("; ".join(parts) + (f", {total} in all" if len(parts) > 1 else "") if parts else
                      f"{total} of steady work" + (f" at about {watts} W" if watts else ""))
        elif work[job].get("loose") or not parts:
            detail = (_and(parts) + f", {total} in all") if parts else f"{total} of hard efforts"
        else:
            detail = _and(parts) + f", {total} of hard efforts"
        hard.append((have / want[job], entry(job, have, want[job], detail)))
    # The job the ride did in full leads; between two done in full, the harder (punch or top end over hold).
    hard.sort(key=lambda x: (x[0] < 1, x[0] >= 1 and x[1]["job"] == "hold", -x[0]))
    jobs = [e for _, e in hard[:1]]
    also = []
    for frac, e in hard[1:]:
        if frac >= 1 and minutes >= TWO_HARD_MIN and len(jobs) < 2:
            jobs.append(e)
        elif frac >= 1:
            # Good work, but a short ride does one hard job: the week still has this one to come (we lean
            # toward more, docs/train-method.md).
            also.append({**e, "status": "also",
                         "line": f"Also {e['detail']}: good {e['title'].lower()} work on top; the week's "
                                 f"{e['title'].lower()} job is still to come{by}."})
    long_want = max(LONG_FLOOR_MIN, round(LONG_SHARE * (long_min or LONG_DEFAULT_MIN) / 5) * 5)
    if minutes >= long_want:
        jobs.append({"job": "long", "title": "Long", "status": "done", "have_min": round(minutes),
                     "want_min": long_want, "left_min": 0,
                     "line": f"Long: done. {_hm(minutes)} in the saddle.", "basis": basis})
    if not hard and not jobs and easy_ride and minutes >= EASY_MIN:
        jobs.append({"job": "easy", "title": "Easy", "status": "done", "have_min": round(minutes), "want_min": EASY_MIN,
                     "left_min": 0, "line": f"Easy: done. {_hm(minutes)} of easy riding.", "basis": basis})
    out["jobs"] = jobs
    out["also"] = also
    if jobs:
        words = {"done": "done", "more": "and then some", "part": "partly done"}
        said = [f"{j['title']}, {words[j['status']]}" for j in jobs]
        out["summary"] = "; ".join(said[:1] + [s[0].lower() + s[1:] for s in said[1:]]) + "."
    return out


# --- the week as jobs (docs/train-method.md, build step 2) ----------------------------------------------

def _slot_want(session: dict, long_min: float | None) -> float:
    """Minutes of its job a planned session asks: its own hard minutes, the long ride's share, or any easy ride."""
    from .plan import JOB_OF, job_minutes
    job = JOB_OF.get(session["kind"])
    if job == "long":
        return max(LONG_FLOOR_MIN, round(LONG_SHARE * (session.get("seconds") or 0) / 60 / 5) * 5)
    if job == "easy":
        return EASY_MIN
    return job_minutes(session).get(job) or JOB_WANT_MIN.get(job, 5)


def count_jobs(sessions: list[dict], rides: list[dict], overrides: dict | None = None) -> dict:
    """The week by jobs, not workouts: each ride's jobs (jobs_done) fill the week's sessions of the same job,
    whatever the workout and whatever the day. sessions: the week's planned sessions; rides: the week's rides,
    oldest first, each {"ride_id", "date", "jobs": jobs_done(...) or None}; overrides: {ride_id: session_id or
    None} set by the rider. A session is done when its job is done in full, by one ride or several; partly done
    leaves the rest open, said in a line. Returns {"counted": {session_id: {"ride_id", "rides", "reason",
    "by_hand"?}}, "progress": {session_id: {"job", "have_min", "want_min", "left_min", "line", "rides"}},
    "extra": [ride_id], "ride_jobs": {ride_id: [{"job", "session_id"}]}}."""
    from .plan import JOB_OF
    overrides = overrides or {}
    slots = {s["id"]: {"session": s, "job": JOB_OF.get(s["kind"]), "want": _slot_want(s, None), "have": 0.0,
                       "rides": []} for s in sessions if not s.get("off_bike")}
    counted: dict[str, dict] = {}
    ride_jobs: dict[str, list] = {}
    extra = []
    for r in rides:
        rid = r["ride_id"]
        if rid in overrides:              # the rider's own call stands
            sid = overrides[rid]
            if sid in slots and sid not in counted:
                counted[sid] = {"ride_id": rid, "rides": [rid], "reason": None, "by_hand": True}
                ride_jobs[rid] = [{"job": slots[sid]["job"], "session_id": sid}]
            else:
                extra.append(rid)
            continue
        used = []
        for j in (r.get("jobs") or {}).get("jobs", []):
            open_ = [x for x in slots.values() if x["job"] == j["job"] and x["session"]["id"] not in counted]
            if not open_:
                continue
            d = r["date"]
            # A slot already started first, then the one planned nearest the ride's day (the earlier on a tie).
            slot = min(open_, key=lambda x: (not x["have"], abs((_d(x["session"]["date"]) - _d(d)).days),
                                             x["session"]["date"]))
            add = slot["want"] if j["job"] in ("long", "easy") else j["have_min"]
            slot["have"] += add
            slot["rides"].append(rid)
            sid = slot["session"]["id"]
            used.append({"job": j["job"], "session_id": sid})
            if slot["have"] >= slot["want"] - 0.05:
                reason = (f"{j['title']}: done. {j['detail']}." if j["status"] == "part" and j.get("detail")
                          else j["line"])
                counted[sid] = {"ride_id": rid, "rides": list(slot["rides"]), "reason": reason}
        if used:
            ride_jobs[rid] = used
        else:
            extra.append(rid)
    progress = {}
    for sid, x in slots.items():
        if sid in counted or not x["have"]:
            continue
        a, b = _mins(x["have"] * 60), _mins(x["want"] * 60)
        if a.endswith(" min") and b.endswith(" min"):
            a = a[:-4]
        left = x["want"] - x["have"]
        progress[sid] = {"job": x["job"], "have_min": round(x["have"], 1), "want_min": x["want"],
                         "left_min": round(left, 1), "rides": x["rides"],
                         "line": f"{JOB_TITLES.get(x['job'], x['job'])}: {a} of {b} done. "
                                 f"{_mins(left * 60)} more finishes it."}
    return {"counted": counted, "progress": progress, "extra": extra, "ride_jobs": ride_jobs}


def _d(s):
    from datetime import date
    return s if isinstance(s, date) else date.fromisoformat(s)


# --- which session each ride counts as -----------------------------------------------------------------

def fit(ride_class: dict, ride_minutes: float, session: dict) -> float:
    """How well a ride does the job of a planned session, 0..1."""
    rk, sk = ride_class.get("kind"), session["kind"]
    if rk is None or session.get("off_bike"):
        return 0.0
    c = 1.0 if rk == sk else COMPAT.get(rk, {}).get(sk, 0.0)
    want = (session.get("seconds") or 0) / 60
    if want and ride_minutes < 0.6 * want:
        c *= 0.6
    return c * (0.5 + 0.5 * ride_class.get("confidence", 0.5))


def match_week(sessions: list[dict], rides: list[dict], overrides: dict | None = None) -> dict:
    """sessions: the week's planned sessions ({"id", "kind", "seconds", "off_bike"}). rides: the week's rides
    ({"ride_id", "minutes", "class"}). overrides: {ride_id: session_id or None} the rider set by hand.
    Returns {"counted": {session_id: {"ride_id", "fit", "reason"}}, "extra": [ride_ids]}: the pairing with the
    best total fit, whatever the days, each ride counting once and each session once."""
    overrides = overrides or {}
    counted: dict[str, dict] = {}
    taken: set[str] = set()
    by_id = {s["id"]: s for s in sessions}
    for r in rides:
        if r["ride_id"] in overrides:
            sid = overrides[r["ride_id"]]
            if sid in by_id and sid not in counted:
                counted[sid] = {"ride_id": r["ride_id"], "fit": None, "reason": r["class"].get("reason"), "by_hand": True}
            taken.add(r["ride_id"])
    free_rides = [r for r in rides if r["ride_id"] not in taken]
    free_sessions = [s for s in sessions if s["id"] not in counted and not s.get("off_bike")]
    scores = [[fit(r["class"], r.get("minutes") or 0, s) for s in free_sessions] for r in free_rides]

    best = (0.0, [])

    def search(i: int, used: frozenset, total: float, pairs: list):
        nonlocal best
        if i == len(free_rides):
            if total > best[0] + 1e-9:
                best = (total, list(pairs))
            return
        # Upper bound: every remaining ride at its best free session.
        bound = total + sum(max([scores[k][j] for j in range(len(free_sessions)) if j not in used] or [0])
                            for k in range(i, len(free_rides)))
        if bound <= best[0] + 1e-9:
            return
        for j in range(len(free_sessions)):
            if j not in used and scores[i][j] >= COUNTS:
                pairs.append((i, j))
                search(i + 1, used | {j}, total + scores[i][j], pairs)
                pairs.pop()
        search(i + 1, used, total, pairs)

    search(0, frozenset(), 0.0, [])
    paired = set()
    for i, j in best[1]:
        r, s = free_rides[i], free_sessions[j]
        counted[s["id"]] = {"ride_id": r["ride_id"], "fit": round(scores[i][j], 2), "reason": r["class"].get("reason")}
        paired.add(r["ride_id"])
    extra = [r["ride_id"] for r in free_rides if r["ride_id"] not in paired]
    return {"counted": counted, "extra": extra}


# --- the ride against the session it counts as ----------------------------------------------------------

def against(session: dict, w: dict, indoor: bool = False, feel: str | None = None) -> dict | None:
    """Planned against ridden, set by set: the session (with its targets filled in, plan.targets) and the ride's
    stored work. {"summary", "lines": [...], "sets": [{"set", "planned", "done", "power", "watts", "target",
    "verdict"}]}, or None when the session has no sets or the ride no power."""
    import math
    planned = [st for st in session.get("steps") or [] if st.get("repeat")]
    sets = w.get("sets") or []
    if not planned or w.get("basis") != "power":
        return None
    from . import pacing
    rows, lines, used = [], [], -1
    steady, extra_lines, last_end = [], [], None
    for ps in planned:
        on = ps["steps"][0]
        label = f"{ps['repeat']} × {say_length(on['seconds'])} {on['label'].lower()}"
        tgt = (on.get("target") or {}).get("watts")
        if on["seconds"] >= pacing.STEADY_S:
            # Steady reps aren't hard efforts: found in the power by their length (rideengine/analysis/pacing.py).
            rd = pacing.read(on, ps["repeat"], w.get("p30") or [], w.get("c30") or [])
            reps = (rd or {}).get("reps") or []
            if not reps:
                rows.append({"set": label, "planned": ps["repeat"], "done": 0, "power": None, "watts": None,
                             "target": tgt, "verdict": "missing", "length": say_length(on["seconds"]),
                             "label": on["label"].lower()})
                lines.append(f"{label}: not found in the ride.")
                continue
            ws = [r["watts"] for r in reps]
            avg = round(sum(ws) / len(ws))
            # Each rep is the job: one under the floor puts the set under, whatever the average.
            verdict = ("below" if tgt and min(ws) < tgt[0] else "above" if tgt and avg > tgt[1] else
                       "on" if tgt else "done")
            rows.append({"set": label, "planned": ps["repeat"], "done": len(reps), "power": avg,
                         "watts": [min(ws), max(ws)], "target": tgt, "verdict": verdict,
                         "length": say_length(on["seconds"]), "label": on["label"].lower(), "reps": reps})
            count = (f"all {ps['repeat']}" if len(reps) == ps["repeat"] else f"{len(reps)} of {ps['repeat']}")
            text = f"{label}: {count}, {avg} W on average"
            if tgt:
                text += ({"above": f", above the {tgt[0]}–{tgt[1]} W planned",
                          "on": f", inside the {tgt[0]}–{tgt[1]} W planned"}.get(verdict) or
                         (f", under the {tgt[0]}–{tgt[1]} W planned" if avg < tgt[0] else
                          f"; {sum(1 for x in ws if x < tgt[0])} of {len(ws)} under the {tgt[0]}–{tgt[1]} W planned"))
            lines.append(text + ".")
            if any(r["pattern"] != "on" for r in reps):
                extra_lines += rd["lines"]
            steady.append({"read": rd, "label": on["label"].lower()})
            last_end = rd["spans"][-1][1]
            continue
        k = next((i for i, x in enumerate(sets) if i > used and abs(math.log(x["seconds"] / on["seconds"])) < 0.45), None)
        if k is None:
            rows.append({"set": label, "planned": ps["repeat"], "done": 0, "power": None, "watts": None,
                         "target": tgt, "verdict": "missing", "length": say_length(on["seconds"]),
                         "label": on["label"].lower()})
            lines.append(f"{label}: not found in the ride.")
            continue
        used = k
        x = sets[k]
        last_end = x["end_s"] // STEP_S
        ws = [r[1] for r in x["reps"]]
        verdict = ("above" if tgt and x["power"] > tgt[1] else "below" if tgt and x["power"] < tgt[0]
                   else "on" if tgt else "done")
        rows.append({"set": label, "planned": ps["repeat"], "done": x["repeat"], "power": x["power"],
                     "watts": [min(ws), max(ws)], "target": tgt, "verdict": verdict,
                     "length": say_length(on["seconds"]), "label": on["label"].lower()})
        count = (f"all {ps['repeat']}" if x["repeat"] == ps["repeat"] else
                 f"{x['repeat']} of {ps['repeat']}" if x["repeat"] < ps["repeat"] else
                 f"{x['repeat']} ({ps['repeat']} planned)")
        text = f"{label}: {count}, {x['power']} W on average"
        if tgt:
            text += {"above": f", above the {tgt[0]}–{tgt[1]} W planned", "below": f", under the {tgt[0]}–{tgt[1]} W planned",
                     "on": f", inside the {tgt[0]}–{tgt[1]} W planned"}[verdict]
        lines.append(text + ".")
    lines += extra_lines
    # What came after the last set, against the easy riding the plan had there.
    tail = planned[-1]
    idx = (session.get("steps") or []).index(tail)
    after_plan = [st for st in (session.get("steps") or [])[idx + 1:] if not st.get("repeat")]
    p30 = w.get("p30") or []
    if last_end is not None and after_plan and p30:
        a = last_end
        vals = [v for v in p30[a:] if v is not None]
        if len(vals) * STEP_S >= 5 * 60:
            mins = round(len(vals) * STEP_S / 60)
            avg = round(sum(vals) / len(vals))
            plan_min = round(sum(st["seconds"] for st in after_plan) / 60)
            hi = max(((st.get("target") or {}).get("watts") or [0, 0])[1] for st in after_plan)
            if hi and avg > 1.1 * hi:
                lines.append(f"Then {mins} min at {avg} W, where the plan had {plan_min} min easy (up to {hi} W).")
    hit = [r for r in rows if r["verdict"] != "missing"]
    full = all(r["done"] >= r["planned"] for r in rows)
    if not hit:
        summary = "The session's sets weren't found in this ride."
    elif full and steady and all(r["verdict"] in ("on", "above", "done") for r in hit) and any(
            rp["pattern"] not in ("on", "over") for x in steady for rp in x["read"]["reps"]):
        summary = "Every set done, inside the targets on average, with some minutes under."
    elif full and all(r["verdict"] in ("on", "done") for r in hit):
        summary = "Ridden as planned."
    elif full and all(r["verdict"] in ("on", "above", "done") for r in hit):
        summary = "Ridden as planned, harder than the targets."
    elif full:
        summary = "Every set done, some under the targets."
    else:
        summary = "Part of the session: " + ", ".join(f"{r['done']} of {r['planned']} {r['set'].split(' ', 2)[2]}"
                                                     for r in rows if r["done"] < r["planned"]) + "."
    # In a few words, for the ride card: "5 × 1 min and 5 × 30 s hard, as planned."
    short = None
    if hit:
        short = " and ".join(f"{r['done']} × {r['length']}" for r in hit) + f" {hit[0]['label']}"
        short += ", as planned." if full else f": {sum(r['done'] for r in rows)} of the {sum(r['planned'] for r in rows)} planned."
    nxt = None
    for x in steady:
        nxt = nxt or pacing.next_time(x["read"], indoor, feel, label=x["label"])
    return {"summary": summary, "short": short, "lines": lines, "sets": rows, "next_time": nxt}
