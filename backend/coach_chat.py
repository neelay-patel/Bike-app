"""A riding coach you can ask anything (docs/train-tab.md step 6, decided 24 Nov 2026).

Every rider has a chatbot; Kova has all of a rider's riding in one place. So the coach is Claude with read-only
tools over the rider's own data (rides, trends, fitness, recovery, the plan, climbs), and the engine still
calculates:

- **tools, not a summary**: the coach looks up what each question needs (`Tools`). Every number a tool returns is
  worked out by the engine;
- **the number check**: every measured number in an answer (watts, bpm, rpm, km, metres, %, ...) must be one a tool
  returned this time (or a rounding of one to 5 or 10), one the rider wrote, or one the coach said before. An answer
  that fails is sent back once with the numbers named; if it fails again the rider gets an honest line instead;
- **advice it follows through on**: advice the coach gives is saved with a measure the engine can read from every
  ride (`MEASURES`), and checked after each new ride ("working", "not yet"), in the engine's words;
- **plan changes are proposals**: the coach can only propose one (ease a week, swap a session, hours, days). The
  engine checks it; it changes nothing until the rider taps OK;
- **memory the rider sees**: notes the coach keeps about the rider, each one deletable;
- **the gate and the cap**: only riders with the personal-use AI setting on; a daily spending cap; every call in
  the cost log (`coach_usage`, key `chat:<id>`). Recovery numbers go to the coach for the rider's own coaching
  (decided 24 Nov 2026) and are never shown to anyone else. No GPS, no place names beyond climb and route names.
"""
from __future__ import annotations

import json
import logging
import math
import re
import statistics
import threading
import time
from datetime import date, datetime, timedelta
from typing import Optional

from . import coach as coach_mod

log = logging.getLogger("uvicorn.error")

MODEL = coach_mod.MODEL
DAY_LIMIT_USD = 3.00     # a rider's chat spend per day, then the coach says so and waits for tomorrow
MAX_ROUNDS = 10          # tool rounds per answer
HISTORY = 12             # earlier messages of the conversation sent with each question
MAX_ADVICE = 3           # advice being followed at once; a new one retires the oldest
MAX_CHARTS = 2

SYSTEM = """You are the riding coach in Kova, a cycling app. The rider can ask you anything about their riding. You
have tools over all of their own data: every ride merged from all their devices, trends, their fitness numbers,
recovery (HRV, resting heart rate, Cardio Recovery, VO2 max), their training plan and goal, and their climbs.
What makes you useful is that context: answer from THEIR riding, not from general tips.

How to answer:
- Look before you speak: call the tools you need. Never guess what a ride or a trend shows.
- Most questions are asking for advice. Give advice like a good coach: ONE clear thing to do (not a list of tips),
  why, from their own numbers, and how to do it this week (which ride, what to aim for, what it should feel like).
- When you give advice the engine can follow up on, record it with give_advice, choosing the measure that will show
  whether it worked. Say you'll check back after their next rides. Don't record small talk or one-off answers.
- Keep it short: it's read on a phone. At most 100 words in two or three short paragraphs (a quick question gets
  two sentences). Pick the two or three numbers that make the point; leave the rest out. Plain text; **bold** for
  at most one phrase. No headings, no tables, no lists.
- A picture helps when the advice rests on a trend or a gap to an aim: use show (at most two per answer). Don't
  describe the chart in words as well.
- Praise only what's earned, and name it. Never empty praise ("Great job!"), never guilt.

Numbers:
- Use only numbers your tools returned (rounding to the nearest 5 or 10 is fine, "about 150 W"), numbers the
  rider wrote, or numbers already said in this conversation. Never calculate your own differences, averages or
  percentages: the tools give changes where they matter. If you don't have a number, say it without one.
- Say what the data can't show. Outdoor rides may have no power and no cadence (no sensor on the bike); a tool
  returning none means the data isn't there, not zero. You never see sleep or other workouts.

Words:
- Plain words. Say "what you could hold for about an hour" rather than FTP unless the rider uses the term first;
  never TSS, CTL, "load", "compliance". Zones by name (zone 2, sweet spot), not by number alone.
- Speak to the rider as "you". Indoors or out is the rider's choice: never suggest one is better.
- Recovery numbers are the rider's own: you may use them with the rider to guide training. This is training
  guidance, not medical advice: for pain, chest symptoms, dizziness, illness or injury, tell them to see a doctor
  and don't coach through it.

Changes and memory:
- You can't change the plan yourself. propose_change makes a proposal the rider approves with one tap; say what it
  would do and that it's waiting for their OK. Never say a change is made.
- remember: save a short note when the rider tells you something lasting that should shape future coaching (their
  bike or sensors, an injury, the days they can ride, a goal event, how they like to train). Not passing numbers.
- Stay on riding and training (fitness, pacing, fuelling, recovery, kit for a ride). For anything else, say briefly
  that you're their riding coach.
"""

# --- what the engine can measure on every ride (for trends, charts and advice it follows up) ---------------------
# id: (label, unit, where it's meaningful, how much of a change counts as moving)
MEASURES = {
    "km": ("Distance", "km", "any", 5),
    "hours": ("Time riding", "h", "any", 0.5),
    "climbing_m": ("Climbing", "m", "any", 100),
    "rides": ("Rides", "", "any", 1),
    "avg_kmh": ("Average speed", "km/h", "outdoor", 0.5),
    "avg_hr": ("Average heart rate", "bpm", "any", 3),
    "avg_power": ("Average power", "W", "power", 3),
    "best_1min": ("Best minute", "W", "power", 5),
    "best_5min": ("Best 5 minutes", "W", "power", 4),
    "best_20min": ("Best 20 minutes", "W", "power", 3),
    "cadence": ("Cadence", "rpm", "cadence", 3),
    "push_cadence": ("Cadence on hard pushes and climbs", "rpm", "cadence", 3),
    "zone2_share": ("Time in zone 2", "%", "any", 5),
    "above_zone2_share": ("Time above zone 2", "%", "any", 5),
    "zone2_watts": ("Watts at zone 2 heart rate", "W", "power", 3),
    "hr_drift": ("Heart-rate drift at steady power", "%", "power", 1),
}
WEEKLY_SUM = {"km", "hours", "climbing_m", "rides"}

UNITS = r"(?:W|watts?|bpm|rpm|km/h|kph|km|kms|m|metres|meters|%|percent|kcal|ms|ml/kg/min|kg)"
_CLAIM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?:\s*(?:[–-]|to)\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?))?"
                    r"\s?" + UNITS + r"(?![\w/])")


def claimed_numbers(text: str) -> list[str]:
    """The measured numbers in an answer: ones followed by a unit ("151 W", "120–125 W", "27%")."""
    out = []
    for m in _CLAIM.finditer(text):
        out += [g for g in m.groups() if g]
    return out


def check_answer(text: str, allowed: set[str]) -> list[str]:
    """Measured numbers in `text` that aren't allowed (an empty list passes). Durations, counts and dates aren't
    checked: "2 × 10 min" is coaching, "151 W" is a claim about the rider."""
    bad = []
    for n in claimed_numbers(text):
        k = n.replace(",", "")
        if n not in allowed and k not in allowed:
            bad.append(n)
    return bad


def allowed_numbers(*sources) -> set[str]:
    """Every number in what the tools returned, the rider's words and the conversation, plus roundings of each to
    the nearest 5 and 10 (a coach says "about 150 W" for 151)."""
    base = coach_mod.numbers_in(list(sources))
    out = set(base)
    for s in base:
        try:
            v = float(s.replace(",", ""))
        except ValueError:
            continue
        if abs(v) >= 20:
            for step in (5, 10):
                r = int(round(v / step) * step)
                out.add(str(r))
                if abs(r) >= 1000:
                    out.add(f"{r:,}")
    return out


def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _r(v, d=0):
    if v is None:
        return None
    return round(v) if d == 0 else round(v, d)


class Rider:
    """One rider's data as the coach's tools see it: worked out once per question."""

    def __init__(self, be, uid: int):
        from rideengine.analysis import train
        self.be, self.uid = be, uid
        self.c = be._plan_context(uid)
        self.tz = self.c["tz"]
        self.z2 = (self.c.get("zone2") or {}).get("bpm")
        self.feats = sorted(self.c["feats"], key=lambda f: f["start"])
        self._kind = {}
        for f in self.feats:
            if f.get("work"):
                k = train.classify(f["work"], self.c["ftp"]["watts"], self.c["max_hr"], self.c["resting_hr"])["kind"]
            else:
                k = "mixed" if (f.get("moving_s") or 0) >= train.MIN_MINUTES * 60 else None
            self._kind[f["ride_id"]] = k

    def day(self, f) -> date:
        return datetime.fromtimestamp(f["start"], self.tz).date()

    def kind(self, f) -> Optional[str]:
        return self._kind.get(f["ride_id"])

    def kind_title(self, f) -> Optional[str]:
        from rideengine.analysis import train
        k = self.kind(f)
        return train.TITLES.get(k, k) if k else None

    def where(self, f) -> str:
        return "indoor" if f.get("indoor") else "outdoor"

    def select(self, since=None, until=None, where="any", kind=None) -> list[dict]:
        out = []
        for f in self.feats:
            d = self.day(f)
            if since and d < since or until and d > until:
                continue
            if where in ("indoor", "outdoor") and self.where(f) != where:
                continue
            if kind and self.kind(f) != kind and not (kind == "easy_any" and self.kind(f) in ("easy", "endurance", "long")):
                continue
            out.append(f)
        return out

    # -- one number per ride -----------------------------------------------------------------------------------
    def value(self, f, measure: str):
        from rideengine.analysis import zone2
        w = f.get("work") or {}
        pc = f.get("power_curve") or {}
        if measure == "km":
            return _r(f.get("km"), 1)
        if measure == "hours":
            return _r((f.get("moving_s") or 0) / 3600, 1)
        if measure == "climbing_m":
            return _r(f.get("ascent_m"))
        if measure == "rides":
            return 1
        if measure == "avg_kmh":
            return None if f.get("indoor") else _r(f.get("kmh"), 1)
        if measure == "avg_hr":
            return _r(f.get("avg_hr"))
        if measure == "avg_power":
            return _r(f.get("power"))
        if measure in ("best_1min", "best_5min", "best_20min"):
            return _r(pc.get({"best_1min": "60", "best_5min": "300", "best_20min": "1200"}[measure]))
        if measure == "cadence":
            return _r(_median([c for c in w.get("c30") or [] if c]))
        if measure == "push_cadence":
            return _r(_median([p[3] for p in w.get("pushes") or [] if len(p) > 3 and p[3]]))
        if measure in ("zone2_share", "above_zone2_share"):
            if not self.z2:
                return None
            sp = zone2.split([f.get("hr_hist")], self.z2)
            return None if not sp else sp["in" if measure == "zone2_share" else "above"]
        if measure == "zone2_watts":
            if not self.z2:
                return None
            z = zone2.watts([f.get("hr_hist")], self.z2, min_s=10 * 60)
            return z["watts"] if z else None
        if measure == "hr_drift":
            d = f.get("z2_drift")
            return d["pct"] if d else None
        raise KeyError(measure)

    def weekly(self, fs: list[dict], measure: str):
        """One number for a set of rides (a week, a month): totals for distance and time, else the typical ride."""
        from rideengine.analysis import zone2
        if measure in WEEKLY_SUM:
            vals = [self.value(f, measure) or 0 for f in fs]
            return _r(sum(vals), 1 if measure in ("km", "hours") else 0)
        if measure in ("zone2_share", "above_zone2_share") and self.z2:
            sp = zone2.split([f.get("hr_hist") for f in fs], self.z2)
            return None if not sp else sp["in" if measure == "zone2_share" else "above"]
        if measure.startswith("best_"):
            vals = [self.value(f, measure) for f in fs]
            vals = [v for v in vals if v is not None]
            return max(vals) if vals else None
        v = _median([self.value(f, measure) for f in fs])
        return None if v is None else _r(v, 1 if measure == "hr_drift" else 0)


def _date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _mmss(s) -> Optional[str]:
    if s is None:
        return None
    s = int(round(s))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _slim(x, depth=0):
    """A tool result without long series (the coach needs the numbers, not every sample)."""
    if isinstance(x, dict):
        return {k: _slim(v, depth + 1) for k, v in x.items()
                if k not in ("series", "points", "samples", "hist", "days_values") and not (isinstance(v, list) and len(v) > 24)}
    if isinstance(x, list):
        return [_slim(v, depth + 1) for v in x[:24]]
    return x


# --- the tools ---------------------------------------------------------------------------------------------------
_DATE = {"type": "string", "description": "YYYY-MM-DD"}
_WHERE = {"type": "string", "enum": ["any", "indoor", "outdoor"]}
_KINDS = ["surges", "steady", "threshold", "vo2", "sprint", "over_unders", "group", "endurance", "long", "easy",
          "mixed", "easy_any"]

TOOLS = [
    {"name": "rides", "description": "The rider's rides, newest first: date, where (indoor/outdoor), what kind of training "
     "it was, minutes, km, climbing, speed, heart rate, power (measured only), time in zone 2, cadence, how it felt. "
     "Filter by dates, where, and kind ('easy_any' = easy, zone 2 and long rides).",
     "input_schema": {"type": "object", "properties": {
         "since": _DATE, "until": _DATE, "where": _WHERE, "kind": {"type": "string", "enum": _KINDS},
         "limit": {"type": "integer", "description": "At most 40; default 15."}}}},
    {"name": "ride", "description": "One ride in detail: its numbers, power bests, hard pushes with cadence, interval "
     "sets, heart-rate drift, time in zone 2, the climbs it went up with times, what was notable, the planned session it "
     "counted as and how it went against the plan, the one thing to try, how it felt.",
     "input_schema": {"type": "object", "properties": {"ride_id": {"type": "string"}}, "required": ["ride_id"]}},
    {"name": "trend", "description": "One measure over time, by ride, week or month, with the first and last values and "
     "the change between them. Measures: " + ", ".join(f"{k} ({v[0]})" for k, v in MEASURES.items()) + ".",
     "input_schema": {"type": "object", "properties": {
         "measure": {"type": "string", "enum": list(MEASURES)}, "by": {"type": "string", "enum": ["ride", "week", "month"]},
         "since": _DATE, "until": _DATE, "where": _WHERE, "kind": {"type": "string", "enum": _KINDS}},
         "required": ["measure"]}},
    {"name": "fitness", "description": "The four headline numbers with their aims and progress, what the rider can hold "
     "for about an hour (and how it's known), best minute and best 20 minutes, zone 2 heart rate range and where it "
     "came from, heart-rate zones, maximum heart rate, the plan's power zones in watts and cadence ranges.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "recovery", "description": "Recovery from Apple Health: HRV, resting heart rate, Cardio Recovery (heart "
     "rate drop one minute after a workout) and VO2 max, each latest against the rider's usual range, and today's "
     "readiness. The rider's own: never shown to anyone else.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "plan", "description": "The goal (in the rider's words, ready-by date), the plan's phase and week, today's "
     "session or rest and why, this week's and next week's sessions (ids, days, status), weekly hours, usual days.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "climbs", "description": "The rider's repeated climbs, timed like segments: name, length, height gained, "
     "attempts, best time, recent attempts with time, speed and heart rate. Optional name filter.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}}},
    {"name": "show", "description": "Put a chart under your answer. type 'trend': a measure over time (same inputs as "
     "the trend tool); 'aim': one headline number against its aim (metric id from fitness); 'ride': a ride snapshot "
     "with its time in zone 2.",
     "input_schema": {"type": "object", "properties": {
         "type": {"type": "string", "enum": ["trend", "aim", "ride"]}, "title": {"type": "string"},
         "measure": {"type": "string", "enum": list(MEASURES)}, "by": {"type": "string", "enum": ["ride", "week", "month"]},
         "since": _DATE, "where": _WHERE, "kind": {"type": "string", "enum": _KINDS},
         "metric": {"type": "string"}, "ride_id": {"type": "string"}}, "required": ["type"]}},
    {"name": "give_advice", "description": "Record the one thing you're advising, so the app follows up after the "
     "rider's next rides with the engine's numbers. 'measure' is how we'll know it worked, 'want' the direction, "
     "where/kind which rides it applies to.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string", "description": "At most 8 words, e.g. 'Shift down early on climbs'."},
         "do": {"type": "string", "description": "One or two sentences: what to do, this week."},
         "why": {"type": "string", "description": "One sentence, from their data."},
         "measure": {"type": "string", "enum": list(MEASURES)}, "want": {"type": "string", "enum": ["up", "down"]},
         "where": _WHERE, "kind": {"type": "string", "enum": _KINDS}},
         "required": ["title", "do", "why", "measure", "want"]}},
    {"name": "propose_change", "description": "Propose a change to the plan, for the rider to OK with one tap. Types: "
     "'ease' (make a week easier: week_start), 'swap' (a session to another kind: session_id, to_kind), 'hours' "
     "(weekly_hours), 'days' (usual riding days, 0=Monday). The engine checks it fits the plan's limits.",
     "input_schema": {"type": "object", "properties": {
         "type": {"type": "string", "enum": ["ease", "swap", "hours", "days"]}, "week_start": _DATE,
         "session_id": {"type": "string"}, "to_kind": {"type": "string", "enum": [k for k in _KINDS if k not in ("mixed", "easy_any")]},
         "weekly_hours": {"type": "number"}, "days": {"type": "array", "items": {"type": "integer"}},
         "why": {"type": "string", "description": "One sentence for the rider."}}, "required": ["type", "why"]}},
    {"name": "remember", "description": "Keep a short note about the rider for future coaching (they can see and delete "
     "it): their bike or sensors, an injury, the days they can ride, an event, how they like to train.",
     "input_schema": {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]}},
]
TOOLS[-1]["cache_control"] = {"type": "ephemeral"}


class Tools:
    """What one question's tool calls run against. Read-only, except the records the coach keeps (advice, proposed
    changes, memory), which change nothing in the rider's plan or data."""

    def __init__(self, be, uid: int, chat_id: int):
        self.be, self.uid, self.chat_id = be, uid, chat_id
        self._rider: Optional[Rider] = None
        self.charts: list[dict] = []
        self.advice: list[int] = []
        self.actions: list[int] = []
        self.looked: list[str] = []      # what the coach looked at, for the "Looking at ..." line while it works

    @property
    def rider(self) -> Rider:
        if self._rider is None:
            self._rider = Rider(self.be, self.uid)
        return self._rider

    def run(self, name: str, args: dict):
        fn = getattr(self, "t_" + name, None)
        if fn is None:
            raise ValueError(f"no tool {name}")
        return fn(**{k: v for k, v in (args or {}).items() if v is not None})

    # -- read --------------------------------------------------------------------------------------------------
    def _row(self, f) -> dict:
        r = self.rider
        felt = self.be.ride_feel(self.uid, f["ride_id"])
        row = {"ride_id": f["ride_id"], "date": r.day(f).isoformat(), "weekday": r.day(f).strftime("%a"),
               "where": r.where(f), "kind": r.kind_title(f), "minutes": round((f.get("moving_s") or 0) / 60),
               "km": r.value(f, "km"), "climbing_m": r.value(f, "climbing_m"), "avg_kmh": r.value(f, "avg_kmh"),
               "avg_hr": r.value(f, "avg_hr"), "max_hr": _r(f.get("max_hr")), "avg_power_w": r.value(f, "avg_power"),
               "cadence_rpm": r.value(f, "cadence"), "zone2_pct": r.value(f, "zone2_share"),
               "above_zone2_pct": r.value(f, "above_zone2_share"), "felt": (felt or {}).get("feel")}
        return {k: v for k, v in row.items() if v is not None}

    def t_rides(self, since=None, until=None, where="any", kind=None, limit=15):
        self.looked.append("your rides")
        fs = self.rider.select(_date(since), _date(until), where, kind)
        fs = list(reversed(fs))[:max(1, min(int(limit), 40))]
        return {"rides": [self._row(f) for f in fs], "count": len(fs),
                "note": "Outdoor rides have no power or cadence unless a sensor recorded it."}

    def t_ride(self, ride_id):
        r = self.rider
        f = next((x for x in r.feats if x["ride_id"] == str(ride_id)), None)
        if f is None:
            return {"error": "no such ride"}
        self.looked.append(f"your ride on {r.day(f).strftime('%-d %b')}")
        w = f.get("work") or {}
        out = self._row(f)
        pc = f.get("power_curve") or {}
        out["power_bests_w"] = {k: _r(pc.get(s)) for k, s in (("1 min", "60"), ("5 min", "300"), ("20 min", "1200"))
                                if pc.get(s)}
        out["hard_pushes"] = [{"at_min": round(p[0] / 60), "seconds": p[1], "watts": p[2], "rpm": p[3] if len(p) > 3 else None}
                              for p in (w.get("pushes") or [])[:12]]
        out["push_cadence_rpm"] = r.value(f, "push_cadence")
        out["interval_sets"] = [{"repeat": s["repeat"], "seconds": s["seconds"], "watts": s["power"],
                                 "rest_s": s["rest_s"], "rest_watts": s["rest_power"]} for s in w.get("sets") or []]
        if f.get("z2_drift"):
            out["drift_at_steady_power"] = {"pct": f["z2_drift"]["pct"], "watts": f["z2_drift"]["watts"],
                                            "hr": f["z2_drift"]["hr"], "minutes": f["z2_drift"]["minutes"],
                                            "ok_below_pct": 5}
        out["zone2_watts"] = r.value(f, "zone2_watts")
        out["climbs"] = self._climbs_on(f["ride_id"])
        out["notable"] = [n.get("text") for n in self.be.notes(self.uid, f["ride_id"]) if n.get("text")][:5]
        try:
            note = self.be.train_ride_note(self.uid, f["ride_id"])
        except Exception:          # the note is a nice-to-have here
            log.exception("coach: ride note for %s", ride_id)
            note = None
        if note:
            keep = ("title", "summary", "lines", "counted_as", "left", "try", "done_well", "why", "zone2", "feel")
            out["train_note"] = _slim({k: note[k] for k in keep if note.get(k)})
        return {k: v for k, v in out.items() if v not in (None, [], {})}

    def _climbs_on(self, ride_id: str) -> list[dict]:
        with self.be.lock:
            rows = self.be.db.execute(
                "SELECT a.climb_id, a.data, c.auto_name, c.custom_name FROM climb_attempts a JOIN climbs c "
                "ON c.user_id = a.user_id AND c.climb_id = a.climb_id WHERE a.user_id = ? AND a.ride_id = ?",
                (self.uid, ride_id)).fetchall()
        out = []
        for row in rows:
            a = json.loads(row["data"])
            out.append({"climb": row["custom_name"] or row["auto_name"], "time": _mmss(a.get("seconds")),
                        "kmh": a.get("kmh"), "avg_hr": a.get("avg_hr")})
        return out

    def series(self, measure, by="week", since=None, until=None, where="any", kind=None) -> dict:
        r = self.rider
        if measure not in MEASURES:
            return {"error": "unknown measure"}
        label, unit, _, _ = MEASURES[measure]
        start = _date(since) or (r.c["today"] - timedelta(days={"ride": 60, "week": 84, "month": 365}[by]))
        fs = r.select(start, _date(until), where, kind)
        pts = []
        if by == "ride":
            for f in fs:
                v = r.value(f, measure)
                if v is not None:
                    pts.append({"label": r.day(f).strftime("%-d %b"), "date": r.day(f).isoformat(), "value": v,
                                "ride_id": f["ride_id"]})
        else:
            groups: dict = {}
            for f in fs:
                d = r.day(f)
                key = d - timedelta(days=d.weekday()) if by == "week" else d.replace(day=1)
                groups.setdefault(key, []).append(f)
            k = start - timedelta(days=start.weekday()) if by == "week" else start.replace(day=1)
            end = _date(until) or r.c["today"]
            while k <= end:
                v = r.weekly(groups.get(k, []), measure) if groups.get(k) or measure in WEEKLY_SUM else None
                if v is not None:
                    pts.append({"label": k.strftime("%-d %b") if by == "week" else k.strftime("%b %Y"),
                                "date": k.isoformat(), "value": v, "rides": len(groups.get(k, []))})
                k = k + timedelta(days=7) if by == "week" else (k.replace(day=28) + timedelta(days=4)).replace(day=1)
        out = {"measure": measure, "label": label, "unit": unit, "by": by, "points": pts}
        if pts:
            first, last = pts[0]["value"], pts[-1]["value"]
            out.update(first=first, last=last, change=_r(last - first, 1 if isinstance(last, float) else 0))
        else:
            out["none"] = ("No rides with this measure in that time." +
                           (" Cadence comes only from rides with a cadence sensor (indoors, the trainer)."
                            if "cadence" in measure else
                            " Power comes only from rides with a power source." if MEASURES[measure][2] == "power" else ""))
        if measure in ("zone2_share", "above_zone2_share", "avg_hr") and r.z2:
            out["zone2_bpm"] = r.z2
        if measure in ("cadence", "push_cadence"):
            out["band"] = [85, 95]
        return out

    def t_trend(self, measure, by="week", since=None, until=None, where="any", kind=None):
        self.looked.append(MEASURES.get(measure, ("your riding",))[0].lower())
        return self.series(measure, by, since, until, where, kind)

    def t_fitness(self):
        from rideengine.analysis import plan as p
        self.looked.append("your fitness numbers")
        c = self.rider.c
        h = self.be.headline(self.uid)
        metrics = []
        for m in h["metrics"]:
            metrics.append({k: m.get(k) for k in ("id", "label", "unit", "current", "target", "focus")} |
                           {"progress_pct": None if m.get("progress") is None else round(m["progress"] * 100)})
        aim = c["aim"].get("watts")
        zones = ({v["name"]: [round(v["ftp"][0] * aim), round(v["ftp"][1] * aim)] for v in p.ZONES.values()}
                 if aim else None)
        pw = self.be.power(self.uid) or {}
        return {"headline": metrics, "next": (h.get("next") or {}).get("text"), "goal": h.get("goal"),
                "hold_for_an_hour_w": aim, "how_known": c["aim"].get("source"),
                "best_20min_w": pw.get("best_1200s"), "best_minute_w": pw.get("best_60s"),
                "zone2": ({"bpm": c["zone2"]["bpm"], "source": c["zone2"].get("source")} if c.get("zone2") else None),
                "hr_zones": c.get("hr_zones"), "max_hr": c.get("max_hr"), "resting_hr_usual": c.get("resting_hr"),
                "power_zones_w": zones, "cadence_rpm": {p.ZONES[z]["name"]: list(v) for z, v in p.CADENCE.items()},
                "cadence_climbing_low_rpm": 65, "cadence_steady_low_rpm": 75}

    def t_recovery(self):
        self.looked.append("your recovery")
        rec = self.be.recovery(self.uid)
        return _slim(rec)

    def t_plan(self):
        self.looked.append("your plan")
        t = self.be.train_today(self.uid)
        view = self.be.plan_view(self.uid)
        out = {"state": t.get("state"), "today": t.get("date"), "week": t.get("week"), "weeks": t.get("weeks"),
               "phase": t.get("phase"), "why_today": t.get("why"), "then": t.get("then"),
               "today_session": (t.get("session") or {}).get("title"), "readiness": t.get("readiness"),
               "goal": self.be.headline(self.uid).get("goal")}
        if view:
            out["weekly_hours"] = view.get("weekly_hours")
            out["usual_days"] = view.get("days")
            today = self.rider.c["today"]
            for label, w in (("this_week", self.be._this_week(view, today)),
                             ("next_week", next((w for w in view["weeks"] if date.fromisoformat(w["week_start"]) > today), None))):
                if w:
                    out[label] = {"week_start": w["week_start"], "phase": w.get("phase"),
                                  "sessions": [{"id": s["id"], "date": s.get("date"), "title": s["title"], "kind": s.get("kind"),
                                                "job": s.get("job"), "minutes": round((s.get("seconds") or 0) / 60),
                                                "status": s.get("status")} for s in w["sessions"]]}
        return _slim(out)

    def t_climbs(self, name=None):
        self.looked.append("your climbs")
        with self.be.lock:
            climbs = self.be.db.execute("SELECT climb_id, auto_name, custom_name, data FROM climbs WHERE user_id = ?",
                                        (self.uid,)).fetchall()
            atts = self.be.db.execute("SELECT climb_id, ride_id, at_t, data FROM climb_attempts WHERE user_id = ? "
                                      "ORDER BY at_t", (self.uid,)).fetchall()
        by: dict = {}
        for a in atts:
            by.setdefault(a["climb_id"], []).append((a["at_t"], json.loads(a["data"])))
        out = []
        for c in climbs:
            nm = c["custom_name"] or c["auto_name"] or "A climb"
            if name and name.lower() not in nm.lower():
                continue
            d = json.loads(c["data"])
            tries = by.get(c["climb_id"], [])
            secs = [x.get("seconds") for _, x in tries if x.get("seconds")]
            out.append({"climb_id": c["climb_id"], "name": nm, "length_m": _r(d.get("length_m")),
                        "gain_m": _r(d.get("gain_m")), "attempts": len(tries), "best": _mmss(min(secs)) if secs else None,
                        "recent": [{"date": datetime.fromtimestamp(t, self.rider.tz).date().isoformat(),
                                    "time": _mmss(x.get("seconds")), "kmh": x.get("kmh"), "avg_hr": x.get("avg_hr")}
                                   for t, x in tries[-5:]]})
        out.sort(key=lambda x: -x["attempts"])
        return {"climbs": out[:12]}

    # -- show --------------------------------------------------------------------------------------------------
    def t_show(self, type, title=None, measure=None, by=None, since=None, where="any", kind=None, metric=None, ride_id=None):
        if len(self.charts) >= MAX_CHARTS:
            return {"error": f"at most {MAX_CHARTS} charts per answer"}
        if type == "trend":
            s = self.series(measure or "km", by or "ride", since, None, where, kind)
            if not s.get("points"):
                return {"error": "nothing to show", **s}
            chart = {"type": "trend", "title": title or s["label"], "unit": s["unit"],
                     "points": [{"label": p["label"], "value": p["value"]} for p in s["points"][-16:]],
                     "band": s.get("band") or (s["zone2_bpm"] if measure == "avg_hr" and s.get("zone2_bpm") else None)}
        elif type == "aim":
            h = self.be.headline(self.uid)
            m = next((x for x in h["metrics"] if x["id"] == metric), None)
            if m is None or m.get("current") is None:
                return {"error": "no such headline number", "ids": [x["id"] for x in h["metrics"]]}
            chart = {"type": "aim", "title": title or m["label"], "unit": m.get("unit") or "",
                     "start": m.get("baseline"),
                     "current": m["current"], "target": m.get("target")}
        elif type == "ride":
            r = self.rider
            f = next((x for x in r.feats if x["ride_id"] == str(ride_id)), None)
            if f is None:
                return {"error": "no such ride"}
            row = self._row(f)
            chart = {"type": "ride", "title": title or (row.get("kind") or "Ride"), "ride_id": f["ride_id"],
                     "date": r.day(f).strftime("%a %-d %b"), "where": row["where"], "minutes": row["minutes"],
                     "km": row.get("km"), "avg_hr": row.get("avg_hr"), "avg_power": row.get("avg_power_w"),
                     "zone2": self._split(f)}
        else:
            return {"error": "unknown chart"}
        self.charts.append(chart)
        return {"shown": chart}

    def _split(self, f) -> Optional[dict]:
        """A ride's time in zone 2 in the shape the app's zone 2 card reads (Zone2Split)."""
        from rideengine.analysis import zone2
        z2 = self.rider.z2
        sp = zone2.split([f.get("hr_hist")], z2) if z2 else None
        if not sp:
            return None
        w = zone2.watts([f.get("hr_hist")], z2, min_s=10 * 60)
        return {"in": sp["in"], "above": sp["above"], "below": sp["below"], "minutes": sp["minutes"],
                "bpm": list(z2), "line": None, "watts": w["watts"] if w else None}

    # -- records the coach keeps -------------------------------------------------------------------------------
    def t_give_advice(self, title, do, why, measure, want, where="any", kind=None):
        if measure not in MEASURES:
            return {"error": "unknown measure"}
        r = self.rider
        before = [f for f in r.select(r.c["today"] - timedelta(days=60), None, where, kind)
                  if r.value(f, measure) is not None][-6:]
        base = r.weekly(before, measure) if measure not in WEEKLY_SUM else None
        if measure in WEEKLY_SUM:     # a weekly total's baseline: the last four weeks' typical week
            weeks = self.series(measure, "week", (r.c["today"] - timedelta(days=28)).isoformat(), None, where, kind)["points"]
            base = _median([p["value"] for p in weeks[:-1]] or [p["value"] for p in weeks])
        data = {"title": title.strip()[:80], "do": do.strip(), "why": why.strip(), "measure": measure, "want": want,
                "where": where, "kind": kind, "baseline": base, "baseline_rides": len(before),
                "since": r.c["today"].isoformat()}
        aid = self.be.coach_chat.add_advice(self.uid, self.chat_id, data)
        self.advice.append(aid)
        label, unit = MEASURES[measure][:2]
        return {"saved": aid, "baseline": base, "unit": unit, "measure": label,
                "note": "The app will check this after the rider's next rides." +
                        ("" if base is not None else " There's no baseline yet: the first rides will set it.")}

    def t_propose_change(self, type, why, week_start=None, session_id=None, to_kind=None, weekly_hours=None, days=None):
        p = self.be.coach_chat.check_change(self.uid, {"type": type, "week_start": week_start, "session_id": session_id,
                                                        "to_kind": to_kind, "weekly_hours": weekly_hours, "days": days})
        if p.get("why_not"):
            return {"proposed": False, "why_not": p["why_not"]}
        aid = self.be.coach_chat.add_action(self.uid, self.chat_id, {**p, "why": why.strip()})
        self.actions.append(aid)
        return {"proposed": True, "preview": p["preview"], "note": "Waiting for the rider's OK."}

    def t_remember(self, note):
        note = " ".join(str(note).split())[:200]
        if not note:
            return {"error": "empty"}
        nid = self.be.coach_chat.remember(self.uid, note)
        return {"saved": nid}


# --- the conversation, advice, changes and memory, stored --------------------------------------------------------
class CoachChat:
    """One per backend (`be.coach_chat`). Answers run on a worker thread; the app asks for the conversation until the
    answer is there, seeing what the coach is looking at while it works."""

    def __init__(self, be, background: bool = True):
        """background: answer on a worker thread (the server). Off, `ask` answers before it returns (tests, the
        command line)."""
        self.be, self.background = be, background
        self.db, self.lock = be.db, be.lock

    @property
    def coach(self):
        return self.be.coach

    # -- the conversation ------------------------------------------------------------------------------------
    def thread(self, uid: int) -> int:
        with self.lock:
            row = self.db.execute("SELECT MAX(thread) AS t FROM coach_chat WHERE user_id = ?", (uid,)).fetchone()
        return row["t"] or 1

    def new_thread(self, uid: int) -> int:
        t = self.thread(uid) + 1
        with self.lock:
            self.db.execute("INSERT INTO coach_chat (user_id, thread, role, text, data, status, at) "
                            "VALUES (?, ?, 'start', '', '{}', 'done', ?)", (uid, t, time.time()))
        return t

    def messages(self, uid: int, after: int = 0, thread: Optional[int] = None, limit: int = 60) -> list[dict]:
        t = thread or self.thread(uid)
        with self.lock:
            rows = self.db.execute("SELECT id, role, text, data, status, progress, at FROM coach_chat WHERE user_id = ? "
                                   "AND thread = ? AND id > ? AND role != 'start' ORDER BY id DESC LIMIT ?",
                                   (uid, t, after, limit)).fetchall()
        out = []
        for r in reversed(rows):
            d = json.loads(r["data"] or "{}")
            m = {"id": r["id"], "role": r["role"], "text": r["text"], "status": r["status"], "at": r["at"]}
            if r["status"] == "working":
                m["progress"] = r["progress"] or "Thinking"
            if d.get("charts"):
                m["charts"] = d["charts"]
            if d.get("ride_id"):
                m["ride_id"] = d["ride_id"]
            if d.get("actions"):
                m["actions"] = [a for a in (self.action(uid, i) for i in d["actions"]) if a]
            if d.get("advice"):
                m["advice"] = [a for a in (self.advice_view(uid, i) for i in d["advice"]) if a]
            out.append(m)
        return out

    def _add(self, uid, role, text, data=None, status="done", thread=None) -> int:
        with self.lock:
            cur = self.db.execute("INSERT INTO coach_chat (user_id, thread, role, text, data, status, at) "
                                  "VALUES (?, ?, ?, ?, ?, ?, ?)",
                                  (uid, thread or self.thread(uid), role, text, json.dumps(data or {}), status, time.time()))
            return cur.lastrowid

    def _update(self, mid, **kw):
        sets = ", ".join(f"{k} = ?" for k in kw)
        vals = [json.dumps(v) if k == "data" else v for k, v in kw.items()]
        with self.lock:
            self.db.execute(f"UPDATE coach_chat SET {sets} WHERE id = ?", (*vals, mid))

    def spent_today(self, uid: int) -> float:
        start = datetime.now(self.be.insights.tz(uid)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        with self.lock:
            row = self.db.execute("SELECT COALESCE(SUM(cost_usd), 0) AS usd FROM coach_usage WHERE user_id = ? "
                                  "AND key LIKE 'chat:%' AND at >= ?", (uid, start)).fetchone()
        return row["usd"]

    def ask(self, uid: int, text: str, ride_id: Optional[str] = None, wait: bool = False) -> dict:
        """The rider's question, saved, and the coach's answer started (on a worker thread, or now with `wait`)."""
        text = (text or "").strip()[:2000]
        if not text:
            raise ValueError("Ask the coach something")
        if not self.coach.allowed(uid):
            raise PermissionError("The coach is off")
        with self.lock:
            busy = self.db.execute("SELECT id FROM coach_chat WHERE user_id = ? AND status = 'working' AND at > ?",
                                   (uid, time.time() - 300)).fetchone()
        if busy:
            raise ValueError("The coach is still answering")
        q = self._add(uid, "rider", text, {"ride_id": ride_id} if ride_id else {})
        a = self._add(uid, "coach", "", status="working")
        if self.spent_today(uid) >= DAY_LIMIT_USD:
            self._update(a, text="That's all the coaching I can do today: there's a daily limit on what I spend. "
                                 "Ask me again tomorrow.", status="done")
        elif wait or not self.background:
            self._answer(uid, q, a)
        else:
            threading.Thread(target=self._answer, args=(uid, q, a), daemon=True).start()
        return {"question": q, "answer": a, "messages": self.messages(uid, after=q - 1)}

    def _context(self, uid: int, ride_id: Optional[str]) -> str:
        me = self.be.me(uid)
        tz = self.be.insights.tz(uid)
        now = datetime.now(tz)
        lines = [f"Today is {now.strftime('%A %-d %B %Y')}, {now.strftime('%H:%M')} for the rider.",
                 f"The rider: {me.get('name') or 'Rider'}."]
        g = self.be.headline(uid).get("goal")
        if g:
            lines.append("Their goal: " + json.dumps({k: g.get(k) for k in ("title", "words", "ready_by") if g.get(k)}))
        notes = self.memory(uid)
        if notes:
            lines.append("What you remember about them:\n" + "\n".join(f"- {n['note']}" for n in notes))
        adv = [a for a in self.advice_list(uid) if a["status"] in ("waiting", "working", "not_yet")]
        if adv:
            lines.append("Advice you're following up:\n" + "\n".join(
                f"- {a['title']} ({a['status_label']}): {a.get('check') or 'no rides since'}" for a in adv))
        if ride_id:
            lines.append(f"They're asking about the ride with ride_id {ride_id}: look at it with the ride tool.")
        return "\n".join(lines)

    def _history(self, uid: int, before: int) -> list[dict]:
        t = self.thread(uid)
        with self.lock:
            rows = self.db.execute("SELECT role, text FROM coach_chat WHERE user_id = ? AND thread = ? AND id < ? "
                                   "AND role IN ('rider', 'coach') AND status = 'done' AND text != '' "
                                   "ORDER BY id DESC LIMIT ?", (uid, t, before, HISTORY)).fetchall()
        out = []
        for r in reversed(rows):
            role = "user" if r["role"] == "rider" else "assistant"
            if out and out[-1]["role"] == role:
                out[-1]["content"] += "\n\n" + r["text"]
            else:
                out.append({"role": role, "content": r["text"]})
        if out and out[0]["role"] == "assistant":
            out.pop(0)
        return out

    def _answer(self, uid: int, qid: int, aid: int) -> None:
        try:
            self._answer_now(uid, qid, aid)
        except Exception:
            log.exception("coach chat failed for user %s", uid)
            self._update(aid, text="Something went wrong on my side. Ask me again in a moment.", status="failed")

    def _answer_now(self, uid: int, qid: int, aid: int) -> None:
        import anthropic
        with self.lock:
            q = self.db.execute("SELECT text, data FROM coach_chat WHERE id = ?", (qid,)).fetchone()
        qdata = json.loads(q["data"] or "{}")
        tools = Tools(self.be, uid, aid)
        history = self._history(uid, qid)
        context = self._context(uid, qdata.get("ride_id"))
        messages = history + [{"role": "user", "content": q["text"]}]
        seen = [q["text"], context] + [m["content"] for m in history]
        started = time.time()
        text, tries = "", 0
        client = self.coach.client()
        for _ in range(MAX_ROUNDS):
            try:
                r = client.messages.create(
                    model=MODEL, max_tokens=8000, output_config={"effort": "medium"},
                    system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}},
                            {"type": "text", "text": context}],
                    tools=TOOLS, messages=messages)
            except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
                log.warning("coach chat call failed: %s", type(exc).__name__)
                self._log(uid, aid, None, started, False)
                self._update(aid, text="I couldn't reach my thinking just now. Ask me again in a moment.", status="failed")
                return
            self._log(uid, aid, r.usage, started, True)
            if r.stop_reason == "refusal":
                text = "That's not something I can help with. I'm your riding coach: ask me about your riding."
                break
            messages.append({"role": "assistant", "content": r.content})
            uses = [b for b in r.content if b.type == "tool_use"]
            if r.stop_reason == "pause_turn":
                continue
            if uses:
                results = []
                for b in uses:
                    try:
                        res = tools.run(b.name, b.input)
                        seen.append(res)
                        results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(res, default=str)})
                    except Exception as exc:
                        log.exception("coach tool %s failed", b.name)
                        results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                                        "content": f"That didn't work: {type(exc).__name__}"})
                messages.append({"role": "user", "content": results})
                if tools.looked:
                    self._update(aid, progress="Looking at " + tools.looked[-1])
                continue
            text = "".join(b.text for b in r.content if b.type == "text").strip()
            bad = check_answer(text, allowed_numbers(*seen, self._said(uid, aid)))
            if not bad:
                break
            tries += 1
            if tries > 1:
                log.info("coach chat: numbers not backed up after a retry: %s", bad)
                text = ("I started to answer with numbers I couldn't check against your rides, so I won't guess. "
                        "Ask me again, or ask about a particular ride or week.")
                break
            messages.append({"role": "user", "content": "(Kova's number check) These numbers aren't in what your tools "
                             f"returned: {', '.join(sorted(set(bad)))}. Look them up, use the numbers as the tools give "
                             "them, or say it without them. Reply with the whole answer again."})
            self._update(aid, progress="Checking the numbers")
        else:
            text = text or "I looked at a lot and didn't get to an answer. Try asking about one thing at a time."
        data = {"charts": tools.charts, "actions": tools.actions, "advice": tools.advice}
        self._update(aid, text=text, data={k: v for k, v in data.items() if v}, status="done", progress=None)

    def _said(self, uid: int, before: int) -> str:
        with self.lock:
            rows = self.db.execute("SELECT text FROM coach_chat WHERE user_id = ? AND role = 'coach' AND id < ? "
                                   "ORDER BY id DESC LIMIT 20", (uid, before)).fetchall()
        return " ".join(r["text"] for r in rows)

    def _log(self, uid, aid, usage, started, ok):
        cost = coach_mod._cost(usage)
        with self.lock:
            self.db.execute("INSERT INTO coach_usage (user_id, key, model, input_tokens, output_tokens, cache_read, "
                            "cache_write, cost_usd, seconds, ok, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (uid, f"chat:{aid}", MODEL, *cost["tokens"], cost["usd"], round(time.time() - started, 2),
                             1 if ok else 0, time.time()))

    # -- memory ----------------------------------------------------------------------------------------------
    def remember(self, uid: int, note: str) -> int:
        with self.lock:
            same = self.db.execute("SELECT id FROM coach_memory WHERE user_id = ? AND note = ?", (uid, note)).fetchone()
            if same:
                return same["id"]
            return self.db.execute("INSERT INTO coach_memory (user_id, note, at) VALUES (?, ?, ?)",
                                   (uid, note, time.time())).lastrowid

    def memory(self, uid: int) -> list[dict]:
        with self.lock:
            return [{"id": r["id"], "note": r["note"], "at": r["at"]} for r in self.db.execute(
                "SELECT id, note, at FROM coach_memory WHERE user_id = ? ORDER BY id", (uid,))]

    def forget(self, uid: int, nid: int) -> bool:
        with self.lock:
            return self.db.execute("DELETE FROM coach_memory WHERE user_id = ? AND id = ?", (uid, nid)).rowcount > 0

    # -- advice and the follow-up ----------------------------------------------------------------------------
    def add_advice(self, uid: int, chat_id: int, data: dict) -> int:
        with self.lock:
            live = self.db.execute("SELECT id FROM coach_advice WHERE user_id = ? AND status = 'open' ORDER BY id",
                                   (uid,)).fetchall()
            for r in live[:max(0, len(live) - MAX_ADVICE + 1)]:
                self.db.execute("UPDATE coach_advice SET status = 'replaced' WHERE id = ?", (r["id"],))
            return self.db.execute("INSERT INTO coach_advice (user_id, chat_id, data, status, at) VALUES (?, ?, ?, 'open', ?)",
                                   (uid, chat_id, json.dumps(data), time.time())).lastrowid

    def set_advice(self, uid: int, aid: int, status: str) -> bool:
        if status not in ("done", "dropped", "open"):
            raise ValueError("status is done, dropped or open")
        with self.lock:
            return self.db.execute("UPDATE coach_advice SET status = ? WHERE user_id = ? AND id = ?",
                                   (status, uid, aid)).rowcount > 0

    def follow_up(self, rider: Rider, data: dict, at: float) -> dict:
        """How the advice is going, from the rides since it was given: the engine's numbers, the engine's words."""
        m = data["measure"]
        label, unit, _, step = MEASURES[m]
        since = datetime.fromtimestamp(at, rider.tz).date()
        fs = [f for f in rider.select(since, None, data.get("where") or "any", data.get("kind"))
              if f["start"] >= at and rider.value(f, m) is not None]
        base = data.get("baseline")
        u = f" {unit}" if unit and unit != "%" else unit
        if not fs:
            return {"status": "waiting", "status_label": "Waiting for a ride", "rides": 0, "last_ride": None,
                    "check": None}
        n = len(fs)
        rides = "1 ride" if n == 1 else f"{n} rides"
        if m in WEEKLY_SUM:          # a weekly total: per week since the advice (a week at least)
            weeks = max(1.0, (rider.c["today"] - since).days / 7)
            now = _r(rider.weekly(fs, m) / weeks, 1 if m in ("km", "hours") else 0)
            if weeks > 1:
                u += " a week"
        else:
            now = rider.weekly(fs, m)
        if base is None:
            return {"status": "working" if n >= 2 else "waiting", "status_label": "Started", "rides": n, "now": now,
                    "last_ride": fs[-1]["ride_id"],
                    "check": f"{label}: {now}{u} over {rides} since. That's the starting point to beat."}
        better = (now - base) if data["want"] == "up" else (base - now)
        status = "working" if better >= step else "not_yet"
        word = "up from" if now > base else "down from" if now < base else "the same as"
        line = f"{label}: {now}{u} over {rides} since, {word} {base}{u} before."
        return {"status": status, "status_label": "Working" if status == "working" else "Not yet",
                "rides": n, "now": now, "last_ride": fs[-1]["ride_id"], "check": line}

    def advice_list(self, uid: int, rider: Optional[Rider] = None, include_closed: bool = False) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT id, chat_id, data, status, at, checked FROM coach_advice WHERE user_id = ? "
                                   + ("" if include_closed else "AND status = 'open' ") + "ORDER BY id DESC LIMIT 10",
                                   (uid,)).fetchall()
        if not rows:
            return []
        rider = rider or Rider(self.be, uid)
        out = []
        for r in rows:
            d = json.loads(r["data"])
            view = {"id": r["id"], "title": d["title"], "do": d["do"], "why": d["why"],
                    "measure": MEASURES[d["measure"]][0], "unit": MEASURES[d["measure"]][1], "want": d["want"],
                    "baseline": d.get("baseline"), "since": d.get("since"), "closed": r["status"]}
            if r["status"] == "open":
                view.update(self.follow_up(rider, d, r["at"]))
                self._checked_in(uid, r, view)
            out.append(view)
        return out

    def advice_view(self, uid: int, aid: int) -> Optional[dict]:
        with self.lock:
            r = self.db.execute("SELECT id, data, status FROM coach_advice WHERE user_id = ? AND id = ?", (uid, aid)).fetchone()
        if r is None:
            return None
        d = json.loads(r["data"])
        return {"id": r["id"], "title": d["title"], "do": d["do"], "measure": MEASURES[d["measure"]][0],
                "status": r["status"]}

    def _checked_in(self, uid: int, row, view: dict) -> None:
        """After a new ride the advice applies to, the coach checks in, once per ride, in the conversation."""
        if not view.get("last_ride") or row["checked"] == view["last_ride"]:
            return
        with self.lock:
            self.db.execute("UPDATE coach_advice SET checked = ? WHERE id = ?", (view["last_ride"], row["id"]))
        lead = {"working": "It's working.", "not_yet": "Not moving yet.", "waiting": "First ride in."}[view["status"]]
        more = {"working": " Keep doing it.", "not_yet": " Give it a few more rides, or ask me what to change.",
                "waiting": ""}[view["status"]]
        self._add(uid, "coach", f"Checking in on **{view['title']}**. {view['check']} {lead}{more}",
                  {"advice": [row["id"]], "checkin": True})

    # -- plan changes --------------------------------------------------------------------------------------------
    def check_change(self, uid: int, ch: dict) -> dict:
        """The engine's check on a change the coach proposes: {"type", ..., "preview"} or {"why_not"}."""
        from rideengine.analysis import plan as p
        from rideengine.analysis import review as rv
        from rideengine.analysis import train
        from rideengine.analysis.today import schedule
        view = self.be.plan_view(uid)
        if view is None:
            return {"why_not": "There's no plan yet."}
        c = self.be._plan_context(uid)
        today = c["today"]
        t = ch["type"]
        if t == "hours":
            hrs = ch.get("weekly_hours")
            if not hrs:
                return {"why_not": "How many hours?"}
            hrs = round(float(hrs) * 4) / 4
            why = rv.check({"apply": {"type": "hours", "weekly_hours": hrs}}, None, view["weekly_hours"])
            if why or hrs < 1:
                return {"why_not": (f"the plan grows at most 10% a week, so {train_hours(view['weekly_hours'])} can go to "
                                    f"{train_hours(math.floor(view['weekly_hours'] * 1.1 * 4 + 1e-9) / 4)} at most")
                        if why else "under an hour a week"}
            return {"type": "hours", "weekly_hours": hrs,
                    "preview": f"Weekly riding time: {train_hours(view['weekly_hours'])} to {train_hours(hrs)}, from next week."}
        if t == "days":
            days = sorted({int(d) for d in ch.get("days") or [] if 0 <= int(d) <= 6})
            if len(days) < 2:
                return {"why_not": "at least two riding days"}
            names = ", ".join(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[d] for d in days)
            return {"type": "days", "days": days, "preview": f"Usual riding days: {names}, from next week."}
        weeks = view["weeks"]
        if t == "ease":
            ws = ch.get("week_start")
            w = next((x for x in weeks if x["week_start"] == ws), None)
            if w is None:
                return {"why_not": "no such week"}
            if date.fromisoformat(ws) + timedelta(days=6) < today:
                return {"why_not": "that week is over"}
            if w.get("phase") in ("recovery", "taper") or w.get("eased"):
                return {"why_not": "that week is already easy"}
            label = "This week" if date.fromisoformat(ws) <= today else "Next week" if \
                date.fromisoformat(ws) <= today + timedelta(days=7) else f"The week of {date.fromisoformat(ws).strftime('%-d %b')}"
            return {"type": "ease", "week_start": ws,
                    "preview": f"{label} becomes an easier week: every session easy or zone 2, about 70% as long."}
        if t == "swap":
            sid, to = ch.get("session_id"), ch.get("to_kind")
            w = next((x for x in weeks if any(s["id"] == sid for s in x["sessions"])), None)
            if w is None or to not in p.JOB_OF:
                return {"why_not": "no such session" if w is None else "unknown kind"}
            s = next(x for x in w["sessions"] if x["id"] == sid)
            if s.get("off_bike") or s.get("status") == "done" or (s.get("date") and date.fromisoformat(s["date"]) < today):
                return {"why_not": "that session is done or past"}
            sessions = [dict(x) for x in w["sessions"] if not x.get("off_bike")]
            for x in sessions:
                if x["id"] == sid:
                    x["kind"] = to
            start = date.fromisoformat(w["week_start"])
            if schedule(sessions, start, start + timedelta(days=7), set(), set()) is None:
                return {"why_not": "the week wouldn't fit with rest between hard days"}
            when = date.fromisoformat(s["date"]).strftime("%A") if s.get("date") else "This week"
            return {"type": "swap", "session_id": sid, "to_kind": to, "week_start": w["week_start"],
                    "preview": f"{when}: {s['title']} becomes {train.TITLES.get(to, to).lower()}."}
        return {"why_not": "unknown change"}

    def add_action(self, uid: int, chat_id: int, data: dict) -> int:
        with self.lock:
            return self.db.execute("INSERT INTO coach_actions (user_id, chat_id, data, status, at) VALUES (?, ?, ?, 'open', ?)",
                                   (uid, chat_id, json.dumps(data), time.time())).lastrowid

    def action(self, uid: int, aid: int) -> Optional[dict]:
        with self.lock:
            r = self.db.execute("SELECT id, data, status FROM coach_actions WHERE user_id = ? AND id = ?", (uid, aid)).fetchone()
        if r is None:
            return None
        d = json.loads(r["data"])
        return {"id": r["id"], "preview": d["preview"], "why": d.get("why"), "status": r["status"]}

    def decide(self, uid: int, aid: int, accept: bool) -> Optional[dict]:
        """The rider's OK (checked again by the engine, the plan may have moved since) or not now."""
        with self.lock:
            r = self.db.execute("SELECT data, status FROM coach_actions WHERE user_id = ? AND id = ?", (uid, aid)).fetchone()
        if r is None or r["status"] != "open":
            return None
        d = json.loads(r["data"])
        status = "declined"
        if accept:
            again = self.check_change(uid, d)
            if again.get("why_not"):
                status = "failed"
                d["why_not"] = again["why_not"]
            else:
                self._apply(uid, again)
                status = "accepted"
        with self.lock:
            self.db.execute("UPDATE coach_actions SET status = ?, data = ? WHERE id = ?", (status, json.dumps(d), aid))
        out = self.action(uid, aid)
        if status == "failed":
            out["why_not"] = d["why_not"]
        return out

    def _apply(self, uid: int, ch: dict) -> None:
        if ch["type"] == "hours":
            self.be.make_plan(uid, weekly_hours=ch["weekly_hours"])
        elif ch["type"] == "days":
            self.be.make_plan(uid, days=ch["days"])
        else:
            a = {"type": ch["type"], "week_start": ch.get("week_start"), "session_id": ch.get("session_id"),
                 "to_kind": ch.get("to_kind")}
            self.be._apply_proposal(uid, {"apply": a}, None)

    # -- the coach's home --------------------------------------------------------------------------------------
    def home(self, uid: int) -> dict:
        """The Coach screen: the one thing, the advice being followed, what the coach watches (engine numbers), ideas
        to ask, and the conversation."""
        if not self.coach.allowed(uid):
            return {"on": False, "why": "The coach uses an AI service, so it's off until you turn on AI for your account."}
        rider = Rider(self.be, uid)
        advice = self.advice_list(uid, rider)
        watching = []
        try:
            h = self.be.headline(uid)
            for m in h["metrics"]:
                if m.get("focus") and m.get("current") is not None:
                    watching.append({"label": m["label"], "value": f"{m['current']:g}" if isinstance(m["current"], (int, float)) else str(m["current"]),
                                     "unit": m.get("unit") or "",
                                     "detail": (f"aim {m['target']:g}" if m.get("target") else None)})
        except Exception:
            log.exception("coach home: headline")
        ready = (self.be.recovery(uid).get("readiness") or {})
        if ready.get("status") and ready["status"] != "unknown":
            watching.append({"label": "Recovery", "value": ready["status"].replace("_", " ").capitalize(), "unit": "",
                             "detail": ready.get("line") or ready.get("text")})
        cad = [rider.value(f, "cadence") for f in rider.feats[-6:]]
        cad = [x for x in cad if x]
        if cad:
            watching.append({"label": "Cadence, latest", "value": str(cad[-1]), "unit": "rpm", "detail": "aim 85–95"})
        g = self._goal(uid)
        ideas = ["What should I work on next?", "Why did my last ride feel the way it did?",
                 "Am I on track for my goal?" if g else "What should my goal be?", "Should I ride hard today?"]
        return {"on": True, "one_thing": advice[0] if advice else None, "working_on": advice[1:],
                "watching": watching, "ideas": ideas, "messages": self.messages(uid),
                "remembers": len(self.memory(uid)), "spent_today_usd": round(self.spent_today(uid), 2)}

    def _goal(self, uid: int) -> Optional[dict]:
        row = self.be._active_goal_row(uid)
        return json.loads(row["data"]) if row else None

    def knows(self, uid: int) -> dict:
        with self.lock:
            n = self.db.execute("SELECT COUNT(*) FROM rides WHERE user_id = ?", (uid,)).fetchone()[0]
        return {"reads": [{"what": "Your rides", "detail": f"{n} rides, merged from every device"},
                          {"what": "Your plan and goal", "detail": "this week, next week, your aim"},
                          {"what": "Your recovery", "detail": "HRV, resting heart rate, Cardio Recovery, VO2 max. "
                                                              "For your coaching only, never shown to anyone else."},
                          {"what": "Your climbs", "detail": "timed like segments"}],
                "never": "Sleep, other workouts, or where you live.",
                "memory": self.memory(uid),
                "advice": [a for a in self.advice_list(uid, include_closed=True)],
                "disclaimer": "Training guidance from your own data, not medical advice."}


def train_hours(h: float) -> str:
    whole = int(h)
    mins = round((h - whole) * 60)
    return f"{whole} h {mins:02d}" if mins else f"{whole} h"
