"""Our own copy of the map: roads and stops from an OpenStreetMap extract, in a small SQLite index the
route check reads (rideengine/routes/osm.py, standard library only).

    python -m backend build-map data/osm/ontario-latest.osm.pbf      # ~1 GB from Geofabrik, a few minutes

The extract comes from download.geofabrik.de (Ontario: north-america/canada/ontario-latest.osm.pbf).
Only what the route check uses is kept: every road and trail (highway=*) with the tags that say what
it's like, and cafés, shops, water, toilets, bike shops and viewpoints. Data © OpenStreetMap
contributors, ODbL. Rebuild from a fresh extract to update (the old index is replaced when the new one
is complete).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from array import array

from rideengine.routes import osm

ROAD_TAGS = {"highway", "surface", "tracktype", "smoothness", "mtb:scale", "width", "sac_scale", "name", "ref",
             "official_name", "maxspeed", "footway", "path", "bicycle", "railway", "lanes", "access"}
POI_TAGS = {"amenity", "shop", "tourism", "name", "brand", "opening_hours", "drinking_water"}
SKIP = set(osm.HIGHWAY_SKIP.split("|"))

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE ways (id INTEGER PRIMARY KEY, tags TEXT NOT NULL, geom BLOB NOT NULL);
CREATE TABLE way_tiles (tile INTEGER NOT NULL, id INTEGER NOT NULL, PRIMARY KEY (tile, id)) WITHOUT ROWID;
CREATE TABLE pois (id TEXT PRIMARY KEY, tile INTEGER NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
                   tags TEXT NOT NULL);
"""


def build(pbf: str, out: str = osm.LOCAL_DB, progress=print) -> dict:
    import osmium  # backend dependency (pyosmium); the engine never needs it

    tmp = out + ".part"
    if os.path.exists(tmp):
        os.remove(tmp)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript("PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;" + SCHEMA)
    ways, tiles, pois = [], [], []
    n_ways = n_pois = 0
    s = w = 90.0
    n = e = -180.0
    t0 = time.time()

    def flush():
        db.executemany("INSERT OR REPLACE INTO ways VALUES (?, ?, ?)", ways)
        db.executemany("INSERT OR IGNORE INTO way_tiles VALUES (?, ?)", tiles)
        db.executemany("INSERT OR REPLACE INTO pois VALUES (?, ?, ?, ?, ?)", pois)
        ways.clear(), tiles.clear(), pois.clear()

    fp = osmium.FileProcessor(pbf).with_locations() \
        .with_filter(osmium.filter.KeyFilter("highway", "amenity", "shop", "tourism"))
    for obj in fp:
        tags = {t.k: t.v for t in obj.tags}
        if obj.is_way():
            pts = [(nd.lat, nd.lon) for nd in obj.nodes if nd.location.valid()]
            if len(pts) < 2:
                continue
            hw = tags.get("highway")
            if hw and hw not in SKIP and not tags.get("area") == "yes":
                keep = {k: v for k, v in tags.items() if k in ROAD_TAGS}
                geom = array("i")
                for la, lo in pts:
                    geom.append(round(la * 1e7))
                    geom.append(round(lo * 1e7))
                ways.append((obj.id, json.dumps(keep, separators=(",", ":")), geom.tobytes()))
                for t in osm.tiles_of_points(pts):
                    tiles.append((osm.tile_key(t), obj.id))
                n_ways += 1
                for la, lo in pts[:: max(1, len(pts) // 4)]:
                    s, n, w, e = min(s, la), max(n, la), min(w, lo), max(e, lo)
            if osm.poi_kind(tags):
                la = sum(p[0] for p in pts) / len(pts)
                lo = sum(p[1] for p in pts) / len(pts)
                pois.append((f"w{obj.id}", osm.tile_key(osm.tile_of(la, lo)), la, lo,
                             json.dumps({k: v for k, v in tags.items() if k in POI_TAGS}, separators=(",", ":"))))
                n_pois += 1
        elif obj.is_node() and osm.poi_kind(tags):
            la, lo = obj.location.lat, obj.location.lon
            pois.append((f"n{obj.id}", osm.tile_key(osm.tile_of(la, lo)), la, lo,
                         json.dumps({k: v for k, v in tags.items() if k in POI_TAGS}, separators=(",", ":"))))
            n_pois += 1
        if len(ways) + len(pois) >= 20000:
            flush()
            if progress and n_ways % 200000 < 20000:
                progress(f"  {n_ways:,} roads and trails, {n_pois:,} stops ({round(time.time() - t0)} s)")
    flush()
    header = osmium.io.Reader(pbf, osmium.osm.osm_entity_bits.NOTHING).header()
    stamp = header.get("osmosis_replication_timestamp") or header.get("timestamp") or ""
    meta = {"source": os.path.basename(pbf), "osm_date": stamp, "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "bbox": json.dumps([s, w, n, e]), "ways": str(n_ways), "pois": str(n_pois)}
    db.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
    db.execute("CREATE INDEX pois_tile ON pois(tile)")
    db.commit()
    db.close()
    os.replace(tmp, out)
    return {**meta, "seconds": round(time.time() - t0)}
