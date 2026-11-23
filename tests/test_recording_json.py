"""Phone-exported recording JSON: format, CLI import, and merge with a Garmin .FIT (synthetic data)."""
import json
import os

import pytest

from fitwriter import write_fit
from rideengine.__main__ import main as cli
from rideengine.importers.fit import read_fit
from rideengine.importers.recording_json import FORMAT, read_recording_json, recording_from_dict, recording_to_dict
from rideengine.merge import build_rides
from rideengine.model import Sample
from rideengine.sources import allowed, blocked_sources, sources_used
from rideengine.store import Store
from test_engine import T0, line_ride


def phone_json(start=T0 - 17 * 60, minutes=77, bpm=144, every=5):
    """What the iPhone app exports: the Watch started 17 min before the Garmin (as on Durham Forest)."""
    route = [{"t": start + i, "lat": 43.70 + i * 1e-5, "lon": -79.37, "ele": 100.0, "speed": 6.9}
             for i in range(0, minutes * 60, 2)]
    hr = [{"t": start + i + 1, "hr": bpm} for i in range(0, minutes * 60, every)]
    return {"format": FORMAT, "source": "apple_watch", "device": "Apple Watch", "start": start,
            "end": start + minutes * 60, "sport": "cycling", "indoor": False,
            "origin": "healthkit:6F1C1C1E-0000-4000-8000-000000000001",
            "totals": {"distance_m": 31000.0, "calories": 1973.0, "avg_hr": 140.0, "max_hr": 173.0,
                       "ascent_m": 300.0, "elapsed_s": minutes * 60.0},
            "samples": route + hr, "someFutureField": {"ignored": True}}


def garmin_fit(tmp_path, minutes=60):
    rec = line_ride(minutes, climb=(5, 10, 120))
    path = tmp_path / "garmin.fit"
    path.write_bytes(write_fit(rec.samples, {"distance_m": 25000, "elapsed_s": minutes * 60,
                                             "moving_s": minutes * 60 - 30, "calories": 800, "ascent_m": 118}))
    return str(path)


def test_round_trip_keeps_everything():
    rec = recording_from_dict(phone_json())
    again = recording_from_dict(json.loads(json.dumps(recording_to_dict(rec))))
    assert again == rec
    assert rec.channels() == {"lat", "lon", "ele", "speed", "hr"}
    assert rec.samples == sorted(rec.samples, key=lambda s: s.t)


@pytest.mark.parametrize("change, message", [
    ({"format": "rideengine.recording/9"}, "unsupported"),
    ({"source": ""}, "source"),
    ({"samples": [{"lat": 1.0}]}, "time"),
    ({"samples": [{"t": 1.0, "hr": "fast"}]}, "finite number"),
    ({"start": 10.0, "end": 5.0}, "end >= start"),
])
def test_bad_json_is_refused(change, message):
    with pytest.raises(ValueError, match=message):
        recording_from_dict({**phone_json(), **change})


def test_fit_writer_reads_back(tmp_path):
    g = read_fit(garmin_fit(tmp_path))
    assert g.totals["distance_m"] == 25000 and g.totals["ascent_m"] == 118
    assert abs(g.samples[100].lat - line_ride(60).samples[100].lat) < 1e-6


def test_phone_ride_merges_with_garmin_fit(tmp_path):
    phone = tmp_path / "apple_watch_ride.json"
    phone.write_text(json.dumps(phone_json()))
    rides = build_rides([read_recording_json(str(phone)), read_fit(garmin_fit(tmp_path))])
    assert len(rides) == 1
    r = rides[0]
    assert len(r.recordings) == 2
    # Route and climbing from the Garmin; heart rate and calories from the Watch.
    for ch in ("lat", "lon", "ele", "speed"):
        assert r.provenance[f"channel:{ch}"] == "garmin"
    assert r.provenance["channel:hr"] == "apple_watch"
    # The Watch rode 17 minutes before the Garmin started: they're part of the ride, the Watch's route and
    # distance for them, the Garmin's after (its device totals plus the Watch's share).
    assert r.start == T0 - 17 * 60 and [a["where"] for a in r.added] == ["before"] and r.added[0]["minutes"] >= 16
    assert r.provenance["total:distance_m"] == "garmin" and r.provenance["extra:distance_m"] == "apple_watch"
    assert 25000 + 2000 < r.totals["distance_m"] < 25000 + 2300       # the Watch's route for those 17 minutes
    assert r.totals["ascent_m"] == 118                                  # flat before the Garmin started
    assert r.totals["calories"] == 1973 and r.provenance["total:calories"] == "apple_watch"   # covers it all
    assert "extra:calories" not in r.provenance
    assert r.totals["avg_hr"] == 144 and sum(s.hr is not None for s in r.samples) > 0.9 * len(r.samples)


def test_a_stop_before_the_head_unit_starts_isnt_added(tmp_path):
    """Riding, then waiting at the start for 10 minutes before starting the Garmin: only the Garmin's ride."""
    p = phone_json()
    p["samples"] = [x for x in p["samples"] if not (T0 - 12 * 60 <= x["t"] < T0 - 2 * 60 and "lat" in x)] + \
        [{"t": T0 - 12 * 60 + i, "lat": 43.703, "lon": -79.37, "ele": 100.0, "speed": 0.0} for i in range(0, 600, 5)]
    p["samples"].sort(key=lambda x: x["t"])
    phone = tmp_path / "w.json"
    phone.write_text(json.dumps(p))
    r = build_rides([read_recording_json(str(phone)), read_fit(garmin_fit(tmp_path))])[0]
    assert T0 - 3 * 60 <= r.start and r.added[0]["minutes"] < 3                # only the riding after the stop


def test_indoor_head_start_from_the_watch():
    """A Watch workout started before the ride game (spinning while choosing a course): the trainer's power,
    cadence and speed from the Watch carry the first minutes; distance indoors is the game's plus the Watch's
    for the minutes before; no climbing is added (only the game's counts)."""
    from rideengine.model import Recording, Sample
    t0 = 1_800_000_000
    watch = Recording(source="apple_watch", device="Watch", start=t0 - 300, end=t0 + 1800, sport="cycling", indoor=True,
                      samples=[Sample(t=t0 - 300 + i, power=60.0, cadence=85.0, speed=7.0, hr=100.0 + i / 60)
                               for i in range(2100)], totals={"calories": 400.0, "distance_m": 14700.0},
                      origin="healthkit:x")
    game = Recording(source="garmin", device="Edge", start=t0, end=t0 + 1800, sport="cycling", indoor=True,
                     samples=[Sample(t=t0 + i, lat=-11.6, lon=166.9 + i * 1e-5, ele=10.0 + i / 100, speed=6.0,
                                     power=150.0, cadence=90.0, hr=0.0) for i in range(1800)],
                     totals={"distance_m": 10800.0, "ascent_m": 18.0, "elapsed_s": 1800.0, "moving_s": 1800.0},
                     origin="garmin:1")
    r = build_rides([watch, game])[0]
    assert r.start == t0 - 300 and r.added[0]["source"] == "apple_watch" and abs(r.added[0]["km"] - 2.1) < 0.05
    assert abs(r.totals["distance_m"] - (10800 + 2093)) < 30 and r.totals["ascent_m"] == 18.0
    assert r.totals["elapsed_s"] >= 2099 and r.totals["calories"] == 400.0
    assert r.provenance["fill:power:apple_watch"] == "apple_watch"
    assert 135 < r.totals["avg_power"] < 139                   # 5 min at 60 W, 30 at 150 W: time-weighted
    assert all(s.hr and s.hr >= 100 for s in r.samples)        # the game's zeros aren't heart rate


def test_cli_imports_json(tmp_path):
    phone = tmp_path / "apple_watch_ride.json"
    phone.write_text(json.dumps(phone_json()))
    store = str(tmp_path / "store")
    cli(["--store", store, "import", garmin_fit(tmp_path), str(phone)])
    rides = Store(store).rides()
    assert len(rides) == 1 and len(rides[0].recordings) == 2


def test_whoop_totals_fill_hr_when_no_stream():
    whoop = recording_from_dict({**phone_json(), "source": "whoop", "samples": [],
                                 "totals": {"avg_hr": 139.0, "max_hr": 171.0, "calories": 1800.0}})
    r = build_rides([line_ride(60), whoop])[0]
    assert r.totals["avg_hr"] == 139 and r.provenance["total:avg_hr"] == "whoop"
    assert r.totals["calories"] == 1800 and r.provenance["total:calories"] == "whoop"


def test_use_policy_follows_provenance():
    r = build_rides([line_ride(60), recording_from_dict(phone_json())])[0]
    assert sources_used(r.provenance) == {"garmin", "apple_watch"}
    assert blocked_sources(r.provenance, "ai") == {"garmin"}  # Garmin terms not reviewed yet
    apple_only = build_rides([recording_from_dict(phone_json())])[0]
    assert allowed(apple_only.provenance, "ai") and allowed(apple_only.provenance, "share")
    oura = build_rides([recording_from_dict({**phone_json(), "source": "oura"})])[0]
    assert not allowed(oura.provenance, "ai")


def test_fuller_recording_wins_when_a_source_appears_twice():
    """A Garmin .FIT plus the thinner copy Garmin Connect wrote to Apple Health."""
    fit = line_ride(60)
    fit.totals = {"distance_m": 25000.0, "ascent_m": 118.0}
    copy = recording_from_dict({**phone_json(start=T0, minutes=60), "source": "garmin", "samples": [],
                                "totals": {"distance_m": 24000.0, "ascent_m": 90.0}})
    r = build_rides([copy, fit])[0]
    assert r.totals["distance_m"] == 25000 and r.totals["ascent_m"] == 118
