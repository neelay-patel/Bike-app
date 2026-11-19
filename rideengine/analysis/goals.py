"""Goals: what the rider wants, what it means from their own riding, and how we'll see it working.

docs/coaching.md. The engine side of the approved goal flow:
- options(): the four objectives and their aspirations, with subtitles from the rider's own bests;
- the reveal: the gap between where they are and the goal, and the two or three things to build;
- markers: the measures we'll watch (current value, proposed target, history), read from ordinary
  riding, never from tests;
- seasons: when this rider rides outdoors and indoors, from their own history.

Rule-based and stdlib only. Every number comes from here; the AI coach (later) only explains them.
Estimates are labelled as estimates.
"""
from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta

from .records import _Entry

# --- physics, for the drafting estimate --------------------------------------------------------
MASS_KG = 85.0       # rider + bike, a typical default until the rider gives a weight
CDA = 0.32           # drag area, hoods position (m²)
CRR = 0.005          # rolling resistance, road tyres
RHO = 1.2            # air density (kg/m³)
DRAFT = 0.70         # sitting in a group needs ~70% of the solo aero power
HR_REF = 140         # heart rate the "speed at the same heart rate" marker is quoted at (when no better one)

OBJECTIVES = ["faster", "further", "stronger", "event"]


def power_watts(kmh: float, draft: float = 1.0, mass: float = MASS_KG) -> float:
    """Power to hold a speed on flat road, no wind."""
    v = kmh / 3.6
    return draft * 0.5 * RHO * CDA * v ** 3 + CRR * mass * 9.81 * v


def draft_ratio(solo_kmh: float, group_kmh: float) -> float:
    """Power to sit in a group at group_kmh, over power to ride alone at solo_kmh."""
    return power_watts(group_kmh, DRAFT) / power_watts(solo_kmh)


def speed_at_hr(kmh: float, hr: float, resting: float, ref: float) -> float | None:
    """A ride's speed scaled to a reference heart rate. Heart rate above resting rises roughly in line
    with power, and on flat road power rises with roughly the cube of speed."""
    if not kmh or not hr or hr <= resting + 10 or ref <= resting:
        return None
    return kmh * ((ref - resting) / (hr - resting)) ** (1 / 3)


# --- seasons ---------------------------------------------------------------------------------
def seasons(es: list[_Entry], today: date, years: int = 2) -> dict:
    """Each calendar month: "outdoor", "indoor", "mixed" or "none", from the last `years` of riding;
    where the rider is now, and when outdoor riding starts and ends."""
    since = today - timedelta(days=365 * years)
    count = {m: [0, 0] for m in range(1, 13)}
    for e in es:
        if e.day >= since:
            count[e.day.month][0 if not e.indoor and e.km >= 0.05 else 1] += 1
    months = {}
    for m, (out, ind) in count.items():
        months[m] = "none" if out + ind == 0 else "outdoor" if out >= 2 * max(ind, 0.5) \
            else "indoor" if ind >= 2 * max(out, 0.5) else "mixed"
    outdoor = [m for m in range(1, 13) if months[m] == "outdoor"]
    now = months[today.month]

    def next_month(start: date, want) -> date | None:
        d = date(start.year, start.month, 1)
        for _ in range(13):
            d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
            if want(months[d.month]):
                return d
        return None

    out_from = None if now == "outdoor" else next_month(today, lambda k: k == "outdoor")
    out_until = None
    if now == "outdoor":
        end = next_month(today, lambda k: k != "outdoor")
        out_until = (end - timedelta(days=1)) if end else None
    return {"months": {str(m): k for m, k in months.items()}, "now": now, "outdoor_months": outdoor,
            "outdoor_from": out_from.isoformat() if out_from else None,
            "outdoor_until": out_until.isoformat() if out_until else None}


# --- where the rider is ----------------------------------------------------------------------
def solo_pace(es: list[_Entry], today: date, n: int = 12) -> dict | None:
    """Typical and best average speed on the rider's recent flat-ish outdoor rides (25 km+, under
    10 m of climbing per km): their most recent `n` such rides, wherever their season left off."""
    rides = [e for e in es if not e.indoor and e.km >= 25 and e.kmh and e.day <= today
             and (e.ascent or 0) <= 10 * e.km]
    rides = sorted(rides, key=lambda e: e.start)[-n:]
    if len(rides) < 3:
        return None
    speeds = [e.kmh for e in rides]
    return {"typical": round(statistics.median(speeds), 1), "best": round(max(speeds), 1), "rides": len(rides),
            "since": rides[0].day.isoformat()}


def home_route(found: dict) -> dict | None:
    return next((r for r in found.get("routes", []) if r.get("home")), None)


def lap_speeds_at_hr(route: dict, resting: float, ref: float) -> list[dict]:
    """Each lap of a route with its speed scaled to the reference heart rate."""
    out = []
    for l in sorted(route["laps"], key=lambda l: l["start"]):
        v = speed_at_hr(l.get("kmh"), l.get("avg_hr"), resting, ref)
        if v:
            out.append({"ride_id": l["ride_id"], "start": l["start"], "value": round(v, 1),
                        "kmh": l["kmh"], "avg_hr": l["avg_hr"]})
    return out


def main_climb(found: dict) -> dict | None:
    return max(found.get("climbs", []), key=lambda c: len(c["attempts"]), default=None)


def _clock(s: float) -> str:
    s = round(s)
    return f"{s // 60}:{s % 60:02d}"


# --- the aspirations -------------------------------------------------------------------------
def options(es: list[_Entry], found: dict, today: date) -> list[dict]:
    """The four objectives and what each can look like, in the rider's words, quoting their own bests."""
    outdoor = [e for e in es if not e.indoor]
    longest = max((e.km for e in outdoor), default=0)
    next_long = next((t for t in (50, 80, 100, 120, 150, 200, 250, 300) if t > longest + 5), 300)
    home = home_route(found)
    climb = main_climb(found)
    best_lap = max((l["kmh"] for l in home["laps"] if l.get("kmh")), default=None) if home else None
    best_climb = min(climb["attempts"], key=lambda a: a["seconds"]) if climb else None
    ride_day = lambda t: datetime.fromtimestamp(t).strftime("%-d %b")
    return [
        {"id": "faster", "title": "Faster", "line": "Keep up, fly by, beat your times", "aspirations": [
            {"id": "keep_up_group", "title": "Keep up with the fast group",
             "line": "Stop getting dropped when they lift the pace"},
            {"id": "beat_my_roads", "title": "Beat my best on my usual roads",
             "line": f"Your home loop best: {best_lap:.1f} km/h" if best_lap else "Your repeated routes, faster"},
            {"id": "climb_faster", "title": "Get up the climbs quicker",
             "line": (f"{climb['name']}: best {_clock(best_climb['seconds'])}, {ride_day(best_climb['start'])}"
                      if climb else "Your climbs, faster")},
            {"id": "sprint", "title": "Have a sprint when it counts", "line": "Town signs, traffic lights, the last kilometre"},
        ]},
        {"id": "further", "title": "Further", "line": "Ride all day, go long", "aspirations": [
            {"id": "first_distance", "title": f"My first {next_long} km ride",
             "line": f"Your longest so far: {longest:.1f} km", "target_km": next_long},
            {"id": "all_day", "title": "Ride all day and still enjoy it", "line": "Long days without fading at the end"},
        ]},
        {"id": "stronger", "title": "Stronger", "line": "More power, own the climbs", "aspirations": [
            {"id": "more_power", "title": "More power", "line": "Push harder for longer"},
            {"id": "own_climbs", "title": "Own the climbs", "line": "Climb strongly, not just survive"},
        ]},
        {"id": "event", "title": "An event", "line": "A gran fondo, a race, a date to be ready by", "aspirations": [
            {"id": "event", "title": "Get ready for an event", "line": "Tell us the date, distance and climbing"},
        ]},
    ]


# --- the reveal ------------------------------------------------------------------------------
def reveal(goal: dict, es: list[_Entry], found: dict, today: date, resting_hr: float | None = None) -> dict:
    """What the goal means from the rider's own data: the gap, and what to build (most important first).
    Every figure the text quotes is in `figures`, so the app (or the coach) can show it."""
    asp, p = goal.get("aspiration"), goal.get("params") or {}
    pace = solo_pace(es, today)
    outdoor = [e for e in es if not e.indoor]
    longest = max((e.km for e in outdoor), default=0)
    figures: dict = {}
    build: list[dict] = []
    headline = ""
    notes: list[str] = []

    if asp == "keep_up_group":
        group = float(p.get("group_kmh") or 30)
        figures["group_kmh"] = group
        if pace:
            figures |= {"solo_kmh": pace["typical"], "solo_best_kmh": pace["best"]}
            more = (draft_ratio(pace["typical"], group) - 1) * 100
            figures["draft_power_pct"] = round(more)
            headline = (f"Sitting in the draft, holding {group:g} takes about {round(more)}% "
                        f"{'more' if more >= 0 else 'less'} power than your solo {pace['typical']:g}.")
        hills = p.get("terrain") in ("rolling", "hilly")
        build = [{"id": "sustained", "title": "Power you can hold", "line": f"Sit on the wheel at {group:g} for the whole ride"},
                 {"id": "surges", "title": "Surges, over and over",
                  "line": "Answer the accelerations" + (" and the rises" if hills else "") + " instead of watching them go"},
                 {"id": "recovery", "title": "Recovering on the move", "line": "Settle quickly after each one, ready for the next"}]
        if pace and figures.get("draft_power_pct", 0) > 20:
            notes.append("The steady pace is the bigger gap for now: the plan starts there, then adds surges.")
        else:
            build[0], build[1] = build[1], build[0]  # the surges are what drop most riders who can hold the pace
            notes.append("What drops riders is the surges: 30 seconds to 2 minutes well above that, again and again.")
        notes.append("Estimated from your rides and heart rate. Power from the KICKR and Zwift will sharpen it.")
    elif asp == "beat_my_roads":
        home = home_route(found)
        if home:
            best = max(home["laps"], key=lambda l: l["kmh"] or 0)
            figures |= {"route": home["name"], "best_kmh": best["kmh"], "laps": len(home["laps"])}
            headline = f"Your best on the {home['name'].lower()} is {best['kmh']:.1f} km/h, over {len(home['laps'])} laps."
        build = [{"id": "sustained", "title": "Power you can hold", "line": "Faster laps come from a higher steady pace"},
                 {"id": "pacing", "title": "Pacing", "line": "Even effort beats a fast start and a slow finish"}]
    elif asp in ("climb_faster", "own_climbs"):
        climb = main_climb(found)
        if climb:
            best = min(climb["attempts"], key=lambda a: a["seconds"])
            figures |= {"climb": climb["name"], "best": _clock(best["seconds"]), "attempts": len(climb["attempts"])}
            headline = f"Your best up {climb['name']} is {_clock(best['seconds'])}, from {len(climb['attempts'])} goes."
        build = [{"id": "climbing", "title": "Climbing power", "line": "Longer efforts just under your limit"},
                 {"id": "sustained", "title": "Power you can hold", "line": "The base everything else sits on"}]
    elif asp in ("first_distance", "all_day"):
        target = float(p.get("target_km") or next((t for t in (100, 150, 200) if t > longest + 5), 200))
        figures |= {"longest_km": round(longest, 1), "target_km": target}
        if pace:
            figures["hours_at_your_pace"] = round(target / pace["typical"], 1)
        headline = (f"Your longest is {longest:.0f} km. {target:g} km at your pace is about "
                    f"{figures.get('hours_at_your_pace', '?')} hours on the bike.")
        build = [{"id": "endurance", "title": "Time in the saddle", "line": "Build the long ride a step at a time"},
                 {"id": "fuelling", "title": "Eating and drinking on the bike", "line": "The difference between finishing and fading"},
                 {"id": "pacing", "title": "Pacing", "line": "Start easier than feels right"}]
    elif asp == "more_power":
        headline = "Power is measured, not guessed: your first rides with the KICKR set the baseline."
        build = [{"id": "sustained", "title": "Power you can hold", "line": "Raise what you can sustain for 20 to 60 minutes"},
                 {"id": "surges", "title": "Short, hard efforts", "line": "1 to 5 minutes well above that"}]
    elif asp == "event":
        km, up = p.get("event_km"), p.get("event_climbing_m")
        when = p.get("ready_by")
        figures |= {"event_km": km, "event_climbing_m": up, "longest_km": round(longest, 1)}
        if when:
            figures["weeks_to_go"] = max(0, (date.fromisoformat(when) - today).days // 7)
        headline = (f"{figures.get('weeks_to_go', '?')} weeks to go. The event is {km or '?'} km; "
                    f"your longest is {longest:.0f} km.")
        build = [{"id": "endurance", "title": "Time in the saddle", "line": "Be ready for the distance"},
                 {"id": "sustained", "title": "Power you can hold", "line": "Ride it at a pace you can keep"}]
    return {"headline": headline, "figures": figures, "build": build, "notes": notes}


# --- markers: how we'll see it working ---------------------------------------------------------
def markers(goal: dict, es: list[_Entry], today: date, metrics: list[dict]) -> list[dict]:
    """The measures we'll watch for this goal: the four headline numbers (headline.four, with the goal's
    targets), plus the longest recent ride for a distance goal. Each has its current value, target and
    history, read from ordinary riding; pending ones say what data they're waiting for. No route-specific
    markers: the same four for every rider, so the You tab's headline card and the goal agree."""
    out = [dict(m) for m in metrics]
    asp = goal.get("aspiration")
    if asp in ("first_distance", "all_day", "event"):
        recent = [e.km for e in es if not e.indoor and (today - e.day).days <= 56]
        p = goal.get("params") or {}
        out.append({"id": "longest_recent", "label": "Longest ride, last 8 weeks", "unit": "km",
                    "current": round(max(recent), 1) if recent else None,
                    "target": p.get("target_km") or p.get("event_km"), "better": "higher", "history": [],
                    "pending": None if recent else "From your next outdoor ride."})
    return out


def best_power_curve(feats: list[dict], since: date | None = None) -> dict[str, int]:
    """The best power for each duration across rides (features' power_curve), optionally recent only."""
    best: dict[str, int] = {}
    for f in feats:
        if since and datetime.fromtimestamp(f["start"]).date() < since:
            continue
        for k, v in (f.get("power_curve") or {}).items():
            if v and v > best.get(k, 0):
                best[k] = v
    return best


def power_curve(samples, durations=(5, 60, 300, 1200, 3600)) -> dict[str, int]:
    """Best average power over each duration in one ride, from measured power (model.power_series:
    1 s steps; long gaps count as zero so a pause can't inflate an effort)."""
    from ..model import power_series
    _, series = power_series(samples)
    if not series:
        return {}
    csum = [0.0]
    for p in series:
        csum.append(csum[-1] + p)
    out = {}
    for d in durations:
        if d <= len(series):
            out[str(d)] = round(max(csum[i + d] - csum[i] for i in range(len(series) - d + 1)) / d)
    return out
