"""Router and tuning on a synthetic grid of roads (no map files, no network)."""
import pytest

from rideengine.model import haversine
from rideengine.routes import tune
from rideengine.routes.route import Route
from rideengine.routes.router import Graph, Prefs

LAT0, LON0, DLAT, DLON = 44.0, -79.0, 0.009, 0.0125     # ~1 km grid


class Flat:
    def height(self, lat, lon):
        return 250.0


def node(i, j):
    return (round(LAT0 + i * DLAT, 6), round(LON0 + j * DLON, 6))


def grid(n=9, gravel_rows=(), busy_cols=(), extra=()):
    """n x n junctions; rows (east-west) and columns (north-south) as separate ways between junctions."""
    ways, wid = [], 1
    for i in range(n):
        for j in range(n - 1):
            tags = {"highway": "unclassified", "name": f"Line {i}",
                    "surface": "gravel" if i in gravel_rows else "asphalt"}
            ways.append({"id": wid, "tags": tags, "geom": [node(i, j), node(i, j + 1)]})
            wid += 1
    for j in range(n):
        for i in range(n - 1):
            tags = {"highway": "secondary" if j in busy_cols else "unclassified", "name": f"Sideroad {j}",
                    "surface": "asphalt"}
            if j in busy_cols:
                tags["maxspeed"] = "80"
            ways.append({"id": wid, "tags": tags, "geom": [node(i, j), node(i + 1, j)]})
            wid += 1
    return ways + list(extra)


def ring(i0, j0, i1, j1, step=4):
    """A loop around the rectangle of junctions (i0, j0)-(i1, j1), as a dense line."""
    corners = [node(i0, j0), node(i0, j1), node(i1, j1), node(i1, j0), node(i0, j0)]
    pts = []
    for a, b in zip(corners, corners[1:]):
        for k in range(step * max(abs(round((b[0] - a[0]) / DLAT)), abs(round((b[1] - a[1]) / DLON)))):
            n = step * max(abs(round((b[0] - a[0]) / DLAT)), abs(round((b[1] - a[1]) / DLON)))
            pts.append((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n, 250.0))
    pts.append((corners[-1][0], corners[-1][1], 250.0))
    return Route(name="Grid loop", points=pts)


def test_router_prefers_gravel_avoids_busy_and_respects_one_way():
    g = Graph(grid(gravel_rows=(2,), busy_cols=(4,)))
    # From (0,0) to (2,8): along gravel Line 2 rather than tarmac Line 0, same length either way.
    p = g.leg(node(0, 0), node(2, 8))
    assert abs(p.m - 10_000 * 1.0) < 600
    names = {g.ways[w]["tags"]["name"] for w in p.ways}
    assert "Line 2" in names and "Line 0" not in names
    # Busy Sideroad 4 is avoided when there's another way north.
    p2 = g.leg(node(0, 4), node(6, 4))
    assert sum(1 for w in p2.ways if g.ways[w]["tags"]["name"] == "Sideroad 4") < len(p2.ways) / 2
    # A one-way street isn't ridden the wrong way; a motorway isn't ridden at all.
    one = grid(n=3)
    for w in one:
        if w["tags"]["name"] == "Line 0":
            w["tags"]["oneway"] = "yes"          # west to east only
        if w["tags"]["name"] == "Line 1":
            w["tags"]["highway"] = "motorway"
    g3 = Graph(one)
    back = g3.leg(node(0, 2), node(0, 0))
    assert back.m > 3500                          # round by Line 2, not straight back along Line 0
    assert all(g3.ways[w]["tags"]["highway"] != "motorway" for w in back.ways)
    assert g3.leg(node(0, 0), node(0, 2)).m < 2200
    assert g.snap(LAT0 + 0.2, LON0 + 0.2) is None    # nowhere near a road


def test_move_start_on_and_off_a_loop():
    g = Graph(grid())
    r = ring(1, 1, 5, 5)
    t = tune.move_start(r, g, *node(5, 3), label="The Bakery", heights=Flat())
    assert t.route.is_loop and abs(t.km_after - t.km_before) < 0.2
    assert haversine(*t.route.points[0][:2], *node(5, 3)) < 30 and "The Bakery" in t.change
    off = tune.move_start(r, g, *node(7, 3), label="Parking", heights=Flat())
    assert 3.5 < off.km_after - off.km_before < 4.5        # 2 km there and back
    assert haversine(*off.route.points[0][:2], *node(7, 3)) < 30 and "there and back" in off.change


def test_add_stop_detours_and_comes_back():
    g = Graph(grid())
    r = ring(1, 1, 5, 5)
    cafe = node(3, 6)           # 1 km east of the loop's east side
    t = tune.add_stop(r, g, *cafe, name="Canter Coffee", heights=Flat())
    assert min(haversine(*p[:2], *cafe) for p in t.route.points) < 30
    assert 1.5 < t.km_after - t.km_before < 2.6 and "Canter Coffee" in t.change
    with pytest.raises(tune.TuneError, match="already on the route"):
        tune.add_stop(r, g, *node(3, 5), name="On it", heights=Flat())


def test_shorter_and_longer():
    g = Graph(grid(n=11))
    r = ring(1, 1, 9, 9)        # ~32 km
    short = tune.change_length(r, g, -10, heights=Flat())
    assert 7 <= short.km_before - short.km_after <= 13 and "shorter" in short.change
    assert short.route.is_loop
    longer = tune.change_length(r, g, 4, heights=Flat())
    assert 2 <= longer.km_after - longer.km_before <= 7 and "longer" in longer.change
    # A stop the rider added stays: the shortcut can't skip it.
    stop = node(9, 5)
    kept = tune.change_length(r, g, -10, heights=Flat(), keep=[stop])
    assert min(haversine(*p[:2], *stop) for p in kept.route.points) < 50
    with pytest.raises(tune.TuneError):
        tune.change_length(r, g, -0.5, heights=Flat())


def test_prefs_for_a_road_rider():
    assert Prefs.for_mix(0.1).surface["paved"] < Prefs.for_mix(0.1).surface["gravel"]
    assert Prefs.for_mix(0.6).surface["gravel"] < Prefs.for_mix(0.6).surface["paved"]
