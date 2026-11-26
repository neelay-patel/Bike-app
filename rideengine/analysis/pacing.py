"""How a session's steady reps were ridden against their targets: each rep found in the ride, where it fell short
(under throughout, started low, faded, or dipped in and out), whether cadence went with it, and one specific thing to
do next time (docs/train-method.md "Short of the target"). Standard library only.

Steady reps (3 minutes or more: sweet spot, threshold, tempo) are found in the ride's 30-second rolling power by
their length: the best stretches of that length, as many as the session asks for, that don't overlap. Hard efforts
(shorter) are read by train.against from the ride's sets instead."""
from __future__ import annotations

STEP_S = 10              # the work stream: one value every 10 seconds
STEADY_S = 180           # reps this long or longer are read here
FOUND = 0.80             # a stretch counts as the rep when it averages this share of the target's floor or more
UNDER_MIN = 2.0          # this many minutes under the floor in a rep is worth saying
FADE = 0.95              # the last third of a rep under this share of the first: it faded
CAD_DROP = 5             # rpm lower in the minutes under the target than in the ones on it
CAD_LOW = 80


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def find_reps(p30: list, seconds: int, n: int, floor: float) -> list[tuple[int, int]]:
    """Up to n non-overlapping stretches of `seconds`, best average first, kept in ride order: (start, end) as
    indexes into the 10-second stream. A stretch averaging under FOUND × floor isn't a rep."""
    L = max(1, round(seconds / STEP_S))
    if len(p30) < L:
        return []
    vals = [v or 0 for v in p30]
    pre = [0.0]
    for v in vals:
        pre.append(pre[-1] + v)
    means = [(pre[i + L] - pre[i]) / L for i in range(len(vals) - L + 1)]
    taken: list[tuple[int, int]] = []
    for _ in range(n):
        best = None
        for i, m in enumerate(means):
            if any(i < e and i + L > s for s, e in taken):
                continue
            if best is None or m > means[best]:
                best = i
        if best is None or means[best] < FOUND * floor:
            break
        taken.append((best, best + L))
    return sorted(taken)


def _minute_word(k: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(k, f"{k}th")


def read_rep(p30: list, c30: list, span: tuple[int, int], target: list) -> dict:
    """One rep against its target: average, minutes under and over, its thirds, its lowest minute and where, the
    pattern (on | under | started_low | faded | dipped | over), and cadence on and under the target."""
    s, e = span
    lo, hi = target
    xs = p30[s:e]
    cs = (c30 or [])[s:e]
    avg = _mean(xs) or 0
    under = [i for i, v in enumerate(xs) if v is not None and v < lo]
    over = [i for i, v in enumerate(xs) if v is not None and v > hi]
    third = max(1, len(xs) // 3)
    thirds = [_mean(xs[:third]), _mean(xs[third:2 * third]), _mean(xs[2 * third:])]
    per_min = [_mean(xs[k:k + 6]) for k in range(0, len(xs), 6)]
    per_min = [m for m in per_min if m is not None]
    low_k = min(range(len(per_min)), key=lambda k: per_min[k]) if per_min else 0
    under_min = len(under) * STEP_S / 60
    if avg > hi:
        pattern = "over"
    elif under_min < UNDER_MIN and avg >= lo:
        pattern = "on"
    elif all(t is not None and t < lo for t in thirds) and avg < lo - 0.03 * lo:
        pattern = "under"
    elif thirds[0] is not None and thirds[0] < lo and all(t is not None and t >= lo for t in thirds[1:]):
        pattern = "started_low"
    elif thirds[2] is not None and thirds[0] and thirds[2] < FADE * thirds[0] and thirds[2] < lo:
        pattern = "faded"
    else:
        pattern = "dipped"
    cad_on = _mean([c for i, c in enumerate(cs) if i not in under and c and c >= 40])
    cad_under = _mean([c for i, c in enumerate(cs) if i in under and c and c >= 40])
    dips = []
    for k, m in enumerate(per_min):            # the minutes under the floor, worst first
        if m < lo:
            dips.append((m, k + 1))
    dips.sort()
    return {"watts": round(avg), "under_min": round(under_min, 1), "over_min": round(len(over) * STEP_S / 60, 1),
            "minutes": round(len(xs) * STEP_S / 60), "thirds": [round(t) if t is not None else None for t in thirds],
            "lowest": {"watts": round(per_min[low_k]) if per_min else None, "minute": low_k + 1},
            "dips": [{"watts": round(m), "minute": k} for m, k in dips[:2]],
            "pattern": pattern,
            "cadence": {"on": round(cad_on) if cad_on else None, "under": round(cad_under) if cad_under else None}}


def _rep_line(i: int, r: dict, target: list, n: int) -> str:
    lo, hi = target
    name = f"Rep {i}" if n > 1 else "The rep"
    w = r["watts"]
    if r["pattern"] == "on":
        return f"{name}: {w} W, inside the {lo}–{hi} W."
    if r["pattern"] == "over":
        return f"{name}: {w} W, above the {lo}–{hi} W."
    under = f"{round(r['under_min'])} of {r['minutes']} min under {lo} W"
    if r["pattern"] == "under":
        return f"{name}: {w} W, under the {lo}–{hi} W from start to finish."
    if r["pattern"] == "started_low":
        return f"{name}: {w} W. It started low ({r['thirds'][0]} W in the first third), then held {r['thirds'][2]} W."
    if r["pattern"] == "faded":
        return f"{name}: {w} W. It faded, from {r['thirds'][0]} W in the first third to {r['thirds'][2]} W in the last."
    dips = " and ".join(f"{d['watts']} W in its {_minute_word(d['minute'])} minute" for d in r["dips"])
    return f"{name}: {w} W, {under}. It dipped to {dips}." if dips else f"{name}: {w} W, {under}."


def read(on: dict, repeat: int, p30: list, c30: list) -> dict | None:
    """A planned steady set (its "on" step, targets filled in) against the ride. None without a watts target."""
    tgt = (on.get("target") or {}).get("watts")
    if not tgt or not p30:
        return None
    spans = find_reps(p30, on["seconds"], repeat, tgt[0])
    reps = [read_rep(p30, c30, sp, tgt) for sp in spans]
    lines = [_rep_line(i + 1, r, tgt, repeat) for i, r in enumerate(reps)] if reps else []
    if reps:
        ons = [r["cadence"]["on"] for r in reps if r["cadence"]["on"]]
        unders = [r["cadence"]["under"] for r in reps if r["cadence"]["under"]]
        cad_on, cad_under = (round(_mean(ons)) if ons else None), (round(_mean(unders)) if unders else None)
        if cad_under and cad_on and (cad_on - cad_under >= CAD_DROP or cad_under < CAD_LOW):
            lines.append(f"Your cadence went down with the watts: {cad_under} rpm in the minutes under, "
                         f"{cad_on} rpm on the target.")
        elif cad_on and any(r["pattern"] != "on" for r in reps):
            lo_c = min(c for r in reps for c in (r["cadence"]["on"], r["cadence"]["under"]) if c)
            hi_c = max(c for r in reps for c in (r["cadence"]["on"], r["cadence"]["under"]) if c)
            lines.append(f"Cadence held {lo_c}–{hi_c} rpm, so it wasn't the gears: the watts just eased off."
                         if lo_c != hi_c else f"Cadence held {lo_c} rpm, so it wasn't the gears.")
    return {"spans": spans, "reps": reps, "lines": lines, "target": tgt}


def next_time(read_: dict, indoor: bool, feel: str | None = None, label: str = "rep") -> dict | None:
    """One thing to do next time, from where the reps fell short (the worst rep's pattern), with the numbers to
    aim for. None when every rep was on the target or above."""
    reps = read_["reps"]
    lo, hi = read_["target"]
    short = [r for r in reps if r["pattern"] not in ("on", "over")]
    if not short:
        return None
    mid = round((lo + hi) / 2 / 5) * 5 if hi - lo >= 5 else round((lo + hi) / 2)
    erg = (f" On the KICKR, set ERG to {mid} W and it holds the watts for you; you only keep the pedals turning."
           if indoor else "")
    order = ["under", "faded", "dipped", "started_low"]
    worst = min(short, key=lambda r: (order.index(r["pattern"]), r["watts"]))
    n = len(reps)
    i = reps.index(worst) + 1
    which = "" if n == 1 else f"rep {i}: "
    if n > 1 and len(short) == n:
        rest = [k + 1 for k, r in enumerate(reps) if k + 1 != i]
        which = f"rep {i} most (rep {', '.join(map(str, rest))} too, less so): " if worst["pattern"] != "under" else ""
    cad = [r["cadence"] for r in short if r["cadence"]["under"] and r["cadence"]["on"]]
    cad_drop = any(c["on"] - c["under"] >= CAD_DROP or c["under"] < CAD_LOW for c in cad)
    evidence = {"pattern": worst["pattern"], "rep_watts": [r["watts"] for r in reps], "target_w": [lo, hi]}
    if cad_drop:
        c = next(c for c in cad if c["on"] - c["under"] >= CAD_DROP or c["under"] < CAD_LOW)
        return {"id": "pacing_cadence", "title": "Shift down when the watts drop",
                "text": f"The watts and your cadence dropped together ({which}{c['under']} rpm against {c['on']} rpm "
                        f"on the target). When the power starts to slip, change to a lighter gear and keep 85–95 rpm: "
                        f"it's easier to hold {lo}–{hi} W spinning than grinding.{erg}",
                "evidence": {**evidence, "rpm": [c["under"], c["on"]]}}
    if worst["pattern"] == "under":
        easy = " It felt easy, so the watts are there." if feel == "easy" else ""
        said = (f"Every rep was under: {' and '.join(str(r['watts']) for r in reps)} W against {lo}–{hi} W."
                if n > 1 and all(r["pattern"] == "under" for r in reps) else
                f"{which.capitalize()}{worst['watts']} W against {lo}–{hi} W.")
        return {"id": "pacing_under", "title": f"Ride to the number: {mid} W",
                "text": f"{said}{easy} Next time be at {mid} W by "
                        f"the end of the first minute and stay there: sweet spot only builds what you can hold when "
                        f"it's at sweet spot.{erg}",
                "evidence": evidence}
    if worst["pattern"] == "faded":
        return {"id": "pacing_fade", "title": f"Start at {lo} W and build",
                "text": f"{which.capitalize()}it went from {worst['thirds'][0]} W to {worst['thirds'][2]} W. Start the "
                        f"{label} at the bottom of the range, {lo} W, and only push towards {hi} W in its last "
                        f"minutes; and eat something in the hour before.{erg}",
                "evidence": evidence}
    if worst["pattern"] == "started_low":
        return {"id": "pacing_start", "title": "Be on target in the first minute",
                "text": f"{which.capitalize()}the first third was {worst['thirds'][0]} W, under {lo} W, before you "
                        f"settled. End the warm-up with a minute at about {lo} W so you start the {label} on the "
                        f"number, not climbing to it.{erg}",
                "evidence": evidence}
    dips = " and ".join(f"minute {d['minute']} ({d['watts']} W)" for d in worst["dips"]) or "a few minutes"
    return {"id": "pacing_even", "title": f"Hold {mid} W, minute by minute",
            "text": f"{which.capitalize()}the watts eased off in {dips}, under {lo} W. Aim for the middle of the "
                    f"range, {mid} W, not its floor, so a dip still lands inside it, and check your power every "
                    f"minute.{erg}",
            "evidence": evidence}
