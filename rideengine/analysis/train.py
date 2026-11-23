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
          "sprint": "Sprints", "over_unders": "Over-unders", "group": "Group ride", "endurance": "Endurance",
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
    """Hard efforts: 30 s power reaches HARD x FTP, lasting while it stays above HARD_HOLD x FTP."""
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
            out.append({"seconds": (b - a) * STEP_S, "watts": round(sum(vals) / len(vals))})
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

def against(session: dict, w: dict) -> dict | None:
    """Planned against ridden, set by set: the session (with its targets filled in, plan.targets) and the ride's
    stored work. {"summary", "lines": [...], "sets": [{"set", "planned", "done", "power", "watts", "target",
    "verdict"}]}, or None when the session has no sets or the ride no power."""
    import math
    planned = [st for st in session.get("steps") or [] if st.get("repeat")]
    sets = w.get("sets") or []
    if not planned or w.get("basis") != "power":
        return None
    rows, lines, used = [], [], -1
    for ps in planned:
        on = ps["steps"][0]
        label = f"{ps['repeat']} × {say_length(on['seconds'])} {on['label'].lower()}"
        tgt = (on.get("target") or {}).get("watts")
        k = next((i for i, x in enumerate(sets) if i > used and abs(math.log(x["seconds"] / on["seconds"])) < 0.45), None)
        if k is None:
            rows.append({"set": label, "planned": ps["repeat"], "done": 0, "power": None, "watts": None,
                         "target": tgt, "verdict": "missing", "length": say_length(on["seconds"]),
                         "label": on["label"].lower()})
            lines.append(f"{label}: not found in the ride.")
            continue
        used = k
        x = sets[k]
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
    # What came after the last set, against the easy riding the plan had there.
    last = sets[used] if used >= 0 else None
    tail = planned[-1]
    idx = (session.get("steps") or []).index(tail)
    after_plan = [st for st in (session.get("steps") or [])[idx + 1:] if not st.get("repeat")]
    p30 = w.get("p30") or []
    if last and after_plan and p30:
        a = last["end_s"] // STEP_S
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
    return {"summary": summary, "short": short, "lines": lines, "sets": rows}
