"""The ride page's profiles (rideengine/analysis/profile.py) and the ride game worlds (rideengine/worlds.py)."""
import math

from rideengine.analysis.profile import index_at, profile
from rideengine.model import Ride, Sample
from rideengine.worlds import world_at, world_of


def _ride(indoor=False, stop=False):
    t0 = 1_790_000_000.0
    samples = []
    for i in range(720):                     # an hour, every 5 s
        moving = not (stop and 200 <= i < 260)
        samples.append(Sample(t=t0 + i * 5, lat=43.9 + i * 0.0001, lon=-79.1, ele=150 + 20 * math.sin(i / 60),
                              speed=8.0 if moving else 0.0, hr=140, power=150 if indoor else None, cadence=88))
    return Ride(start=t0, end=t0 + 3600, sport="cycling", indoor=indoor, samples=samples,
                totals={"distance_m": 30000, "ascent_m": 250, "moving_s": 3300}, provenance={}, recordings=["x"])


def test_profile_steps_end_on_the_rides_totals():
    p = profile(_ride())
    assert p["step_s"] == 30 and len(p["t"]) == 120
    assert p["km"][-1] == 30.0 and p["cu"][-1] == 250          # scaled to the device's distance and climbing
    assert p["cu"] == sorted(p["cu"])                          # climbing so far only goes up
    assert p["s"][0] == 28.8 and p["h"][0] == 140 and all(v is None for v in p["p"])
    assert p["lat"][0] is not None


def test_profile_leaves_stops_out_outdoors_only():
    out = profile(_ride(stop=True))
    assert len(out["t"]) == 111 and 1020 not in out["t"]         # the 9 fully stopped steps are gone
    assert index_at(out["t"], 1100) in (out["t"].index(990), out["t"].index(1290))
    assert all(v >= 2 for v in out["s"])
    indoor = profile(_ride(indoor=True, stop=True))
    assert len(indoor["t"]) == 120 and indoor["p"][0] == 150


def test_worlds():
    assert world_at(40.77, -73.97) == ("Zwift", "New York")
    assert world_at(-11.65, 166.95) == ("Zwift", "Watopia")
    assert world_at(43.9, -79.1) is None
    r = _ride(indoor=True)
    assert world_of(r) is None                                 # an indoor ride on real Ontario roads: no game
