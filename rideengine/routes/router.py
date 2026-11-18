"""A bike router on our own map (data/osm/map.sqlite3), for tuning routes: new starts, detours to a stop,
shortcuts and longer ways round. Standard library only.

The cost of a road is its length times how much this rider wants to be on it (Prefs): gravel is
cheaper than tarmac for a gravel rider, busy roads cost much more, singletrack a great deal more, and
roads a bike can't use (motorways, private, steps, sidewalks) aren't in the graph at all. One-way streets
are respected unless bikes are exempt.

    g = Graph.around(bbox)                  # roads in (south, west, north, east)
    path = g.route([(lat, lon), (lat, lon), ...])   # via each point in turn
    path.points, path.m, path.ways          # the line, metres, the way under each segment
"""
from __future__ import annotations

import heapq
import json
import math
import sqlite3
from array import array
from dataclasses import dataclass, field

from ..model import haversine
from . import osm

NO_BIKES = {"motorway", "motorway_link", "steps", "bus_guideway", "raceway", "corridor", "elevator", "escalator",
            "busway", "via_ferrata"}
NO_ACCESS = {"no", "private", "customers", "delivery", "agricultural", "forestry", "military", "discouraged"}
BIKE_OK = {"yes", "designated", "permissive", "official"}
SNAP_M = 250          # a point further than this from any road can't be routed from


@dataclass
class Prefs:
    """How much the rider wants each surface, as a multiplier on distance (lower = preferred)."""
    surface: dict = field(default_factory=lambda: {"paved": 1.0, "gravel": 0.8, "rough": 1.15, "trail": 1.8,
                                                   "singletrack": 5.0, "unknown": 0.95})
    busy: float = 3.0
    service: float = 1.6       # driveways, parking aisles
    footway: float = 2.5       # paths where bikes aren't clearly welcome

    @staticmethod
    def for_mix(gravel_share: float | None) -> "Prefs":
        """A road rider (little gravel) prefers tarmac; a gravel rider prefers gravel."""
        p = Prefs()
        if gravel_share is not None and gravel_share < 0.25:
            p.surface.update(paved=0.9, gravel=1.1, rough=1.5)
        return p


def _cost_factor(tags: dict, prefs: Prefs) -> float | None:
    """Multiplier on length, or None when bikes can't use the way."""
    hw = tags.get("highway", "")
    bike = tags.get("bicycle", "")
    if hw in NO_BIKES or bike in ("no", "use_sidepath"):
        return None
    if tags.get("access") in NO_ACCESS and bike not in BIKE_OK:
        return None
    if tags.get("footway") in ("sidewalk", "crossing") or tags.get("path") == "sidewalk":
        return None
    cls, _ = osm.classify(tags)
    f = prefs.surface.get(cls, 1.0)
    if osm.busy(tags):
        f *= prefs.busy
    if hw == "service" and tags.get("service") in ("driveway", "parking_aisle", "drive-through", "alley"):
        f *= prefs.service
    if hw in ("footway", "pedestrian") and bike not in BIKE_OK:
        f *= prefs.footway
    if bike == "dismount":
        f *= 3
    return f


def _oneway(tags: dict) -> int:
    """1: only along the way's direction, -1: only against it, 0: both (for bikes)."""
    if tags.get("oneway:bicycle") == "no" or (tags.get("cycleway") or "").startswith("opposite"):
        return 0
    ow = tags.get("oneway", "")
    if ow in ("yes", "1", "true") or (tags.get("junction") in ("roundabout", "circular") and ow != "no"):
        return 1
    if ow == "-1":
        return -1
    return 0


@dataclass
class Path:
    points: list[tuple[float, float]]
    ways: list[int]            # index into Graph.ways for each segment (len(points) - 1)
    m: float
    cost: float


class Graph:
    def __init__(self, ways: list[dict], prefs: Prefs | None = None):
        self.prefs = prefs or Prefs()
        self.ways = ways
        # Junctions: points shared by two or more ways (or used twice), and every way's ends.
        count: dict[tuple[int, int], int] = {}
        keyed = []
        for w in ways:
            ks = [(round(la * 1e7), round(lo * 1e7)) for la, lo in w["geom"]]
            keyed.append(ks)
            for k in ks:
                count[k] = count.get(k, 0) + 1
        self.node_of: dict[tuple[int, int], int] = {}
        self.coord: list[tuple[float, float]] = []
        self.adj: list[list[tuple[int, int, bool]]] = []    # node -> [(other node, edge, forward)]
        self.edges: list[tuple] = []                        # (u, v, metres, cost, geom, way index, oneway)
        self.seg_grid: dict[tuple[int, int], list[tuple[int, int]]] = {}   # cell -> [(edge, segment)]

        def node(k):
            n = self.node_of.get(k)
            if n is None:
                n = self.node_of[k] = len(self.coord)
                self.coord.append((k[0] / 1e7, k[1] / 1e7))
                self.adj.append([])
            return n

        for wi, (w, ks) in enumerate(zip(ways, keyed)):
            f = _cost_factor(w["tags"], self.prefs)
            if f is None or len(ks) < 2:
                continue
            ow = _oneway(w["tags"])
            start = 0
            for i in range(1, len(ks)):
                if i == len(ks) - 1 or count[ks[i]] > 1:
                    geom = [w["geom"][j] for j in range(start, i + 1)]
                    m = sum(haversine(*geom[j], *geom[j + 1]) for j in range(len(geom) - 1))
                    if m > 0:
                        u, v = node(ks[start]), node(ks[i])
                        e = len(self.edges)
                        self.edges.append((u, v, m, m * f, geom, wi, ow))
                        if ow >= 0:
                            self.adj[u].append((v, e, True))
                        if ow <= 0:
                            self.adj[v].append((u, e, False))
                        for j in range(len(geom) - 1):
                            for c in {_cell(*geom[j]), _cell(*geom[j + 1])}:
                                self.seg_grid.setdefault(c, []).append((e, j))
                    start = i
        self.min_factor = min([e[3] / e[2] for e in self.edges] or [1.0])

    # --- loading -------------------------------------------------------------------------------
    @staticmethod
    def around(bbox, path: str = osm.LOCAL_DB, prefs: Prefs | None = None) -> "Graph":
        s, w, n, e = bbox
        i0, i1 = math.floor(s / osm.TILE_LAT), math.floor(n / osm.TILE_LAT)
        j0, j1 = math.floor(w / osm.TILE_LON), math.floor(e / osm.TILE_LON)
        keys = [osm.tile_key((i, j)) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        ways, seen = [], set()
        try:
            for k in range(0, len(keys), 500):
                chunk = keys[k:k + 500]
                marks = ",".join("?" * len(chunk))
                for wid, tags, geom in db.execute(
                        f"SELECT id, tags, geom FROM ways WHERE id IN "
                        f"(SELECT DISTINCT id FROM way_tiles WHERE tile IN ({marks}))", chunk):
                    if wid in seen:
                        continue
                    seen.add(wid)
                    g = array("i")
                    g.frombytes(geom)
                    ways.append({"id": wid, "tags": json.loads(tags),
                                 "geom": [(g[i] / 1e7, g[i + 1] / 1e7) for i in range(0, len(g), 2)]})
        finally:
            db.close()
        return Graph(ways, prefs)

    # --- snapping ------------------------------------------------------------------------------
    def snap(self, lat: float, lon: float, within: float = SNAP_M):
        """The nearest point on a routable road: (edge, segment, fraction, metres away), or None."""
        best = None
        ci, cj = _cell(lat, lon)
        reach = max(1, int(within / 200) + 1)
        for di in range(-reach, reach + 1):
            for dj in range(-reach, reach + 1):
                for e, j in self.seg_grid.get((ci + di, cj + dj), ()):
                    geom = self.edges[e][4]
                    d, t = _project(lat, lon, geom[j], geom[j + 1])
                    if d <= within and (best is None or d < best[3]):
                        best = (e, j, t, d)
        return best

    def _split(self, snap) -> tuple[list[tuple[float, float]], list[tuple[float, float]], float, float]:
        """Geometry from the edge's start to the snapped point, and from there to its end, with metres."""
        e, j, t, _ = snap
        geom = self.edges[e][4]
        a, b = geom[j], geom[j + 1]
        p = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        head = geom[:j + 1] + [p]
        tail = [p] + geom[j + 1:]
        return head, tail, _length(head), _length(tail)

    # --- routing -------------------------------------------------------------------------------
    def leg(self, a: tuple[float, float], b: tuple[float, float]) -> Path | None:
        """Cheapest path from a to b (each snapped to the nearest road), or None."""
        sa, sb = self.snap(*a), self.snap(*b)
        if sa is None or sb is None:
            return None
        ea, eb = self.edges[sa[0]], self.edges[sb[0]]
        a_head, a_tail, a_hm, a_tm = self._split(sa)
        b_head, b_tail, b_hm, b_tm = self._split(sb)
        fa, fb = ea[3] / ea[2], eb[3] / eb[2]
        # Virtual start (-1) and goal (-2) on their edges, honouring one-way.
        starts = []   # (node, cost, metres, geom from a to node, way index)
        if ea[6] >= 0:
            starts.append((ea[1], a_tm * fa, a_tm, a_tail, ea[5]))
        if ea[6] <= 0:
            starts.append((ea[0], a_hm * fa, a_hm, list(reversed(a_head)), ea[5]))
        goals = {}    # node -> (cost, metres, geom from node to b, way index)
        if eb[6] >= 0:
            goals[eb[0]] = (b_hm * fb, b_hm, b_head, eb[5])
        if eb[6] <= 0:
            goals[eb[1]] = (b_tm * fb, b_tm, list(reversed(b_tail)), eb[5])
        best_direct = None
        if sa[0] == sb[0]:
            # Both on the same edge: straight along it if the direction is allowed.
            ahead = (sa[1], sa[2]) <= (sb[1], sb[2])
            if (ahead and ea[6] >= 0) or (not ahead and ea[6] <= 0):
                geom = ea[4]
                pa = a_tail[0]
                pb = b_tail[0]
                if ahead:
                    mid = geom[sa[1] + 1:sb[1] + 1]
                else:
                    mid = list(reversed(geom[sb[1] + 1:sa[1] + 1]))
                line = [pa] + mid + [pb]
                m = _length(line)
                best_direct = Path(line, [ea[5]] * (len(line) - 1), m, m * fa)

        goal_xy = b
        h = lambda n: haversine(*self.coord[n], *goal_xy) * self.min_factor
        dist: dict[int, float] = {}
        prev: dict[int, tuple] = {}
        heap = []
        for n, c, m, geom, wi in starts:
            if c < dist.get(n, math.inf):
                dist[n] = c
                prev[n] = ("start", geom, wi)
                heapq.heappush(heap, (c + h(n), c, n))
        best_goal = None
        while heap:
            f, c, n = heapq.heappop(heap)
            if c > dist.get(n, math.inf):
                continue
            if best_goal is not None and f >= best_goal[0]:
                break
            if n in goals:
                total = c + goals[n][0]
                if best_goal is None or total < best_goal[0]:
                    best_goal = (total, n)
            for v, e, fwd in self.adj[n]:
                nc = c + self.edges[e][3]
                if nc < dist.get(v, math.inf):
                    dist[v] = nc
                    prev[v] = (n, e, fwd)
                    heapq.heappush(heap, (nc + h(v), nc, v))
        if best_goal is None:
            return best_direct
        total, n = best_goal
        if best_direct is not None and best_direct.cost <= total:
            return best_direct
        # Walk back.
        pieces = []
        g = goals[n]
        pieces.append((g[2], g[3]))
        cur = n
        while True:
            p = prev[cur]
            if p[0] == "start":
                pieces.append((p[1], p[2]))
                break
            u, e, fwd = p
            geom = self.edges[e][4] if fwd else list(reversed(self.edges[e][4]))
            pieces.append((geom, self.edges[e][5]))
            cur = u
        pieces.reverse()
        pts: list[tuple[float, float]] = []
        ways: list[int] = []
        for geom, wi in pieces:
            for p in geom:
                if pts and haversine(*pts[-1], *p) < 0.05:
                    continue      # joins between pieces, and zero-length pieces at a junction
                if pts:
                    ways.append(wi)
                pts.append(p)
        m = _length(pts)
        return Path(pts, ways, m, total)

    def route(self, via: list[tuple[float, float]]) -> Path | None:
        """Through each point in turn."""
        pts, ways, m, cost = [], [], 0.0, 0.0
        for a, b in zip(via, via[1:]):
            leg = self.leg(a, b)
            if leg is None:
                return None
            if pts:
                leg_pts, leg_ways = leg.points[1:], leg.ways
            else:
                leg_pts, leg_ways = leg.points, leg.ways
            pts += leg_pts
            ways += leg_ways
            m += leg.m
            cost += leg.cost
        return Path(pts, ways, m, cost)


def _cell(lat: float, lon: float) -> tuple[int, int]:
    return int(lat // 0.002), int(lon // 0.0027)


def _length(pts) -> float:
    return sum(haversine(*pts[i], *pts[i + 1]) for i in range(len(pts) - 1))


def _project(lat: float, lon: float, a, b) -> tuple[float, float]:
    k = math.cos(math.radians(lat))
    ax, ay = (a[1] - lon) * 111320 * k, (a[0] - lat) * 110540
    bx, by = (b[1] - lon) * 111320 * k, (b[0] - lat) * 110540
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L))
    return math.hypot(ax + t * dx, ay + t * dy), t
