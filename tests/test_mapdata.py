"""Our own map: built from a (tiny, hand-written) OpenStreetMap file, read back by the route check."""
import pytest

pytest.importorskip("osmium")

from backend.mapdata import build  # noqa: E402
from rideengine.routes import check, osm  # noqa: E402
from rideengine.routes.route import Route  # noqa: E402

OSM = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="test">
  {nodes}
  <node id="900" lat="44.0450" lon="-79.0004"><tag k="amenity" v="cafe"/><tag k="name" v="Corner Café"/>
    <tag k="opening_hours" v="Mo-Su 07:00-16:00"/></node>
  <node id="901" lat="44.0450" lon="-79.0300"><tag k="amenity" v="bench"/></node>
  <node id="902" lat="44.0451" lon="-79.0001"><tag k="highway" v="stop"/></node>
  <way id="1"><nd ref="1"/><nd ref="2"/><nd ref="3"/>
    <tag k="highway" v="unclassified"/><tag k="name" v="Concession 6"/><tag k="surface" v="gravel"/>
    <tag k="note" v="not kept"/></way>
  <way id="2"><nd ref="3"/><nd ref="4"/><tag k="highway" v="path"/><tag k="surface" v="dirt"/></way>
  <way id="3"><nd ref="1"/><nd ref="4"/><tag k="highway" v="proposed"/></way>
</osm>
"""
POINTS = {1: (44.0, -79.0), 2: (44.045, -79.0), 3: (44.09, -79.0), 4: (44.10, -79.0)}


def test_build_and_read_local_map(tmp_path):
    nodes = "\n  ".join(f'<node id="{i}" lat="{la}" lon="{lo}"/>' for i, (la, lo) in POINTS.items())
    src = tmp_path / "tiny.osm"
    src.write_text(OSM.format(nodes=nodes))
    out = str(tmp_path / "map.sqlite3")
    info = build(str(src), out, progress=None)
    assert info["ways"] == "2" and info["pois"] == "1"      # proposed road, bench and stop sign left out
    route = Route(name="Up the concession", points=[(44.0 + i * 0.001, -79.0, 250.0) for i in range(101)])
    data = osm.local(route, out)
    assert data["map"] == "local" and {w["id"] for w in data["ways"]} == {1, 2}
    road = next(w for w in data["ways"] if w["id"] == 1)
    assert road["tags"] == {"highway": "unclassified", "name": "Concession 6", "surface": "gravel"}
    assert road["geom"][1] == pytest.approx((44.045, -79.0), abs=1e-6)
    assert data["pois"][0]["name"] == "Corner Café" and data["pois"][0]["kind"] == "food"
    r = check.check(route, data)
    assert r["surfaces"][0]["class"] == "gravel" and r["stops"][0]["items"][0]["name"] == "Corner Café"
    # A route outside the map's area isn't answered from it (Overpass then).
    far = Route(name="London", points=[(51.47, -0.07, 10.0), (51.48, -0.07, 10.0)])
    assert osm.local(far, out) is None
    assert osm.local(route, str(tmp_path / "missing.sqlite3")) is None
