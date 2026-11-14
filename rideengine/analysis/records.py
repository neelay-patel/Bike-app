"""Tallies, personal bests and what's notable about a ride (docs/roadmap.md, bucket 1).

Everything here is rule-based: the text is written by these rules, not by an AI model, so it can be
shown whatever the sources' AI terms say. Pass only visible rides (clean.visible): false starts and
empty recordings must not count. Simulated power never reaches a Ride, so power bests are measured.

Notes are worked out as of the ride: "your longest ride of 2026 so far" compares with earlier rides
only, so a ride's notes don't change when later rides arrive (a card keeps what it was).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo

from ..model import Ride
from .basics import summary

EVEREST_M = 8849
MIN_HISTORY = 5          # earlier rides needed before "yet" / "of the year" mean anything
SINCE_MIN_DAYS = 45      # "longest since ..." only when the last better ride is at least this old
SPEED_MIN_KM = 30        # average-speed bests only count outdoor rides at least this long
STREAK_WEEKS = {4, 6, 8, 10, 12, 15, 20, 26, 30, 40, 52}  # streak lengths worth a note (plus new records)
YEAR_RANK_HISTORY = 10   # earlier rides in the year before "2nd/3rd ... of the year" means anything
MAX_SINCE_NOTES = 2
MAX_NOTES = 4

# Great-circle distances (km, rounded), to put distance in real terms.
CROW_FLIES = [
    (344, "London to Paris"), (504, "Toronto to Montreal"), (551, "Toronto to New York"),
    (702, "Toronto to Chicago"), (1434, "London to Rome"), (1986, "Toronto to Miami"),
    (3358, "Toronto to Vancouver"), (5710, "Toronto to London"),
]
EARTH_KM = 40075


@dataclass(frozen=True)
class Metric:
    key: str        # field on _Entry
    kind: str       # what the app groups by
    label: str      # personal-best title
    noun: str       # "longest ride" → "your 2nd longest ride of 2026 so far"
    unit: str
    decimals: int


METRICS = [
    Metric("km", "distance", "Longest ride", "longest ride", "km", 1),
    Metric("ascent", "climbing", "Most climbing", "hilliest ride", "m", 0),
    Metric("hours", "time", "Longest in the saddle", "longest ride by time", "h", 2),
    Metric("kmh", "speed", f"Fastest average ({SPEED_MIN_KM} km+)", "fastest ride", "km/h", 1),
    Metric("power", "power", "Highest average power", "highest-powered ride", "W", 0),
]
_BY_KEY = {m.key: m for m in METRICS}

KM_MILESTONE_YEAR = 500       # "took 2026 past 2,000 km"
KM_MILESTONE_ALL = 1000       # "took you past 5,000 km"
RIDE_MILESTONE = 50           # "your 100th ride"
FIRST_OVER = {"km": [50, 100, 150, 200, 300], "ascent": [500, 1000, 1500, 2000, 3000]}


@dataclass
class _Entry:
    ride_id: str
    start: float
    day: date
    km: float
    ascent: float | None
    hours: float
    kmh: float | None
    power: float | None
    indoor: bool

    def value(self, key: str) -> float | None:
        v = getattr(self, key)
        if key == "kmh" and (self.indoor or self.km < SPEED_MIN_KM):
            return None
        return v if v else None


def ride_id(ride: Ride) -> str:
    return str(int(ride.start))


def entries(rides: list[Ride], tz: tzinfo | None = None) -> list[_Entry]:
    """One flat record per ride, oldest first, in the rider's local time."""
    out = []
    for r in rides:
        s = summary(r)
        out.append(_Entry(ride_id(r), r.start, datetime.fromtimestamp(r.start, tz).astimezone(tz).date(),
                          s["km"] or 0.0, s["ascent_m"], s["moving_h"] or 0.0, s["avg_kmh"],
                          s["avg_power"] if r.provenance.get("channel:power") else None, r.indoor))
    return sorted(out, key=lambda e: e.start)


def entries_from_features(feats: list[dict], tz: tzinfo | None = None) -> list[_Entry]:
    """The same records from stored per-ride features (features.extract), without the samples."""
    out = [_Entry(f["ride_id"], f["start"], datetime.fromtimestamp(f["start"], tz).astimezone(tz).date(),
                  f["km"], f["ascent_m"], f["moving_s"] / 3600, f["kmh"], f["power"], f["indoor"]) for f in feats]
    return sorted(out, key=lambda e: e.start)


# --- formatting ------------------------------------------------------------------------------
def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _num(v: float, decimals: int = 0) -> str:
    return f"{v:,.{decimals}f}"


def _value(m: Metric, v: float) -> str:
    if m.unit == "h":
        minutes = round(v * 60)
        return f"{minutes // 60}:{minutes % 60:02d}"
    return f"{_num(v, m.decimals)} {m.unit}"


def _since(d: date, today: date) -> str:
    return d.strftime("%-d %b") if d.year == today.year else d.strftime("%B %Y")


def crow_flies(km: float) -> str | None:
    """Distance in real terms: "Toronto to Montreal and back", "2.3 times around the Earth"."""
    if km >= EARTH_KM:
        return f"{km / EARTH_KM:.1f} times around the Earth"
    best = None
    for d, name in CROW_FLIES:
        for mult, phrase in ((1, name), (2, f"{name} and back")):
            if d * mult <= km and (best is None or d * mult > best[0]):
                best = (d * mult, phrase)
    return best[1] if best else None


# --- tallies -------------------------------------------------------------------------------
def _tally(es: list[_Entry]) -> dict:
    km = sum(e.km for e in es)
    up = sum(e.ascent or 0 for e in es)
    return {"rides": len(es), "km": round(km, 1), "hours": round(sum(e.hours for e in es), 1),
            "ascent_m": round(up), "everests": round(up / EVEREST_M, 2),
            "longest_km": round(max((e.km for e in es), default=0), 1)}


def _week(d: date) -> date:
    return d - timedelta(days=d.weekday())  # Monday


def streaks(es: list[_Entry], today: date) -> dict:
    """Weeks (Monday to Sunday) in a row with at least one ride: the longest, and the current one
    (still alive if this week or last week had a ride)."""
    weeks = sorted({_week(e.day) for e in es})
    longest, run, best_from, run_from = 0, 0, None, None
    prev = None
    for w in weeks:
        run = run + 1 if prev and w - prev == timedelta(weeks=1) else 1
        run_from = w if run == 1 else run_from
        if run > longest:
            longest, best_from = run, run_from
        prev = w
    this = _week(today)
    current = run if weeks and this - weeks[-1] <= timedelta(weeks=1) else 0
    return {"longest_weeks": longest, "longest_from": best_from.isoformat() if best_from else None,
            "current_weeks": current}


def tallies(es: list[_Entry], today: date) -> dict:
    year = [e for e in es if e.day.year == today.year]
    last = [e for e in es if e.day.year == today.year - 1]
    month = [e for e in year if e.day.month == today.month]
    # Last year up to the same day, for a fair "ahead of last year" comparison.
    try:
        same_day = today.replace(year=today.year - 1)
    except ValueError:  # 29 Feb
        same_day = today.replace(year=today.year - 1, day=28)
    last_to_date = [e for e in last if e.day <= same_day]
    all_ = _tally(es)
    all_["crow_flies"] = crow_flies(all_["km"])
    months: dict[tuple[int, int], list[_Entry]] = {}
    for e in es:
        months.setdefault((e.day.year, e.day.month), []).append(e)
    big = max(months.items(), key=lambda kv: sum(e.km for e in kv[1]), default=None)
    return {
        "since": es[0].day.isoformat() if es else None,
        "all": all_,
        "year": {"label": str(today.year), **_tally(year)},
        "last_year": {"label": str(today.year - 1), **_tally(last)},
        "last_year_to_date": {"label": f"{today.year - 1} to {same_day.strftime('%-d %b')}", **_tally(last_to_date)},
        "month": {"label": today.strftime("%B %Y"), **_tally(month)},
        "biggest_month": ({"label": date(*big[0], 1).strftime("%B %Y"), **_tally(big[1])} if big else None),
        "streak": streaks(es, today),
    }


# --- personal bests ------------------------------------------------------------------------
def bests(es: list[_Entry]) -> list[dict]:
    """The best ride for each metric (the earliest one, if tied)."""
    out = []
    for m in METRICS:
        having = [e for e in es if e.value(m.key) is not None]
        if not having:
            continue
        top = max(having, key=lambda e: (e.value(m.key), -e.start))
        v = top.value(m.key)
        out.append({"kind": m.kind, "label": m.label, "value": round(v, m.decimals), "unit": m.unit,
                    "text": _value(m, v), "ride_id": top.ride_id, "start": top.start,
                    "date": top.day.isoformat()})
    return out


# --- what's notable ---------------------------------------------------------------------------
def _note(kind: str, text: str, weight: float, detail: str | None = None, pb: bool = False,
          milestone: bool = False, since: bool = False) -> dict:
    """pb: a personal best at the time (a holo card later). milestone: a round number crossed."""
    return {"kind": kind, "text": text, "detail": detail, "weight": round(weight), "pb": pb,
            "milestone": milestone, "since": since}


def _rank_notes(e: _Entry, before: list[_Entry]) -> list[dict]:
    """For each metric: best yet, top 3 of the year so far, or best since a while back."""
    out = []
    for m in METRICS:
        v = e.value(m.key)
        if v is None:
            continue
        detail = _value(m, v)
        earlier = [x for x in before if x.value(m.key) is not None]
        if len(earlier) >= MIN_HISTORY and v > max(x.value(m.key) for x in earlier):
            out.append(_note(m.kind, f"Your {m.noun} yet", 100, detail, pb=True))
            continue
        year = [x for x in earlier if x.day.year == e.day.year]
        rank = 1 + sum(1 for x in year if x.value(m.key) >= v)  # a tie ranks after the earlier ride
        if rank <= 3 and len(year) >= (MIN_HISTORY if rank == 1 else YEAR_RANK_HISTORY):
            lead = f"{_ordinal(rank)} " if rank > 1 else ""
            out.append(_note(m.kind, f"Your {lead}{m.noun} of {e.day.year} so far", 85 - 10 * rank, detail))
            continue
        better = [x for x in earlier if x.value(m.key) >= v]
        if better and len(earlier) >= MIN_HISTORY:
            last = better[-1]
            gap = (e.day - last.day).days
            if gap >= SINCE_MIN_DAYS:
                out.append(_note(m.kind, f"Your {m.noun} since {_since(last.day, e.day)}",
                                 min(60, 30 + gap / 10), detail, since=True))
    return out


def _first_over(e: _Entry, before: list[_Entry]) -> list[dict]:
    """First ride over a round number: ever (on record), or this year."""
    out = []
    for key, marks in FIRST_OVER.items():
        v = e.value(key)
        if v is None:
            continue
        crossed = [t for t in marks if v >= t]
        if not crossed:
            continue
        t = crossed[-1]
        m = _BY_KEY[key]
        if not any((x.value(key) or 0) >= t for x in before):
            text = f"Your first {_num(t)} km ride" if key == "km" else f"Your first ride with {_num(t)} m of climbing"
            out.append(_note(m.kind, text, 95, _value(m, v), pb=True, milestone=True))
        elif not any((x.value(key) or 0) >= t for x in before if x.day.year == e.day.year):
            text = (f"Your first {_num(t)} km ride of {e.day.year}" if key == "km"
                    else f"Your first ride of {e.day.year} with {_num(t)} m of climbing")
            out.append(_note(m.kind, text, 70, _value(m, v), milestone=True))
    return out


def _milestones(e: _Entry, before: list[_Entry]) -> list[dict]:
    out = []
    year_before = sum(x.km for x in before if x.day.year == e.day.year)
    year_after = year_before + e.km
    mark = int(year_after // KM_MILESTONE_YEAR) * KM_MILESTONE_YEAR
    if mark and year_before < mark:
        out.append(_note("distance", f"Took {e.day.year} past {_num(mark)} km", 65,
                         f"{_num(year_after)} km this year", milestone=True))
    all_before = sum(x.km for x in before)
    mark = int((all_before + e.km) // KM_MILESTONE_ALL) * KM_MILESTONE_ALL
    if mark and all_before < mark:
        out.append(_note("distance", f"Took you past {_num(mark)} km on record", 68, milestone=True))
    n = len(before) + 1
    if n % RIDE_MILESTONE == 0:
        out.append(_note("rides", f"Your {_ordinal(n)} ride on record", 62, milestone=True))
    up_before = sum(x.ascent or 0 for x in before if x.day.year == e.day.year)
    k = int((up_before + (e.ascent or 0)) // EVEREST_M)
    if k and up_before < k * EVEREST_M:
        text = f"A full Everest of climbing in {e.day.year}" if k == 1 else f"{k} Everests of climbing in {e.day.year}"
        out.append(_note("climbing", text, 66,
                         f"{_num(k * EVEREST_M)} m", milestone=True))
    return out


def _streak_note(e: _Entry, before: list[_Entry]) -> list[dict]:
    w = _week(e.day)
    if any(_week(x.day) == w for x in before):
        return []  # only the week's first ride says so
    run = streaks(before + [e], e.day)["current_weeks"]
    record = streaks(before, e.day)["longest_weeks"] if before else 0
    if run > record and run >= min(STREAK_WEEKS):
        return [_note("streak", f"{run} weeks in a row with a ride: your longest streak yet", 55 + min(run, 20),
                      pb=True)]
    if run in STREAK_WEEKS:
        return [_note("streak", f"{run} weeks in a row with a ride", 40 + min(run, 20), milestone=True)]
    return []


# --- repeated routes and climbs (repeats.find) --------------------------------------------------
LAP_MILESTONES = {10, 25, 50, 75, 100, 150, 200, 300, 500}


def _day_of(t: float, tz: tzinfo | None) -> date:
    return datetime.fromtimestamp(t, tz).astimezone(tz).date()


def _ranked(kind: str, items: list[dict], key: str, better, phrase: str, best_word: str, fmt, tz,
            unit_word: str) -> dict[str, list[dict]]:
    """Notes for each lap or attempt, compared with the earlier ones. `better(a, b)`: a beats b."""
    out: dict[str, list[dict]] = {}
    for i, it in enumerate(items):
        v = it.get(key)
        if v is None:
            continue
        earlier = [x for x in items[:i] if x.get(key) is not None]
        day = _day_of(it["start"], tz)
        notes = []
        detail = fmt(v)
        if len(earlier) >= MIN_REPEATS_BEFORE and all(better(v, x[key]) for x in earlier):
            notes.append(_note(kind, f"Your {best_word} {phrase} yet", 92, detail, pb=True))
        else:
            rank = 1 + sum(1 for x in earlier if not better(v, x[key]))  # ties rank after earlier
            if len(earlier) >= YEAR_RANK_HISTORY // 2 and rank <= 3:
                notes.append(_note(kind, f"Your {_ordinal(rank)} {best_word} {phrase}", 72 - 8 * (rank - 2), detail))
            elif len(earlier) >= MIN_REPEATS_BEFORE:
                beat_me = [x for x in earlier if not better(v, x[key])]
                if beat_me:
                    last = _day_of(beat_me[-1]["start"], tz)
                    gap = (day - last).days
                    if gap >= SINCE_MIN_DAYS:
                        notes.append(_note(kind, f"Your {best_word} {phrase} since {_since(last, day)}",
                                           min(58, 28 + gap / 10), detail, since=True))
        if i + 1 in LAP_MILESTONES:
            notes.append(_note(kind, f"Your {_ordinal(i + 1)} {unit_word}", 45, milestone=True))
        for n in notes:
            out.setdefault(it["ride_id"], []).append(n)
    return out


MIN_REPEATS_BEFORE = 3


def _clock(seconds: float) -> str:
    seconds = round(seconds)
    h, m, s = seconds // 3600, seconds % 3600 // 60, seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _phrase(name: str) -> str:
    """Route names read inside a sentence: "Home loop via X" -> "home loop via X"."""
    return "home" + name[4:] if name.startswith("Home") else name


def repeat_notes(found: dict, tz: tzinfo | None = None) -> dict[str, list[dict]]:
    """Notes about laps of repeated routes and times on repeated climbs, per ride."""
    out: dict[str, list[dict]] = {}
    for r in found.get("routes", []):
        phrase = _phrase(r["name"])
        laps = sorted(r["laps"], key=lambda x: x["start"])
        for rid, ns in _ranked("route", laps, "kmh", lambda a, b: a > b, phrase, "fastest",
                               lambda v: f"{v:.1f} km/h", tz, phrase).items():
            out.setdefault(rid, []).extend(ns)
    for c in found.get("climbs", []):
        atts = sorted(c["attempts"], key=lambda x: x["at"])
        name = f"the {c['name']}" if c["name"].endswith(" climb") else c["name"]
        for rid, ns in _ranked("climb", atts, "seconds", lambda a, b: a < b, f"time on {name}", "best",
                               _clock, tz, f"time up {name}").items():
            out.setdefault(rid, []).extend(ns)
    return out


def notes(e: _Entry, es: list[_Entry], extra: list[dict] | None = None) -> list[dict]:
    """What's notable about one ride, best first: at most one note per kind (one ranking and one
    milestone), MAX_NOTES in all. `extra`: this ride's route and climb notes (repeat_notes)."""
    before = [x for x in es if x.start < e.start]
    cands = _rank_notes(e, before) + _first_over(e, before) + _milestones(e, before) + _streak_note(e, before)
    cands += extra or []
    cands.sort(key=lambda n: -n["weight"])
    out, seen, since = [], set(), 0
    ranked = {n["kind"] for n in cands if not n["milestone"]}
    for n in cands:
        # Each kind keeps its best ranking and its best milestone.
        # A lap of a repeated route and the ride's speed say the same thing: keep the stronger.
        key = ("speed" if n["kind"] == "route" else n["kind"], n["milestone"])
        if key in seen:
            continue
        # Time in the saddle mostly repeats distance: only say it when distance has nothing.
        if n["kind"] == "time" and "distance" in ranked:
            continue
        if n["since"]:
            if since >= MAX_SINCE_NOTES:
                continue
            since += 1
        seen.add(key)
        out.append(n)
    return out[:MAX_NOTES]


def _found(rides: list[Ride], found: dict | None) -> dict:
    if found is None:
        from . import repeats
        found = repeats.find(rides)
    return found


def notes_by_ride(rides: list[Ride], tz: tzinfo | None = None, found: dict | None = None) -> dict[str, list[dict]]:
    """found: repeats.find(rides), if already worked out (it takes a few seconds)."""
    return notes_for(entries(rides, tz), _found(rides, found), tz)


def notes_for(es: list[_Entry], found: dict, tz: tzinfo | None = None, since: float | None = None
              ) -> dict[str, list[dict]]:
    """Notes for every ride (or only rides starting at or after `since`: a ride's notes depend only
    on the rides before it, so a change at time T only changes notes from T on)."""
    extra = repeat_notes(found, tz)
    return {e.ride_id: notes(e, es, extra.get(e.ride_id)) for e in es if since is None or e.start >= since}


def _route_view(r: dict) -> dict:
    laps = [l for l in r["laps"] if l["kmh"]]
    best = max(laps, key=lambda l: l["kmh"], default=None)
    return {"id": r["id"], "name": r["name"], "home": r["home"], "km": r["km"], "count": len(r["laps"]),
            "custom": bool(r.get("custom_name")),
            "best": best, "last": laps[-1] if laps else None,
            "laps": [{"ride_id": l["ride_id"], "start": l["start"], "kmh": l["kmh"], "avg_hr": l["avg_hr"]}
                     for l in r["laps"]]}


def _climb_view(c: dict) -> dict:
    best = min(c["attempts"], key=lambda a: a["seconds"])
    return {"id": c["id"], "name": c["name"], "custom": bool(c.get("custom_name")),
            "length_m": c["length_m"], "gain_m": c["gain_m"],
            "grade": c["grade"], "count": len(c["attempts"]), "best": best, "last": c["attempts"][-1],
            "attempts": [{"ride_id": a["ride_id"], "start": a["start"], "seconds": a["seconds"],
                          "avg_hr": a["avg_hr"]} for a in c["attempts"]]}


def you(rides: list[Ride], today: date | None = None, tz: tzinfo | None = None, recent: int = 5,
        found: dict | None = None) -> dict:
    """Everything for the You screen: tallies, streaks, personal bests, repeated routes and climbs,
    the latest rides' notes."""
    es = entries(rides, tz)
    found = _found(rides, found)
    latest = {e.ride_id for e in es[-recent:]}
    by_ride = {rid: n for rid, n in notes_for(es, found, tz).items() if rid in latest}
    return you_from(es, found, by_ride, today, tz, recent)


def you_from(es: list[_Entry], found: dict, ride_notes: dict[str, list[dict]], today: date | None = None,
             tz: tzinfo | None = None, recent: int = 5) -> dict:
    """you() from parts a backend keeps stored: entries, routes and climbs, each ride's notes."""
    today = today or datetime.now(tz).astimezone(tz).date()
    latest = [{"ride_id": e.ride_id, "start": e.start, "km": e.km, "notes": ride_notes.get(e.ride_id, [])}
              for e in reversed(es[-recent:])]
    return {**tallies(es, today), "bests": bests(es), "routes": [_route_view(r) for r in found["routes"]],
            "climbs": [_climb_view(c) for c in found["climbs"]], "recent": latest}


def headline(ride_notes: list[dict]) -> str | None:
    """The top note as a card headline: "Your hilliest ride yet." """
    return ride_notes[0]["text"] + "." if ride_notes else None


def report(y: dict) -> str:
    """The You screen as plain text, for the command line."""
    a, yr, ly, ld = y["all"], y["year"], y["last_year"], y["last_year_to_date"]
    lines = [f"On record since {y['since']}: {a['rides']} rides, {_num(a['km'])} km, {_num(a['hours'])} h, "
             f"{_num(a['ascent_m'])} m climbed ({a['everests']:.2f} Everests)."]
    if a.get("crow_flies"):
        lines.append(f"  That's about {a['crow_flies']}, as the crow flies.")
    lines.append(f"{yr['label']}: {yr['rides']} rides, {_num(yr['km'])} km, {_num(yr['ascent_m'])} m. "
                 f"{ld['label']}: {_num(ld['km'])} km. All of {ly['label']}: {_num(ly['km'])} km.")
    if y.get("biggest_month"):
        b = y["biggest_month"]
        lines.append(f"Biggest month: {b['label']}, {_num(b['km'])} km over {b['rides']} rides.")
    s = y["streak"]
    lines.append(f"Streak: {s['current_weeks']} weeks now; longest {s['longest_weeks']} weeks "
                 f"(from {s['longest_from']}).")
    lines.append("Personal bests:")
    for b in y["bests"]:
        lines.append(f"  {b['label']:<26} {b['text']:>10}  {b['date']}  ride {b['ride_id']}")
    if y.get("routes"):
        lines.append("Repeated routes:")
        for r in y["routes"]:
            b = r["best"]
            lines.append(f"  {r['name']:<32} {r['km']:5.1f} km  {r['count']:3d} laps  best {b['kmh']:.1f} km/h "
                         f"({datetime.fromtimestamp(b['start']).astimezone():%Y-%m-%d})" if b else f"  {r['name']}")
    if y.get("climbs"):
        lines.append("Repeated climbs:")
        for c in y["climbs"]:
            b = c["best"]
            lines.append(f"  {c['name']:<32} {c['length_m'] / 1000:4.1f} km {c['grade']:4.1f}%  {c['count']:3d} times  "
                         f"best {_clock(b['seconds'])} ({datetime.fromtimestamp(b['start']).astimezone():%Y-%m-%d}), "
                         f"last {_clock(c['last']['seconds'])}")
    lines.append("Latest rides:")
    for r in y["recent"]:
        day = datetime.fromtimestamp(r["start"]).astimezone().strftime("%Y-%m-%d")
        lines.append(f"  {day} {r['km']:6.1f} km  " + (" | ".join(n["text"] for n in r["notes"]) or "-"))
    return "\n".join(lines)
