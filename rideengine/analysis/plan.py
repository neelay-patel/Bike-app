"""Training plans: structured workouts, a week-by-week plan to the goal, and exports (calendar, Zwift).

docs/coaching.md. Rule-based and stdlib only:
- zones: power from FTP (when known) and heart rate (always), so every target has both;
- a workout library: warm-up, the main set (how many, how long, how hard, recovery between), cool-down,
  progressing over the weeks;
- build_plan: from now to the goal's date, in phases (base, build, sharpen, taper), an easier week every
  fourth, on the rider's own days and times; indoors or out is the rider's choice (`indoor` marks the trainer
  season, a suggestion only);
- to_ics (calendar feed) and to_zwo (Zwift workout file: Zwift then sets the KICKR's resistance).

FTP: the rider's own number if they give one, else 95% of their best 20-minute power from recent rides,
else unknown (targets show as % of FTP plus heart rate until power arrives).
"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from xml.sax.saxutils import escape

# Zones as fractions of FTP, and of heart-rate reserve (Karvonen) for the heart-rate target.
ZONES = {
    "Z1": {"name": "Easy", "ftp": (0.40, 0.55), "hrr": (0.50, 0.60), "rpe": 2},
    "Z2": {"name": "Zone 2", "ftp": (0.56, 0.75), "hrr": (0.60, 0.70), "rpe": 3},
    "Z3": {"name": "Tempo", "ftp": (0.76, 0.87), "hrr": (0.70, 0.80), "rpe": 5},
    "SS": {"name": "Sweet spot", "ftp": (0.88, 0.94), "hrr": (0.78, 0.85), "rpe": 6},
    "Z4": {"name": "Threshold", "ftp": (0.95, 1.05), "hrr": (0.85, 0.90), "rpe": 7},
    "Z5": {"name": "VO2 max", "ftp": (1.06, 1.20), "hrr": (0.90, 0.95), "rpe": 8},
    "Z6": {"name": "Anaerobic", "ftp": (1.21, 1.50), "hrr": (0.92, 1.00), "rpe": 9},
    "Z7": {"name": "Sprint", "ftp": (1.51, 2.50), "hrr": None, "rpe": 10},
}
# Zone 2 steps by name: "Endurance" and "Steady endurance" in plans made before 24 Nov 2026 (renamed when shown).
Z2_LABELS = ("Zone 2", "Endurance", "Steady endurance")
SHORT_EFFORT_S = 120   # heart rate lags short efforts: ride them by power or feel, not heart rate
# Cadence to aim for, in rpm: smooth and quick for steady work, a touch quicker for the hard efforts. A sprint has
# none: wind it up as fast as you can.
CADENCE = {"Z1": (85, 95), "Z2": (85, 95), "Z3": (85, 95), "SS": (85, 95), "Z4": (85, 95), "Z5": (90, 100),
           "Z6": (95, 105)}


def ftp_estimate(manual: float | None, power_curve: dict | None) -> dict:
    """The FTP to train with and where it came from."""
    if manual:
        return {"watts": round(manual), "source": "yours"}
    best20 = (power_curve or {}).get("1200")
    if best20:
        return {"watts": round(best20 * 0.95), "source": "estimated from your best 20 minutes"}
    return {"watts": None, "source": "unknown until your first rides with power"}


def hr_zones(max_hr: float | None, resting: float | None) -> dict | None:
    if not max_hr or not resting or max_hr <= resting + 30:
        return None
    reserve = max_hr - resting
    return {z: [round(resting + lo * reserve), round(resting + hi * reserve)]
            for z, v in ZONES.items() if (r := v["hrr"]) for lo, hi in [r]}


def max_hr_estimate(ride_max_hrs: list[float]) -> float | None:
    """A robust max: the 98th percentile of rides' maximum heart rate (ignores one-off spikes)."""
    v = sorted(h for h in ride_max_hrs if h and 100 < h < 230)
    return v[min(len(v) - 1, int(len(v) * 0.98))] if len(v) >= 10 else None


# --- workouts --------------------------------------------------------------------------------
def step(label: str, minutes: float, zone: str, ramp_to: str | None = None) -> dict:
    return {"label": label, "seconds": round(minutes * 60), "zone": zone, "ramp_to": ramp_to}


def rep_set(repeat: int, on: dict, off: dict, label: str) -> dict:
    return {"set": label, "repeat": repeat, "steps": [on, off]}


def _warm(minutes=10):
    return step("Warm up", minutes, "Z1", ramp_to="Z2")


def _cool(minutes=8):
    return step("Cool down", minutes, "Z1")


def _lerp(a: float, b: float, level: float) -> int:
    return round(a + (b - a) * max(0.0, min(1.0, level)))


def workout(kind: str, level: float, minutes: int, indoor: bool) -> dict:
    """One session. level 0..1 is how far into the progression it is; minutes the time available."""
    w: dict = {"kind": kind, "indoor": indoor, "off_bike": False}
    if kind == "surges":
        n = _lerp(5, 8, level)
        hard = 1.0
        w |= {"title": "Surges", "purpose": "Answer the accelerations: hard minute, settle, again.",
              "steps": [_warm(12),
                        rep_set(n, step("Hard", hard, "Z6"), step("Recover", 2, "Z2"), f"{n} × 1 min hard / 2 min easy"),
                        step("Easy", 5, "Z2"),
                        rep_set(n, step("Hard", 0.5, "Z6"), step("Recover", 0.5, "Z2"), f"{n} × 30 s on / 30 s off"),
                        _cool()]}
    elif kind == "steady":
        n, each = (2, _lerp(10, 15, level)) if level < 0.5 else (3, _lerp(12, 15, level))
        w |= {"title": "Sweet spot", "purpose": "Raise the power you can hold for the whole ride.",
              "steps": [_warm(10), rep_set(n, step("Steady", each, "SS"), step("Recover", 5, "Z1"),
                                           f"{n} × {each} min sweet spot / 5 min easy"), _cool()]}
    elif kind == "threshold":
        n, each = 3, _lerp(8, 12, level)
        w |= {"title": "Threshold", "purpose": "Lift your ceiling: efforts right at the limit you can hold.",
              "steps": [_warm(12), rep_set(n, step("Threshold", each, "Z4"), step("Recover", 4, "Z1"),
                                           f"{n} × {each} min threshold / 4 min easy"), _cool()]}
    elif kind == "over_unders":
        n = _lerp(3, 4, level)
        w |= {"title": "Over-unders", "purpose": "Recover while still working: pace changes in a hard group.",
              "steps": [_warm(12), {"set": f"{n} × (4 × 1 min over / 1 min under), 5 min easy between", "repeat": n,
                                    "steps": [rep_set(4, step("Over", 1, "Z5"), step("Under", 1, "SS"), "4 × 1/1"),
                                              step("Recover", 5, "Z1")]}, _cool()]}
    elif kind == "vo2":
        n = _lerp(4, 6, level)
        w |= {"title": "VO2 max", "purpose": "Short hard efforts that raise your top end.",
              "steps": [_warm(12), rep_set(n, step("Hard", 3, "Z5"), step("Recover", 3, "Z1"),
                                           f"{n} × 3 min hard / 3 min easy"), _cool()]}
    elif kind == "sprint":
        n = _lerp(6, 8, level)
        w |= {"title": "Sprints", "purpose": "Snap: all-out efforts from a rolling start.",
              "steps": [_warm(15), rep_set(n, step("Sprint", 0.25, "Z7"), step("Recover", 4.75, "Z1"),
                                           f"{n} × 15 s all out / 5 min easy"), _cool(10)]}
    elif kind == "group":
        # Indoors or out is the rider's call (21 Nov 2026): `indoor` only says the season suits the trainer.
        w |= {"title": "Group ride",
              "purpose": "Practise holding the wheel at the group's pace, and answering the surges: a club ride "
                         "outside, or a Zwift group ride.",
              "steps": [_warm(10), step("Ride with the group", minutes - 15, "Z3"), step("Cool down", 5, "Z1")]}
    elif kind == "long":
        w |= {"title": "Long ride",
              "purpose": "Time in the saddle in zone 2: a pace you could chat at the whole way.",
              "steps": [_warm(10), step("Zone 2", minutes - 15, "Z2"), step("Cool down", 5, "Z1")]}
    elif kind == "endurance":
        w |= {"title": "Zone 2", "purpose": "Easy aerobic riding that builds the base: easy enough to talk in full "
                                           "sentences.",
              "steps": [step("Zone 2", minutes, "Z2")]}
    elif kind == "easy":
        w |= {"title": "Easy spin", "purpose": "Recovery: legs moving, nothing hard.",
              "steps": [step("Easy", minutes, "Z1")]}
    elif kind == "strength":
        return {"kind": "strength", "title": "Strength and mobility", "indoor": True, "off_bike": True,
                "purpose": "A reminder: 20 minutes off the bike. Tick it off when you've done it.",
                "steps": [], "seconds": 20 * 60}
    else:
        raise ValueError(kind)
    w["seconds"] = sum(_seconds(s) for s in w["steps"])
    # Fill structured sessions to the time available with easy riding before the cool-down.
    if kind not in ("group", "long", "endurance", "easy") and w["seconds"] < minutes * 60 - 300:
        w["steps"].insert(-1, step("Zone 2", (minutes * 60 - w["seconds"]) / 60, "Z2"))
        w["seconds"] = minutes * 60
    return w


def _seconds(s: dict) -> int:
    if "set" in s:
        return s["repeat"] * sum(_seconds(x) for x in s["steps"])
    return s["seconds"]


def renamed(steps: list) -> list:
    """Steps of plans made before 24 Nov 2026 with zone 2 called by its name."""
    return [{**x, "steps": renamed(x["steps"])} if "set" in x else
            {**x, "label": "Zone 2"} if x.get("zone") == "Z2" and x.get("label") in Z2_LABELS else x for x in steps]


def flatten(steps: list) -> list[dict]:
    out = []
    for s in steps:
        if "set" in s:
            for _ in range(s["repeat"]):
                out += flatten(s["steps"])
        else:
            out.append(s)
    return out


def targets(w: dict, ftp: float | None, hrz: dict | None) -> dict:
    """The workout with each step's targets filled in: % of FTP, watts (when FTP is known), heart rate,
    and how it feels."""
    def fill(s):
        if "set" in s:
            return {**s, "steps": [fill(x) for x in s["steps"]]}
        z = ZONES[s["zone"]]
        lo, hi = z["ftp"]
        if s.get("ramp_to"):
            hi = ZONES[s["ramp_to"]]["ftp"][1]
        t = {"pct_ftp": [round(lo * 100), round(hi * 100)], "zone_name": z["name"], "rpe": z["rpe"]}
        if s["zone"] in CADENCE:
            t["rpm"] = list(CADENCE[s["zone"]])
        if ftp:
            t["watts"] = [round(lo * ftp), round(hi * ftp)]
        if hrz and s["zone"] in hrz and s["seconds"] > SHORT_EFFORT_S:
            t["hr"] = hrz[s["ramp_to"] or s["zone"]] if s.get("ramp_to") else hrz[s["zone"]]
        return {**s, "target": t}
    out = {**w, "steps": [fill(s) for s in w["steps"]]}
    flat = flatten(w["steps"])
    if flat:
        # Training load like TSS: hours × intensity² × 100, intensity = mid-zone fraction of FTP.
        load = sum(x["seconds"] / 3600 * (sum(ZONES[x["zone"]]["ftp"]) / 2) ** 2 * 100 for x in flat)
        out["load"] = round(load)
    return out


# --- the plan ----------------------------------------------------------------------------------
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Sessions per week by focus, most important first. "long" is the week's longest ride.
FOCUS = {
    "keep_up_group": ["surges", "steady", "group", "endurance", "over_unders"],
    "beat_my_roads": ["threshold", "steady", "long", "endurance", "surges"],
    "climb_faster": ["threshold", "vo2", "long", "steady", "endurance"],
    "own_climbs": ["threshold", "vo2", "long", "steady", "endurance"],
    "more_power": ["threshold", "vo2", "long", "steady", "endurance"],
    "sprint": ["sprint", "surges", "long", "steady", "endurance"],
    "first_distance": ["long", "steady", "endurance", "threshold", "endurance"],
    "all_day": ["long", "steady", "endurance", "threshold", "endurance"],
    "event": ["long", "steady", "threshold", "endurance", "surges"],
}
# In base weeks the hardest sessions give way to steadier ones; the key session stays, at its lightest.
BASE_SWAP = {"over_unders": "endurance", "vo2": "threshold"}
SHARE = {"group": 0.32, "long": 0.36}  # the long session's share of the week's time


# The job each workout does (docs/train-method.md): a week is a set of jobs, a workout one good way to do one.
# A group ride answers surges at the group's pace: punch (docs/train-method.md, the jobs table).
JOB_OF = {"surges": "punch", "sprint": "punch", "vo2": "top_end", "steady": "hold", "threshold": "hold",
          "over_unders": "hold", "long": "long", "group": "punch", "endurance": "easy", "easy": "easy",
          "strength": "strength"}
_JOB_ZONE = {"Z6": "punch", "Z7": "punch", "Z5": "top_end", "SS": "hold", "Z4": "hold"}


def job_minutes(w: dict) -> dict:
    """Minutes of each job's work the workout asks for: {"punch": 7.5} for the lightest surges. Over-unders count
    whole (over and under are both hold work); long rides their whole time."""
    out: dict[str, float] = {}
    if w.get("kind") == "long":
        return {"long": round(w.get("seconds", 0) / 60)}
    if w.get("kind") == "group":
        return {}                     # the group sets the efforts: any punch counts

    def walk(steps, mult=1, whole=None):
        for st in steps:
            if st.get("steps"):
                ou = whole or (w.get("kind") == "over_unders")
                walk(st["steps"], mult * st.get("repeat", 1), "hold" if ou else None)
            elif whole and st.get("zone") != "Z1":
                out[whole] = out.get(whole, 0) + mult * st["seconds"] / 60
            elif not whole and st.get("zone") in _JOB_ZONE and mult > 1:
                job = _JOB_ZONE[st["zone"]]
                out[job] = out.get(job, 0) + mult * st["seconds"] / 60
    walk(w.get("steps") or [])
    return {k: round(v, 1) for k, v in out.items()}


def leftover(job: str, left_min: float) -> dict | None:
    """What's left of a partly done job, as a set to add near the end of a planned ride (docs/train-method.md):
    the work in the shape its session had, rounded up so it finishes the job."""
    import math
    if job == "punch":
        n = max(2, math.ceil(left_min))
        return rep_set(n, step("Hard", 1, "Z6"), step("Recover", 2, "Z2"), f"Added: {n} × 1 min hard / 2 min easy")
    if job == "top_end":
        n = max(1, math.ceil(left_min / 3))
        return rep_set(n, step("Hard", 3, "Z5"), step("Recover", 3, "Z1"), f"Added: {n} × 3 min hard / 3 min easy")
    if job == "hold":
        m = max(5, math.ceil(left_min))
        return rep_set(1, step("Steady", m, "SS"), step("Recover", 3, "Z2"), f"Added: {m} min steady")
    return None


def with_leftover(session: dict, block: dict) -> dict:
    """The session with a leftover set added before its cool-down (or at the end). It takes the place of easy
    riding the session had to fill its time, where there is some, so the session stays as long as planned."""
    steps = list(session.get("steps") or [])
    at = len(steps) - 1 if steps and steps[-1].get("label") == "Cool down" else len(steps)
    extra = _seconds(block)
    fill = next((i for i in range(at - 1, -1, -1) if not steps[i].get("steps") and steps[i].get("zone") == "Z2"
                 and steps[i].get("label") in Z2_LABELS), None)
    if fill is not None:
        take = min(extra, max(0, steps[fill]["seconds"] - 300))      # leave at least 5 min of it
        steps[fill] = {**steps[fill], "seconds": steps[fill]["seconds"] - take}
        extra -= take
    steps.insert(at, block)
    return {**session, "steps": steps, "seconds": (session.get("seconds") or 0) + extra}


def shape(session: dict, watts: list | None = None) -> str | None:
    """The job's shape in words, so any workout the rider likes can do it (docs/train-method.md: no Zwift or other
    app's workout names). watts: the session's main target range, when it has one."""
    job = JOB_OF.get(session.get("kind"))
    mins = job_minutes(session).get(job)
    w = f" at about {watts[0]}–{watts[1]} W" if watts else ""
    if job == "punch":
        m = mins or 5
        return (f"Or any ride with {m:g} min or more of hard efforts of 30 s to 2 min, easy riding between: an interval "
                f"workout, a hard group ride, or hills taken hard.")
    if job == "top_end":
        m = mins or 10
        return f"Or any ride with {m:g} min or more of hard efforts of 3 to 5 min{w}, as long easy between."
    if job == "hold":
        m = mins or 20
        return (f"Or any ride with {m:g} min or more of steady work{w}, in blocks of 8 min or more: a long steady "
                f"climb counts.")
    if job == "long":
        m = round((session.get("seconds") or 0) / 60)
        return f"Or any ride of {m} min or more at a pace you could chat at, indoors or out."
    if job == "easy":
        return "Or any easy ride: legs turning, nothing hard."
    return None


# Growth by evidence (docs/train-method.md, progression): a job's sessions step up when the last one was done in
# full and felt fine, stay when it felt hard or was partly done, step back when it wrecked the rider or hurt.
GROW_STEP = 0.25                 # one step of `level` (surges: 5 -> 6 reps; sweet spot 2 x 10 -> 2 x 11 min)
GROW_CAP = {"base": 0.5, "build": 1.0, "sharpen": 1.0}   # phases where sessions grow, and how far
GROW_FLOOR = {"sharpen": 0.5}
GROWS = ("surges", "sprint", "vo2", "steady", "threshold", "over_unders")


def grow_score(score: int, outcome: str) -> int:
    """outcome: done (felt fine, or no tap) | hard | part | missed | wrecked."""
    return max(-2, min(8, score + {"done": 1, "wrecked": -1}.get(outcome, 0)))


def grown(session: dict, score: int, phase: str) -> dict | None:
    """The session at the size the rider's evidence says, or None when it doesn't grow (easy, long and group
    rides; easier weeks and the taper)."""
    if session.get("kind") not in GROWS or phase not in GROW_CAP:
        return None
    level = min(GROW_CAP[phase], max(GROW_FLOOR.get(phase, 0.0), GROW_STEP * score))
    w = workout(session["kind"], level, max(30, round((session.get("seconds") or 0) / 60)), session.get("indoor", True))
    return {**session, **w, "level": level}


def usual_days(starts: list[datetime], n: int) -> list[str]:
    """The rider's n most-ridden weekdays, spread out (not back to back) where possible."""
    count = {d: 0 for d in WEEKDAYS}
    for s in starts:
        count[WEEKDAYS[s.weekday()]] += 1
    ranked = sorted(WEEKDAYS, key=lambda d: (-count[d], WEEKDAYS.index(d)))
    picked: list[str] = []
    for d in ranked:
        i = WEEKDAYS.index(d)
        if all(abs(i - WEEKDAYS.index(p)) not in (1, 6) for p in picked):
            picked.append(d)
        if len(picked) == n:
            break
    for d in ranked:  # not enough spread-out days: allow neighbours
        if len(picked) == n:
            break
        if d not in picked:
            picked.append(d)
    return sorted(picked, key=WEEKDAYS.index)


def usual_times(starts: list[datetime]) -> dict[str, str]:
    """Each weekday's usual start time (median, to the quarter hour); 07:00 where there's no history."""
    by: dict[str, list[float]] = {d: [] for d in WEEKDAYS}
    for s in starts:
        by[WEEKDAYS[s.weekday()]].append(s.hour + s.minute / 60)
    out = {}
    for d, v in by.items():
        if v:
            v.sort()
            h = round(v[len(v) // 2] * 4) / 4
            out[d] = f"{int(h):02d}:{int(round((h % 1) * 60)):02d}"
        else:
            out[d] = "07:00"
    return out


def sessions_for(hours: float) -> int:
    return 3 if hours <= 3.5 else 4 if hours <= 5.25 else 5


def phases(n_weeks: int) -> list[str]:
    """base, build, sharpen, then a taper week; every fourth week easier ("recovery")."""
    if n_weeks <= 1:
        return ["taper"][:n_weeks]
    body = n_weeks - 1
    base = max(1, round(body * 0.4))
    build = max(1, round(body * 0.4))
    sharpen = max(0, body - base - build)
    out = ["base"] * base + ["build"] * build + ["sharpen"] * sharpen + ["taper"]
    for i in range(3, len(out) - 1, 4):
        out[i] = "recovery"
    return out


def _indoor(season: dict, d: date) -> bool:
    kind = season.get("months", {}).get(str(d.month), "mixed")
    return kind == "indoor" or (kind == "mixed" and d.weekday() < 5)


def build_plan(goal: dict, today: date, season: dict, days: list[str], times: dict[str, str],
               weekly_hours: float, start: date | None = None) -> dict:
    """The plan from `start` (default: today) to the goal's ready-by date. Sessions carry the workout
    structure; targets are filled in when shown (they follow the rider's current FTP and zones)."""
    start = start or today
    ready = date.fromisoformat(goal["ready_by"]) if goal.get("ready_by") else start + timedelta(weeks=16)
    week0 = start - timedelta(days=start.weekday())
    # Starting late in the week (no riding day left): begin with next week, not an empty one.
    if not any(WEEKDAYS.index(d) >= start.weekday() for d in days):
        week0 += timedelta(weeks=1)
    n_weeks = max(4, min(40, (ready - week0).days // 7 + 1))
    focus = FOCUS.get(goal.get("aspiration"), FOCUS["beat_my_roads"])
    n_bike = min(sessions_for(weekly_hours), len(days))
    weeks = []
    for wi, phase in enumerate(phases(n_weeks)):
        ws = week0 + timedelta(weeks=wi)
        span = [p for p in phases(n_weeks)[:wi + 1] if p == phase]
        level = min(1.0, (len(span) - 1) / 4) if phase in ("build", "sharpen") else 0.0
        if phase == "sharpen":
            level = 1.0
        scale = {"recovery": 0.6, "taper": 0.55}.get(phase, 1.0)
        hours = weekly_hours * scale * (0.85 + 0.15 * min(1.0, wi / 6))   # ramp up gently from week one
        kinds = focus[:n_bike]
        if phase == "base":
            kinds = [BASE_SWAP.get(k, k) for k in kinds]
        if phase in ("recovery", "taper"):
            kinds = [k if k in ("group", "long", "steady") else "easy" for k in kinds]
            if phase == "taper" and goal.get("aspiration") in ("keep_up_group", "sprint"):
                kinds[0] = "surges"
        # Minutes: the long session gets its share, the rest split the remainder.
        long_k = next((k for k in kinds if k in SHARE), None)
        total = hours * 60
        long_min = round(total * SHARE[long_k] / 5) * 5 if long_k else 0
        rest = [k for k in kinds if k != long_k]
        each = max(35, round((total - long_min) / max(1, len(rest)) / 5) * 5)
        # Long session on the latest chosen weekend day if there is one, else the last day; the key session
        # (focus[0]) on the first day; spread the others.
        order = sorted(days, key=WEEKDAYS.index)[:n_bike]
        weekend = [d for d in order if d in ("Sat", "Sun")]
        placement: dict[str, str] = {}
        if long_k:
            placement[(weekend or order)[-1]] = long_k
        free = [d for d in order if d not in placement]
        for d, k in zip(free, rest):
            placement[d] = k
        sessions = []
        for d, k in placement.items():
            day = ws + timedelta(days=WEEKDAYS.index(d))
            if day < start or day > ready:
                continue
            mins = long_min if k == long_k else each
            w = workout(k, level, int(mins), _indoor(season, day))
            sessions.append({"id": f"{day.isoformat()}-{k}", "date": day.isoformat(), "time": times.get(d, "07:00"),
                             **w})
        # Strength and mobility: a reminder on a non-riding day (or the easiest one).
        off = [d for d in WEEKDAYS if d not in placement]
        sd = off[len(off) // 2] if off else order[-1]
        sday = ws + timedelta(days=WEEKDAYS.index(sd))
        if start <= sday <= ready and phase != "taper":
            sessions.append({"id": f"{sday.isoformat()}-strength", "date": sday.isoformat(),
                             "time": times.get(sd, "07:00"), **workout("strength", 0, 20, True)})
        sessions.sort(key=lambda s: s["date"])
        weeks.append({"week_start": ws.isoformat(), "phase": phase, "index": wi + 1,
                      "hours": round(sum(s["seconds"] for s in sessions if not s["off_bike"]) / 3600, 1),
                      "sessions": sessions})
    return {"goal_id": goal.get("id"), "start": start.isoformat(), "ready_by": ready.isoformat(),
            "weeks": weeks, "days": days, "times": times, "weekly_hours": weekly_hours}


# --- did you do it --------------------------------------------------------------------------
def status(session: dict, rides_on_day: list[dict], today: date, done_ids: set[str]) -> str:
    """done | missed | today | upcoming. A ride on the day of at least 60% of the planned time counts;
    off-bike sessions count when ticked."""
    d = date.fromisoformat(session["date"])
    if session["id"] in done_ids:
        return "done"
    if not session["off_bike"]:
        if sum(r.get("moving_s") or 0 for r in rides_on_day) >= 0.6 * session["seconds"]:
            return "done"
    if d < today:
        return "missed"
    return "today" if d == today else "upcoming"


# --- exports ---------------------------------------------------------------------------------
def _hms(s: int) -> str:
    if s < 60:
        return f"{s} s"
    m = round(s / 60)
    return f"{m // 60} h {m % 60:02d}" if m >= 60 else f"{m} min"


def describe(w: dict) -> str:
    """The workout as plain text: one line per step or set, with targets."""
    lines = []

    def tgt(s):
        t = s.get("target") or {}
        parts = []
        if "watts" in t:
            parts.append(f"{t['watts'][0]}–{t['watts'][1]} W")
        else:
            parts.append(f"{t.get('pct_ftp', ['?', '?'])[0]}–{t.get('pct_ftp', ['?', '?'])[1]}% FTP")
        if "hr" in t:
            parts.append(f"HR {t['hr'][0]}–{t['hr'][1]}")
        return ", ".join(parts)

    for s in w["steps"]:
        if "set" in s:
            inner = "; ".join(f"{x['label']} {_hms(x['seconds'])} at {tgt(x)}" if "set" not in x else x["set"]
                              for x in s["steps"])
            lines.append(f"{s['set']} ({inner})")
        else:
            lines.append(f"{s['label']}: {_hms(s['seconds'])} at {tgt(s)}")
    return "\n".join(lines)


def _ics_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def to_ics(sessions: list[dict], tz: tzinfo | None, name: str = "Kova training") -> str:
    """A calendar feed (iCalendar) of the plan's sessions. Times in UTC, computed from the rider's zone."""
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Kova//Training plan//EN", "CALSCALE:GREGORIAN",
           f"X-WR-CALNAME:{_ics_text(name)}", "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"]
    for s in sessions:
        d = date.fromisoformat(s["date"])
        hh, mm = (int(x) for x in s["time"].split(":"))
        start = datetime.combine(d, time(hh, mm), tzinfo=tz).astimezone(timezone.utc) if tz else \
            datetime.combine(d, time(hh, mm)).astimezone(timezone.utc)
        end = start + timedelta(seconds=s["seconds"])
        where = "Off the bike" if s["off_bike"] else "Indoors or out"
        body = f"{s['purpose']}\n\n{describe(s)}" if s["steps"] else s["purpose"]
        out += ["BEGIN:VEVENT", f"UID:{s['id']}@ride-training", f"DTSTAMP:{now}",
                f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}", f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
                f"SUMMARY:{_ics_text(s['title'] + ' · ' + _hms(s['seconds']))}",
                f"LOCATION:{where}", f"DESCRIPTION:{_ics_text(body)}", "END:VEVENT"]
    out.append("END:VCALENDAR")
    # Lines over 75 octets must be folded (RFC 5545).
    folded = []
    for line in out:
        b = line.encode("utf-8")
        while len(b) > 75:
            cut = 75
            while (b[cut] & 0xC0) == 0x80:
                cut -= 1
            folded.append(b[:cut].decode("utf-8"))
            b = b" " + b[cut:]
        folded.append(b.decode("utf-8"))
    return "\r\n".join(folded) + "\r\n"


def to_zwo(w: dict) -> str:
    """The workout as a Zwift .zwo file (power as a fraction of FTP): Zwift then sets the trainer's
    resistance (ERG mode) for each step."""
    def mid(z):
        lo, hi = ZONES[z]["ftp"]
        return round((lo + hi) / 2, 2)

    parts = []
    for s in w["steps"]:
        if "set" in s and len(s["steps"]) == 2 and all("set" not in x for x in s["steps"]):
            on, off = s["steps"]
            parts.append(f'<IntervalsT Repeat="{s["repeat"]}" OnDuration="{on["seconds"]}" OffDuration="{off["seconds"]}" '
                         f'OnPower="{mid(on["zone"])}" OffPower="{mid(off["zone"])}"/>')
        elif "set" in s:
            for x in flatten([s]):
                parts.append(f'<SteadyState Duration="{x["seconds"]}" Power="{mid(x["zone"])}"/>')
        elif s.get("ramp_to"):
            parts.append(f'<Warmup Duration="{s["seconds"]}" PowerLow="{ZONES[s["zone"]]["ftp"][0]}" '
                         f'PowerHigh="{ZONES[s["ramp_to"]]["ftp"][1]}"/>')
        elif s["label"] == "Cool down":
            parts.append(f'<Cooldown Duration="{s["seconds"]}" PowerLow="{ZONES["Z2"]["ftp"][0]}" '
                         f'PowerHigh="{ZONES["Z1"]["ftp"][0]}"/>')
        else:
            parts.append(f'<SteadyState Duration="{s["seconds"]}" Power="{mid(s["zone"])}"/>')
    body = "\n    ".join(parts)
    return (f'<workout_file>\n  <author>Kova</author>\n  <name>{escape(w["title"])}</name>\n'
            f'  <description>{escape(w["purpose"])}</description>\n  <sportType>bike</sportType>\n'
            f'  <tags/>\n  <workout>\n    {body}\n  </workout>\n</workout_file>\n')
