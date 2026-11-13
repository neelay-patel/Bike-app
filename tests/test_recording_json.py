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
    assert r.totals["distance_m"] == 25000 and r.provenance["total:distance_m"] == "garmin"
    assert r.totals["ascent_m"] == 118
    assert r.totals["calories"] == 1973 and r.provenance["total:calories"] == "apple_watch"
    # The Watch's 17 extra minutes before the Garmin start are not part of the ride.
    assert r.start == T0
    assert r.totals["avg_hr"] == 144 and sum(s.hr is not None for s in r.samples) > 0.9 * len(r.samples)


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
