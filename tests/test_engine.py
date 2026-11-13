"""Unit tests on synthetic rides (no personal data needed)."""
import math
import os
import tempfile

from rideengine.analysis.basics import moving_time, stops, summary
from rideengine.analysis.climbs import find_climbs
from rideengine.analysis.fitness import efficiency
from rideengine.importers.gpx import read_gpx
from rideengine.merge import build_rides, group, merge
from rideengine.model import Recording, Sample

T0 = 1_790_000_000.0
LAT0, LON0 = 43.70, -79.37


def line_ride(minutes=60, kmh=25.0, every=1, climb=None, source="garmin", hr=None, start=T0, stop_at=None):
    """A straight northward ride. climb=(start_km, end_km, gain_m) adds a steady hill."""
    v = kmh / 3.6
    samples, d, t, ele = [], 0.0, start, 100.0
    while t <= start + minutes * 60:
        paused = stop_at and stop_at[0] <= (t - start) / 60 < stop_at[1]
        if not paused:
            d += v * every
        km = d / 1000
        if climb and climb[0] <= km <= climb[1]:
            ele = 100 + climb[2] * (km - climb[0]) / (climb[1] - climb[0])
        elif climb and km > climb[1]:
            ele = 100 + climb[2]
        samples.append(Sample(t=t, lat=LAT0 + d / 111_195, lon=LON0, ele=ele, speed=0 if paused else v,
                              hr=hr))
        t += every
    return Recording(source=source, device=source, start=samples[0].t, end=samples[-1].t, samples=samples,
                     origin=f"{source}:{start}")


def watch(start, minutes, bpm=140, every=5, calories=900):
    s = [Sample(t=start + i * every, hr=bpm) for i in range(int(minutes * 60 / every) + 1)]
    return Recording(source="apple_watch", device="watch", start=s[0].t, end=s[-1].t, samples=s,
                     totals={"calories": calories, "distance_m": 1.0}, origin="watch")


def test_group_pairs_overlapping_recordings_only():
    g = line_ride(60)
    w = watch(T0 - 17 * 60, 77)          # watch started 17 min early, like the Durham ride
    other = watch(T0 + 5 * 3600, 30)     # a separate activity later that day
    groups = group([g, w, other])
    assert [len(x) for x in groups] == [2, 1]


def test_merge_takes_route_from_garmin_and_hr_calories_from_watch():
    ride = merge([line_ride(60), watch(T0 - 600, 70, bpm=150, calories=1234)])
    assert ride.provenance["channel:lat"] == "garmin"
    assert ride.provenance["channel:hr"] == "apple_watch"
    assert ride.provenance["total:calories"] == "apple_watch"
    assert ride.totals["calories"] == 1234
    assert ride.totals["avg_hr"] == 150
    # base timeline is the Garmin one: watch minutes before the start are dropped
    assert ride.start == T0


def test_distance_derived_from_winning_track_not_watch_total():
    ride = merge([line_ride(60, kmh=30), watch(T0, 60)])
    assert abs(ride.totals["distance_m"] - 30_000) < 300
    assert ride.provenance["total:distance_m"] == "derived:garmin"


def test_power_energy_used_for_calories_only_without_wearable():
    r = line_ride(60)
    for s in r.samples:
        s.power = 200.0
    r.source = "kickr"
    ride = merge([r])
    assert ride.provenance["total:calories"] == "derived:power"
    assert abs(ride.totals["calories"] - 720) < 10   # 200 W for an hour = 720 kJ


def test_moving_time_and_stops():
    r = merge([line_ride(60, stop_at=(20, 30))])
    assert abs(moving_time(r) - 50 * 60) < 30
    st = stops(r)
    assert len(st) == 1 and abs(st[0]["seconds"] - 600) < 30


def test_climb_found_with_length_gain_and_grade():
    r = merge([line_ride(40, kmh=20, climb=(3.0, 5.0, 80))])
    c = find_climbs(r)
    assert len(c) == 1
    assert 1800 <= c[0]["length_m"] <= 2500  # smoothing widens edges slightly and 65 <= c[0]["gain_m"] <= 85


def test_efficiency_on_flat_steady_ride():
    r = merge([line_ride(30, kmh=30), watch(T0, 30, bpm=150)])
    # 30 km/h = 500 m/min; at 150 bpm that's 3.33 m per beat
    assert abs(efficiency(r) - 3.33) < 0.05


def test_gpx_reads_apple_style_extensions():
    gpx = """<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>
    <trkpt lon="-79.37" lat="43.70"><ele>100</ele><time>2026-10-31T17:37:49Z</time><extensions><speed>7.5</speed></extensions></trkpt>
    <trkpt lon="-79.37" lat="43.701"><ele>101</ele><time>2026-10-31T17:37:59Z</time><extensions><speed>8.0</speed></extensions></trkpt>
    </trkseg></trk></gpx>"""
    with tempfile.NamedTemporaryFile("w", suffix=".gpx", delete=False) as f:
        f.write(gpx)
    rec = read_gpx(f.name)
    os.unlink(f.name)
    assert len(rec.samples) == 2 and rec.samples[1].speed == 8.0 and rec.duration == 10


def test_build_rides_end_to_end():
    rides = build_rides([line_ride(60), watch(T0, 60), line_ride(30, start=T0 + 86400)])
    assert len(rides) == 2
    assert summary(rides[0])["avg_kmh"] > 24
