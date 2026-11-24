"""Zone 2 (rideengine/analysis/zone2.py): the range, a ride's time in it, the drift check, the words (synthetic)."""
from rideengine.analysis import zone2
from rideengine.model import Ride, Sample
from test_backend import env  # noqa: F401  (pytest fixture)

T0 = 1_795_000_000.0
RNG = [126, 138]


def ride(parts, indoor=True, power=None, drift=0.0):
    """[(minutes, heart rate)], one sample a second; outdoors moving at 8 m/s unless the heart rate is under 90
    (a stop). `power`: steady watts throughout; `drift`: bpm added by the end."""
    samples, t, lat = [], T0, 43.6
    total = sum(m for m, _ in parts) * 60
    for minutes, hr in parts:
        for _ in range(minutes * 60):
            moving = hr >= 90
            if not indoor and moving:
                lat += 8 / 111_000
            h = hr + drift * (t - T0) / total
            samples.append(Sample(t=t, hr=h, power=power, lat=None if indoor else lat,
                                  lon=None if indoor else -79.4))
            t += 1
    prov = {"channel:hr": "apple_watch"} | ({"channel:power": "apple_watch"} if power else {})
    return Ride(start=T0, end=t - 1, sport="cycling", indoor=indoor, samples=samples, totals={},
                provenance=prov, recordings=["test"])


def test_the_range_is_worked_out_or_the_riders_own():
    z = zone2.zone2_range(173, 55)
    assert z["bpm"] == [126, 138] and z["source"] == "estimated" and "heart rate reserve" in z["how"]
    assert zone2.zone2_range(173, 55, [130, 145])["bpm"] == [130, 145]
    assert zone2.zone2_range(None, 55) is None
    assert zone2.parse_own("126–138") == [126, 138] and zone2.parse_own(" 120 - 135 ") == [120, 135]
    assert zone2.parse_own("138-126") is None and zone2.parse_own("fast") is None and zone2.parse_own("130-132") is None


def test_a_rides_split_counts_moving_time_only():
    h = zone2.hist(ride([(20, 120), (40, 132), (20, 145)]))
    assert zone2.split([h], RNG) == {"in": 50, "above": 25, "below": 25, "minutes": 80, "in_min": 40}
    # Outdoors, a stop (heart rate falling to 80) doesn't make the ride look easier.
    h = zone2.hist(ride([(30, 132), (15, 80), (30, 145)], indoor=False))
    assert zone2.split([h], RNG)["below"] == 0 and zone2.split([h], RNG)["in"] == 50


def test_watts_at_zone_2_and_the_drift_check():
    steady = ride([(70, 130)], power=120, drift=2)
    h = zone2.hist(steady)
    assert zone2.watts([h], RNG) == {"watts": 120, "minutes": 70}
    d = zone2.steady(steady)
    assert d["watts"] == 120 and d["pct"] < 5 and d["minutes"] == 60
    feat = {"ride_id": "1", "start": T0, "indoor": True, "z2_drift": d, "hr_hist": h}
    c = zone2.check([feat], RNG)
    assert c["verdict"] == "fits" and "inside zone 2" in c["line"]
    # Heart rate climbing 20 bpm at the same power: not all aerobic.
    d = zone2.steady(ride([(70, 122)], power=120, drift=20))
    c = zone2.check([{**feat, "z2_drift": d}], RNG)
    assert d["pct"] > 5 and c["verdict"] == "lower" and "fan" in c["line"]
    # Steady above the range with little drift: zone 2 may reach higher.
    c = zone2.check([{**feat, "z2_drift": zone2.steady(ride([(70, 142)], power=150, drift=1))}], RNG)
    assert c["verdict"] == "higher" and "higher than 138" in c["line"]
    assert zone2.steady(ride([(70, 130)])) is None                     # no power, no check
    assert zone2.trend([{**feat, "start": T0}], RNG)[0]["watts"] == 120


def test_the_words_only_where_zone_2_was_the_point():
    s = {"in": 52, "above": 31, "below": 17, "minutes": 80, "in_min": 42}
    assert "31% above zone 2" in zone2.ride_line(s, RNG, "endurance") and "low gear" in zone2.ride_line(s, RNG, "long")
    assert "ease the trainer down" in zone2.ride_line(s, RNG, "endurance", indoor=True)
    assert zone2.ride_line(s, RNG, "surges") is None                  # hard days: the split, nothing said
    assert zone2.ride_line({**s, "in": 84, "above": 6, "below": 10}, RNG, "long") == "84% in zone 2: a textbook long ride."
    assert "easier than it needs to be" in zone2.ride_line({**s, "in": 20, "above": 5, "below": 75}, RNG, "endurance")
    assert "proper recovery" in zone2.ride_line({**s, "in": 20, "above": 5, "below": 75}, RNG, "easy")
    assert zone2.week_line({**s, "in": 60, "above": 18, "below": 22}) == \
        "18% of this week was above zone 2: right where it should be."
    assert "31% of this week was above zone 2. Most riders get faster with about 20%" in zone2.week_line(s)
    assert zone2.week_line({**s, "minutes": 40}) is None


def test_the_riders_own_range_and_the_zone_2_page(env):
    be, uid, client, _ = env
    assert client.put("/v1/me", json={"zone2": "fast"}).status_code == 400
    assert client.put("/v1/me", json={"zone2": "120-135"}).json()["zone2"] == "120-135"
    z = client.get("/v1/train/zone2").json()
    assert z["range"] == [120, 135] and z["source"] == "yours"
    assert be._plan_context(uid)["hr_zones"] is None or be._plan_context(uid)["hr_zones"]["Z2"] == [120, 135]
    assert client.put("/v1/me", json={"zone2": None}).json()["zone2"] is None
