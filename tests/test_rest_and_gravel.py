"""Rest stops (a few sensible ones, not every café) and where the gravel is."""
from rideengine.routes import check, gravelmap as gm
from rideengine.routes import osm


def stop(km, name, what="cafe", kind="food", lat=44.0, off_m=50):
    item = {"name": name, "kind": kind, "what": what, "hours": "", "off_m": off_m, "lat": lat + km / 100, "lon": -79.0}
    return {"km": km, "lat": item["lat"], "lon": -79.0, "place": "Town", "food": kind == "food", "shop": kind == "shop",
            "water": kind == "water", "toilets": False, "view": False, "coffee": what == "cafe", "items": [item]}


def test_a_city_ride_gets_one_stop_not_forty():
    # A café every km for 60 km (the city), 2:30 of riding: one stop about halfway, the local café over the chain.
    stops = [stop(k, "Tim Hortons" if k % 2 else f"Café {k}", what="cafe") for k in range(0, 61)]
    stops[30]["items"].append({**stops[30]["items"][0], "name": "Tim Hortons"})
    rest = check.rest_stops(stops, 60.0, 2.5 * 3600, gaps=[])
    assert len(rest) == 1 and rest[0]["rest"] and rest[0]["why"].startswith("about halfway")
    assert 22 <= rest[0]["km"] <= 38 and not rest[0]["name"].startswith("Tim")


def test_the_countryside_gets_what_there_is():
    # 110 km, 5 h: food at km 20 and km 45, then nothing for 65 km.
    stops = [stop(20, "Corner Store", what="convenience", kind="shop"), stop(45, "Bakery on Main", what="bakery")]
    gaps = [{"from_km": 0, "to_km": 20, "km": 20}, {"from_km": 20, "to_km": 45, "km": 25},
            {"from_km": 45, "to_km": 110, "km": 65}]
    rest = check.rest_stops(stops, 110.0, 5 * 3600, gaps=gaps)
    whys = {r["name"]: r["why"] for r in rest}
    assert whys == {"Bakery on Main": "first stop, after about 2:00; the last food or water for 65 km"}
    # Without the bakery, the store is the last food before 90 km with none.
    alone = check.rest_stops(stops[:1], 110.0, 5 * 3600, gaps=[{"from_km": 20, "to_km": 110, "km": 90}])
    assert [(r["name"], r["why"]) for r in alone] == [("Corner Store", "last food or water for 90 km")]


def test_your_own_stop_is_always_listed_and_short_rides_get_a_cafe_if_good():
    stops = [stop(k, f"Café {k}") for k in (3, 9, 15)]
    chosen = [(stops[0]["items"][0]["lat"], -79.0)]
    rest = check.rest_stops(stops, 20.0, 50 * 60, gaps=[], chosen=chosen)
    assert rest[0]["name"] == "Café 3" and rest[0]["why"] == "your stop"
    short = check.rest_stops(stops, 20.0, 50 * 60, gaps=[])
    assert [r["name"] for r in short] == ["Café 9"]           # under 1:30: a coffee halfway, if you want one
    chains = [stop(9, "Tim Hortons")]
    assert check.rest_stops(chains, 20.0, 50 * 60, gaps=[]) == []


def tile_grid(fn):
    """A grid over 43.0-44.6 N, 80.6-78.4 W: fn(lat, lon) -> {class: metres} per tile."""
    g = {}
    for i in range(int(43.0 / osm.TILE_LAT), int(44.6 / osm.TILE_LAT)):
        for j in range(int(-80.6 / osm.TILE_LON), int(-78.4 / osm.TILE_LON)):
            v = fn((i + .5) * osm.TILE_LAT, (j + .5) * osm.TILE_LON)
            if v:
                g[(i, j)] = v
    return g


def test_where_the_gravel_is():
    # Paved city in the south; gravel north of 44.0; a lake (no roads) east of -79.0 below 43.8.
    def fn(lat, lon):
        if lon > -79.0 and lat < 43.8:
            return None
        return {"paved": 10000, "gravel": 12000 if lat > 44.0 else 100}
    g = tile_grid(fn)
    home = (43.70, -79.40)
    assert gm.poor(gm.share(g, *home, 13), 0.5) and not gm.poor(gm.share(g, 44.2, -79.4, 13), 0.5)
    assert gm.share({}, *home, 13) is None and not gm.poor(None, 0.5)
    places = [{"name": "Northtown", "lat": 44.25, "lon": -79.40, "population": 5000},
              {"name": "Hamlet", "lat": 44.30, "lon": -79.60, "population": 40},           # too small to name
              {"name": "Across the Lake", "lat": 43.75, "lon": -78.6, "population": 9000},  # gravel? no; and a lake
              {"name": "Rode Here", "lat": 44.20, "lon": -80.2, "population": 0}]
    out = gm.starts(g, places, home, (60, 70), 0.5, ridden=[(44.21, -80.2)])
    assert [o["name"] for o in out] == ["Northtown", "Rode Here"] and out[1]["ridden"]
    assert out[0]["direction"] == "north"


def test_home_follows_a_move():
    from rideengine.analysis import repeats
    year = 365 * 86400
    def ride(t, lat, lon):
        return {"ride_id": str(t), "start": t, "indoor": False, "first": [lat, lon], "cells": [[0, 0]]}
    london = [ride(i * 86400, 51.5, -0.1) for i in range(40)]                      # years ago, lots of rides
    toronto = [ride(3 * year + i * 86400, 43.7, -79.37) for i in range(10)]       # this year, fewer
    assert repeats.home_point(london + toronto) == (43.7, -79.37)
    assert repeats.home_point(london + toronto[:3]) == (51.5, -0.1)                # too few recent: all count
