"""Loops from a description: reading the request, and generating loops on a synthetic grid of roads."""
from rideengine.model import haversine
from rideengine.routes import generate as gen
from rideengine.routes.request import Ask, read
from rideengine.routes.router import Graph
from test_tune import Flat, grid, node

UXBRIDGE = {"name": "Uxbridge", "lat": 44.10012, "lon": -79.11628, "population": 21176}


def fake_find(text):
    out = []
    if "uxbridge" in text.lower():
        out.append(UXBRIDGE)
    if "halfway" in text.lower():
        out.append({"name": "Halfway", "lat": 45.4, "lon": -77.6, "population": 0})
    return out


def test_reading_a_request():
    a = read("60-70km gravel loop near Uxbridge, cafe halfway", find=fake_find)
    assert a.km == (60, 70) and a.surface == "gravel" and a.gravel == (0.5, 0.7) and a.stop == "midway"
    assert a.start["name"] == "Uxbridge" and a.missing == []     # "Halfway" the village isn't the start
    assert a.tags == ["LOOP", "60–70 KM", "GRAVEL 50–70%", "FROM UXBRIDGE", "CAFÉ HALFWAY"]
    b = read("flat road ride, about 80 km, coffee stop", find=fake_find)
    assert b.surface == "road" and b.hills == "flat" and b.stop == "any" and 72 <= b.km[0] < b.km[1] <= 88
    assert b.missing == ["start"]
    c = read("30 miles of 40-60% gravel from home", home={"name": "home", "lat": 1.0, "lon": 2.0}, find=fake_find)
    assert c.km == (44, 52) and c.gravel == (0.4, 0.6) and c.start["name"] == "home"
    d = read("something hilly", find=fake_find)
    assert d.missing == ["start", "km", "surface"] and d.hills == "hilly"
    again = Ask.from_dict(a.to_dict())
    assert again.km == (60, 70) and again.tags == a.tags


def test_gravel_loops_with_a_cafe_halfway():
    # 25 x 25 km of roads; every other east-west line is gravel; one busy north-south road.
    ways = grid(n=26, gravel_rows=tuple(range(0, 26, 2)), busy_cols=(16,))
    g = Graph(ways, gen.prefs_for(Ask(surface="gravel")))
    start = node(12, 4)
    cafe = node(12, 16)          # ~12 km east of the start, just across the busy road
    pois = [{"id": "n1", "lat": cafe[0], "lon": cafe[1], "kind": "food", "name": "Canter Coffee", "what": "cafe",
             "hours": ""}]
    ask = Ask(km=(40, 50), surface="gravel", gravel=(0.5, 0.7), stop="midway",
              start={"name": "Goodwood", "lat": start[0], "lon": start[1]}).refresh()
    opts = gen.loops(ask, g, pois, places=[{"name": "Coffeeville", "lat": cafe[0], "lon": cafe[1]}], heights=Flat())
    assert len(opts) >= 2
    best = opts[0]
    assert 38 <= best.km <= 52
    assert best.stop and best.stop["name"] == "Canter Coffee" and 0.35 <= best.stop["km"] / best.km <= 0.65
    assert min(haversine(*p, *cafe) for p in best.path.points) < 50
    assert best.off_share >= 0.4 and best.twice_share < 0.3
    assert haversine(*best.path.points[0], *start) < 50 and haversine(*best.path.points[-1], *start) < 50
    assert "Canter Coffee" in best.route.name and best.why[0].startswith("Canter Coffee at km")
    # The options aren't the same loop three times.
    assert gen._shared(opts[0].path.points, opts[1].path.points) < 0.55


def test_loops_without_a_stop_go_in_different_directions():
    ways = grid(n=26, gravel_rows=tuple(range(0, 26, 2)))
    g = Graph(ways, gen.prefs_for(Ask(surface="gravel")))
    s = node(12, 12)
    ask = Ask(km=(25, 30), surface="gravel", start={"name": "Mid", "lat": s[0], "lon": s[1]}).refresh()
    opts = gen.loops(ask, g, [], heights=Flat())
    assert len(opts) == 3 and all(22 <= o.km <= 34 for o in opts)


PORT_PERRY = {"name": "Port Perry", "lat": 44.10676, "lon": -78.94441, "population": 9553}


def find2(text):
    low = text.lower()
    return [p for p, k in ((UXBRIDGE, "uxbridge"), (PORT_PERRY, "port perry")) if k in low]


def test_reading_the_shape_of_a_ride():
    a = read("gravel from Uxbridge to Port Perry", find=find2)
    assert a.shape == "oneway" and a.start["name"] == "Uxbridge" and a.end["name"] == "Port Perry" and a.missing == []
    assert a.tags[0] == "ONE WAY" and "TO PORT PERRY" in a.tags
    b = read("out and back to Port Perry from Uxbridge, road", find=find2)
    assert b.shape == "out_back" and b.start["name"] == "Uxbridge" and b.end["name"] == "Port Perry"
    assert b.surface == "road" and b.missing == []
    c = read("Uxbridge to Port Perry and back a different way, gravel", find=find2)
    assert c.shape == "loop" and c.via["name"] == "Port Perry" and c.end is None and c.missing == []
    d = read("40 km gravel there and back", find=find2)
    assert d.shape == "out_back" and d.missing == ["start"]
    e = read("gravel ride to Port Perry", find=find2)          # where from? (a lone "to" is the destination)
    assert e.shape == "oneway" and e.end["name"] == "Port Perry" and e.missing == ["start"]
    f = read("a gravel loop to Port Perry from Uxbridge", find=find2)
    assert f.shape == "loop" and f.via["name"] == "Port Perry"


def test_one_way_bends_out_to_make_the_distance():
    ways = grid(n=26, gravel_rows=tuple(range(0, 26, 2)))
    g = Graph(ways, gen.prefs_for(Ask(surface="gravel")))
    a, b = node(12, 2), node(12, 14)          # 12 km apart
    base = dict(surface="gravel", gravel=(0.5, 0.7), shape="oneway", start={"name": "A", "lat": a[0], "lon": a[1]},
                end={"name": "B", "lat": b[0], "lon": b[1]})
    direct = gen.routes(Ask(**base).refresh(), g, [], heights=Flat())
    assert direct and 11 <= direct[0].km <= 15
    longer = gen.routes(Ask(km=(25, 30), **base).refresh(), g, [], heights=Flat())
    best = longer[0]
    assert 23 <= best.km <= 32 and best.route.name.startswith("A to B")
    assert haversine(*best.path.points[0], *a) < 50 and haversine(*best.path.points[-1], *b) < 50


def test_there_and_back():
    ways = grid(n=26, gravel_rows=tuple(range(0, 26, 2)))
    g = Graph(ways, gen.prefs_for(Ask(surface="gravel")))
    s, t = node(12, 2), node(12, 12)
    cafe = node(12, 12)
    pois = [{"id": "n1", "lat": cafe[0], "lon": cafe[1], "kind": "food", "name": "Canter Coffee", "what": "cafe", "hours": ""}]
    ask = Ask(surface="gravel", gravel=(0.5, 0.7), shape="out_back", stop="midway",
              start={"name": "A", "lat": s[0], "lon": s[1]}, end={"name": "Ville", "lat": t[0], "lon": t[1]}).refresh()
    opts = gen.routes(ask, g, pois, heights=Flat())
    best = opts[0]
    assert 18 <= best.km <= 26 and best.route.name == "A to Ville and back"
    assert best.stop["name"] == "Canter Coffee" and "turns round at Canter Coffee" in best.why[0]
    assert haversine(*best.path.points[0], *best.path.points[-1]) < 50
    # Only a distance: it picks the turn itself.
    far = gen.routes(Ask(km=(18, 22), surface="gravel", shape="out_back", start={"name": "A", "lat": s[0], "lon": s[1]}).refresh(),
                     g, [], heights=Flat())
    assert far and all(16 <= o.km <= 24 for o in far)


def test_addresses_and_one_way_words():
    home = {"name": "home", "lat": 1.0, "lon": 2.0}
    a = read("One-way from home to 48 Sample Cres in Markham.  Road ride.", home=home, find=find2)
    assert a.shape == "oneway" and a.start["name"] == "home" and a.end is None and a.surface == "road"
    assert a.guess == {"end": "48 Sample Cres, Markham"} and a.missing == ["end"]
    b = read("from 4321 Concession Rd 7, Uxbridge to Port Perry, gravel", find=find2)
    assert b.guess == {"start": "4321 Concession Rd 7, Uxbridge"} and b.end["name"] == "Port Perry" and b.missing == ["start"]
    c = read("one way to Port Perry, road", find=find2)
    assert c.shape == "oneway" and c.missing == ["start"]
    assert read("to 152 St. Clair Ave, Port Perry", find=find2).guess == {"end": "152 St. Clair Ave, Port Perry"}
    d = read("60 to 70 km road loop from home", home=home, find=find2)       # "70 km road" isn't an address
    assert d.guess == {} and d.km == (60, 70) and d.missing == []
    e = read("gravel to the Port Perry bakery from Uxbridge", find=find2)
    assert e.start["name"] == "Uxbridge" and e.guess == {"end": "Port Perry bakery"}
