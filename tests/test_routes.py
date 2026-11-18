"""Route check and course export, on a synthetic map (no network)."""
import struct

from rideengine.importers.fit import SEMI, decode
from rideengine.routes import check, osm
from rideengine.routes.course import crc16, course_points, fit_course, gpx_course
from rideengine.routes.route import Route, read_route

GPX = b"""<?xml version="1.0"?>
<gpx version="1.1" creator="http://ridewithgps.com/" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata><name>Uxbridge Gravel</name><link href="https://ridewithgps.com/routes/1"/></metadata>
  <wpt lat="44.1" lon="-79.1"><name>Coffee</name></wpt>
  <trk><name>Uxbridge Gravel</name><trkseg>
    <trkpt lat="44.10000" lon="-79.10000"><ele>270</ele></trkpt>
    <trkpt lat="44.10000" lon="-79.10000"><ele>270</ele></trkpt>
    <trkpt lat="44.10500" lon="-79.10000"><ele>275</ele></trkpt>
    <trkpt lat="44.11000" lon="-79.10000"><ele>280</ele></trkpt>
  </trkseg></trk>
</gpx>"""


def test_read_route_from_ride_with_gps():
    r = read_route(GPX)
    assert r.name == "Uxbridge Gravel" and r.source == "ridewithgps"
    assert len(r.points) == 3          # the repeated point is dropped
    assert r.waypoints[0]["name"] == "Coffee"
    assert 1.0 < r.km < 1.3 and not r.is_loop
    rte = GPX.replace(b"trkpt", b"rtept").replace(b"<trk>", b"<rte>").replace(b"</trk>", b"</rte>") \
        .replace(b"<trkseg>", b"").replace(b"</trkseg>", b"")
    assert len(read_route(rte).points) == 3


def test_surface_classes():
    c = lambda **t: osm.classify(t)[0]
    assert c(highway="tertiary") == "paved"
    assert c(highway="unclassified", surface="gravel") == "gravel"
    assert c(highway="unclassified") == "unknown"                 # the map doesn't say: no guessing
    assert c(highway="track") == "gravel"
    assert c(highway="track", tracktype="grade5") == "rough"
    assert c(highway="path", surface="fine_gravel") == "gravel"     # rail trail
    assert c(highway="path", name="Uxbridge Rail Trail") == "gravel"
    assert c(highway="path", surface="dirt") == "singletrack"
    assert c(highway="path", **{"mtb:scale": "2"}) == "singletrack"
    assert c(highway="path") == "trail"                             # could be either
    assert c(highway="residential", surface="asphalt", smoothness="horrible") == "rough"
    assert osm.busy({"highway": "primary"}) and osm.busy({"highway": "secondary", "maxspeed": "80"})
    assert not osm.busy({"highway": "secondary", "maxspeed": "50"})
    assert osm.poi_kind({"amenity": "cafe"}) == "food" and osm.poi_kind({"shop": "convenience"}) == "shop"
    assert osm.poi_kind({"amenity": "drinking_water"}) == "water" and osm.poi_kind({"amenity": "bench"}) is None


def _line(lat0, lon0, lat1, lon1, n=20):
    return [(lat0 + (lat1 - lat0) * i / n, lon0 + (lon1 - lon0) * i / n) for i in range(n + 1)]


def synthetic():
    """10 km north on a paved road, 8 km east on a gravel concession, 2 km on a dirt trail, with a café
    at km 9.9 and a climb on the gravel."""
    a = _line(44.0, -79.0, 44.09, -79.0)              # ~10 km north
    b = _line(44.09, -79.0, 44.09, -78.9)             # ~8 km east
    c = _line(44.09, -78.9, 44.108, -78.9, 4)         # ~2 km north
    ways = [{"id": 1, "tags": {"highway": "secondary", "name": "Regional Road 1", "maxspeed": "80"}, "geom": a},
            {"id": 2, "tags": {"highway": "unclassified", "name": "Concession 6", "surface": "gravel"}, "geom": b},
            {"id": 3, "tags": {"highway": "path", "name": "Ridge Trail", "surface": "dirt"}, "geom": c}]
    pois = [{"id": "n1", "lat": 44.0895, "lon": -79.0005, "kind": "food", "name": "Corner Café", "what": "cafe",
             "hours": "Mo-Su 07:00-16:00"},
            {"id": "n2", "lat": 44.0, "lon": -79.003, "kind": "water", "name": "", "what": "drinking_water",
             "hours": ""}]
    pts = []
    for seg in (a, b[1:], c[1:]):
        pts += seg
    ele = []
    for i, p in enumerate(pts):
        ele.append(250 + (max(0, i - 25) * 4 if 25 <= i <= 35 else (40 if i > 35 else 0)))
    route = Route(name="Test loop", points=[(la, lo, e) for (la, lo), e in zip(pts, ele)])
    return route, {"ways": ways, "pois": pois, "fetched": "2026-11-17T00:00:00Z"}


def test_check_reads_surfaces_stops_and_warnings():
    route, data = synthetic()
    r = check.check(route, data, known_cells=set())
    km = {s["class"]: s["km"] for s in r["surfaces"]}
    assert 9.5 <= km["paved"] <= 10.5 and 7.5 <= km["gravel"] <= 8.5 and 1.5 <= km["singletrack"] <= 2.5
    assert r["unknown_km"] == 0
    assert r["singletrack"] and r["singletrack"][0]["name"] == "Ridge Trail"
    assert r["busy"] and r["busy"][0]["name"] == "Regional Road 1"
    assert r["midway"] and r["midway"]["name"] == "Corner Café"
    assert r["climbs"] and r["ascent_m"] >= 35
    assert r["known_share"] == 0
    texts = " ".join(v["text"] for v in r["verdict"])
    assert "singletrack" in texts and "Corner Café" in texts and "busy roads" in texts
    cues = [c["text"] for c in r["cues"]]
    assert cues[0] == "Start on Regional Road 1"
    assert any(t.startswith("Turn right onto Concession 6") for t in cues)
    assert any(t.startswith("Turn left onto Ridge Trail") for t in cues)
    assert cues[-1] == "Finish"
    assert r["time_s"] > 0 and r["stretches"][0]["class"] == "paved"


def test_long_gap_without_food_is_flagged():
    route, data = synthetic()
    data["pois"] = []
    r = check.check(route, data)
    assert r["longest_gap"]["km"] == r["km"]
    data2 = dict(data)
    route2 = Route(name="Long", points=[(44.0 + i * 0.0045, -79.0, 250) for i in range(100)])  # ~50 km straight
    data2["ways"] = [{"id": 9, "tags": {"highway": "tertiary", "name": "Line 7"},
                      "geom": [(p[0], p[1]) for p in route2.points]}]
    r2 = check.check(route2, data2)
    texts = " ".join(v["text"] for v in r2["verdict"])
    assert "No food or water on the map" in texts and "Carry enough" in texts and "Longest straight" in texts
    # Through a village the map shows no shops for: say so, rather than "nowhere".
    r3 = check.check(route2, data2, places=[{"name": "Cannington", "lat": 44.2, "lon": -79.0005, "population": 1900}])
    gap = next(v["text"] for v in r3["verdict"] if "No food" in v["text"])
    assert "Cannington (km 22" in gap and "check before you go" in gap


def test_fit_course_decodes_with_course_points():
    route, data = synthetic()
    r = check.check(route, data)
    buf = fit_course(route, r)
    assert buf[8:12] == b".FIT"
    assert struct.unpack("<H", buf[12:14])[0] == crc16(buf[:12])
    assert crc16(buf) == 0                        # a file with its CRC appended checks to zero
    msgs = decode(buf)
    kinds = [m for m, _ in msgs]
    assert msgs[0][0] == 0 and msgs[0][1][0] == 6                     # file_id: course
    assert 31 in kinds and 19 in kinds and kinds.count(20) == len(route.points)
    cps = [v for m, v in msgs if m == 32]
    names = [v[6].rstrip(b"\0").decode() for v in cps]
    assert "Corner Café" in names and "Singletrack" in names
    assert any(v[5] == 1 for v in cps)                                 # a summit
    recs = [v for m, v in msgs if m == 20]
    assert abs(recs[-1][0] * SEMI - route.points[-1][0]) < 1e-5
    assert recs[-1][5] / 100 / 1000 == r["km"] or abs(recs[-1][5] / 100000 - r["km"]) < 0.2
    assert [v[1] for v in cps] == sorted(v[1] for v in cps)


def test_gpx_course_round_trips():
    route, data = synthetic()
    r = check.check(route, data)
    again = read_route(gpx_course(route, r))
    assert len(again.points) == len(route.points) and again.name == "Test loop"
    assert {w["name"] for w in again.waypoints} >= {"Corner Café"}
    assert len(course_points(r)) == len(again.waypoints)
