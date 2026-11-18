"""Where the gravel is: a coarse grid over our own map (rideengine/routes/osm.py LOCAL_DB) with the km of
road of each surface class per map tile (~4.4 x 4 km). Built once from the map in a few seconds and cached
next to it (data/osm/gravel_grid.json, rebuilt when the map is newer).

Used before making loops: a gravel ride from home in the city can't be a gravel ride (within 20 km of
Leaside under 5% of roads are unpaved), so we say so and offer starts where the gravel is.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from array import array

from ..model import haversine
from . import osm

GRID = os.path.join(os.path.dirname(osm.LOCAL_DB), "gravel_grid.json")
OFF = ("gravel", "rough")
ROADS = ("paved", "gravel", "rough", "unknown")
SKIP = {"footway", "service", "steps", "corridor", "pedestrian", "bridleway"}   # sidewalks, driveways


def build(db_path: str = osm.LOCAL_DB) -> dict:
    """{(tile_lat, tile_lon): {surface class: metres}} from the local map."""
    db = sqlite3.connect(db_path)
    grid: dict = {}
    for tags, geom in db.execute("SELECT tags, geom FROM ways"):
        tg = json.loads(tags)
        if tg.get("highway") in SKIP:
            continue
        a = array("i")
        a.frombytes(geom)
        pts = [(a[i] / 1e7, a[i + 1] / 1e7) for i in range(0, len(a), 2)]
        m = 0.0
        for (la1, lo1), (la2, lo2) in zip(pts, pts[1:]):
            m += math.hypot((lo2 - lo1) * 111320 * math.cos(math.radians(la1)), (la2 - la1) * 110540)
        cls, _ = osm.classify(tg)
        d = grid.setdefault(osm.tile_of(*pts[len(pts) // 2]), {})
        d[cls] = d.get(cls, 0.0) + m
    db.close()
    return grid


_cache: dict = {}


def load(db_path: str = osm.LOCAL_DB, path: str = GRID) -> dict | None:
    """The grid, from the cache file (rebuilt if the map is newer). None without a local map."""
    if not os.path.exists(db_path):
        return None
    if path in _cache and _cache[path][0] >= os.path.getmtime(db_path):
        return _cache[path][1]
    if os.path.exists(path) and os.path.getmtime(path) >= os.path.getmtime(db_path):
        with open(path) as f:
            grid = {tuple(map(int, k.split(","))): v for k, v in json.load(f).items()}
    else:
        grid = build(db_path)
        tmp = path + ".part"
        with open(tmp, "w") as f:
            json.dump({f"{k[0]},{k[1]}": {c: round(m) for c, m in v.items()} for k, v in grid.items()}, f)
        os.replace(tmp, path)
    _cache[path] = (os.path.getmtime(db_path), grid)
    return grid


def share(grid: dict, lat: float, lon: float, r_km: float) -> float | None:
    """Off-pavement share of the roads within r_km (roads the map doesn't describe count as roads); None
    where the map has no roads (outside it)."""
    off = tot = 0.0
    ti, tj = osm.tile_of(lat, lon)
    di = int(r_km / (osm.TILE_LAT * 110.5)) + 1
    dj = int(r_km / (osm.TILE_LON * 111.3 * math.cos(math.radians(lat)))) + 1
    for i in range(ti - di, ti + di + 1):
        for j in range(tj - dj, tj + dj + 1):
            v = grid.get((i, j))
            if not v or haversine(lat, lon, (i + .5) * osm.TILE_LAT, (j + .5) * osm.TILE_LON) > r_km * 1000:
                continue
            off += sum(v.get(c, 0) for c in OFF)
            tot += sum(v.get(c, 0) for c in ROADS)
    return off / tot if tot > 1000 else None


# The router finds the gravel: loops come out with about 3x the area's share (Leaside 1.5% of roads -> 8%
# loops; Uxbridge 25% -> 60-83%). So a start is poor for a gravel ride below a quarter of the share wanted,
# and good from about 45% of it.
POOR = 0.25
GOOD = 0.45


def poor(share_: float | None, want: float) -> bool:
    return share_ is not None and share_ < want * POOR


def radius_km(km: tuple[float, float] | None) -> float:
    """How far from the start a loop of this length reaches, roughly."""
    mid = sum(km) / 2 if km else 50
    return max(6.0, min(25.0, mid / 5))


def _across_water(grid: dict, a: tuple[float, float], b: tuple[float, float]) -> bool:
    """True when the straight line from a to b crosses 8+ km with no roads at all (a lake): the drive is
    much longer than the distance."""
    n = max(2, int(haversine(*a, *b) / 2000))
    empty = 0
    for k in range(n + 1):
        f = k / n
        v = grid.get(osm.tile_of(a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])), {})
        empty = empty + 1 if sum(v.get(c, 0) for c in ROADS) < 300 else 0
        if empty >= 4:
            return True
    return False


def _direction(lat0, lon0, lat, lon) -> str:
    b = math.degrees(math.atan2((lon - lon0) * math.cos(math.radians(lat0)), lat - lat0)) % 360
    return ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"][round(b / 45) % 8]


def starts(grid: dict, places: list[dict], origin: tuple[float, float], km, want: float, n: int = 3,
           ridden: list[tuple[float, float]] = (), within_km: float = 90) -> list[dict]:
    """Places to start from with plenty of off-pavement roads around them (area share >= GOOD x the share
    wanted), closest first, places the rider has started rides from before first of all; towns people know
    (500+) or places ridden from; at least 15 km apart from each other."""
    r = radius_km(km)
    cands = []
    for p in places:
        d = haversine(origin[0], origin[1], p["lat"], p["lon"]) / 1000
        if d > within_km or d < r:
            continue
        before = any(haversine(p["lat"], p["lon"], la, lo) < 4000 for la, lo in ridden)
        if p.get("population", 0) < 500 and not before:
            continue
        s = share(grid, p["lat"], p["lon"], r)
        if s is None or s < want * GOOD:
            continue
        if _across_water(grid, origin, (p["lat"], p["lon"])):
            continue
        cands.append({"name": p["name"], "lat": p["lat"], "lon": p["lon"], "share": round(s, 2),
                      "km_away": round(d), "direction": _direction(origin[0], origin[1], p["lat"], p["lon"]),
                      "ridden": before, "population": p.get("population", 0)})
    # Closest good gravel first (a short drive), then more gravel.
    cands.sort(key=lambda c: c["km_away"] - 40 * c["share"] - (15 if c["ridden"] else 0))
    out: list[dict] = []
    for c in cands:
        if all(haversine(c["lat"], c["lon"], o["lat"], o["lon"]) > 15000 for o in out):
            out.append(c)
        if len(out) == n:
            break
    return out
