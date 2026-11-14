"""Repeated routes (home loop) and repeated climbs timed like segments. Synthetic rides only;
places=[] so names don't depend on GeoNames being downloaded."""
from datetime import timezone

from rideengine.analysis import records, repeats
from rideengine.model import Ride, Sample

T0 = 1_780_000_000.0
LAT0, LON0 = 43.70, -79.37
M_PER_DEG = 111_195


def out_and_back(day: int, kmh: float, km: float = 10, climb=(2.0, 4.0, 60), lon=LON0, stop_on_climb_s=0) -> Ride:
    """North for `km`, then back: a loop from home. The climb (from km, to km, metres up) is on the way out."""
    v = kmh / 3.6
    t = T0 + day * 86400
    start, samples, d, stopped = t, [], 0.0, 0
    while d <= 2 * km * 1000:
        out = min(d, 2 * km * 1000 - d)  # distance north of home
        a, b, gain = climb
        k = out / 1000
        ele = 100 + gain * min(max((k - a) / (b - a), 0), 1)
        samples.append(Sample(t=t, lat=LAT0 + out / M_PER_DEG, lon=lon, ele=ele, speed=v))
        if stop_on_climb_s and stopped < stop_on_climb_s and d / 1000 >= (a + b) / 2:
            stopped += 1
            t += 1
            continue
        d += v
        t += 1
    return Ride(start=start, end=t, sport="cycling", indoor=False, samples=samples,
                totals={"distance_m": 2 * km * 1000, "moving_s": 2 * km * 1000 / v, "ascent_m": climb[2]},
                provenance={"channel:lat": "garmin"}, recordings=["test"])


def found(rides):
    return repeats.find(rides, places=[])


SPEEDS = [24, 25, 23, 26, 27]


def test_home_loop_found_and_laps_compared():
    rides = [out_and_back(i * 3, kmh) for i, kmh in enumerate(SPEEDS)]
    rides.append(out_and_back(20, 25, km=30, lon=LON0 + 0.3))  # somewhere else: not the home loop
    f = found(rides)
    assert len(f["routes"]) == 1
    home = f["routes"][0]
    assert home["home"] and home["name"] == "Home loop" and home["loop"]
    assert [round(l["kmh"]) for l in home["laps"]] == SPEEDS
    assert home["km"] == 20.0


def test_climb_timed_on_the_same_gates_every_time():
    rides = [out_and_back(i * 3, kmh) for i, kmh in enumerate(SPEEDS)]
    c = found(rides)["climbs"]
    assert len(c) == 1
    climb = c[0]
    # Once per ride: the way back passes the gates in the wrong order and isn't counted.
    assert len(climb["attempts"]) == 5
    assert 1900 <= climb["length_m"] <= 2400  # detection smooths the ends a little and climb["name"].endswith("km climb")
    times = [a["seconds"] for a in climb["attempts"]]
    assert times.index(min(times)) == 4  # the 27 km/h ride
    assert abs(times[0] - climb["length_m"] / (24 / 3.6)) <= 3


def test_a_stop_on_the_climb_counts():
    rides = [out_and_back(i * 3, 25) for i in range(3)] + [out_and_back(10, 25, stop_on_climb_s=120)]
    times = [a["seconds"] for a in found(rides)["climbs"][0]["attempts"]]
    assert times[-1] - times[0] >= 115


def test_not_repeated_enough():
    rides = [out_and_back(0, 25), out_and_back(3, 26)]
    assert found(rides) == {"routes": [], "climbs": []}


def test_route_and_climb_notes():
    rides = [out_and_back(i * 3, kmh) for i, kmh in enumerate(SPEEDS)]
    f = found(rides)
    nb = records.notes_by_ride(rides, timezone.utc, found=f)
    fourth = [n["text"] for n in nb[str(int(rides[3].start))]]
    assert "Your fastest home loop yet" in fourth
    assert any(t.startswith("Your best time on the 2.0 km climb yet") or t.startswith("Your best time on the 2.")
               for t in fourth)
    third = [n["text"] for n in nb[str(int(rides[2].start))]]
    assert not any("yet" in t for t in third)  # only two laps before it
    y = records.you(rides, tz=timezone.utc, found=f)
    assert y["routes"][0]["count"] == 5 and y["routes"][0]["best"]["ride_id"] == str(int(rides[4].start))
    assert y["climbs"][0]["best"]["seconds"] == min(a["seconds"] for a in f["climbs"][0]["attempts"])
