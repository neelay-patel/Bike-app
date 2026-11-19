"""The fun bucket's numbers (docs/roadmap.md): badges, the rider card's ratings, and the season binder.

All worked out from the rider's own rides (stored features, records entries, repeated routes and climbs,
ride notes), by rules: badges are earned, never handed out, and each says when and on which ride.
Holo cards are rides that set a personal best at the time (a note with pb).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, tzinfo

from .records import EVEREST_M, _Entry, _week, streaks

# --- badges ----------------------------------------------------------------------------------
# (id, group, title, description, kind, target): kind says how progress is measured.
BADGES = [
    ("ride_50", "Distance", "Half century", "A ride of 50 km or more", "ride_km", 50),
    ("ride_100", "Distance", "Century", "A ride of 100 km or more", "ride_km", 100),
    ("ride_150", "Distance", "150", "A ride of 150 km or more", "ride_km", 150),
    ("ride_200", "Distance", "Double century", "A ride of 200 km or more", "ride_km", 200),
    ("climb_1000", "Climbing", "Thousand-metre day", "1,000 m of climbing in one ride", "ride_up", 1000),
    ("climb_2000", "Climbing", "Mountain day", "2,000 m of climbing in one ride", "ride_up", 2000),
    ("everest_month", "Climbing", "Everest month", "8,849 m of climbing in one calendar month", "month_up", EVEREST_M),
    ("km_1000", "Tally", "1,000 km", "1,000 km on record", "total_km", 1000),
    ("km_2500", "Tally", "2,500 km", "2,500 km on record", "total_km", 2500),
    ("km_5000", "Tally", "5,000 km", "5,000 km on record", "total_km", 5000),
    ("km_10000", "Tally", "10,000 km", "10,000 km on record", "total_km", 10000),
    ("rides_50", "Tally", "50 rides", "50 rides on record", "rides", 50),
    ("rides_100", "Tally", "100 rides", "100 rides on record", "rides", 100),
    ("rides_250", "Tally", "250 rides", "250 rides on record", "rides", 250),
    ("streak_4", "Consistency", "Four in a row", "A ride every week for 4 weeks", "streak", 4),
    ("streak_10", "Consistency", "Ten in a row", "A ride every week for 10 weeks", "streak", 10),
    ("streak_26", "Consistency", "Half a year", "A ride every week for 26 weeks", "streak", 26),
    ("year_round", "Consistency", "Year-rounder", "A ride in every month of a calendar year", "months", 12),
    ("fast_50", "Speed", "Fast fifty", "50 km or more at 25 km/h or faster", "fast50", 25),
    ("thirty_club", "Speed", "Thirty club", "30 km or more at 30 km/h or faster", "fast30", 30),
    ("dawn", "Fun", "Dawn patrol", "A ride started before 6:30 am", "dawn", 1),
    ("home_10", "Routes", "Regular", "10 laps of your home loop", "home_laps", 10),
    ("home_50", "Routes", "Local legend", "50 laps of your home loop", "home_laps", 50),
    ("climb_10", "Routes", "Hill repeats", "10 times up the same climb", "climb_reps", 10),
]


HOLO_KINDS = {"distance", "climbing", "time", "speed", "power", "sustained", "punch"}
AWAY_KM = 500   # a ride further than this from home is in another time zone (probably)


def is_holo(ride_notes: list[dict]) -> bool:
    """A holo card: the ride set an all-time best (distance, climbing, time, speed, power) or a first
    (first 100 km...). Climb times, home-loop laps and streaks are good days, but too frequent."""
    return any(n.get("pb") and n.get("kind") in HOLO_KINDS for n in ride_notes)


def local_times(feats: list[dict], tz: tzinfo | None, home: tuple | None) -> dict[str, datetime]:
    """Each ride's start in local time: the rider's zone near home; far away (a ride in London for a
    rider in Toronto), the sun's time from the longitude, since the zone isn't known."""
    from datetime import timezone
    from ..model import haversine
    out = {}
    for f in feats:
        t = datetime.fromtimestamp(f["start"], tz).astimezone(tz)
        if home and f.get("first") and haversine(*home, *f["first"]) > AWAY_KM * 1000:
            lat, lon = f["first"]
            utc = datetime.fromtimestamp(f["start"], timezone.utc)
            summer = 1 if lat > 20 and 4 <= utc.month <= 10 else 0  # most northern zones keep summer time
            t = utc.astimezone(timezone(timedelta(hours=round(lon / 15) + summer)))
        out[f["ride_id"]] = t
    return out


def badges(es: list[_Entry], found: dict, tz: tzinfo | None = None,
           local: dict[str, datetime] | None = None) -> list[dict]:
    """Every badge, earned or not: when it was earned and on which ride, or how far along.
    local: each ride's local start time (local_times); else the rider's zone."""
    es = sorted(es, key=lambda e: e.start)
    local = local or {}
    home = next((r for r in found.get("routes", []) if r.get("home")), None)
    out = []
    for bid, group, title, desc, kind, target in BADGES:
        earned, best = None, 0.0
        if kind in ("ride_km", "ride_up", "fast50", "fast30", "dawn"):
            for e in es:
                if kind == "ride_km":       # one ride's distance or climbing: road rides (as bests)
                    v = e.value("km") or 0
                elif kind == "ride_up":
                    v = e.value("ascent") or 0
                elif kind == "fast50":
                    v = (e.kmh or 0) if e.km >= 50 and not e.indoor else 0
                elif kind == "fast30":
                    v = (e.kmh or 0) if e.km >= 30 and not e.indoor else 0
                else:
                    lt = local.get(e.ride_id) or datetime.fromtimestamp(e.start, tz).astimezone(tz)
                    v = 1 if (lt.hour, lt.minute) < (6, 30) and not e.indoor else 0
                best = max(best, v)
                if v >= target and earned is None:
                    earned = e
        elif kind in ("total_km", "rides"):
            total = 0.0
            for i, e in enumerate(es):
                total = total + e.km if kind == "total_km" else i + 1
                if total >= target and earned is None:
                    earned = e
            best = total
        elif kind == "month_up":
            months: dict[tuple, float] = {}
            for e in es:
                key = (e.day.year, e.day.month)
                months[key] = months.get(key, 0) + (e.ascent or 0)
                if months[key] >= target and earned is None:
                    earned = e
            best = max(months.values(), default=0)
        elif kind == "streak":
            for i, e in enumerate(es):
                run = streaks(es[:i + 1], e.day)["current_weeks"]
                best = max(best, run)
                if run >= target and earned is None:
                    earned = e
        elif kind == "months":
            years: dict[int, set] = {}
            for e in es:
                years.setdefault(e.day.year, set()).add(e.day.month)
                best = max(best, len(years[e.day.year]))
                if len(years[e.day.year]) >= 12 and earned is None:
                    earned = e
        elif kind == "home_laps":
            laps = sorted(home["laps"], key=lambda l: l["start"]) if home else []
            best = len(laps)
            if len(laps) >= target:
                rid = laps[target - 1]["ride_id"]
                earned = next((e for e in es if e.ride_id == rid), None)
        elif kind == "climb_reps":
            for c in found.get("climbs", []):
                at = sorted(c["attempts"], key=lambda a: a["at"])
                best = max(best, len(at))
                if len(at) >= target:
                    e = next((x for x in es if x.ride_id == at[target - 1]["ride_id"]), None)
                    if e and (earned is None or e.start < earned.start):
                        earned = e
        out.append({"id": bid, "group": group, "title": title, "description": desc, "earned": earned is not None,
                    "date": earned.day.isoformat() if earned else None,
                    "ride_id": earned.ride_id if earned else None,
                    "progress": {"value": round(min(best, target), 1), "target": target}})
    return out


# --- rider card ratings ----------------------------------------------------------------------
def _scale(v: float, lo: float, hi: float, log: bool = False) -> int:
    """lo -> 30, hi -> 99 (linear or log), clamped to 1..99."""
    if v <= 0:
        return 1
    f = (math.log(v / lo) / math.log(hi / lo)) if log else (v - lo) / (hi - lo)
    return max(1, min(99, round(30 + 69 * f)))


TYPES = {"distance": "Rouleur", "climbing": "Climber", "speed": "Flier", "endurance": "Diesel",
         "consistency": "Metronome"}


def ratings(es: list[_Entry], today: date) -> dict:
    """Five ratings out of 99 from the last 12 months, the overall, and the rider type (the strongest)."""
    year = [e for e in es if today - timedelta(days=365) < e.day <= today]
    outdoor = [e for e in year if not e.indoor]

    def top3(vals):
        vals = sorted((v for v in vals if v), reverse=True)[:3]
        return sum(vals) / len(vals) if vals else 0.0

    weeks = {_week(e.day) for e in year if today - _week(e.day) < timedelta(weeks=26)}
    r = {
        "distance": _scale(top3(e.km for e in outdoor), 20, 200, log=True),
        "climbing": _scale(top3(e.ascent for e in outdoor), 150, 2500, log=True),
        "speed": _scale(max((e.kmh or 0 for e in outdoor if e.km >= 30), default=0), 18, 35),
        "endurance": _scale(max((e.hours for e in year), default=0), 1, 6, log=True),
        "consistency": max(1, min(99, round(20 + 79 * len(weeks) / 26))) if year else 1,
    }
    overall = round(sum(r.values()) / len(r))
    kind = max(r, key=lambda k: r[k])
    return {"ratings": r, "overall": overall, "type": TYPES[kind], "rides": len(year),
            "km": round(sum(e.km for e in year)), "basis": "your last 12 months"}


# --- season binder ---------------------------------------------------------------------------
def binder(es: list[_Entry], notes: dict[str, list[dict]], names: dict[str, str], shapes: dict[str, list],
           today: date) -> list[dict]:
    """One page per year, newest first: every ride's card in order (number in the year, holo when it
    set a personal best), and the weeks of the season with no ride (the gaps in the binder)."""
    years: dict[int, list[_Entry]] = {}
    for e in sorted(es, key=lambda e: e.start):
        years.setdefault(e.day.year, []).append(e)
    out = []
    for y in sorted(years, reverse=True):
        rides = years[y]
        cards = []
        for i, e in enumerate(rides, 1):
            ns = notes.get(e.ride_id, [])
            cards.append({"ride_id": e.ride_id, "start": e.start, "date": e.day.isoformat(), "number": i,
                          "name": names.get(e.ride_id), "km": round(e.km, 1), "ascent_m": e.ascent,
                          "indoor": e.indoor,
                          "holo": is_holo(ns), "headline": ns[0]["text"] if ns else None,
                          "shape": shapes.get(e.ride_id) or [], "week": _week(e.day).isoformat()})
        first = _week(rides[0].day)
        last = _week(min(today, date(y, 12, 31))) if y == today.year else _week(rides[-1].day)
        ridden = {c["week"] for c in cards}
        gaps, w = [], first
        while w <= last:
            if w.isoformat() not in ridden:
                gaps.append(w.isoformat())
            w += timedelta(weeks=1)
        out.append({"year": y, "cards": cards, "gaps": gaps, "holo": sum(c["holo"] for c in cards),
                    "weeks": (last - first).days // 7 + 1})
    return out
