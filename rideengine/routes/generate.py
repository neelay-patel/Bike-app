"""Loops from a request (request.Ask): a start, a distance, the surface mix, maybe a café halfway.

Each candidate goes start -> one side -> a far point -> the other side -> back to the start, routed on our
own map with this rider's surface costs (router.py). The far point is a café when one is wanted (so it
falls halfway), otherwise a point in each of twelve directions. The side points are placed on an ellipse
sized to the distance asked for, then nudged once using the length the router actually found.

Candidates are scored on: the distance, the off-pavement share, busy roads, singletrack, riding the same
road twice, and (with a stop) where the café falls. The best few that don't overlap each other are kept;
the full route check (check.py) then reports on each, as on any route.

    opts = loops(ask, graph, pois)       # [Option], best first
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field

from ..model import haversine
from . import osm
from .request import Ask
from .route import Route
from .router import Graph, Path, Prefs

TORTUOSITY = 1.3          # roads are this much longer than the shape they follow, to start with
COFFEE = {"cafe": 0, "coffee": 0, "bakery": 0, "ice_cream": 1, "restaurant": 2, "fast_food": 3, "pub": 2}
# Chains are fine for a refill, but a local café is the better halfway stop.
CHAINS = osm.CHAINS
SAMPLE_M = 25


def prefs_for(ask: Ask) -> Prefs:
    p = Prefs()
    if ask.surface == "road":
        p.surface.update(paved=0.85, gravel=1.4, rough=2.0, trail=3.0, unknown=1.2)
    elif ask.surface == "mixed":
        p.surface.update(paved=0.95, gravel=0.85, rough=1.2, trail=1.8, unknown=0.95)
    else:   # gravel: unknown rural roads are often gravel in Ontario, so they're cheap-ish too
        p.surface.update(paved=1.0, gravel=0.62, rough=0.85, trail=1.4, unknown=0.8)
    p.surface["singletrack"] = 1.2 if ask.singletrack else 8.0
    return p


def bbox_for(ask: Ask) -> tuple[float, float, float, float]:
    """Roads to load: around the start and any destination or place to pass, out as far as the route
    could reach, and a bit."""
    pts = [(p["lat"], p["lon"]) for p in (ask.start, ask.end, ask.via) if p]
    lat = sum(p[0] for p in pts) / len(pts)
    span = max((haversine(*a, *b) for a in pts for b in pts), default=0.0) / 1000
    if ask.shape == "out_back" and not ask.end:
        reach = ask.km[1] / 2 / TORTUOSITY * 1.2 + 3
    elif ask.shape == "oneway":
        extra = max(0.0, (ask.km[1] if ask.km else 0) - span * TORTUOSITY)
        reach = max(5.0, 0.35 * span, extra / 2.2) + 3
    elif ask.km:
        reach = ask.km[1] / (math.pi * TORTUOSITY) * 1.25 + 3
    else:
        reach = 0.6 * span + 4
    dla, dlo = reach / 110.54, reach / (111.32 * math.cos(math.radians(lat)))
    return (min(p[0] for p in pts) - dla, min(p[1] for p in pts) - dlo,
            max(p[0] for p in pts) + dla, max(p[1] for p in pts) + dlo)


def pois_in(bbox, path: str = osm.LOCAL_DB) -> list[dict]:
    """Stops (osm.poi_kind) inside the box, from our own map."""
    s, w, n, e = bbox
    i0, i1 = math.floor(s / osm.TILE_LAT), math.floor(n / osm.TILE_LAT)
    j0, j1 = math.floor(w / osm.TILE_LON), math.floor(e / osm.TILE_LON)
    keys = [osm.tile_key((i, j)) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]
    out = []
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        for k in range(0, len(keys), 500):
            chunk = keys[k:k + 500]
            for pid, lat, lon, tags in db.execute(
                    f"SELECT id, lat, lon, tags FROM pois WHERE tile IN ({','.join('?' * len(chunk))})", chunk):
                t = json.loads(tags)
                kind = osm.poi_kind(t)
                if kind and s <= lat <= n and w <= lon <= e:
                    out.append({"id": pid, "lat": lat, "lon": lon, "kind": kind, "name": t.get("name") or t.get("brand") or "",
                                "what": t.get("amenity") or t.get("shop") or t.get("tourism") or "",
                                "hours": t.get("opening_hours") or ""})
    finally:
        db.close()
    return out


@dataclass
class Option:
    route: Route
    path: Path
    km: float
    off_share: float | None
    busy_km: float
    singletrack_km: float
    twice_share: float
    stop: dict | None = None        # {"name", "what", "km"}
    via: str | None = None          # the far point, in words
    score: float = 0.0
    why: list = field(default_factory=list)


# --- geometry ---------------------------------------------------------------------------------------
def _xy(lat0: float):
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110540

    def to(p):
        return (p[1] * kx, p[0] * ky)

    def back(x, y):
        return (y / ky, x / kx)
    return to, back


def _ellipse_len(a: float, b: float) -> float:
    """Ramanujan's perimeter of an ellipse with half-axes a, b."""
    return math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))


def _side_offset(axis_m: float, target_m: float) -> float | None:
    """Half-width of the ellipse whose long axis is the start-to-far-point line and whose perimeter
    (times the road factor) is the target."""
    a = axis_m / 2
    want = target_m / TORTUOSITY
    if _ellipse_len(a, 0.05 * a) > want:
        return None                      # even a thin loop out there is too long
    lo, hi = 0.05 * a, 3 * a
    if _ellipse_len(a, hi) < want:
        return None
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _ellipse_len(a, mid) < want else (lo, mid)
    return (lo + hi) / 2


def _shape(start, far, offset_m: float, skew: float = 0.0):
    """The two side points: either side of the start-to-far line, at its middle (skew moves them along it)."""
    to, back = _xy(start[0])
    sx, sy = to(start)
    fx, fy = to(far)
    L = math.hypot(fx - sx, fy - sy) or 1.0
    ux, uy = (fx - sx) / L, (fy - sy) / L
    nx, ny = -uy, ux
    t = 0.5 + skew
    mx, my = sx + ux * L * t, sy + uy * L * t
    return back(mx + nx * offset_m, my + ny * offset_m), back(mx - nx * offset_m, my - ny * offset_m)


# --- measuring a candidate ----------------------------------------------------------------------------
def _measure(g: Graph, path: Path) -> dict:
    km = {"paved": 0.0, "gravel": 0.0, "rough": 0.0, "trail": 0.0, "singletrack": 0.0, "unknown": 0.0}
    busy = 0.0
    for wi, a, b in zip(path.ways, path.points, path.points[1:]):
        tags = g.ways[wi]["tags"]
        d = haversine(*a, *b)
        km[osm.classify(tags)[0]] += d
        if osm.busy(tags):
            busy += d
    known = sum(v for k, v in km.items() if k != "unknown")
    off = km["gravel"] + km["rough"] + km["trail"] + km["singletrack"]
    return {"off_share": off / known if known > 500 else None, "busy_m": busy, "single_m": km["singletrack"],
            "trail_m": km["trail"], "unknown_m": km["unknown"]}


def _samples(points, step: float = SAMPLE_M) -> list[tuple[float, float, float]]:
    out, d, nxt = [], 0.0, 0.0
    for i, p in enumerate(points):
        if i:
            d += haversine(*points[i - 1], *p)
        if d >= nxt:
            out.append((p[0], p[1], d))
            nxt = d + step
    return out


def _twice(points) -> float:
    """Share of the loop ridden twice: within 30 m of another part of it at least 600 m away along it
    (out-and-back spurs, the same road out and home)."""
    smp = _samples(points)
    grid: dict = {}
    for p in smp:
        grid.setdefault((int(p[0] // 0.0005), int(p[1] // 0.0007)), []).append(p)
    hit = 0
    for la, lo, d in smp:
        ci, cj = int(la // 0.0005), int(lo // 0.0007)
        if any(abs(q[2] - d) > 600 and haversine(la, lo, q[0], q[1]) < 30
               for di in (-1, 0, 1) for dj in (-1, 0, 1) for q in grid.get((ci + di, cj + dj), ())):
            hit += 1
    return hit / len(smp) if smp else 0.0


def _shared(a_pts, b_pts) -> float:
    """Share of loop a within 60 m of loop b (to keep the options different from each other)."""
    grid: dict = {}
    for p in _samples(b_pts, 50):
        grid.setdefault((int(p[0] // 0.001), int(p[1] // 0.0014)), []).append(p)
    smp = _samples(a_pts, 50)
    near = sum(1 for la, lo, _ in smp if any(haversine(la, lo, q[0], q[1]) < 60
                                               for di in (-1, 0, 1) for dj in (-1, 0, 1)
                                               for q in grid.get((int(la // 0.001) + di, int(lo // 0.0014) + dj), ())))
    return near / len(smp) if smp else 0.0


def _score(ask: Ask, m: float, meas: dict, twice: float, stop_pos: float | None) -> tuple[float, list[str]]:
    lo, hi = ask.km[0] * 1000, ask.km[1] * 1000
    why = []
    s = 0.0
    if m < lo:
        s += 6 * (lo - m) / lo
    elif m > hi:
        s += 6 * (m - hi) / hi
    else:
        s -= 0.2
    want = ask.gravel or (0.5, 0.7)
    off = meas["off_share"]
    if off is not None:
        if off < want[0]:
            s += 3 * (want[0] - off)
        elif off > want[1]:
            s += 1.5 * (off - want[1])
    else:
        s += 0.5
    s += 4 * meas["busy_m"] / m
    s += (0 if ask.singletrack else 25) * meas["single_m"] / m
    # Trails the map says nothing more about can turn out to be singletrack: some is fine, lots isn't.
    s += (0 if ask.singletrack else 3) * max(0.0, meas["trail_m"] / m - 0.03)
    s += 3 * twice
    if stop_pos is not None and ask.stop == "midway":
        s += 2 * max(0.0, abs(stop_pos - 0.5) - 0.1)
    return s, why


# --- the search ---------------------------------------------------------------------------------------
def _main_network(g: Graph) -> set[int]:
    """Edges in the biggest connected piece of road network (islands of private or unconnected roads left out)."""
    nbr: list[list[int]] = [[] for _ in g.coord]
    for u, v, *_ in g.edges:
        nbr[u].append(v)
        nbr[v].append(u)
    seen = [False] * len(g.coord)
    best: list[int] = []
    for s0 in range(len(g.coord)):
        if seen[s0]:
            continue
        comp, stack = [], [s0]
        seen[s0] = True
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in nbr[x]:
                if not seen[y]:
                    seen[y] = True
                    stack.append(y)
        if len(comp) > len(best):
            best = comp
    nodes = set(best)
    return {e for e, (u, v, *_) in enumerate(g.edges) if u in nodes}


def _onto_road(g: Graph, main: set[int], lat: float, lon: float, within: float = 2500):
    """The nearest point on the main road network (rural roads can be 2 km apart), or None."""
    from .router import _cell, _project
    best = None
    ci, cj = _cell(lat, lon)
    reach = int(within / 200) + 1
    for di in range(-reach, reach + 1):
        for dj in range(-reach, reach + 1):
            for e, j in g.seg_grid.get((ci + di, cj + dj), ()):
                if e not in main:
                    continue
                geom = g.edges[e][4]
                d, t = _project(lat, lon, geom[j], geom[j + 1])
                if d <= within and (best is None or d < best[0]):
                    a, b = geom[j], geom[j + 1]
                    best = (d, (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    return best[1] if best else None


def _anchors(ask: Ask, pois: list[dict]) -> list[dict]:
    """Far points to build loops around: cafés (when a stop is wanted) at about the loop's far side, else
    twelve directions."""
    start = (ask.start["lat"], ask.start["lon"])
    mid_m = (ask.km[0] + ask.km[1]) / 2 * 1000
    far = mid_m / (math.pi * TORTUOSITY) * 1.15           # a round loop's far side, a little stretched
    out = []
    if ask.stop:
        for p in pois:
            if p["kind"] != "food" or not p["name"] or COFFEE.get(p["what"], 4) > 2:
                continue
            d = haversine(*start, p["lat"], p["lon"])
            if 0.55 * far <= d <= 1.15 * far:
                chain = 0.6 if p["name"].lower() in CHAINS else 0.0
                out.append({"pt": (p["lat"], p["lon"]), "stop": p,
                            "rank": COFFEE.get(p["what"], 4) + chain + abs(d / far - 0.9)})
        # One per place (a town with three cafés is one anchor), coffee first.
        out.sort(key=lambda a: a["rank"])
        picked: list[dict] = []
        for a in out:
            if all(haversine(*a["pt"], *b["pt"]) > 1500 for b in picked):
                picked.append(a)
        out = picked[:14]
    if len(out) < 6:
        to, back = _xy(start[0])
        sx, sy = to(start)
        for k in range(12):
            th = math.radians(k * 30)
            out.append({"pt": back(sx + far * math.sin(th), sy + far * math.cos(th)), "stop": None, "rank": 5})
    return out


def _climb_per_km(points, heights) -> float:
    """Metres climbed per km, from ground heights every 100 m (3 m hysteresis, as the route check)."""
    smp = _samples(points, 100)
    hs = [heights.height(la, lo) for la, lo, _ in smp]
    up, ref = 0.0, hs[0] if hs else 0.0
    for h in hs[1:]:
        if h > ref + 3:
            up += h - ref
            ref = h
        elif h < ref - 3:
            ref = h
    return up / (smp[-1][2] / 1000) if smp and smp[-1][2] > 0 else 0.0


def _evaluate(ask: Ask, g: Graph, via: list, kind: str, stop: dict | None = None, stop_index: int | None = None,
              turn: dict | None = None, extra: float = 0.0) -> dict | None:
    """Route through `via` and score it. kind: loop | oneway | out_back (ride `via` out, then the same way
    back) | loop_back (a loop through the destination: back a different way)."""
    out = g.route(via)
    if out is None or out.m < 500:
        return None
    if kind == "out_back":
        path = Path(out.points + out.points[-2::-1], out.ways + out.ways[::-1], 2 * out.m, 2 * out.cost)
        twice = 0.0                 # the same road back is the point
        meas = _measure(g, out)
        meas = {**meas, "busy_m": 2 * meas["busy_m"], "single_m": 2 * meas["single_m"], "trail_m": 2 * meas["trail_m"]}
    else:
        path = out
        twice = _twice(path.points)
        meas = _measure(g, path)
    stop_pos = None
    if stop is not None:
        if kind == "out_back" and stop_index == len(via) - 1:
            stop_pos = 0.5
        else:
            first = g.route(via[:stop_index + 1])
            stop_pos = first.m / path.m if first else None
    score, _ = _score(ask, path.m, meas, twice, stop_pos)
    if ask.stop and stop is None:
        score += 1.0        # asked for a café: a route without one only if there's nothing better
    return {"kind": kind, "via": via, "path": path, "meas": meas, "twice": twice, "stop": stop, "stop_pos": stop_pos,
            "turn": turn, "score": score + extra}


def _with_km(ask: Ask, lo_m: float, hi_m: float) -> Ask:
    """The same ask with a distance range (for routes where the rider didn't give one)."""
    from dataclasses import replace
    return replace(ask, km=(lo_m / 1000, hi_m / 1000))


def _loop_cands(ask: Ask, g: Graph, main: set, start, pois: list[dict], anchors: list[dict] | None = None,
                kind: str = "loop", extra: float = 0.0) -> list[dict]:
    if ask.via and anchors is None:
        v = _onto_road(g, main, ask.via["lat"], ask.via["lon"])
        if v is None:
            raise ValueError(f"No roads near {ask.via['name']} on our map.")
        anchors = [{"pt": v, "stop": None, "place": ask.via}]
        if ask.stop:
            anchors += [{"pt": (p["lat"], p["lon"]), "stop": p, "place": ask.via} for p in pois
                        if p["kind"] == "food" and p["name"] and COFFEE.get(p["what"], 4) <= 2
                        and haversine(p["lat"], p["lon"], *v) < 2500][:4]
    if not ask.km:
        # Through a place, no distance given: a moderately round loop out to it.
        axis = haversine(*start, *anchors[0]["pt"])
        per = _ellipse_len(axis / 2, 0.35 * axis / 2) * TORTUOSITY
        ask = _with_km(ask, per * 0.85, per * 1.2)
    target = (ask.km[0] + ask.km[1]) / 2 * 1000
    cands: list[dict] = []

    def attempt(anchor, offset, skew=0.0):
        a, b = _shape(start, anchor["pt"], offset, skew)
        a, b = _onto_road(g, main, *a), _onto_road(g, main, *b)
        far = _onto_road(g, main, *anchor["pt"], within=400 if anchor["stop"] else 2500)
        if a is None or b is None or far is None:
            return None
        c = _evaluate(ask, g, [start, a, far, b, start], kind, stop=anchor["stop"], stop_index=2,
                      turn=anchor.get("place"), extra=extra)
        if c:
            c.update(anchor=anchor, offset=offset)
            cands.append(c)
        return c

    for anchor in anchors if anchors is not None else _anchors(ask, pois):
        axis = haversine(*start, *anchor["pt"])
        off = _side_offset(axis, target)
        if off is None:
            continue
        c = attempt(anchor, off)
        if c is None:
            continue
        # Nudge once: the road factor this direction actually has, from what the router found.
        ratio = c["path"].m / (_ellipse_len(axis / 2, off) or 1.0)
        if not (ask.km[0] * 1000 <= c["path"].m <= ask.km[1] * 1000) and ratio > 0:
            a2 = axis / 2
            want = target / ratio
            lo, hi = 0.05 * a2, 3 * a2
            if _ellipse_len(a2, lo) < want < _ellipse_len(a2, hi):
                for _ in range(40):
                    mid = (lo + hi) / 2
                    lo, hi = (mid, hi) if _ellipse_len(a2, mid) < want else (lo, mid)
                attempt(anchor, (lo + hi) / 2)
        for skew in (-0.15, 0.15):
            attempt(anchor, off, skew=skew)
        attempt(anchor, off * 1.3)
    return cands


def _side_points(start, end, offsets, skews=(-0.2, 0.0, 0.2)):
    for off in offsets:
        for skew in skews:
            a, b = _shape(start, end, off, skew)
            yield a
            yield b


def _one_way_cands(ask: Ask, g: Graph, main: set, start, pois: list[dict]) -> list[dict]:
    end = _onto_road(g, main, ask.end["lat"], ask.end["lon"])
    if end is None:
        raise ValueError(f"No roads near {ask.end['name']} on our map.")
    direct = g.leg(start, end)
    if direct is None:
        raise ValueError(f"Couldn't find roads from {ask.start['name']} to {ask.end['name']}.")
    crow = haversine(*start, *end) or 1.0
    if not ask.km:
        ask = _with_km(ask, direct.m * 0.95, direct.m * 1.35)
    target = (ask.km[0] + ask.km[1]) / 2 * 1000
    if target < direct.m * 0.9:
        ask.notes.append(f"The shortest way from {ask.start['name']} to {ask.end['name']} is about "
                         f"{direct.m / 1000:.0f} km, so these are longer than you asked.")
    cands = [c for c in [_evaluate(ask, g, [start, end], "oneway", turn=ask.end)] if c]
    # Bend out to one side to make up the distance: points on an ellipse with the start and end as foci.
    half_sum = target / (direct.m / crow) / 2
    c2 = crow / 2
    offs = [math.sqrt(half_sum ** 2 - c2 ** 2) * f for f in (0.75, 1.0, 1.25)] if half_sum > c2 * 1.03 \
        else [0.12 * crow, 0.25 * crow]
    for p in _side_points(start, end, offs):
        q = _onto_road(g, main, *p)
        if q is not None:
            c = _evaluate(ask, g, [start, q, end], "oneway", turn=ask.end)
            if c:
                cands.append(c)
    if ask.stop:
        cafes = []
        for p in pois:
            if p["kind"] != "food" or not p["name"] or COFFEE.get(p["what"], 4) > 2:
                continue
            da, db = haversine(*start, p["lat"], p["lon"]), haversine(p["lat"], p["lon"], *end)
            if da + db <= 2 * half_sum * 1.15 and 0.25 <= da / (da + db) <= 0.75:
                cafes.append((abs(da / (da + db) - 0.5) + (0.3 if p["name"].lower() in CHAINS else 0), p))
        # One café per town, best placed first (not every café in the area: that's slow).
        cafes.sort(key=lambda x: x[0])
        chosen: list[dict] = []
        for _, p in cafes:
            if all(haversine(p["lat"], p["lon"], q["lat"], q["lon"]) > 3000 for q in chosen):
                chosen.append(p)
        for p in chosen[:30]:
            q = _onto_road(g, main, p["lat"], p["lon"], within=400)
            if q is not None:
                c = _evaluate(ask, g, [start, q, end], "oneway", stop=p, stop_index=1, turn=ask.end,
                              extra=0.6 if p["name"].lower() in CHAINS else 0.0)
                if c:
                    cands.append(c)
    return cands


def _out_back_cands(ask: Ask, g: Graph, main: set, start, pois: list[dict], places: list[dict] | None) -> list[dict]:
    cands: list[dict] = []
    if ask.end:
        end = _onto_road(g, main, ask.end["lat"], ask.end["lon"])
        if end is None:
            raise ValueError(f"No roads near {ask.end['name']} on our map.")
        direct = g.leg(start, end)
        if direct is None:
            raise ValueError(f"Couldn't find roads from {ask.start['name']} to {ask.end['name']}.")
        if not ask.km:
            ask = _with_km(ask, 2 * direct.m * 0.95, 2 * direct.m * 1.3)
        crow = haversine(*start, *end) or 1.0
        stop = None
        if ask.stop:      # the café to turn round at: the nearest good one to the destination
            near = [p for p in pois if p["kind"] == "food" and p["name"] and COFFEE.get(p["what"], 4) <= 2
                    and haversine(p["lat"], p["lon"], *end) < 2000]
            near.sort(key=lambda p: (p["name"].lower() in CHAINS, COFFEE.get(p["what"], 4),
                                     haversine(p["lat"], p["lon"], *end)))
            if near:
                stop = near[0]
                end = _onto_road(g, main, stop["lat"], stop["lon"], within=400) or end
        for via in [[start, end]] + [[start, q, end] for q in
                                     (_onto_road(g, main, *p) for p in _side_points(start, end, (0.15 * crow, 0.3 * crow), (0.0,)))
                                     if q is not None]:
            c = _evaluate(ask, g, via, "out_back", stop=stop, stop_index=len(via) - 1 if stop else None, turn=ask.end)
            if c:
                cands.append(c)
        # And one that comes back a different way (a loop through the destination), if it's good.
        from dataclasses import replace
        loop_ask = replace(ask, via=ask.end, end=None, shape="loop")
        anchors = [{"pt": end, "stop": stop, "place": ask.end}]
        cands += _loop_cands(loop_ask, g, main, start, pois, anchors=anchors, kind="loop_back", extra=0.2)
        return cands
    # Only a distance: turn round half way out, at a café or a town if there's one about the right distance.
    half = (ask.km[0] + ask.km[1]) / 4 * 1000
    reach = half / TORTUOSITY
    turns = []
    if ask.stop:
        for p in pois:
            if p["kind"] == "food" and p["name"] and COFFEE.get(p["what"], 4) <= 2:
                d = haversine(*start, p["lat"], p["lon"])
                if 0.6 * reach <= d <= 1.15 * reach:
                    turns.append(({"name": p["name"], "lat": p["lat"], "lon": p["lon"]}, p))
    for pl in places or []:
        d = haversine(*start, pl["lat"], pl["lon"])
        if 0.6 * reach <= d <= 1.15 * reach and pl.get("population", 0) > 0:
            turns.append((pl, None))
    to, back = _xy(start[0])
    sx, sy = to(start)
    for k in range(12):
        th = math.radians(k * 30)
        la, lo = back(sx + reach * math.sin(th), sy + reach * math.cos(th))
        turns.append(({"name": None, "lat": la, "lon": lo}, None))
    for place, stop in turns[:40]:
        q = _onto_road(g, main, place["lat"], place["lon"], within=400 if stop else 2500)
        if q is None:
            continue
        c = _evaluate(ask, g, [start, q], "out_back", stop=stop, stop_index=1 if stop else None,
                      turn=place if place["name"] else None)
        if c:
            cands.append(c)
            # Nudge once along the same line when the length is off (open directions only).
            if not place["name"] and not (ask.km[0] * 1000 <= c["path"].m <= ask.km[1] * 1000):
                f = 2 * half / c["path"].m
                qx, qy = to(q)
                q2 = _onto_road(g, main, *back(sx + (qx - sx) * f, sy + (qy - sy) * f))
                if q2 is not None:
                    c2 = _evaluate(ask, g, [start, q2], "out_back")
                    if c2:
                        cands.append(c2)
    return cands


def routes(ask: Ask, g: Graph, pois: list[dict], places: list[dict] | None = None, n: int = 3,
           heights=None) -> list[Option]:
    """Best first. A loop, one way, or there and back (ask.shape)."""
    if not ask.start:
        raise ValueError("A route needs a start.")
    main = _main_network(g)
    start = _onto_road(g, main, ask.start["lat"], ask.start["lon"], within=1500)
    if start is None:
        raise ValueError(f"No roads near {ask.start['name']} on our map.")
    if ask.shape == "oneway":
        if not ask.end:
            raise ValueError("A one-way route needs somewhere to end.")
        cands = _one_way_cands(ask, g, main, start, pois)
    elif ask.shape == "out_back":
        if not ask.end and not ask.km:
            raise ValueError("There and back needs a distance or a place to turn round.")
        cands = _out_back_cands(ask, g, main, start, pois, places)
    else:
        if not ask.km and not ask.via:
            raise ValueError("A loop needs a distance or a place to go through.")
        cands = _loop_cands(ask, g, main, start, pois)
    cands.sort(key=lambda c: c["score"])
    if ask.hills and heights is not None:
        # Flat or hilly: measure the climbing of the best dozen and rank them again.
        for c in cands[:12]:
            c["climb"] = _climb_per_km(c["path"].points, heights)
            c["score"] += 0.05 * c["climb"] if ask.hills == "flat" else -0.02 * c["climb"]
        cands[:12] = sorted(cands[:12], key=lambda c: c["score"])
    # Different from each other: routes to one named place share their ends, so allow more overlap there.
    same_place = ask.shape in ("oneway", "out_back") and ask.end
    limit = 0.8 if same_place else 0.55
    picked: list[dict] = []
    for c in cands:
        if c["kind"] == "loop_back" and any(p["kind"] == "loop_back" for p in picked):
            continue
        if all(_shared(c["path"].points, p["path"].points) < limit for p in picked):
            picked.append(c)
        if len(picked) == n:
            break
    return [_option(ask, g, c, places) for c in picked]


loops = routes      # the first name, kept for callers


def _nearest_place(places, pt, within=4000):
    if not places:
        return None
    near = min(places, key=lambda p: haversine(*pt, p["lat"], p["lon"]))
    return near["name"] if haversine(*pt, near["lat"], near["lon"]) < within else None


def _option(ask: Ask, g: Graph, c: dict, places: list[dict] | None) -> Option:
    path, meas, kind = c["path"], c["meas"], c["kind"]
    stop = None
    if c["stop"]:
        st = c["stop"]
        stop = {"name": st["name"], "what": st["what"], "lat": st["lat"], "lon": st["lon"],
                "km": round(c["stop_pos"] * path.m / 1000, 1) if c["stop_pos"] else None}
    surface = {"gravel": "gravel ", "road": "road ", "mixed": ""}.get(ask.surface or "", "")
    start = ask.start["name"]
    turn = c.get("turn")
    far = c["via"][len(c["via"]) // 2] if kind != "out_back" else c["via"][-1]
    place = (turn or {}).get("name") or _nearest_place(places, far) or (stop or {}).get("name")
    via = place
    if kind == "oneway":
        name = f"{start} to {ask.end['name']}" + (f", {surface.strip()}" if surface else "")
        middle = c["via"][1] if len(c["via"]) == 3 else None
        by = stop["name"] if stop else (_nearest_place(places, middle) if middle else None)
        if by and by != ask.end["name"]:
            name += f" via {by}"
            via = by
    elif kind == "out_back":
        name = f"{start} to {place or 'the turn'} and back"
    elif kind == "loop_back":
        name = f"{start} to {place} and back a different way"
    else:
        name = f"{start} {surface}loop"
        if stop and place and place != stop["name"]:
            name += f" via {stop['name']}, {place}"
        elif place or stop:
            name += f" via {place or stop['name']}"
    # Only what the route check won't say itself (its figures are the ones to trust).
    why = []
    if kind == "out_back":
        why.append(f"turns round at {stop['name'] if stop else place or 'the halfway point'}, km {path.m / 2000:.0f}")
    elif stop and stop["km"]:
        why.append(f"{stop['name']} at km {stop['km']:.0f} of {path.m / 1000:.0f}")
    if kind == "loop_back":
        why.append("back a different way")
    if c["twice"] > 0.05:
        why.append(f"{c['twice'] * 100:.0f}% ridden twice")
    if c.get("climb") is not None:
        why.append("picked for flat roads" if ask.hills == "flat" else "picked for climbing")
    pts = [(la, lo, 0.0) for la, lo in path.points]
    return Option(route=Route(name=name[:1].upper() + name[1:], points=pts, source="generated"), path=path, km=round(path.m / 1000, 1),
                  off_share=round(meas["off_share"], 2) if meas["off_share"] is not None else None,
                  busy_km=round(meas["busy_m"] / 1000, 1), singletrack_km=round(meas["single_m"] / 1000, 1),
                  twice_share=round(c["twice"], 2), stop=stop, via=via, score=round(c["score"], 3), why=why)
