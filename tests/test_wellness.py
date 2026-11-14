"""Recovery and fitness (rideengine/analysis/wellness.py) and the metrics upload. Synthetic data only."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from rideengine.analysis import records, wellness
from rideengine.importers.recording_json import recording_from_dict, recording_to_dict
from rideengine.merge import merge
from rideengine.model import Recording, Sample
from test_engine import T0, line_ride

UTC = timezone.utc


def watch(start=T0, minutes=60, end_hr=150, after=((60, 120), (120, 100))):
    end = start + minutes * 60
    samples = [Sample(t=start + i * 5, hr=end_hr) for i in range(minutes * 12 + 1)]
    return Recording(source="apple_watch", device="Apple Watch", start=start, end=end, samples=samples,
                     totals={"calories": 900}, origin="healthkit:w1",
                     after=[Sample(t=end + s, hr=hr) for s, hr in after])


def test_ride_recovery():
    assert wellness.ride_recovery(watch()) == {"hr_end": 150, "hr_drop_60s": 30, "hr_drop_120s": 50}
    assert wellness.ride_recovery(watch(after=())) == {}
    assert wellness.ride_recovery(watch(after=((300, 90),))) == {}  # nothing near a minute after


def test_merged_ride_carries_recovery_from_the_watch():
    garmin = line_ride(60)
    ride = merge([garmin, watch()])
    assert ride.totals["hr_drop_60s"] == 30 and ride.provenance["total:hr_drop_60s"] == "apple_watch"
    assert "hr_drop_60s" not in merge([garmin]).totals


def test_recording_json_keeps_after():
    rec = recording_from_dict(recording_to_dict(watch()))
    assert [(s.t - rec.end, s.hr) for s in rec.after] == [(60, 120), (120, 100)]
    assert "after" not in recording_to_dict(watch(after=()))


def series(kind, days, value, today, jitter=0.0):
    out = []
    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        t = datetime(d.year, d.month, d.day, 6, tzinfo=UTC).timestamp()
        out.append({"kind": kind, "t": t, "value": value(i) + (jitter if i % 2 else -jitter), "source": "apple_watch"})
    return out


TODAY = date(2026, 11, 14)


def test_usual_range_and_readiness():
    # 60 days around 50 ms, then a week at 38: HRV is low. Resting HR 50, then a week at 58: high.
    hrv = series("hrv_sdnn", 67, lambda i: 50 if i < 60 else 38, TODAY, jitter=3)
    rhr = series("resting_hr", 67, lambda i: 50 if i < 60 else 58, TODAY, jitter=1)
    s = wellness.summary(hrv + rhr, [], today=TODAY, tz=UTC)
    assert s["hrv_sdnn"]["status"] == "worse" and s["hrv_sdnn"]["usual"] == 50
    assert s["resting_hr"]["status"] == "worse"
    assert s["readiness"]["status"] == "strained"
    calm = series("hrv_sdnn", 67, lambda i: 50, TODAY, jitter=3)
    assert wellness.summary(calm, [], today=TODAY, tz=UTC)["readiness"]["status"] == "good"


def test_too_few_readings_says_so():
    s = wellness.summary(series("hrv_sdnn", 10, lambda i: 50, TODAY), [], today=TODAY, tz=UTC)
    assert s["hrv_sdnn"]["status"] == "unknown" and s["readiness"]["status"] == "unknown"
    assert s["hrv_sdnn"]["latest"] == 50


def test_vo2max_change():
    vo2 = series("vo2max", 120, lambda i: 44 + i * 0.02, TODAY)
    s = wellness.summary(vo2, [], today=TODAY, tz=UTC)
    assert s["vo2max"]["change_90d"] == pytest.approx(1.8, abs=0.05)
    assert "walks, runs and hikes" in s["vo2max"]["note"]


def test_unbelievable_readings_rejected():
    assert wellness.valid({"kind": "hrv_sdnn", "t": 1.0, "value": 45})
    assert not wellness.valid({"kind": "hrv_sdnn", "t": 1.0, "value": 900})
    assert not wellness.valid({"kind": "sleep", "t": 1.0, "value": 7})


def test_ride_recovery_trend_and_note():
    rides = [{"ride_id": str(i), "start": T0 + i * 86400, "hr_drop_60s": v}
             for i, v in enumerate([20, 22, 21, 26, 28, 30])]
    rr = wellness.summary([], rides, today=TODAY, tz=UTC)["ride_recovery"]
    assert rr["count"] == 6 and rr["best"]["hr_drop_60s"] == 30 and rr["trend"] == "faster"
    feats = [{"ride_id": r["ride_id"], "start": r["start"], "km": 30, "ascent_m": 100, "moving_s": 3600,
              "kmh": 25, "power": None, "indoor": False, "hr_drop_60s": r["hr_drop_60s"]} for r in rides]
    es = records.entries_from_features(feats, UTC)
    notes = records.notes_for(es, {"routes": [], "climbs": []}, UTC)
    assert "Your fastest heart-rate recovery yet" in [n["text"] for n in notes["3"]]
    assert "Your fastest heart-rate recovery yet" not in [n["text"] for n in notes["2"]]


# --- backend ---------------------------------------------------------------------------------
@pytest.fixture
def env(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("cryptography")
    from fastapi.testclient import TestClient

    from backend.app import create_app
    from backend.config import Settings
    from backend.connectors.apple_health import AppleHealth
    from backend.service import Backend
    settings = Settings(data_dir=str(tmp_path), database=str(tmp_path / "db.sqlite3"),
                        raw_dir=str(tmp_path / "raw"), secret_key_file=str(tmp_path / "secret.key"),
                        public_base_url="http://test")
    be = Backend(settings, registry={"apple_health": AppleHealth()})
    uid, token = be.create_user()
    return be, uid, TestClient(create_app(be), headers={"Authorization": f"Bearer {token}"}), tmp_path


def batch(metrics):
    return json.dumps({"format": "rideengine.metrics/1", "metrics": metrics})


def test_metrics_upload_recovery_and_disconnect(env):
    be, uid, client, tmp = env
    today = date.today()
    ms = [{**m, "id": f"m{i}"} for i, m in enumerate(series("hrv_sdnn", 30, lambda i: 48, today))]
    ms += [{"id": "x1", "kind": "sleep_hours", "t": T0, "value": 7},          # not in scope: dropped
           {"id": "x2", "kind": "resting_hr", "t": T0, "value": 400}]       # not believable: dropped
    r = client.post("/v1/metrics/apple_health", content=batch(ms))
    assert r.status_code == 201 and r.json() == {"received": 30, "new": 30}
    assert client.post("/v1/metrics/apple_health", content=batch(ms)).json()["new"] == 0  # repeats ignored
    assert client.post("/v1/metrics/apple_health", content="{}").status_code == 400
    rec = client.get("/v1/recovery").json()
    assert rec["hrv_sdnn"]["latest"] == 48 and len(rec["hrv_sdnn"]["series"]) == 30
    assert rec["disclaimer"].endswith("not medical advice.")
    # Disconnecting Apple Health deletes the readings and the batches as received.
    client.delete("/v1/connections/apple_health")
    assert be.db.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 0
    assert not (tmp / "raw" / str(uid) / "apple_health" / "metrics").exists()
    assert client.get("/v1/recovery").json()["hrv_sdnn"]["latest"] is None
