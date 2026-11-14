"""Routes and climbs ridden again and again: the home loop, and named climbs timed like segments.

Routes: rides whose tracks cover mostly the same ground (~300 m grid cells, Jaccard >= ROUTE_SAME)
and are about as long are one route. Ridden MIN_REPEATS+ times, it's a repeated route. The most-ridden
route that starts and ends at home (the commonest start) is the home loop. Laps are compared on
average moving speed.

Climbs: find_climbs() spots climbs in each ride, but where it starts and stops each one moves a
little from ride to ride. So each repeated climb gets fixed start and finish points (from its most
typical detection) and every ride that passes the start, then the finish, the right distance later,
is timed between them, like a segment. Elapsed time, stops included.

Names come from GeoNames (rideengine.places) when it's downloaded: "Regent Park to Leaside" (the places
nearest the bottom and the top), "Uxbridge loop". Without it: "2.7 km climb", "42 km loop".

Works incrementally, on plain JSON-able dicts, so a backend can store everything:
  features.extract(ride)               once per ride: summary, grid cells, detected climbs
  match_route / time_climb             a new ride against the routes and climbs already known
  discover_routes / discover_climbs    new routes and climbs among rides (a background job)
  update_home                          which route is the home loop
Once made, a route or climb keeps its id; later rides are only matched to it. find() runs the same
steps over a list of rides in one go (command line, tests).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from ..model import Ride, haversine
from .climbs import match_climbs

CELL_LAT = 0.0027        # ~300 m
CELL_LON = 0.0037        # ~300 m at 43°N, ~260 m at 51°N
ROUTE_SAME = 0.6         # share of cells two rides must share (of all cells either visits)
ROUTE_KM_TOL = 0.15      # and lengths within 15%
MIN_REPEATS = 3          # rides (or attempts) before a route or climb counts as repeated
HOME_M = 1000            # a start/finish this close to home counts as home
LOOP_M = 5000            # a route that finishes this close to its start is a loop
GATE_M = 50              # passing this close to a climb's start or finish point counts as passing it
SEG_LEN_TOL = (0.85, 1.25)
CLIMB_MATCH_M = 250      # detections whose starts and ends are this close are the same climb
COVERED_M = 150          # a detection whose ends both lie this close to a known climb is that climb
OVERLAP_M = 60           # a candidate climb mostly within this of a kept one is the same climb
NAME_NEAR_M = 3000       # a place this close to a climb's end can name it


def cell(lat: float, lon: float) -> tuple[int, int]:
    return round(lat / CELL_LAT), round(lon / CELL_LON)


def _metres(lat0: float, lon0: float, lat: float, lon: float) -> float:
    """Fast flat-earth distance, fine for the few hundred metres used here."""
    dy = (lat - lat0) * 110_540
    dx = (lon - lon0) * 111_320 * math.cos(math.radians(lat0))
    return math.hypot(dx, dy)


@dataclass
class Track:
    """A ride's GPS points with distance along the ride, and which grid cells it visits."""
    ride: Ride
    ride_id: str
    lat: list[float] = field(default_factory=list)
    lon: list[float] = field(default_factory=list)
    t: list[float] = field(default_factory=list)
    d: list[float] = field(default_factory=list)
    hr: list[float | None] = field(default_factory=list)
    cells: dict = field(default_factory=dict)   # cell -> sample indices

    @staticmethod
    def of(ride: Ride) -> "Track":
        tr = Track(ride, str(int(ride.start)))
        dist, prev = 0.0, None
        for s in ride.samples:
            if s.lat is None or s.lon is None:
                continue
            if prev is not None:
                dist += haversine(prev[0], prev[1], s.lat, s.lon)
            prev = (s.lat, s.lon)
            tr.cells.setdefault(cell(s.lat, s.lon), []).append(len(tr.lat))
            tr.lat.append(s.lat)
            tr.lon.append(s.lon)
            tr.t.append(s.t)
            tr.d.append(dist)
            tr.hr.append(s.hr)
        return tr

    @property
    def km(self) -> float:
        return self.d[-1] / 1000 if self.d else 0.0

    def near(self, lat: float, lon: float) -> list[int]:
        """Sample indices in the 3x3 cells around a point (candidates for a pass)."""
        ci, cj = cell(lat, lon)
        out = []
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                out += self.cells.get((ci + di, cj + dj), [])
        return sorted(out)

    def passes(self, lat: float, lon: float, radius: float = GATE_M) -> list[int]:
        """Each time the track goes by a point: the index of its closest sample."""
        hits = [(i, _metres(lat, lon, self.lat[i], self.lon[i])) for i in self.near(lat, lon)]
        hits = [h for h in hits if h[1] <= radius]
        out, run = [], []
        for h in hits:
            if run and h[0] - run[-1][0] > 5:
                out.append(min(run, key=lambda x: x[1])[0])
                run = []
            run.append(h)
        if run:
            out.append(min(run, key=lambda x: x[1])[0])
        return out


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def _cells(x: dict) -> set:
    return {tuple(c) for c in x.get("cells") or []}


def _outdoor(feats: list[dict]) -> list[dict]:
    return [f for f in feats if not f["indoor"] and f.get("cells")]


# --- naming ---------------------------------------------------------------------------------
def _nearest(places: list[dict], lat: float, lon: float, within: float = NAME_NEAR_M) -> dict | None:
    """The best name for a spot: near, and not a hyphenated district ("Cabbagetown-South St.James Town")."""
    best = None
    for p in places:
        d = haversine(lat, lon, p["lat"], p["lon"])
        if d > within:
            continue
        score = d * (1.6 if "-" in p["name"] else 1.0)
        if best is None or score < best[0]:
            best = (score, p)
    return best[1] if best else None


def bbox(points, pad: float = 0.04):
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return (min(lats) - pad, min(lons) - pad, max(lats) + pad, max(lons) + pad)


def load_places(boxes: list) -> list[dict]:
    """GeoNames places in these boxes; empty when GeoNames isn't downloaded."""
    try:
        from ..places import load
        return load(boxes) if boxes else []
    except (OSError, ValueError):
        return []


def place_boxes(routes: list[dict], climbs: list[dict], feats_by_id: dict) -> list:
    """Areas to read place names for: each new route's reference ride, each new climb."""
    boxes = []
    for r in routes:
        f = feats_by_id.get(r["ref_ride_id"])
        if f and f.get("bbox"):
            s, w, n, e = f["bbox"]
            boxes.append((s - 0.04, w - 0.04, n + 0.04, e + 0.04))
    return boxes + [bbox(c["path"], pad=0.03) for c in climbs]


def name_route(route: dict, ref: Ride, places: list[dict]) -> str:
    """Named after the most notable place on it (where you stopped, else the biggest)."""
    on = []
    if places:
        from ..places import places_on_route
        on = places_on_route(ref, limit=1, places=places)
    if on:
        return f"Home loop via {on[0]['name']}" if route.get("from_home") else \
            f"{on[0]['name']} {'loop' if route['loop'] else 'ride'}"
    return f"{route['km']:.0f} km {'loop' if route['loop'] else 'route'}"


def name_climb(climb: dict, places: list[dict]) -> str:
    bottom = _nearest(places, climb["lat0"], climb["lon0"])
    top = _nearest(places, climb["lat1"], climb["lon1"])
    if bottom and top and bottom["name"] != top["name"]:
        return f"{bottom['name']} to {top['name']}"
    if top:
        return f"{top['name']} climb"
    return f"{climb['length_m'] / 1000:.1f} km climb"


def display_names(routes: list[dict], climbs: list[dict]) -> None:
    """Set "name" for showing: the rider's own name, else "Home loop", else the automatic name;
    two the same get told apart by length."""
    for r in routes:
        r["name"] = r.get("custom_name") or ("Home loop" if r.get("home") else r.get("auto_name") or
                                             f"{r['km']:.0f} km route")
    for c in climbs:
        c["name"] = c.get("custom_name") or c.get("auto_name") or f"{c['length_m'] / 1000:.1f} km climb"
    for items, extra in ((routes, lambda r: f"{r['km']:.0f} km"), (climbs, lambda c: f"{c['length_m'] / 1000:.1f} km")):
        seen: dict[str, list[dict]] = {}
        for it in items:
            seen.setdefault(it["name"], []).append(it)
        for name, same in seen.items():
            if len(same) > 1:
                for it in same:
                    if not it.get("custom_name"):
                        it["name"] = f"{name} ({extra(it)})"


# --- routes ---------------------------------------------------------------------------------
def lap(feat: dict, route_id: str) -> dict:
    return {"route_id": route_id, "ride_id": feat["ride_id"], "start": feat["start"], "km": feat["km"],
            "kmh": feat["kmh"], "moving_s": feat["moving_s"], "avg_hr": feat.get("avg_hr")}


def match_route(feat: dict, routes: list[dict]) -> str | None:
    """The known route this ride is a lap of, if any."""
    if feat["indoor"] or not feat.get("cells"):
        return None
    cells = _cells(feat)
    best = None
    for r in routes:
        if abs(feat["track_km"] - r["km"]) > ROUTE_KM_TOL * r["km"]:
            continue
        j = _jaccard(cells, _cells(r))
        if j >= ROUTE_SAME and (best is None or j > best[0]):
            best = (j, r["id"])
    return best[1] if best else None


def discover_routes(feats: list[dict], assigned: set[str]) -> list[tuple[dict, list[dict]]]:
    """New routes among rides that aren't laps of a known route: (route, laps) for each group of
    MIN_REPEATS+ rides. Not named yet (name_route)."""
    groups: list[list[dict]] = []
    for f in sorted(_outdoor(feats), key=lambda f: f["start"]):
        if f["ride_id"] in assigned:
            continue
        cells = _cells(f)
        for g in groups:
            ref = g[0]
            if abs(f["track_km"] - ref["track_km"]) <= ROUTE_KM_TOL * ref["track_km"] \
                    and _jaccard(cells, _cells(ref)) >= ROUTE_SAME:
                g.append(f)
                break
        else:
            groups.append([f])
    out = []
    for g in groups:
        if len(g) < MIN_REPEATS:
            continue
        ref = g[0]
        kms = sorted(f["track_km"] for f in g)
        route = {"id": f"r{ref['ride_id']}", "ref_ride_id": ref["ride_id"], "km": round(kms[len(kms) // 2], 1),
                 "cells": ref["cells"], "home": False, "from_home": False,
                 "loop": haversine(*ref["first"], *ref["last"]) <= LOOP_M}
        out.append((route, [lap(f, route["id"]) for f in g]))
    return out


def home_point(feats: list[dict]) -> tuple[float, float] | None:
    """Where most rides start."""
    count: dict = {}
    for f in _outdoor(feats):
        count.setdefault(cell(*f["first"]), []).append(f)
    if not count:
        return None
    best = max(count.values(), key=len)
    return tuple(best[0]["first"])


def update_home(feats: list[dict], routes: list[dict], laps: list[dict]) -> tuple[float, float] | None:
    """Mark which routes start and finish at home, and which one is the home loop (the most ridden
    of those). Returns the home point."""
    home = home_point(feats)
    by_id = {f["ride_id"]: f for f in feats}
    count = {r["id"]: 0 for r in routes}
    at_home = {r["id"]: 0 for r in routes}
    for l in laps:
        f = by_id.get(l["ride_id"])
        if f is None or l["route_id"] not in count:
            continue
        count[l["route_id"]] += 1
        if home and all(haversine(*home, *p) <= HOME_M for p in (f["first"], f["last"])):
            at_home[l["route_id"]] += 1
    for r in routes:
        r["from_home"] = count[r["id"]] > 0 and at_home[r["id"]] > count[r["id"]] / 2
        r["home"] = False
    homes = [r for r in routes if r["from_home"] and count[r["id"]] >= MIN_REPEATS]
    if homes:
        max(homes, key=lambda r: count[r["id"]])["home"] = True
    return home


# --- climbs ---------------------------------------------------------------------------------
@dataclass
class _Segment:
    lat0: float
    lon0: float
    lat1: float
    lon1: float
    length_m: float
    gain_m: float
    path: list[tuple[float, float]]   # points every ~50 m along the typical attempt

    @staticmethod
    def of(c: dict) -> "_Segment":
        return _Segment(c["lat0"], c["lon0"], c["lat1"], c["lon1"], c["length_m"], c["gain_m"],
                        [tuple(p) for p in c["path"]])


def time_segment(t: Track, seg: _Segment) -> list[dict]:
    """Every pass over the segment in this ride: start gate, then the finish gate the right
    distance later."""
    starts = t.passes(seg.lat0, seg.lon0)
    if not starts:
        return []
    ends = t.passes(seg.lat1, seg.lon1)
    out, used = [], -1
    lo, hi = SEG_LEN_TOL
    for i in starts:
        if i <= used:
            continue
        for j in ends:
            if j > i and lo * seg.length_m <= t.d[j] - t.d[i] <= hi * seg.length_m:
                hr = [h for h in t.hr[i:j + 1] if h is not None]
                secs = t.t[j] - t.t[i]
                out.append({"ride_id": t.ride_id, "start": t.ride.start, "at": t.t[i], "seconds": round(secs),
                            "kmh": round((t.d[j] - t.d[i]) / secs * 3.6, 1) if secs > 0 else None,
                            "avg_hr": round(sum(hr) / len(hr)) if len(hr) >= 3 else None})
                used = j
                break
    return out


def may_pass(feat: dict, climb: dict) -> bool:
    """Cheap check before loading a ride: does it visit the cells around both of the climb's gates?"""
    cells = _cells(feat)
    for lat, lon in ((climb["lat0"], climb["lon0"]), (climb["lat1"], climb["lon1"])):
        ci, cj = cell(lat, lon)
        if not any((ci + di, cj + dj) in cells for di in (-1, 0, 1) for dj in (-1, 0, 1)):
            return False
    return True


def time_climb(track: Track, climb: dict) -> list[dict]:
    """A ride's attempts on a known climb."""
    return [{**a, "climb_id": climb["id"]} for a in time_segment(track, _Segment.of(climb))]


def _segment_from(t: Track, c: dict) -> _Segment | None:
    """The fixed start/finish for a detected climb, from the ride it was found in."""
    i = min(range(len(t.lat)), key=lambda k: _metres(c["start"][0], c["start"][1], t.lat[k], t.lon[k])
            if abs(t.lat[k] - c["start"][0]) < 0.01 else 1e9)
    j = min(range(len(t.lat)), key=lambda k: _metres(c["end"][0], c["end"][1], t.lat[k], t.lon[k])
            if abs(t.lat[k] - c["end"][0]) < 0.01 and k > i else 1e9)
    if j <= i:
        return None
    path, nxt = [], t.d[i]
    for k in range(i, j + 1):
        if t.d[k] >= nxt:
            path.append((t.lat[k], t.lon[k]))
            nxt = t.d[k] + 50
    return _Segment(t.lat[i], t.lon[i], t.lat[j], t.lon[j], t.d[j] - t.d[i], c["gain_m"], path)


def _overlaps(a: _Segment, b: _Segment) -> bool:
    """Most of a lies along b (the same road, the same way)."""
    close = sum(1 for p in a.path if min(_metres(p[0], p[1], q[0], q[1]) for q in b.path) <= OVERLAP_M)
    return close >= 0.5 * len(a.path)


def _covered(det: dict, climbs: list[dict]) -> bool:
    """A detection that is (part of) a climb already known."""
    for c in climbs:
        if all(min(_metres(p[0], p[1], q[0], q[1]) for q in c["path"]) <= COVERED_M
               for p in (det["start"], det["end"])):
            return True
    return False


def discover_climbs(feats: list[dict], climbs: list[dict], load_track: Callable[[str], "Track | None"]
                    ) -> list[tuple[dict, list[dict]]]:
    """New repeated climbs: detections that aren't a known climb, seen on 2+ rides, then timed on
    every ride that might pass (only those rides are loaded). Returns (climb, attempts), not named
    yet (name_climb)."""
    outdoor = _outdoor(feats)
    found = []
    for f in outdoor:
        for d in f.get("climbs") or []:
            if not _covered(d, climbs):
                found.append({**d, "ride_id": f["ride_id"], "start": tuple(d["start"]), "end": tuple(d["end"])})
    known = [_Segment.of(c) for c in climbs]
    out: list[tuple[dict, list[dict]]] = []
    tracks: dict[str, Track | None] = {}

    def track(rid: str) -> Track | None:
        if rid not in tracks:
            tracks[rid] = load_track(rid)
        return tracks[rid]

    for g in match_climbs(found, radius_m=CLIMB_MATCH_M):
        if len(g) < 2:
            continue
        # The most typical detection: the one whose ends are closest to the others'.
        ref = min(g, key=lambda c: sum(haversine(*c["start"], *o["start"]) + haversine(*c["end"], *o["end"])
                                       for o in g))
        t = track(ref["ride_id"])
        seg = _segment_from(t, ref) if t and t.lat else None
        if seg is None or len(seg.path) < 3:
            continue
        if any(_overlaps(seg, k) or _overlaps(k, seg) for k in known):
            continue
        climb = {"id": f"c{seg.lat0:.5f},{seg.lon0:.5f}", "lat0": seg.lat0, "lon0": seg.lon0, "lat1": seg.lat1,
                 "lon1": seg.lon1, "length_m": round(seg.length_m), "gain_m": round(seg.gain_m),
                 "grade": round(seg.gain_m / seg.length_m * 100, 1), "path": [list(p) for p in seg.path]}
        attempts = []
        for f in outdoor:
            if may_pass(f, climb):
                tf = track(f["ride_id"])
                if tf:
                    attempts += time_climb(tf, climb)
        if len(attempts) >= MIN_REPEATS:
            known.append(seg)
            out.append((climb, sorted(attempts, key=lambda a: a["at"])))
    return out


# --- views (what records.py and the app read) -------------------------------------------------
def assemble(routes: list[dict], laps: list[dict], climbs: list[dict], attempts: list[dict],
             visible: set[str] | None = None) -> dict:
    """{"routes": [...route, "laps"], "climbs": [...climb, "attempts"]}: only routes and climbs with
    MIN_REPEATS+ visible laps or attempts, the home loop first, then most ridden; display names set."""
    def ok(x):
        return visible is None or x["ride_id"] in visible
    lap_by: dict[str, list] = {}
    for l in laps:
        if ok(l):
            lap_by.setdefault(l["route_id"], []).append(l)
    att_by: dict[str, list] = {}
    for a in attempts:
        if ok(a):
            att_by.setdefault(a["climb_id"], []).append(a)
    rs, cs = [], []
    for r in routes:
        ls = sorted(lap_by.get(r["id"], []), key=lambda l: l["start"])
        if len(ls) >= MIN_REPEATS:
            rs.append({k: v for k, v in r.items() if k != "cells"} | {"laps": ls})
    for c in climbs:
        at = sorted(att_by.get(c["id"], []), key=lambda a: a["at"])
        if len(at) >= MIN_REPEATS:
            cs.append({k: v for k, v in c.items() if k != "path"}
                      | {"start": [round(c["lat0"], 5), round(c["lon0"], 5)],
                         "end": [round(c["lat1"], 5), round(c["lon1"], 5)], "attempts": at})
    rs.sort(key=lambda r: (not r.get("home"), -len(r["laps"])))
    cs.sort(key=lambda c: -len(c["attempts"]))
    display_names(rs, cs)
    return {"routes": rs, "climbs": cs}


def find(rides: list[Ride], places: list[dict] | None = None) -> dict:
    """Every step in one go over a list of rides (the backend does the same steps as rides arrive).
    places: GeoNames places to name from ([] for none); read from data/geo when not given."""
    from .features import extract
    by_id = {str(int(r.start)): r for r in rides}
    feats = [extract(r) for r in rides]
    feats_by_id = {f["ride_id"]: f for f in feats}
    new_routes = discover_routes(feats, set())
    routes = [r for r, _ in new_routes]
    laps = [l for _, ls in new_routes for l in ls]
    update_home(feats, routes, laps)
    new_climbs = discover_climbs(feats, [], lambda rid: Track.of(by_id[rid]) if rid in by_id else None)
    climbs = [c for c, _ in new_climbs]
    attempts = [a for _, at in new_climbs for a in at]
    if places is None:
        places = load_places(place_boxes(routes, climbs, feats_by_id))
    for r in routes:
        r["auto_name"] = name_route(r, by_id[r["ref_ride_id"]], places)
    for c in climbs:
        c["auto_name"] = name_climb(c, places)
    return assemble(routes, laps, climbs, attempts)
