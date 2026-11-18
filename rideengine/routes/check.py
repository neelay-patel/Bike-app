"""The route check: everything a rider researches before committing to a route, in one report.

    report = check(route, osm.corridor(route), pace=Pace.of(feats), known_cells=cells)

- Surface: km of paved, gravel, rough and singletrack (and how much the map doesn't say), from the
  OpenStreetMap roads the route follows (each point snapped to the nearest road heading the same way).
- Stops: cafés, shops, water, toilets near the route with their km and detour, grouped by village,
  and the longest stretch with nowhere to refuel.
- Warnings: singletrack, busy roads, long dead-straight grid roads, stretches ridden twice.
- Effort: climbs, ascent, and the time it'd take at the rider's own pace on each surface.
- Cue sheet: each change of road with its turn, surface and distance to the next.
- How much of it the rider already knows (grid cells shared with their own rides).

Rule-based and stdlib only. Everything is worked out from the map: report["unknown_km"] says how much
the map leaves open, so the rider knows what to trust.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from ..analysis.climbs import find_climbs
from ..analysis.repeats import cell
from ..model import Ride, Sample, haversine
from . import osm
from .route import Route, bearing

STEP_M = 20               # route resampled this often for matching
SNAP_M = 25               # a road counts when the route passes within this
GRID = 0.002              # ~200 m cells for the road index
TRAIL_PENALTY_M = 8       # prefer the road over a footpath beside it (sidewalks, parallel trails)
MIN_RUN_M = 80            # shorter changes of road are junction noise
GAP_WARN_KM = 35          # longer than this with no food or water on the map gets a warning
STRAIGHT_KM = 4.0         # a straight road longer than this is "a long straight"
TWICE_M = 30
CLASSES = ["paved", "gravel", "rough", "trail", "singletrack", "unknown"]
LABEL = {"paved": "Paved", "gravel": "Gravel", "rough": "Rough", "trail": "Trail", "singletrack": "Singletrack",
         "unknown": "Unknown"}


@dataclass
class Pace:
    """The rider's riding speed (km/h, on the flat) per surface, plus the extra seconds per metre climbed."""
    kmh: dict = field(default_factory=lambda: {"paved": 25.0, "gravel": 21.5, "rough": 17.0, "trail": 15.0,
                                                "singletrack": 12.0, "unknown": 22.0})
    climb_s_per_m: float = 5.0
    source: str = "typical"

    FACTORS = {"paved": 1.0, "gravel": 0.86, "rough": 0.68, "trail": 0.6, "singletrack": 0.48, "unknown": 0.9}

    @staticmethod
    def of(feats: list[dict], today_t: float | None = None) -> "Pace":
        """From the rider's own outdoor rides (last year): flat-equivalent speed with climbing taken
        out, scaled per surface. A first estimate until rides are matched to surfaces too."""
        import time
        now = today_t or time.time()
        speeds = []
        for f in feats:
            if f.get("indoor") or not f.get("km") or not f.get("moving_s") or f["km"] < 15:
                continue
            if now - f["start"] > 365 * 86400:
                continue
            flat_s = f["moving_s"] - (f.get("ascent_m") or 0) * Pace().climb_s_per_m
            if flat_s > 0:
                speeds.append(f["km"] / (flat_s / 3600))
        if len(speeds) < 3:
            return Pace()
        # The rider's mix of road and gravel: call their typical speed "between road and gravel".
        base = statistics.median(speeds) / 0.93
        return Pace(kmh={k: round(base * v, 1) for k, v in Pace.FACTORS.items()}, source="your rides")


# --- matching -------------------------------------------------------------------------------------
class _Index:
    def __init__(self, ways: list[dict]):
        self.ways = ways
        self.grid: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for wi, w in enumerate(ways):
            tags = w["tags"]
            # Sidewalks and crossings are drawn beside the road; the rider is on the road.
            if tags.get("footway") in ("sidewalk", "crossing") or tags.get("path") == "sidewalk":
                continue
            g = w["geom"]
            for si in range(len(g) - 1):
                a, b = g[si], g[si + 1]
                for c in {(int(a[0] // GRID), int(a[1] // GRID)), (int(b[0] // GRID), int(b[1] // GRID))}:
                    self.grid.setdefault(c, []).append((wi, si))

    def near(self, lat: float, lon: float):
        ci, cj = int(lat // GRID), int(lon // GRID)
        seen = set()
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for k in self.grid.get((ci + di, cj + dj), ()):
                    if k not in seen:
                        seen.add(k)
                        yield k


def _seg_dist(lat: float, lon: float, a, b) -> tuple[float, float]:
    """(metres from the point to segment a-b, bearing of the segment)."""
    k = math.cos(math.radians(lat))
    ax, ay = (a[1] - lon) * 111320 * k, (a[0] - lat) * 110540
    bx, by = (b[1] - lon) * 111320 * k, (b[0] - lat) * 110540
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L))
    return math.hypot(ax + t * dx, ay + t * dy), (math.degrees(math.atan2(dx, dy)) + 360) % 360


def _angle(a: float, b: float) -> float:
    """Difference between two headings, ignoring direction (0-90)."""
    d = abs(a - b) % 180
    return min(d, 180 - d)


def match(pts, ways: list[dict]) -> list[int | None]:
    """For each resampled point, the index of the road it's on (or None)."""
    idx = _Index(ways)
    out: list[int | None] = []
    for i, (la, lo, _, _) in enumerate(pts):
        p, q = pts[max(0, i - 2)], pts[min(len(pts) - 1, i + 2)]
        head = bearing(p[0], p[1], q[0], q[1])
        best, bw = None, None
        for wi, si in idx.near(la, lo):
            g = ways[wi]["geom"]
            d, h = _seg_dist(la, lo, g[si], g[si + 1])
            if d > SNAP_M:
                continue
            score = d + 0.25 * _angle(head, h)
            if ways[wi]["tags"].get("highway") in osm.TRAILS:
                score += TRAIL_PENALTY_M
            if best is None or score < best:
                best, bw = score, wi
        out.append(bw)
    # Smooth: a short run on another road between two runs on the same road is a junction blip.
    runs = _runs(out)
    for k in range(1, len(runs) - 1):
        a, (s, e, w), c = runs[k - 1], runs[k], runs[k + 1]
        if a[2] == c[2] and (e - s) * STEP_M < MIN_RUN_M:
            for i in range(s, e):
                out[i] = a[2]
    return out


def _runs(xs) -> list[tuple[int, int, object]]:
    """[(start, end, value)] for each run of equal values (end exclusive)."""
    out, s = [], 0
    for i in range(1, len(xs) + 1):
        if i == len(xs) or xs[i] != xs[s]:
            out.append((s, i, xs[s]))
            s = i
    return out


# --- the report -----------------------------------------------------------------------------------
def _km(m: float) -> float:
    return round(m / 1000, 1)


def _ascent(eles: list[float], hysteresis: float = 3.0) -> tuple[float, float]:
    up = down = 0.0
    ref = eles[0]
    for e in eles[1:]:
        if e - ref >= hysteresis:
            up += e - ref
            ref = e
        elif ref - e >= hysteresis:
            down += ref - e
            ref = e
    return up, down


def _turn(delta: float) -> str:
    a = abs(delta)
    side = "right" if delta > 0 else "left"
    if a < 25:
        return "Continue"
    if a < 60:
        return f"Bear {side}"
    if a < 150:
        return f"Turn {side}"
    return "U-turn"


def _road_key(w: dict | None) -> str:
    if w is None:
        return "?"
    nm = osm.road_name(w["tags"])
    return nm or f"#{w['id']}"


def _road_label(w: dict | None) -> str:
    if w is None:
        return "unmapped way"
    nm = osm.road_name(w["tags"])
    if nm:
        return nm
    hw = w["tags"].get("highway", "")
    return {"track": "track", "path": "trail", "footway": "footpath", "bridleway": "bridleway",
            "cycleway": "bike path", "service": "lane"}.get(hw, "unnamed road")


def check(route: Route, data: dict, pace: Pace | None = None, known_cells: set | None = None,
          places: list[dict] | None = None, chosen: list[tuple[float, float]] = ()) -> dict:
    """`chosen`: stops the rider picked (the café they asked for, stops added in tuning): always listed."""
    pace = pace or Pace()
    pts = route.resample(STEP_M)
    ways = data["ways"]
    on = match(pts, ways)
    total_m = pts[-1][3]

    cls, assumed = [], []
    for wi in on:
        if wi is None:
            cls.append("unknown")
            assumed.append(True)
        else:
            c, a = osm.classify(ways[wi]["tags"])
            cls.append(c)
            assumed.append(a)
    # Each point stands for the STEP_M after it.
    seg_m = [pts[i + 1][3] - pts[i][3] if i + 1 < len(pts) else 0.0 for i in range(len(pts))]
    km = {c: 0.0 for c in CLASSES}
    assumed_m = 0.0
    for c, a, m in zip(cls, assumed, seg_m):
        km[c] += m
        if a and c != "unknown":
            assumed_m += m
    surfaces = [{"class": c, "label": LABEL[c], "km": _km(km[c]), "share": round(km[c] / total_m, 3)}
                for c in CLASSES if km[c] > 0]
    unpaved = km["gravel"] + km["rough"] + km["trail"] + km["singletrack"]
    known = total_m - km["unknown"]

    # Stretches by surface (for the map and the profile), and the warnings that come with them.
    stretches = []
    for s, e, c in _runs(cls):
        stretches.append({"class": c, "from_km": _km(pts[s][3]), "to_km": _km(pts[min(e, len(pts) - 1)][3]),
                          "points": [[round(p[0], 5), round(p[1], 5)] for p in pts[s:e + 1:3]] +
                                    [[round(pts[min(e, len(pts) - 1)][0], 5), round(pts[min(e, len(pts) - 1)][1], 5)]]})
    single, trails = [], []
    for s, e, c in _runs(cls):
        if c in ("singletrack", "trail") and (pts[min(e, len(pts) - 1)][3] - pts[s][3]) >= 100:
            names = [n for n in dict.fromkeys(_road_label(ways[on[i]]) for i in range(s, e) if on[i] is not None)
                     if n not in ("trail", "footpath")]
            (single if c == "singletrack" else trails).append(
                {"from_km": _km(pts[s][3]), "to_km": _km(pts[min(e, len(pts) - 1)][3]),
                 "km": _km(pts[min(e, len(pts) - 1)][3] - pts[s][3]), "name": ", ".join(names)[:60]})
    busy_flags = [on[i] is not None and osm.busy(ways[on[i]]["tags"]) for i in range(len(pts))]
    busy = []
    for s, e, b in _runs(busy_flags):
        if b and (pts[min(e, len(pts) - 1)][3] - pts[s][3]) >= 300:
            names = [_road_label(ways[on[i]]) for i in range(s, e) if on[i] is not None]
            busy.append({"from_km": _km(pts[s][3]), "to_km": _km(pts[min(e, len(pts) - 1)][3]),
                         "km": _km(pts[min(e, len(pts) - 1)][3] - pts[s][3]),
                         "name": max(set(names), key=names.count) if names else ""})

    # Elevation: climbs (same detection as rides), ascent, profile.
    have = [i for i, p in enumerate(pts) if p[2] is not None]
    has_ele = len(have) >= 0.9 * len(pts)
    if has_ele and len(have) < len(pts):
        fill, j = [], 0
        for i, p in enumerate(pts):
            while j < len(have) - 1 and have[j + 1] <= i:
                j += 1
            fill.append((p[0], p[1], pts[have[j]][2], p[3]) if p[2] is None else p)
        pts = fill
    climbs, ascent, descent, profile = [], None, None, []
    if has_ele:
        eles = [p[2] for p in pts]
        ascent, descent = _ascent(eles)
        fake = Ride(start=0, end=len(pts), sport="cycling", indoor=False, totals={}, provenance={}, recordings=[],
                    samples=[Sample(t=float(i), lat=p[0], lon=p[1], ele=p[2]) for i, p in enumerate(pts)])
        for c in find_climbs(fake):
            climbs.append({"km": c["km_into_ride"], "length_m": c["length_m"], "gain_m": c["gain_m"],
                           "grade": c["grade"], "top": list(c["end"])})
        every = max(1, int(100 / STEP_M))
        profile = [[_km(p[3]), round(p[2]), cls[i]] for i, p in enumerate(pts) if i % every == 0]

    # Time at the rider's pace.
    secs = sum(m / (pace.kmh[c] / 3.6) for c, m in zip(cls, seg_m)) + (ascent or 0) * pace.climb_s_per_m

    # Long straights: the same bearing (within 8°) for STRAIGHT_KM or more.
    straights, coarse = [], route.resample(100)
    i = 0
    while i < len(coarse) - 2:
        h0 = bearing(coarse[i][0], coarse[i][1], coarse[i + 1][0], coarse[i + 1][1])
        j = i + 1
        while j < len(coarse) - 1 and _angle(h0, bearing(coarse[j][0], coarse[j][1],
                                                          coarse[j + 1][0], coarse[j + 1][1])) < 8:
            j += 1
        length = coarse[j][3] - coarse[i][3]
        if length >= STRAIGHT_KM * 1000:
            k = min(len(pts) - 1, int(coarse[i][3] / STEP_M) + 3)
            straights.append({"from_km": _km(coarse[i][3]), "to_km": _km(coarse[j][3]), "km": _km(length),
                              "name": _road_label(ways[on[k]]) if on[k] is not None else ""})
            i = j
        else:
            i += 1

    # Stretches ridden twice (out and back): a point within TWICE_M of the route more than 1 km earlier.
    twice_m, seen = 0.0, {}
    for la, lo, _, d in coarse:
        key = (round(la / 0.0005), round(lo / 0.0007))
        hit = False
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for (pl, po, pd) in seen.get((key[0] + di, key[1] + dj), ()):
                    if d - pd > 1000 and haversine(la, lo, pl, po) < TWICE_M:
                        hit = True
        if hit:
            twice_m += 100
        seen.setdefault(key, []).append((la, lo, d))
    if route.is_loop:
        twice_m = max(0.0, twice_m - 200)   # the last few hundred metres back to the start

    # Stops near the route, grouped into places.
    stops = _stops(pts, data["pois"], places)
    supply = sorted({0.0, _km(total_m)} | {s["km"] for s in stops if s["food"] or s["shop"] or s["water"]})
    gaps = [{"from_km": a, "to_km": b, "km": round(b - a, 1)} for a, b in zip(supply, supply[1:])]
    longest_gap = max(gaps, key=lambda g: g["km"]) if gaps else None
    mid = _midway(stops, _km(total_m))
    rest = rest_stops(stops, _km(total_m), secs, gaps, chosen)
    # Villages and towns the route goes through (GeoNames): OpenStreetMap misses many rural shops, so a long
    # gap that passes through a village may not really be one.
    towns = []
    for pl in places or []:
        best = min(coarse, key=lambda p: haversine(pl["lat"], pl["lon"], p[0], p[1]))
        if haversine(pl["lat"], pl["lon"], best[0], best[1]) <= (2000 if pl.get("population", 0) >= 5000 else 1000):
            towns.append({"name": pl["name"], "km": _km(best[3]), "population": pl.get("population", 0)})
    towns.sort(key=lambda t: t["km"])
    for g in gaps:
        g["towns"] = [t for t in towns if g["from_km"] + 1 < t["km"] < g["to_km"] - 1]

    known_share = None
    if known_cells is not None:
        cells = {cell(p[0], p[1]) for p in coarse}
        known_share = round(len(cells & known_cells) / len(cells), 2) if cells else None

    cues = cue_sheet(pts, on, ways, cls, rest)
    out = {
        "name": route.name, "source": route.source, "link": route.link,
        "km": _km(total_m), "loop": route.is_loop,
        "ascent_m": round(ascent) if ascent is not None else None,
        "descent_m": round(descent) if descent is not None else None,
        "surfaces": surfaces,
        "gravel_share": round(unpaved / known, 2) if known > 0 else None,
        "unknown_km": _km(km["unknown"]), "assumed_km": _km(assumed_m),
        "singletrack": single, "trails": trails, "busy": busy, "straights": straights, "twice_km": _km(twice_m),
        "climbs": climbs, "stops": stops, "gaps": gaps, "longest_gap": longest_gap, "midway": mid,
        "rest": rest,
        "towns": towns,
        "time_s": round(secs), "pace": {"kmh": pace.kmh, "source": pace.source},
        "known_share": known_share, "stretches": stretches, "profile": profile, "cues": cues,
        "start": [pts[0][0], pts[0][1]], "end": [pts[-1][0], pts[-1][1]],
        "bbox": [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)],
        "credit": osm.CREDIT, "osm_date": data.get("fetched"),
    }
    out["verdict"] = verdict(out)
    return out


RANK = {"food": 0, "shop": 1, "water": 2, "bike": 3, "toilets": 4, "view": 5}
COFFEE = {"cafe": 0, "bakery": 0, "coffee": 0, "ice_cream": 1, "fast_food": 1, "restaurant": 2, "pub": 2}


def _stops(pts, pois: list[dict], places: list[dict] | None) -> list[dict]:
    """POIs near the route as stops: km along, detour, grouped within 800 m along the route."""
    grid: dict[tuple[int, int], list[int]] = {}
    for i, p in enumerate(pts[::5]):
        grid.setdefault((int(p[0] // 0.005), int(p[1] // 0.005)), []).append(i * 5)
    hits = []
    for poi in pois:
        ci, cj = int(poi["lat"] // 0.005), int(poi["lon"] // 0.005)
        cand = [i for di in (-1, 0, 1) for dj in (-1, 0, 1) for i in grid.get((ci + di, cj + dj), ())]
        if not cand:
            continue
        # The first time the route passes, then refine around it.
        best = min(cand, key=lambda i: haversine(poi["lat"], poi["lon"], pts[i][0], pts[i][1]))
        lo, hi = max(0, best - 5), min(len(pts), best + 6)
        best = min(range(lo, hi), key=lambda i: haversine(poi["lat"], poi["lon"], pts[i][0], pts[i][1]))
        off = haversine(poi["lat"], poi["lon"], pts[best][0], pts[best][1])
        if off > (osm.VIEW_M if poi["kind"] == "view" else osm.POI_M):
            continue
        hits.append({**poi, "km": _km(pts[best][3]), "off_m": round(off)})
    hits.sort(key=lambda h: h["km"])
    groups: list[list[dict]] = []
    for h in hits:
        if groups and h["km"] - groups[-1][0]["km"] <= 0.8:
            groups[-1].append(h)
        else:
            groups.append([h])
    out = []
    for g in groups:
        kinds = {h["kind"] for h in g}
        lat = sum(h["lat"] for h in g) / len(g)
        lon = sum(h["lon"] for h in g) / len(g)
        place = None
        if places:
            near = min(places, key=lambda p: haversine(lat, lon, p["lat"], p["lon"]))
            if haversine(lat, lon, near["lat"], near["lon"]) < 2500:
                place = near["name"]
        items = sorted(g, key=lambda h: (RANK[h["kind"]], COFFEE.get(h["what"], 3), h["off_m"]))
        out.append({"km": g[0]["km"], "lat": round(lat, 5), "lon": round(lon, 5), "place": place,
                    "food": "food" in kinds, "shop": "shop" in kinds, "water": "water" in kinds,
                    "toilets": "toilets" in kinds, "view": kinds == {"view"},
                    "coffee": any(h["what"] in ("cafe", "bakery", "coffee") for h in g),
                    "items": [{"name": h["name"] or h["what"].replace("_", " ").capitalize(), "kind": h["kind"],
                               "what": h["what"], "hours": h["hours"], "off_m": h["off_m"],
                               "lat": h["lat"], "lon": h["lon"]} for h in items[:6]]})
    return out


FILL_KM = 25.0            # other places to eat are listed only where nothing else is within this


def _quality(item: dict) -> float:
    """How good a place is to stop at, lower is better: a local café or bakery, then a chain café, ice
    cream or a local takeaway, a restaurant or pub, other chains, a shop (petrol station, store), water."""
    chain = (item["name"] or "").lower() in osm.CHAINS
    if item["kind"] == "food":
        base = {"cafe": 0.0, "bakery": 0.0, "coffee": 0.0, "ice_cream": 1.0, "fast_food": 1.2,
                "restaurant": 1.6, "pub": 1.6}.get(item["what"], 2.0)
        return base + (1.0 if chain else 0.0) + item["off_m"] / 400
    if item["kind"] == "shop":
        return 2.6 + item["off_m"] / 400
    if item["kind"] == "water":
        return 4.0 + item["off_m"] / 400
    return 9.0


def _hm(s: float) -> str:
    h, m = divmod(round(s / 60 / 15) * 15, 60)    # to the quarter hour
    return f"{h}:{m:02d}" if h else f"{m} min"


def rest_stops(stops: list[dict], total_km: float, secs: float, gaps: list[dict] | None = None,
               chosen: list[tuple[float, float]] = ()) -> list[dict]:
    """A few sensible places to stop, not every café on the way: how many by riding time (none under
    1:30, one halfway up to 4:30, two to 7 h, then one every 3 h), the best place near each (local cafés
    and bakeries first), the rider's own stops (`chosen`), on a short ride a local café about halfway if
    there is one, plus the last food before a long stretch with none, and, where nothing else is
    listed for FILL_KM, whatever there is (the countryside has little). Each: {"km", "name", "what",
    "place", "lat", "lon", "why", "rest": True for a planned stop, "also": [other names there]}."""
    hours = secs / 3600 if secs else total_km / 22
    n = 0 if hours < 1.5 else 1 if hours < 4.5 else 2 if hours < 7 else round(hours / 3)
    supply = [s for s in stops if not s["view"] and (s["food"] or s["shop"] or s["water"])]
    picked: list[dict] = []

    def entry(st: dict, why: str, rest: bool) -> dict:
        items = sorted((i for i in st["items"] if i["kind"] in ("food", "shop", "water")),
                       key=lambda i: _quality({**i, "off_m": i["off_m"]}))
        top = items[0]
        also = [i["name"] for i in items[1:] if i["kind"] in ("food", "shop") and i["name"] != top["name"]][:2]
        return {"km": st["km"], "name": top["name"], "what": top["what"], "kind": top["kind"], "hours": top["hours"],
                "place": st["place"], "lat": top["lat"], "lon": top["lon"], "off_m": top["off_m"], "why": why,
                "rest": rest, "also": also}

    def at(km: float) -> str:
        return _hm(secs * km / total_km) if secs and total_km else ""

    # The rider's own stops first: they chose them.
    for la, lo in chosen:
        hit = [(haversine(la, lo, i["lat"], i["lon"]), st, i) for st in supply for i in st["items"]]
        if hit:
            d, st, item = min(hit, key=lambda h: h[0])
            if d < 150:
                e = entry(st, "your stop", True)
                e.update(name=item["name"], what=item["what"], kind=item["kind"], lat=item["lat"], lon=item["lon"])
                picked.append(e)
    if n == 0 and not picked:       # a short ride: a good café about halfway, if you fancy one
        cafes = [s for s in supply if 0.35 * total_km <= s["km"] <= 0.65 * total_km
                 and min(_quality(i) for i in s["items"]) < 1.0]
        if cafes:
            best = min(cafes, key=lambda s: abs(s["km"] - total_km / 2))
            picked.append(entry(best, "about halfway, if you want a coffee", True))
    window = max(8.0, 0.15 * total_km)
    for k in range(1, n + 1):
        target = total_km * k / (n + 1)
        cands = [s for s in supply if abs(s["km"] - target) <= window and (s["food"] or s["shop"])]
        if not cands or any(abs(p["km"] - target) <= window for p in picked if p["why"] == "your stop"):
            continue
        best = min(cands, key=lambda s: min(_quality(i) for i in s["items"]) + 1.5 * abs(s["km"] - target) / window)
        if any(abs(best["km"] - p["km"]) < 5 for p in picked):
            continue
        why = "about halfway" if n == 1 else ["first stop", "second stop", "third stop", "fourth stop"][min(k, 4) - 1]
        when = at(best["km"])
        picked.append(entry(best, f"{why}, after about {when}" if when else why, True))
    # The last food before a long stretch with none.
    for g in gaps or []:
        if g["km"] < GAP_WARN_KM or g["from_km"] < 1:
            continue
        before = [s for s in supply if abs(s["km"] - g["from_km"]) < 0.5]
        if not before:
            continue
        near = [p for p in picked if abs(p["km"] - before[0]["km"]) < 3]
        if near:
            near[0]["why"] += f"; the last food or water for {g['km']:.0f} km"
        else:
            picked.append(entry(before[0], f"last food or water for {g['km']:.0f} km", True))
    # Elsewhere, only where nothing else is listed for FILL_KM.
    picked.sort(key=lambda p: p["km"])
    marks = [0.0] + [p["km"] for p in picked]
    for st in supply:
        if all(abs(st["km"] - m) >= FILL_KM for m in marks) and total_km - st["km"] >= FILL_KM / 2:
            picked.append(entry(st, "on the way", False))
            marks.append(st["km"])
    picked.sort(key=lambda p: p["km"])
    return picked


def _midway(stops: list[dict], total_km: float) -> dict | None:
    """The best coffee stop near halfway (35-65% of the way, closest to half, cafés first)."""
    cands = [s for s in stops if (s["food"] or s["shop"]) and 0.35 * total_km <= s["km"] <= 0.65 * total_km]
    if not cands:
        return None
    s = min(cands, key=lambda s: (not s["coffee"], not s["food"], abs(s["km"] - total_km / 2)))
    return {"km": s["km"], "place": s["place"], "name": s["items"][0]["name"]}


def cue_sheet(pts, on, ways, cls, stops) -> list[dict]:
    """A cue at each change of road (ignoring junction blips), with the turn, the new road's surface,
    and the km to the next cue. `stops`: the rest stops (rest_stops), added in order."""
    keys = [_road_key(ways[w]) if w is not None else "?" for w in on]
    runs = [r for r in _runs(keys) if r[2] != "?"]
    merged: list[list] = []
    for s, e, k in runs:
        if merged and (merged[-1][2] == k or (e - s) * STEP_M < MIN_RUN_M):
            merged[-1][1] = e
        else:
            merged.append([s, e, k])
    cues = []
    for n, (s, e, k) in enumerate(merged):
        w = ways[on[s]] if on[s] is not None else None
        seg = [c for c in cls[s:e]]
        main = max(set(seg), key=seg.count) if seg else "unknown"
        if n == 0:
            text, turn = f"Start on {_road_label(w)}", "start"
        else:
            a, b = pts[max(0, s - 3)], pts[s]
            c = pts[min(len(pts) - 1, s + 3)]
            delta = (bearing(b[0], b[1], c[0], c[1]) - bearing(a[0], a[1], b[0], b[1]) + 540) % 360 - 180
            turn = _turn(delta)
            text = f"{turn} onto {_road_label(w)}"
        cues.append({"km": _km(pts[s][3]), "turn": turn.split()[-1].lower() if turn != "Continue" else "straight",
                     "text": text, "surface": main, "for_km": _km(pts[min(e, len(pts) - 1)][3] - pts[s][3]),
                     "lat": round(pts[s][0], 5), "lon": round(pts[s][1], 5)})
    for st in stops:          # the rest stops (rest_stops), not every café in town
        cues.append({"km": st["km"], "turn": "stop", "text": f"{st['name']}{' · ' + st['place'] if st['place'] else ''}",
                     "surface": None, "for_km": None, "lat": st["lat"], "lon": st["lon"]})
    cues.sort(key=lambda c: (c["km"], c["turn"] == "stop"))
    cues.append({"km": _km(pts[-1][3]), "turn": "finish", "text": "Finish", "surface": None, "for_km": None,
                 "lat": round(pts[-1][0], 5), "lon": round(pts[-1][1], 5)})
    return cues


def hms(s: float) -> str:
    h, m = divmod(round(s / 60), 60)
    return f"{h}:{m:02d}"


def verdict(r: dict) -> list[dict]:
    """The lines that answer "should I ride this?", most important first. tone: good, warn, info."""
    out = []
    share = r["gravel_share"]
    if share is not None:
        pct = round(share * 100)
        unk = f" ({r['unknown_km']} km the map doesn't say)" if r["unknown_km"] >= 1 else ""
        out.append({"tone": "good" if 0.4 <= share <= 0.8 else "info",
                    "text": f"{pct}% off pavement, {100 - pct}% paved{unk}."})
    st = round(sum(s["km"] for s in r["singletrack"]), 1)
    tr = round(sum(s["km"] for s in r["trails"]), 1)
    if st >= 0.5:
        first = r["singletrack"][0]
        out.append({"tone": "warn", "text": f"{st} km of singletrack: first at km {first['from_km']}"
                    f"{' (' + first['name'] + ')' if first['name'] else ''}."})
    if tr >= 0.5:
        first = max(r["trails"], key=lambda t: t["km"])
        out.append({"tone": "warn" if tr >= 5 else "info",
                    "text": f"{tr} km on trails the map doesn't describe (wide or narrow): longest "
                            f"{first['km']} km from km {first['from_km']}{' (' + first['name'] + ')' if first['name'] else ''}."})
    if st < 0.5 and tr < 0.5:
        out.append({"tone": "good", "text": "No singletrack."})
    planned = [p for p in r.get("rest", []) if p["rest"] and not p["why"].startswith("last")]
    if planned:
        names = "; ".join(f"{p['name']}{', ' + p['place'] if p['place'] else ''} at km {p['km']:.0f}" for p in planned)
        out.append({"tone": "good", "text": ("Rest stop: " if len(planned) == 1 else "Rest stops: ") + names + "."})
    g = r["longest_gap"]
    if g and g["km"] >= GAP_WARN_KM:
        passes = sorted(g.get("towns") or [], key=lambda t: -t["population"])[:2]
        if passes:
            names = " and ".join(f"{t['name']} (km {t['km']})" for t in sorted(passes, key=lambda t: t["km"]))
            tail = f" It goes through {names}: the map may be missing shops there, so check before you go."
        else:
            tail = " Carry enough."
        out.append({"tone": "warn", "text": f"No food or water on the map from km {g['from_km']} to km {g['to_km']}"
                    f" ({g['km']} km).{tail}"})
    elif not r["stops"]:
        out.append({"tone": "warn", "text": "No cafés, shops or water on the map near this route."})
    if r["busy"]:
        tot = round(sum(b["km"] for b in r["busy"]), 1)
        names = ", ".join(dict.fromkeys(b["name"] for b in r["busy"] if b["name"]))[:60]
        out.append({"tone": "warn" if tot >= 3 else "info", "text": f"{tot} km on busy roads{': ' + names if names else ''}."})
    if r["straights"]:
        s = max(r["straights"], key=lambda s: s["km"])
        out.append({"tone": "info", "text": f"Longest straight: {s['km']} km{' on ' + s['name'] if s['name'] else ''}"
                    f" from km {s['from_km']}."})
    if r["twice_km"] >= 2:
        out.append({"tone": "info", "text": f"{r['twice_km']} km ridden twice (out and back)."})
    if r["climbs"]:
        big = max(r["climbs"], key=lambda c: c["gain_m"])
        out.append({"tone": "info", "text": f"{len(r['climbs'])} climbs; biggest {big['gain_m']} m over "
                    f"{big['length_m'] / 1000:.1f} km ({big['grade']}%) at km {big['km']}."})
    if r["known_share"] is not None:
        k = round(r["known_share"] * 100)
        out.append({"tone": "info", "text": "All new roads to you." if k == 0 else
                    f"You've ridden {k}% of these roads before."})
    return out
