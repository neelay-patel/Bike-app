"""Tuning a route: start somewhere else, add a stop, make it shorter or longer, while keeping what the rider
liked about it (the surface mix, no singletrack, not riding the same road twice).

Each operation returns a Tuned: the new Route (heights from elevation tiles for consistency), a sentence
saying what changed, and how the length moved. The router draws the new roads; the route check then
reports on the result as on any route.

    g = graph_for(route)
    t = move_start(route, g, lat, lon, label="The Tin Cup")
    t = add_stop(route, g, lat, lon, name="Canter Coffee")
    t = change_length(route, g, -10)      # about 10 km shorter
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..model import haversine
from . import osm
from .elevation import Heights
from .route import Route
from .router import Graph, Path, Prefs

STEP_M = 250                # candidate points along the route this far apart
NEAR_M = 150                # a new start this close to the route just moves where the loop begins
TWICE_M = 30                # new road this close to the rest of the route counts as riding it twice


class TuneError(ValueError):
    """Something we can't do to this route (shown to the rider as it is)."""


@dataclass
class Tuned:
    route: Route
    change: str
    km_before: float
    km_after: float


def graph_for(route: Route, pad_km: float = 8.0, prefs: Prefs | None = None, path: str = osm.LOCAL_DB) -> Graph:
    """Roads around the route (with room for detours), from our own map."""
    lats = [p[0] for p in route.points]
    lons = [p[1] for p in route.points]
    dla = pad_km / 110.54
    dlo = pad_km / (111.32 * math.cos(math.radians(sum(lats) / len(lats))))
    return Graph.around((min(lats) - dla, min(lons) - dlo, max(lats) + dla, max(lons) + dlo), path=path, prefs=prefs)


# --- helpers ------------------------------------------------------------------------------------
def _cum(points) -> list[float]:
    out, d = [0.0], 0.0
    for a, b in zip(points, points[1:]):
        d += haversine(a[0], a[1], b[0], b[1])
        out.append(d)
    return out


def _samples(cum: list[float], lo: float = 0.0, hi: float | None = None, step: float = STEP_M) -> list[int]:
    """Point indices every `step` metres along the route between lo and hi."""
    hi = cum[-1] if hi is None else hi
    out, nxt = [], max(0.0, lo)
    for i, d in enumerate(cum):
        if d >= nxt and d <= hi:
            out.append(i)
            nxt = d + step
    return out


def _nearest(points, lat: float, lon: float) -> tuple[int, float]:
    best = min(range(len(points)), key=lambda i: (points[i][0] - lat) ** 2 + ((points[i][1] - lon) * 0.72) ** 2)
    return best, haversine(lat, lon, points[best][0], points[best][1])


def _finish(route: Route, pts2d: list[tuple[float, float]], heights: Heights | None, change: str) -> Tuned:
    """A new Route from a 2-D line: heights from the elevation tiles, the same name and source."""
    clean = [pts2d[0]]
    for p in pts2d[1:]:
        if haversine(*clean[-1], *p) > 0.5:
            clean.append(p)
    h = heights or Heights()
    pts = [(la, lo, round(h.height(la, lo), 1)) for la, lo in clean]
    new = Route(name=route.name, points=pts, source=route.source, link=route.link)
    return Tuned(new, change, round(route.km, 1), round(new.km, 1))


def _overlap(path_pts, others, skip_near: list[tuple[float, float]] = ()) -> float:
    """Share of the new road (metres) within TWICE_M of the given points (the rest of the route), not
    counting the first and last 150 m (where the new road joins the old)."""
    grid: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for p in others:
        grid.setdefault((int(p[0] // 0.0005), int(p[1] // 0.0007)), []).append(p)
    cum = _cum(path_pts)
    total, near = cum[-1] or 1.0, 0.0
    for i in range(len(path_pts) - 1):
        if cum[i] < 150 or cum[-1] - cum[i] < 150:
            continue
        la, lo = path_pts[i]
        ci, cj = int(la // 0.0005), int(lo // 0.0007)
        hit = any(haversine(la, lo, q[0], q[1]) < TWICE_M
                  for di in (-1, 0, 1) for dj in (-1, 0, 1) for q in grid.get((ci + di, cj + dj), ()))
        if hit:
            near += cum[i + 1] - cum[i]
    return near / total


def _self_overlap(a_pts, b_pts) -> float:
    """How much of an out-and-back two legs make (share of leg b along leg a)."""
    return _overlap(b_pts, a_pts)


def _quality(path: Path) -> float:
    """Cost per metre: how much this rider likes the new road (lower is better; 0.8 is all gravel)."""
    return path.cost / path.m if path.m else 1.0


def _surface_km(g: Graph, path: Path) -> dict:
    out: dict[str, float] = {}
    for wi, a, b in zip(path.ways, path.points, path.points[1:]):
        c = osm.classify(g.ways[wi]["tags"])[0]
        out[c] = out.get(c, 0.0) + haversine(*a, *b)
    return out


def _desc_surface(g: Graph, path: Path) -> str:
    s = _surface_km(g, path)
    if not s:
        return ""
    off = sum(v for k, v in s.items() if k in ("gravel", "rough", "trail", "singletrack"))
    pct = round(100 * off / max(1.0, sum(s.values())))
    return "all paved" if pct == 0 else "all off pavement" if pct == 100 else f"{pct}% off pavement"


# --- operations ---------------------------------------------------------------------------------
def move_start(route: Route, g: Graph, lat: float, lon: float, label: str | None = None,
               heights: Heights | None = None) -> Tuned:
    """Start (and, on a loop, finish) at a new point. On the route: the loop just begins there. Off it:
    the shortest way to join the route, ridden there and back."""
    pts = [(p[0], p[1]) for p in route.points]
    where = label or "the new start"
    i, d = _nearest(pts, lat, lon)
    if route.is_loop:
        if d <= NEAR_M:
            new = pts[i:-1] + pts[:i + 1]
            return _finish(route, new, heights, f"Starts at {where}, km {round(_cum(pts)[i] / 1000, 1)} of the old loop.")
        cum = _cum(pts)
        cands = sorted(_samples(cum), key=lambda k: haversine(lat, lon, *pts[k]))[:8]
        best = None
        for k in cands:
            there = g.leg((lat, lon), pts[k])
            back = g.leg(pts[k], (lat, lon))
            if there and back and (best is None or there.cost + back.cost < best[0]):
                best = (there.cost + back.cost, k, there, back)
        if best is None:
            raise TuneError(f"Couldn't find roads from {where} to the route.")
        _, k, there, back = best
        new = there.points + pts[k + 1:-1] + pts[:k + 1] + back.points[1:]
        km = round((there.m + back.m) / 1000, 1)
        return _finish(route, new, heights, f"Starts at {where}: {km} km there and back to join the loop "
                                           f"({_desc_surface(g, there)}).")
    # Point to point: join the route at the nearest place and ride the rest.
    cum = _cum(pts)
    cands = sorted(_samples(cum), key=lambda k: haversine(lat, lon, *pts[k]))[:8]
    best = None
    for k in cands:
        leg = g.leg((lat, lon), pts[k])
        if leg and (best is None or leg.cost - cum[k] * 0.5 < best[0]):
            best = (leg.cost - cum[k] * 0.5, k, leg)
    if best is None:
        raise TuneError(f"Couldn't find roads from {where} to the route.")
    _, k, leg = best
    new = leg.points + pts[k + 1:]
    return _finish(route, new, heights, f"Starts at {where} and joins the route at its km {round(cum[k] / 1000, 1)}.")


def add_stop(route: Route, g: Graph, lat: float, lon: float, name: str, heights: Heights | None = None,
             reach_m: float = 4000) -> Tuned:
    """Go via a stop (a café, a shop, water): the detour that adds the least, leaving and rejoining the
    route within reach_m either side of where it passes closest."""
    pts = [(p[0], p[1]) for p in route.points]
    cum = _cum(pts)
    i, d = _nearest(pts, lat, lon)
    if d <= 60:
        raise TuneError(f"{name} is already on the route, at km {round(cum[i] / 1000, 1)}.")
    befores = _samples(cum, cum[i] - reach_m, cum[i])[-12:] or [max(0, i - 1)]
    afters = _samples(cum, cum[i], cum[i] + reach_m)[:12] or [min(len(pts) - 1, i + 1)]
    ins = {a: g.leg(pts[a], (lat, lon)) for a in befores}
    outs = {b: g.leg((lat, lon), pts[b]) for b in afters}
    best = None
    for a, la in ins.items():
        for b, lb in outs.items():
            if not la or not lb or b <= a:
                continue
            added = la.m + lb.m - (cum[b] - cum[a])
            score = la.cost + lb.cost - (cum[b] - cum[a]) * 0.8 + 0.5 * added * _self_overlap(la.points, lb.points)
            if best is None or score < best[0]:
                best = (score, a, b, la, lb, added)
    if best is None:
        raise TuneError(f"Couldn't find roads to {name} from the route.")
    _, a, b, la, lb, added = best
    new = pts[:a] + la.points + lb.points[1:] + pts[b + 1:]
    sign = "+" if added >= 0 else "−"
    return _finish(route, new, heights, f"Goes via {name} at km {round(cum[a] / 1000 + la.m / 1000, 1)}: "
                                       f"{sign}{abs(round(added / 1000, 1))} km.")


def change_length(route: Route, g: Graph, delta_km: float, heights: Heights | None = None,
                  keep: list[tuple[float, float]] = ()) -> Tuned:
    """About delta_km shorter (negative) or longer (positive). Shorter: a shortcut between two points on
    the route. Longer: a way round between two points, out to the side. Prefers the roads this rider likes
    and avoids riding the same road twice. `keep`: points that must stay on the route (stops)."""
    if abs(delta_km) < 1:
        raise TuneError("Change it by at least 1 km.")
    return (_shorter if delta_km < 0 else _longer)(route, g, abs(delta_km) * 1000, heights, keep)


def _keeps_ok(pts, cum, a: int, b: int, keep) -> bool:
    for la, lo in keep:
        k, d = _nearest(pts, la, lo)
        if d < 200 and a < k < b:
            return False
    return True


def _shorter(route: Route, g: Graph, cut_m: float, heights, keep) -> Tuned:
    pts = [(p[0], p[1]) for p in route.points]
    cum = _cum(pts)
    if cum[-1] - cut_m < 5000:
        raise TuneError("That would leave almost nothing of the route.")
    idx = _samples(cum, step=500)
    cands = []
    for x, a in enumerate(idx):
        for b in idx[x + 1:]:
            span = cum[b] - cum[a]
            if span < cut_m * 1.05:
                continue
            if span > cut_m * 3 + 15000:
                break
            crow = haversine(*pts[a], *pts[b])
            guess = span - 1.3 * crow             # what a shortcut of ~1.3x the crow line would save
            if abs(guess - cut_m) <= 0.5 * cut_m and _keeps_ok(pts, cum, a, b, keep):
                cands.append((abs(guess - cut_m), a, b))
    cands.sort()
    rest = pts
    best = None
    for _, a, b in cands[:80]:
        leg = g.leg(pts[a], pts[b])
        if leg is None:
            continue
        saved = (cum[b] - cum[a]) - leg.m
        if saved <= 0:
            continue
        twice = _overlap(leg.points, rest[:a] + rest[b:])
        # Getting the length right matters most; then the roads (gravel for a gravel rider); then not
        # riding the same road twice.
        score = 2.5 * abs(saved - cut_m) / cut_m + (_quality(leg) - 0.8) + 2 * twice
        if best is None or score < best[0]:
            best = (score, a, b, leg, saved)
    if best is None:
        raise TuneError(f"Couldn't find a shortcut that saves about {round(cut_m / 1000)} km.")
    _, a, b, leg, saved = best
    new = pts[:a] + leg.points + pts[b + 1:]
    return _finish(route, new, heights,
                   f"{round(saved / 1000, 1)} km shorter: a shortcut from km {round(cum[a] / 1000, 1)} to km "
                   f"{round(cum[b] / 1000, 1)} ({_desc_surface(g, leg)}).")


def _longer(route: Route, g: Graph, add_m: float, heights, keep) -> Tuned:
    pts = [(p[0], p[1]) for p in route.points]
    cum = _cum(pts)
    lat0 = sum(p[0] for p in pts) / len(pts)
    kx = 111320 * math.cos(math.radians(lat0))
    cands = []
    for span in (3000, 6000, 10000):
        for a in _samples(cum, 1000, cum[-1] - span - 1000, step=2000):
            b = next((k for k in range(a, len(pts)) if cum[k] - cum[a] >= span), None)
            if b is None or not _keeps_ok(pts, cum, a, b, keep):
                continue
            m = next(k for k in range(a, b + 1) if cum[k] - cum[a] >= span / 2)
            # Out to the side of the chord a-b, far enough that a -> v -> b adds about add_m.
            ax, ay = pts[a][1] * kx, pts[a][0] * 110540
            bx, by = pts[b][1] * kx, pts[b][0] * 110540
            chord = math.hypot(bx - ax, by - ay) or 1.0
            nx, ny = -(by - ay) / chord, (bx - ax) / chord
            need = (span + add_m) / 2.6          # each half of the way round, allowing for wiggle
            off = math.sqrt(max(need ** 2 - (chord / 2) ** 2, 0.0))
            mx, my = pts[m][1] * kx, pts[m][0] * 110540
            for side in (1, -1):
                vx, vy = mx + side * nx * off, my + side * ny * off
                cands.append((a, b, (vy / 110540, vx / kx)))
    rest_cache = {}
    best = None
    for a, b, v in cands[:120]:
        la = g.leg(pts[a], v)
        lb = g.leg(v, pts[b]) if la else None
        if not la or not lb:
            continue
        added = la.m + lb.m - (cum[b] - cum[a])
        if added <= 0.3 * add_m:
            continue
        key = (a, b)
        if key not in rest_cache:
            rest_cache[key] = pts[:a] + pts[b:]
        twice = _overlap(la.points + lb.points[1:], rest_cache[key]) + _self_overlap(la.points, lb.points)
        q = (la.cost + lb.cost) / (la.m + lb.m)
        score = 2.5 * abs(added - add_m) / add_m + (q - 0.8) + 2 * twice
        if best is None or score < best[0]:
            best = (score, a, b, la, lb, added)
    if best is None:
        raise TuneError(f"Couldn't find a way round that adds about {round(add_m / 1000)} km.")
    _, a, b, la, lb, added = best
    detour = Path(la.points + lb.points[1:], la.ways + lb.ways, la.m + lb.m, la.cost + lb.cost)
    new = pts[:a] + detour.points + pts[b + 1:]
    return _finish(route, new, heights,
                   f"{round(added / 1000, 1)} km longer: a way round from km {round(cum[a] / 1000, 1)} to km "
                   f"{round(cum[b] / 1000, 1)} ({_desc_surface(g, detour)}).")
