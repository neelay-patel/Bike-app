"""Vehicle stretches (bike computer left on in a car) are left out of the ride. Synthetic data."""
from rideengine.clean import vehicle_segments
from rideengine.merge import build_rides
from rideengine.model import Recording, Sample

T0 = 1_790_000_000.0
LAT0, LON0 = 43.70, -79.37


def track(legs, start=T0, ele=100.0):
    """legs: [(seconds, km/h, climb_m)] driven north in a straight line, 1 Hz."""
    samples, t, d = [], start, 0.0
    for secs, kmh, climb in legs:
        v = kmh / 3.6
        for i in range(int(secs)):
            d += v
            ele += climb / secs
            samples.append(Sample(t=t, lat=LAT0 + d / 111_195, lon=LON0, ele=ele, speed=v, hr=140))
            t += 1
    return samples


def garmin(samples, **totals):
    return Recording(source="garmin", device="Garmin", start=samples[0].t, end=samples[-1].t,
                     samples=samples, totals=totals, origin="garmin:1")


RIDE = (3600, 25, 300)        # 1 h at 25 km/h, 300 m up
LOAD_BIKE = (300, 0, 0)       # 5 min still
DRIVE = (1800, 100, 0)        # 30 min at 100 km/h


def test_car_after_the_ride_is_cut_and_totals_redone():
    s = track([RIDE, LOAD_BIKE, DRIVE])
    r = build_rides([garmin(s, distance_m=75000.0, ascent_m=320.0, moving_s=5400.0, calories=2000.0,
                            max_speed_ms=27.8)])[0]
    assert len(r.excluded) == 1
    e = r.excluded[0]
    assert e["reason"] == "vehicle" and e["peak_kmh"] == 100.0 and 49 <= e["km"] <= 51
    assert abs(r.totals["distance_m"] - 25000) < 100
    assert r.totals["max_speed_ms"] < 8
    assert 310 < r.totals["ascent_m"] <= 320          # device total, scaled to the part kept (all of it)
    assert 1300 < r.totals["calories"] < 1400         # head-unit calories: share of moving time kept
    assert r.end < T0 + 3600 + 300 + 1                # the ride ends before the drive


def test_car_to_the_start_is_cut():
    s = track([DRIVE, LOAD_BIKE, RIDE])
    r = build_rides([garmin(s)])[0]
    assert r.excluded and r.start >= T0 + 1800
    assert abs(r.totals["distance_m"] - 25000) < 100


def test_fast_descent_is_not_a_car():
    descent = (45, 75, -100)  # 45 s at 75 km/h: fast, but a bike can do that
    s = track([RIDE, descent, RIDE])
    assert vehicle_segments(s) == []
    assert not build_rides([garmin(s)])[0].excluded


def test_wearable_calories_are_kept():
    s = track([RIDE, LOAD_BIKE, DRIVE])
    watch = Recording(source="apple_watch", device="Watch", start=T0, end=T0 + 3600,
                      samples=[Sample(t=T0 + i * 5, hr=150) for i in range(720)],
                      totals={"calories": 900.0}, origin="healthkit:x")
    r = build_rides([garmin(s, calories=2000.0), watch])[0]
    assert r.totals["calories"] == 900 and r.provenance["total:calories"] == "apple_watch"


def test_recording_that_is_all_driving_is_left_alone():
    r = build_rides([garmin(track([DRIVE]))])[0]
    assert r.excluded == [] and r.totals["distance_m"] > 45000


# --- false starts ------------------------------------------------------------------------------------
from rideengine.clean import hidden_reasons, visible  # noqa: E402


def ride_at(start, minutes, kmh=25):
    s = track([(minutes * 60, kmh, 0)], start=start)
    return garmin(s)


def test_false_starts_before_a_ride_are_hidden_but_kept():
    # 30 Jul 2026 pattern: 1.3 km, an empty one, 0.7 km, then the real ride.
    recs = [ride_at(T0, 3), ride_at(T0 + 300, 0.5, kmh=0), ride_at(T0 + 480, 2), ride_at(T0 + 660, 120)]
    rides = build_rides(recs)
    assert len(rides) == 4
    reasons = hidden_reasons(rides)
    assert sorted(reasons.values()) == ["empty", "false_start", "false_start"]
    assert [round(r.totals["distance_m"] / 1000) for r in visible(rides)] == [50]


def test_a_short_ride_on_its_own_stays():
    rides = build_rides([ride_at(T0, 5), ride_at(T0 + 86400, 120)])  # 2 km one day, 50 km the next
    assert hidden_reasons(rides) == {}


def test_tiny_rides_with_no_real_ride_nearby_stay():
    rides = build_rides([ride_at(T0, 4), ride_at(T0 + 600, 4)])
    assert hidden_reasons(rides) == {}


def test_empty_recording_is_hidden_even_alone():
    rides = build_rides([ride_at(T0, 0.5, kmh=0)])
    assert hidden_reasons(rides) == {0: "empty"}
