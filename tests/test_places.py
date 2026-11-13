"""Towns on the route, from a tiny made-up gazetteer (the real GeoNames file isn't needed)."""
import zipfile

from rideengine.merge import build_rides
from rideengine.places import places_on_route
from test_engine import LAT0, LON0, line_ride

KM = 1 / 111.195  # degrees of latitude per km


def gazetteer(tmp_path, rows):
    path = tmp_path / "cities500.zip"
    lines = []
    for i, (name, lat, lon, pop) in enumerate(rows):
        col = [str(i), name, name, "", str(lat), str(lon), "P", "PPL", "CA", "", "", "", "", "", str(pop),
               "", "", "America/Toronto", "2026-01-01"]
        lines.append("\t".join(col))
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("cities500.txt", "\n".join(lines) + "\n")
    return str(path)


def test_stops_beat_size_and_home_is_skipped(tmp_path):
    # 60 min north at 25 km/h with a 20-minute stop from minute 20 (about 8.3 km in).
    ride = build_rides([line_ride(80, stop_at=(20, 40))])[0]
    path = gazetteer(tmp_path, [
        ("Hometown", LAT0, LON0, 90000),                  # the start
        ("Cafeville", LAT0 + 8.3 * KM, LON0 + 0.005, 0),   # where the stop was, ~400 m off the road
        ("Bigtown", LAT0 + 20 * KM, LON0, 50000),          # passed, no stop
        ("Faraway", LAT0 + 10 * KM, LON0 + 0.2, 99999),    # 16 km off the route
    ])
    found = places_on_route(ride, path)
    assert [p["name"] for p in found] == ["Cafeville", "Bigtown"]
    assert found[0]["stop_min"] == 20


def test_start_town_only_as_a_fallback(tmp_path):
    ride = build_rides([line_ride(20)])[0]
    path = gazetteer(tmp_path, [("Hometown", LAT0, LON0, 90000)])
    assert [p["name"] for p in places_on_route(ride, path)] == ["Hometown"]


def test_no_gazetteer_no_places(tmp_path):
    ride = build_rides([line_ride(20)])[0]
    assert places_on_route(ride, str(tmp_path / "missing.zip")) == []
