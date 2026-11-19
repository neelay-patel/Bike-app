"""The insights pipeline (backend/insights.py): stored, incremental, the same answers as the batch.

Rides go in one at a time through the real upload path; what's stored must match working everything
out in one go (repeats.find + records.notes_by_ride), whatever order the rides arrive in."""
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("cryptography")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import create_app  # noqa: E402
from backend.config import Settings  # noqa: E402
from backend.connectors.apple_health import AppleHealth  # noqa: E402
from backend.service import Backend  # noqa: E402
from rideengine.analysis import records, repeats  # noqa: E402
from rideengine.importers.recording_json import recording_to_dict  # noqa: E402
from rideengine.model import Recording  # noqa: E402
from test_repeats import SPEEDS, out_and_back  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    # Names mustn't depend on whether GeoNames is downloaded on this machine.
    monkeypatch.setattr(repeats, "load_places", lambda boxes: [])
    settings = Settings(data_dir=str(tmp_path), database=str(tmp_path / "db.sqlite3"),
                        raw_dir=str(tmp_path / "raw"), secret_key_file=str(tmp_path / "secret.key"),
                        public_base_url="http://test")
    be = Backend(settings, registry={"apple_health": AppleHealth()})
    uid, token = be.create_user()
    client = TestClient(create_app(be), headers={"Authorization": f"Bearer {token}"})
    return be, uid, client


def upload(client, ride, n):
    rec = Recording(source="apple_watch", device="Apple Watch", start=ride.start, end=ride.end,
                    samples=ride.samples, totals=ride.totals, origin=f"healthkit:w{n}")
    r = client.post("/v1/uploads/apple_health", content=json.dumps(recording_to_dict(rec)))
    assert r.status_code == 201, r.text


def loops():
    return [out_and_back(i * 3, kmh) for i, kmh in enumerate(SPEEDS)]


def stored_notes(be, uid):
    return {rid: [n["text"] for n in ns] for rid, ns in be.insights.notes(uid).items() if ns}


def batch_notes(be, uid):
    rides = be.visible_rides(uid)
    found = repeats.find(rides, places=[])
    return {rid: [n["text"] for n in ns] for rid, ns in records.notes_by_ride(rides, found=found).items() if ns}


@pytest.mark.parametrize("order", [[0, 1, 2, 3, 4], [4, 3, 2, 1, 0], [0, 1, 2, 4, 3]])
def test_one_at_a_time_matches_all_at_once(env, order):
    be, uid, client = env
    rides = loops()
    for n in order:
        upload(client, rides[n], n)
    y = client.get("/v1/you").json()
    assert not y["updating"]
    assert [(r["name"], r["count"]) for r in y["routes"]] == [("Home loop", 5)]
    assert len(y["climbs"]) == 1 and y["climbs"][0]["count"] == 5
    assert y["routes"][0]["best"]["ride_id"] == str(int(rides[4].start))
    assert stored_notes(be, uid) == batch_notes(be, uid)
    assert "Your fastest home loop yet" in stored_notes(be, uid)[str(int(rides[3].start))]


def test_route_and_climb_keep_their_ids_and_names(env):
    be, uid, client = env
    rides = loops()
    for n in range(3):
        upload(client, rides[n], n)
    y = client.get("/v1/you").json()
    route_id, climb_id = y["routes"][0]["id"], y["climbs"][0]["id"]
    assert client.patch(f"/v1/climbs/{climb_id}", json={"name": "Bayview drag"}).status_code == 200
    assert client.patch(f"/v1/routes/{route_id}", json={"name": "Before work"}).status_code == 200
    for n in (3, 4):
        upload(client, rides[n], n)
    y = client.get("/v1/you").json()
    assert (y["routes"][0]["id"], y["routes"][0]["name"], y["routes"][0]["count"]) == (route_id, "Before work", 5)
    assert (y["climbs"][0]["id"], y["climbs"][0]["name"]) == (climb_id, "Bayview drag")
    notes = stored_notes(be, uid)[str(int(rides[3].start))]
    assert "Your fastest Before work yet" in notes or any("Bayview drag" in t for t in notes)
    # Back to the automatic name.
    client.patch(f"/v1/routes/{route_id}", json={"name": None})
    assert client.get("/v1/you").json()["routes"][0]["name"] == "Home loop"
    assert client.patch("/v1/routes/nope", json={"name": "x"}).status_code == 404


def test_rides_only_matched_not_rediscovered(env, monkeypatch):
    be, uid, client = env
    rides = loops()
    for n in range(3):
        upload(client, rides[n], n)
    # Once a route and climb exist, a new lap is matched on arrival; nothing is searched for again.
    monkeypatch.setattr(repeats, "discover_climbs", lambda *a, **k: [])
    monkeypatch.setattr(repeats, "discover_routes", lambda *a, **k: [])
    upload(client, rides[3], 3)
    y = client.get("/v1/you").json()
    assert y["routes"][0]["count"] == 4 and y["climbs"][0]["count"] == 4


def test_disconnect_removes_everything_derived(env):
    be, uid, client = env
    for n, r in enumerate(loops()):
        upload(client, r, n)
    client.delete("/v1/connections/apple_health")
    for table in ("ride_features", "routes", "route_laps", "climbs", "climb_attempts", "ride_notes"):
        assert be.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    y = client.get("/v1/you").json()
    assert y["routes"] == [] and y["climbs"] == [] and y["all"]["rides"] == 0


def test_rides_stored_before_insights_are_caught_up(env):
    be, uid, client = env
    for n, r in enumerate(loops()):
        upload(client, r, n)
    want = stored_notes(be, uid)
    for table in ("ride_features", "routes", "route_laps", "climbs", "climb_attempts", "ride_notes", "insight_state"):
        be.db.execute(f"DELETE FROM {table}")
    be.insights.refresh(uid)
    assert stored_notes(be, uid) == want
    be.insights.rebuild(uid)
    assert stored_notes(be, uid) == want


def test_time_zone(env):
    be, uid, client = env
    assert client.put("/v1/me", json={"tz": "Mars/Olympus"}).status_code == 400
    r = client.put("/v1/me", json={"tz": "America/Toronto"})
    assert r.status_code == 200 and r.json()["tz"] == "America/Toronto"
    assert client.get("/v1/me").json()["tz"] == "America/Toronto"


def test_ride_card_endpoint(env):
    be, uid, client = env
    rides = loops()
    for n, r in enumerate(rides):
        upload(client, r, n)
    rid = str(int(rides[4].start))
    r = client.get(f"/v1/rides/{rid}/card?fonts=local&background=transparent")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert "googleapis" not in html and "Doto-Black.ttf" in html  # the app's own fonts
    assert ">Home loop</h1>" in html and ">NO. 5<" in html         # the route's name, its number in the year
    assert "Your fastest home loop yet." in html                   # the top note as headline
    assert client.get("/v1/rides/1/card").status_code == 404
    assert client.get(f"/v1/rides/{rid}/card?fonts=comic").status_code == 400
    assert client.get(f"/v1/rides/{rid}/card?background=red;x").status_code == 400


def test_card_route_is_cut_around_home():
    from rideengine.card.ride_card import PRIVACY_M, trim_near
    from rideengine.model import haversine
    ride = out_and_back(0, 25)
    home = (ride.samples[0].lat, ride.samples[0].lon)
    cut = trim_near(ride, [home])
    assert len(cut.samples) < len(ride.samples)
    assert all(haversine(*home, s.lat, s.lon) > PRIVACY_M for s in cut.samples)
    assert cut.totals == ride.totals  # only the drawing changes
