"""OpenStreetMap along a route: the roads and trails it uses (with their surface tags) and the places
to stop near it (cafés, shops, water, toilets, viewpoints).

Read from our own copy of the map when the route is inside it (data/osm/map.sqlite3, built from a
Geofabrik extract by `python -m backend build-map`; instant and offline). Elsewhere, fetched from the
public Overpass API in tiles around the route only (no account, nothing about the rider is sent) and
cached under data/osm-cache/ (all git-ignored). Data © OpenStreetMap contributors, ODbL: credit it
wherever a route report is shown.

    data = corridor(route)            # {"ways": [...], "pois": [...]}
    classify(way["tags"])             # ("gravel", False) = (surface class, assumed from the road type?)
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from array import array
import urllib.parse
import urllib.request

from .route import Route

ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "osm-cache")
LOCAL_DB = os.path.join(os.path.dirname(__file__), "..", "..", "data", "osm", "map.sqlite3")
CREDIT = "Map data © OpenStreetMap contributors (ODbL)"
USER_AGENT = "rideengine-route-check/0.1"

WAY_M = 35        # roads within this of the route line
POI_M = 400       # a stop is worth it within this detour
VIEW_M = 600

# --- surfaces -------------------------------------------------------------------------------------
# Classes, in the order the report shows them: paved, gravel, rough (dirt roads and tracks: rideable but
# slow), trail (a path the map doesn't describe: wide forest trail or singletrack), singletrack (narrow or
# natural-surface path: what a gravel rider wants to avoid), unknown.
PAVED = {"asphalt", "paved", "concrete", "concrete:plates", "concrete:lanes", "paving_stones", "sett",
         "chipseal", "metal", "wood", "bricks", "cobblestone", "unhewn_cobblestone"}
GRAVEL = {"gravel", "fine_gravel", "compacted", "unpaved", "pebblestone", "crushed_limestone", "shells",
          "gravel;dirt", "dirt;gravel"}
ROUGH = {"dirt", "earth", "ground", "mud", "sand", "grass", "grass_paver", "woodchips", "rock", "stone",
         "clay", "soil"}
TRAILS = {"path", "footway", "bridleway", "steps", "pedestrian"}
MAJOR = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary",
         "secondary_link", "tertiary", "tertiary_link", "residential", "living_street", "service"}
BAD_SMOOTHNESS = {"very_bad", "horrible", "very_horrible", "impassable"}


def _mtb(tags: dict) -> float:
    try:
        return float((tags.get("mtb:scale") or "0").split(";")[0].rstrip("+-"))
    except ValueError:
        return 0.0


def _width(tags: dict) -> float | None:
    try:
        return float((tags.get("width") or "").split()[0])
    except (ValueError, IndexError):
        return None


def classify(tags: dict) -> tuple[str, bool]:
    """(surface class, assumed): assumed=True when the map has no surface tag and the class comes from
    the kind of road."""
    hw = tags.get("highway", "")
    surface = (tags.get("surface") or "").lower()
    rough_ride = tags.get("smoothness") in BAD_SMOOTHNESS
    if hw in TRAILS or _mtb(tags) >= 1 or tags.get("sac_scale"):
        narrow = (_width(tags) or 2.0) < 1.5 or _mtb(tags) >= 1 or hw == "steps" or bool(tags.get("sac_scale"))
        if surface in PAVED and not narrow:
            return "paved", False
        # Rail trails and multi-use paths: wide, crushed stone. A gravel bike's ideal.
        if surface in GRAVEL and not narrow and not rough_ride:
            return "gravel", False
        if not surface and not narrow and (tags.get("railway") == "abandoned" or "rail trail" in
                                           (tags.get("name") or "").lower()):
            return "gravel", True
        if narrow or surface in ROUGH or surface.split(";")[0] in ROUGH:
            return "singletrack", False
        # A path the map says nothing more about: could be a wide forest trail, could be singletrack.
        return "trail", True
    if hw == "track":
        if surface:
            return _by_surface(surface, rough_ride), False
        grade = tags.get("tracktype", "")
        if grade == "grade1":
            return "paved", True
        if grade in ("grade4", "grade5"):
            return "rough", True
        return "gravel", True        # farm and forest tracks are unpaved unless the map says otherwise
    if surface:
        return _by_surface(surface, rough_ride), False
    if hw == "cycleway":
        return "paved", True
    if hw in MAJOR:
        return "paved", True
    return "unknown", True           # unclassified roads: in rural Ontario, often gravel; we don't guess


def _by_surface(surface: str, rough_ride: bool) -> str:
    s = surface.split(";")[0]
    if surface in PAVED or s in PAVED:
        return "rough" if rough_ride else "paved"
    if surface in GRAVEL or s in GRAVEL:
        return "rough" if rough_ride else "gravel"
    if surface in ROUGH or s in ROUGH:
        return "rough"
    return "unknown"


def _speed(tags: dict) -> float | None:
    raw = (tags.get("maxspeed") or "").lower()
    try:
        v = float(raw.split()[0])
    except (ValueError, IndexError):
        return None
    return v * 1.609 if "mph" in raw else v


def busy(tags: dict) -> bool:
    """Roads with fast or heavy traffic: highways, main roads, and fast regional roads."""
    hw = tags.get("highway", "")
    if hw in ("motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"):
        return True
    sp = _speed(tags)
    return hw in ("secondary", "secondary_link") and (sp is None or sp >= 70)


def road_name(tags: dict) -> str | None:
    return tags.get("name") or tags.get("ref") or tags.get("official_name")


# --- stops ----------------------------------------------------------------------------------------
FOOD = {"cafe", "restaurant", "fast_food", "pub", "ice_cream", "bar", "food_court"}
SHOP = {"convenience", "bakery", "supermarket", "general", "deli", "farm", "greengrocer", "coffee"}


def poi_kind(tags: dict) -> str | None:
    """food, shop, water, toilets, bike, view (or None)."""
    am, sh = tags.get("amenity", ""), tags.get("shop", "")
    if am in FOOD or sh == "bakery" or sh == "coffee":
        return "food"
    if sh in SHOP or am == "fuel":
        return "shop"
    if am in ("drinking_water", "water_point") or tags.get("drinking_water") == "yes" and am == "fountain":
        return "water"
    if am == "toilets":
        return "toilets"
    if sh == "bicycle" or am == "bicycle_repair_station":
        return "bike"
    if tags.get("tourism") == "viewpoint":
        return "view"
    return None


# --- fetching -------------------------------------------------------------------------------------
def _xy(lat0: float, lat: float, lon: float) -> tuple[float, float]:
    k = math.cos(math.radians(lat0))
    return lon * 111320 * k, lat * 110540


def simplify(points: list[tuple[float, float]], tol_m: float = 10.0) -> list[tuple[float, float]]:
    """Douglas-Peucker in metres: the fewest points that stay within tol_m of the line."""
    if len(points) < 3:
        return list(points)
    lat0 = points[0][0]
    xy = [_xy(lat0, la, lo) for la, lo in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = xy[a], xy[b]
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        worst, wi = 0.0, -1
        for i in range(a + 1, b):
            px, py = xy[i]
            t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
            d = math.hypot(px - ax - t * dx, py - ay - t * dy)
            if d > worst:
                worst, wi = d, i
        if worst > tol_m and wi > 0:
            keep[wi] = True
            stack += [(a, wi), (wi, b)]
    return [p for p, k in zip(points, keep) if k]


TILE_LAT, TILE_LON = 0.04, 0.05      # ~4.4 x 4 km map tiles, cached one file each
BATCH = 10                            # tiles per request
HIGHWAY_SKIP = "proposed|construction|abandoned|platform|razed|disused"
AMENITY = ("cafe|restaurant|fast_food|pub|bar|ice_cream|food_court|drinking_water|water_point|toilets|fuel|"
           "bicycle_repair_station")
SHOPS = "convenience|bakery|supermarket|general|deli|farm|greengrocer|coffee|bicycle"


def tiles(route: Route, pad_m: float = VIEW_M) -> list[tuple[int, int]]:
    """The map tiles the route passes, plus neighbours within pad_m (stops just off the route)."""
    out = set()
    for la, lo, _, _ in route.resample(200):
        dla, dlo = pad_m / 110540, pad_m / (111320 * math.cos(math.radians(la)))
        for a in (la - dla, la, la + dla):
            for b in (lo - dlo, lo, lo + dlo):
                out.add((math.floor(a / TILE_LAT), math.floor(b / TILE_LON)))
    return sorted(out)


def tile_of(lat: float, lon: float) -> tuple[int, int]:
    return math.floor(lat / TILE_LAT), math.floor(lon / TILE_LON)


def tile_key(t: tuple[int, int]) -> int:
    """One integer per tile, for the local map's index."""
    return (t[0] + 5000) * 100000 + (t[1] + 50000)


def tiles_of_points(pts) -> set[tuple[int, int]]:
    """Every tile a line of (lat, lon) points passes through (segment ends and midpoints)."""
    out = set()
    for a, b in zip(pts, pts[1:] or pts):
        out.add(tile_of(*a))
        out.add(tile_of(*b))
        # Long segments (rural roads have few nodes) can cross tiles between their ends.
        steps = int(max(abs(b[0] - a[0]) / TILE_LAT, abs(b[1] - a[1]) / TILE_LON) * 2)
        for k in range(1, steps + 1):
            f = k / (steps + 1)
            out.add(tile_of(a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])))
    return out


def _bbox(t: tuple[int, int]) -> str:
    s, w = t[0] * TILE_LAT, t[1] * TILE_LON
    return f"{s:.4f},{w:.4f},{s + TILE_LAT:.4f},{w + TILE_LON:.4f}"


def query(batch: list[tuple[int, int]]) -> str:
    ways = "".join(f'way[highway][highway!~"^({HIGHWAY_SKIP})$"]({_bbox(t)});' for t in batch)
    pois = "".join(f'nwr[amenity~"^({AMENITY})$"]({_bbox(t)});nwr[shop~"^({SHOPS})$"]({_bbox(t)});'
                   f"nwr[tourism=viewpoint]({_bbox(t)});" for t in batch)
    return f"[out:json][timeout:180];({ways});out tags geom;({pois});out tags center;"


def _tiles_of(el: dict, wanted: set) -> set:
    if "geometry" in el:
        pts = [(g["lat"], g["lon"]) for g in el["geometry"] if g]
    else:
        c = el.get("center") or el
        pts = [(c.get("lat"), c.get("lon"))] if c.get("lat") is not None else []
    if not pts:
        return set()
    i0, i1 = math.floor(min(p[0] for p in pts) / TILE_LAT), math.floor(max(p[0] for p in pts) / TILE_LAT)
    j0, j1 = math.floor(min(p[1] for p in pts) / TILE_LON), math.floor(max(p[1] for p in pts) / TILE_LON)
    return {(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)} & wanted


def _fetch(q: str) -> dict:
    body = urllib.parse.urlencode({"data": q}).encode()
    last = None
    for attempt, url in enumerate(ENDPOINTS * 2):
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=240) as r:
                doc = json.loads(r.read())
            # A server under load can answer with nothing (or a remark) rather than an error.
            if doc.get("remark") or not doc.get("elements"):
                raise RuntimeError(doc.get("remark") or "empty answer")
            return doc
        except Exception as e:      # busy server (429/504): try the other one, then again after a pause
            last = e
            time.sleep(2 + 3 * attempt)
    raise RuntimeError(f"OpenStreetMap lookup failed: {last}")


def _tile_path(cache_dir: str, t: tuple[int, int]) -> str:
    return os.path.join(cache_dir, "tiles", f"{t[0]}_{t[1]}.json")


def _local_covers(db: sqlite3.Connection, want: list[tuple[int, int]]) -> bool:
    row = db.execute("SELECT value FROM meta WHERE key = 'bbox'").fetchone()
    if not row:
        return False
    s, w, n, e = json.loads(row[0])
    # A tile's centre within a tile of the map's extent (the route's own tiles reach a little past it).
    return all(s - TILE_LAT <= (i + 0.5) * TILE_LAT <= n + TILE_LAT and w - TILE_LON <= (j + 0.5) * TILE_LON <= e + TILE_LON
               for i, j in want)


def local(route: Route, path: str = LOCAL_DB) -> dict | None:
    """Roads and stops around the route from our own copy of the map, or None if it isn't there or
    doesn't cover the route."""
    if not os.path.exists(path):
        return None
    want = tiles(route)
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if not _local_covers(db, want):
            return None
        keys = [tile_key(t) for t in want]
        ways, pois = [], []
        for k in range(0, len(keys), 500):
            chunk = keys[k:k + 500]
            marks = ",".join("?" * len(chunk))
            for wid, tags, geom in db.execute(
                    f"SELECT id, tags, geom FROM ways WHERE id IN (SELECT DISTINCT id FROM way_tiles WHERE tile IN ({marks}))",
                    chunk):
                g = array("i")
                g.frombytes(geom)
                ways.append({"id": wid, "tags": json.loads(tags),
                             "geom": [(g[i] / 1e7, g[i + 1] / 1e7) for i in range(0, len(g), 2)]})
            for pid, lat, lon, tags in db.execute(f"SELECT id, lat, lon, tags FROM pois WHERE tile IN ({marks})", chunk):
                t = json.loads(tags)
                kind = poi_kind(t)
                if kind:
                    pois.append({"id": pid, "lat": lat, "lon": lon, "kind": kind,
                                 "name": t.get("name") or t.get("brand") or "",
                                 "what": t.get("amenity") or t.get("shop") or t.get("tourism") or "",
                                 "hours": t.get("opening_hours") or ""})
        date = db.execute("SELECT value FROM meta WHERE key = 'osm_date'").fetchone()
        return {"ways": ways, "pois": pois, "fetched": date[0] if date else None, "tiles": len(want), "map": "local"}
    finally:
        db.close()


def corridor(route: Route, cache_dir: str = CACHE_DIR, refresh: bool = False, progress=None,
             local_db: str | None = LOCAL_DB) -> dict:
    """Roads and stops around the route: from our own map if it covers the route, else Overpass tiles
    (cached, the rest fetched in batches)."""
    if local_db and not refresh:
        found = local(route, local_db)
        if found is not None:
            return found
    want = tiles(route)
    missing = [t for t in want if refresh or not os.path.exists(_tile_path(cache_dir, t))]
    os.makedirs(os.path.join(cache_dir, "tiles"), exist_ok=True)
    stamp = None
    for k in range(0, len(missing), BATCH):
        batch = missing[k:k + BATCH]
        doc = _fetch(query(batch))
        stamp = doc.get("osm3s", {}).get("timestamp_osm_base")
        per: dict = {t: [] for t in batch}
        for el in doc["elements"]:
            for t in _tiles_of(el, set(batch)):
                per[t].append(el)
        for t, els in per.items():
            path = _tile_path(cache_dir, t)
            with open(path + ".part", "w") as f:
                json.dump({"fetched": stamp, "elements": els}, f)
            os.replace(path + ".part", path)
        if progress:
            progress(min(len(missing), k + BATCH), len(missing))
    seen, elements, dates = set(), [], set()
    for t in want:
        with open(_tile_path(cache_dir, t)) as f:
            doc = json.load(f)
        dates.add(doc.get("fetched"))
        for el in doc["elements"]:
            key = (el["type"], el["id"])
            if key not in seen:
                seen.add(key)
                elements.append(el)
    out = parse({"elements": elements})
    out["fetched"] = min((d for d in dates if d), default=None)
    out["tiles"] = len(want)
    out["map"] = "overpass"
    return out


def parse(doc: dict) -> dict:
    ways, pois = [], []
    for el in doc.get("elements", []):
        tags = el.get("tags") or {}
        if el["type"] == "way" and "geometry" in el and "highway" in tags:
            ways.append({"id": el["id"], "tags": tags,
                         "geom": [(g["lat"], g["lon"]) for g in el["geometry"] if g]})
            continue
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        kind = poi_kind(tags)
        if lat is None or kind is None:
            continue
        pois.append({"id": f"{el['type'][0]}{el['id']}", "lat": lat, "lon": lon, "kind": kind,
                     "name": tags.get("name") or tags.get("brand") or "",
                     "what": tags.get("amenity") or tags.get("shop") or tags.get("tourism") or "",
                     "hours": tags.get("opening_hours") or ""})
    return {"ways": ways, "pois": pois, "fetched": doc.get("osm3s", {}).get("timestamp_osm_base")}


