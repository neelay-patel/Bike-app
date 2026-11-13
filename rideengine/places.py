"""Towns and villages a ride passes through, from the GeoNames gazetteer, offline.

GeoNames "cities500" (every populated place with 500+ people; CC BY 4.0, credit GeoNames) is looked
up locally, so ride locations never leave the machine. Country files add every village and hamlet
(e.g. Cannington, Claremont) for the countries you ride in. Get them once:

    python -m rideengine.places --download            # cities500, ~14 MB, into data/geo/ (git-ignored)
    python -m rideengine.places --download CA GB      # all places in Canada (~8 MB), Britain

    places_on_route(ride)  ->  [{"name": "Uxbridge", "lat": .., "lon": .., "km": 35.4, "population": 21176}]
"""
from __future__ import annotations

import glob
import io
import os
import sys
import urllib.request
import zipfile

import math

from .analysis.basics import stops
from .model import Ride, haversine

BASE = "https://download.geonames.org/export/dump/"
GEO_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "geo")
DEFAULT = os.path.join(GEO_DIR, "cities500.zip")
CREDIT = "Places: GeoNames (geonames.org), CC BY 4.0"

NEAR_M = 2000        # route passes within this of a small place's centre point
NEAR_BIG_M = 3000    # towns of BIG_POP+ spread wider
BIG_POP = 10_000
START_M = 3000       # places this close to the start or finish are "home", used only as a fallback
STOP_M = 1200        # a stop this close to a place's centre counts as stopping there
STOP_MIN_S = 600     # stops of 10+ minutes (coffee, lunch) make a place the story


def download(name: str = "cities500") -> str:
    """name: "cities500", or a two-letter country code for that country's full list."""
    os.makedirs(GEO_DIR, exist_ok=True)
    path = os.path.join(GEO_DIR, f"{name}.zip")
    tmp = path + ".part"
    with urllib.request.urlopen(BASE + f"{name}.zip", timeout=300) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 16):
            f.write(chunk)
    zipfile.ZipFile(tmp).testzip()
    os.replace(tmp, path)
    return path


def _files(path: str) -> list[tuple[str, str]]:
    """(zip path, member) for cities500 plus any country files beside it."""
    out = [(path, "cities500.txt")] if os.path.exists(path) else []
    for z in sorted(glob.glob(os.path.join(os.path.dirname(path), "[A-Z][A-Z].zip"))):
        out.append((z, os.path.basename(z)[:2] + ".txt"))
    return out


def load(bbox: tuple[float, float, float, float], path: str = DEFAULT) -> list[dict]:
    """Populated places inside (south, west, north, east), from cities500 and any country files.
    Empty if nothing is downloaded."""
    s, w, n, e = bbox
    seen, out = set(), []
    for zpath, member in _files(path):
        with zipfile.ZipFile(zpath) as zf, zf.open(member) as raw:
            for line in io.TextIOWrapper(raw, encoding="utf-8"):
                col = line.split("\t", 15)
                if col[6] != "P" or col[0] in seen:
                    continue
                lat, lon = float(col[4]), float(col[5])
                if s <= lat <= n and w <= lon <= e:
                    seen.add(col[0])
                    out.append({"name": col[1], "lat": lat, "lon": lon, "population": int(col[14] or 0)})
    return out


def places_on_route(ride: Ride, path: str = DEFAULT, limit: int = 2) -> list[dict]:
    """Up to `limit` places the route goes through, most notable first, spread along the ride.

    A place counts when the route passes within NEAR_M of its centre (NEAR_BIG_M for towns of
    BIG_POP+). Ranking: places where the rider stopped for 10+ minutes first (longest stop first),
    then by population (GeoNames has no population for most villages), then by how close the route
    passes. The start/finish town is skipped unless nothing else qualifies.
    Each result carries "stop_min" when the rider stopped there.
    """
    track, d, prev = [], 0.0, None
    for s in ride.samples:
        if s.lat is None or s.lon is None:
            continue
        if prev is not None:
            d += haversine(prev.lat, prev.lon, s.lat, s.lon)
        prev = s
        track.append((s.lat, s.lon, d))
    if len(track) < 2:
        return []
    step = max(1, len(track) // 800)
    pts = track[::step] + [track[-1]]
    pad = 0.04
    bbox = (min(p[0] for p in pts) - pad, min(p[1] for p in pts) - pad,
            max(p[0] for p in pts) + pad, max(p[1] for p in pts) + pad)
    start, end = pts[0], pts[-1]
    long_stops = [st for st in stops(ride) if st["seconds"] >= STOP_MIN_S and st["lat"] is not None]
    found, home = [], []
    for pl in load(bbox, path):
        near = NEAR_BIG_M if pl["population"] >= BIG_POP else NEAR_M
        best, along = min((haversine(pl["lat"], pl["lon"], la, lo), dd) for la, lo, dd in pts)
        if best > near:
            continue
        hit = {**pl, "km": round(along / 1000, 1), "off_m": round(best)}
        stopped = [st["seconds"] for st in long_stops
                   if haversine(pl["lat"], pl["lon"], st["lat"], st["lon"]) <= STOP_M]
        if stopped:
            hit["stop_min"] = round(max(stopped) / 60)
        at_ends = min(haversine(pl["lat"], pl["lon"], start[0], start[1]),
                      haversine(pl["lat"], pl["lon"], end[0], end[1])) <= START_M
        (home if at_ends else found).append(hit)
    pool = sorted(found or home, key=lambda p: (-p.get("stop_min", 0), -math.log10(p["population"] + 10), p["off_m"]))
    total_km = track[-1][2] / 1000
    chosen: list[dict] = []
    for p in pool:  # keep picks apart along the ride, so labels don't pile up
        if all(abs(p["km"] - c["km"]) >= 0.25 * total_km for c in chosen):
            chosen.append(p)
        if len(chosen) == limit:
            break
    return chosen


if __name__ == "__main__":
    if "--download" in sys.argv:
        names = [a.upper() for a in sys.argv[sys.argv.index("--download") + 1:]] or ["cities500"]
        for name in names:
            name = "cities500" if name == "CITIES500" else name
            print(f"Downloading {BASE}{name}.zip ...")
            print("Saved", download(name))
        print(CREDIT)
    else:
        print(__doc__)
