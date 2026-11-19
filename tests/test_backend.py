"""Backend: connections, Garmin personal-key sync (mocked Garmin), Apple Health upload, merge, disconnect.

Skipped when the backend's dependencies aren't installed (pip install -r requirements-backend.txt).
"""
import base64
import io
import json
import zipfile

import pytest

pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")
pytest.importorskip("cryptography")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import create_app  # noqa: E402
from backend.config import Settings  # noqa: E402
from backend.connectors import PLANNED, Planned  # noqa: E402
from backend.connectors.apple_health import AppleHealth  # noqa: E402
from backend.connectors.garmin_personal import BASE_URL, GarminPersonal  # noqa: E402
from backend.service import Backend  # noqa: E402
from fitwriter import write_fit  # noqa: E402
from test_engine import T0, line_ride  # noqa: E402
from test_recording_json import phone_json  # noqa: E402

API_KEY = "test-personal-key"


def jwt(exp: float) -> str:
    part = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"e30.{part}.sig"


class FakeGarmin:
    """Just the three Personal API endpoints the connector uses."""

    def __init__(self, rides):
        self.rides = rides  # {activityId: fit bytes}
        self.token_calls = 0
        self.now = T0  # tokens last 24 h from "now", like Garmin's
        self.downloads = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/personal-api-key/token"):
            self.token_calls += 1
            if req.headers.get("Authorization") != f"ApiKey {API_KEY}":
                return httpx.Response(401)
            return httpx.Response(200, text=jwt(self.now + 86400))
        if req.headers.get("Authorization", "").split(" ")[0] != "Bearer":
            return httpx.Response(401)
        if req.url.path == "/activitylist-service/activities/search/activities":
            assert req.url.params["activityType"] == "cycling"
            start = int(req.url.params["start"])
            items = [{"activityId": a, "activityName": "Ride"} for a in sorted(self.rides)]
            return httpx.Response(200, json=items[start:start + int(req.url.params["limit"])])
        if req.url.path.startswith("/download-service/files/activity/"):
            aid = int(req.url.path.rsplit("/", 1)[1])
            self.downloads.append(aid)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr(f"{aid}_ACTIVITY.fit", self.rides[aid])
            return httpx.Response(200, content=buf.getvalue())
        return httpx.Response(404)


@pytest.fixture
def env(tmp_path):
    ride = line_ride(60, climb=(5, 10, 120))
    other_day = line_ride(30, start=T0 + 86400)
    garmin = FakeGarmin({
        111: write_fit(ride.samples, {"distance_m": 25000, "elapsed_s": 3600, "moving_s": 3570,
                                      "calories": 800, "ascent_m": 118}),
        222: write_fit(other_day.samples, {"distance_m": 12500, "elapsed_s": 1800, "calories": 400}),
    })
    connector = GarminPersonal(client=httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(garmin)),
                               clock=lambda: garmin.now)
    registry = {"apple_health": AppleHealth(), "garmin_personal": connector,
                **{i.key: Planned(i) for i in PLANNED}}
    settings = Settings(data_dir=str(tmp_path), database=str(tmp_path / "db.sqlite3"),
                        raw_dir=str(tmp_path / "raw"), secret_key_file=str(tmp_path / "secret.key"),
                        public_base_url="http://test")
    be = Backend(settings, registry=registry)
    uid, token = be.create_user()
    client = TestClient(create_app(be), headers={"Authorization": f"Bearer {token}"})
    return be, uid, client, garmin


def test_needs_a_token(env):
    _, _, client, _ = env
    assert TestClient(client.app).get("/v1/rides").status_code == 401
    assert client.get("/v1/rides", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_connections_list_every_provider(env):
    _, _, client, _ = env
    rows = {c["provider"]: c for c in client.get("/v1/connections").json()}
    assert {"apple_health", "garmin_personal", "garmin", "wahoo", "hammerhead", "whoop", "oura",
            "google_health"} <= set(rows)
    assert rows["garmin_personal"]["state"] == "not_connected"
    assert rows["hammerhead"]["availability"] == "blocked"
    r = client.put("/v1/connections/wahoo", json={})
    assert r.status_code == 400 and "can't be connected" in r.json()["error"]


def test_bad_garmin_key_is_refused(env):
    _, _, client, _ = env
    r = client.put("/v1/connections/garmin_personal", json={"api_key": "wrong"})
    assert r.status_code == 400 and "didn't accept" in r.json()["error"]


def test_garmin_sync_then_phone_upload_merge(env, tmp_path):
    be, uid, client, garmin = env
    r = client.put("/v1/connections/garmin_personal?since=2026-01-01", json={"api_key": API_KEY})
    assert r.status_code == 202
    # The background sync pulled both rides.
    assert sorted(garmin.downloads) == [111, 222]
    rides = client.get("/v1/rides").json()
    assert len(rides) == 2 and all(r["sources"] == ["garmin"] for r in rides)
    # Credentials are stored encrypted.
    blob = be.db.execute("SELECT secret FROM connections").fetchone()["secret"]
    assert API_KEY.encode() not in blob
    # Original files are kept.
    assert (tmp_path / "raw" / str(uid) / "garmin_personal" / "111.fit").exists()

    # A second sync downloads nothing new.
    assert client.post("/v1/connections/garmin_personal/sync?since=2026-01-01").json()["new"] == 0
    assert sorted(garmin.downloads) == [111, 222]

    # The phone uploads the Apple Watch workout for the first ride: it merges.
    up = client.post("/v1/uploads/apple_health", content=json.dumps(phone_json()))
    assert up.status_code == 201
    ride_id = up.json()["ride_id"]
    assert ride_id == str(int(T0))
    d = client.get(f"/v1/rides/{ride_id}").json()
    assert d["sources"] == ["apple_watch", "garmin"]
    assert d["provenance"]["channel:lat"] == "garmin" and d["provenance"]["channel:hr"] == "apple_watch"
    assert d["totals"]["calories"] == 1973 and d["totals"]["ascent_m"] == 118
    assert d["use"]["ai"] == {"allowed": False, "blocked_by": ["garmin"]}
    assert len(client.get("/v1/rides").json()) == 2

    # Uploading the same workout again changes nothing.
    client.post("/v1/uploads/apple_health", content=json.dumps(phone_json()))
    assert be.db.execute("SELECT COUNT(*) FROM recordings").fetchone()[0] == 3

    # Disconnecting Garmin deletes its data; the Watch recording becomes the ride on its own.
    assert client.delete("/v1/connections/garmin_personal").json()["recordings_deleted"] == 2
    rides = client.get("/v1/rides").json()
    assert len(rides) == 1 and rides[0]["sources"] == ["apple_watch"]
    assert not (tmp_path / "raw" / str(uid) / "garmin_personal" / "111.fit").exists()
    states = {c["provider"]: c["state"] for c in client.get("/v1/connections").json()}
    assert states["garmin_personal"] == "not_connected" and states["apple_health"] == "connected"


def test_expired_token_is_renewed(env):
    be, uid, _, garmin = env
    be.connect(uid, "garmin_personal", {"api_key": API_KEY})
    assert garmin.token_calls == 1
    be.sync(uid, "garmin_personal", "2026-01-01")
    assert garmin.token_calls == 1  # still valid: reused
    garmin.now += 2 * 86400  # two days later the 24 h token has expired
    be.sync(uid, "garmin_personal", "2026-01-01")
    assert garmin.token_calls == 2


@pytest.mark.parametrize("change, message", [
    ({"sport": "running"}, "Only cycling"),
    ({"source": "strava"}, "Unknown source"),
    ({"origin": "somewhere"}, "healthkit"),
    ({"samples": "nope"}, "must be a list"),
])
def test_upload_validation(env, change, message):
    _, _, client, _ = env
    r = client.post("/v1/uploads/apple_health", content=json.dumps({**phone_json(), **change}))
    assert r.status_code == 400 and message in r.json()["error"]
    assert client.get("/v1/rides").json() == []


def test_upload_only_to_device_connectors(env):
    _, _, client, _ = env
    r = client.post("/v1/uploads/garmin_personal", content=json.dumps(phone_json()))
    assert r.status_code == 400


def test_network_failure_is_a_clear_error_not_a_500(env):
    """E.g. Python linked to an old TLS library that Garmin's servers refuse."""
    be, _, client, _ = env

    def refuse(req):
        raise httpx.ConnectError("[SSL: TLSV1_ALERT_PROTOCOL_VERSION] tlsv1 alert protocol version")
    be.registry["garmin_personal"].http = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(refuse))
    r = client.put("/v1/connections/garmin_personal", json={"api_key": API_KEY})
    assert r.status_code == 400
    assert "Couldn't reach Garmin" in r.json()["error"] and "Python 3.11+" in r.json()["error"]
    assert API_KEY not in r.json()["error"]


def test_key_pasted_twice_is_caught_before_asking_garmin(env):
    be, uid, _, garmin = env
    from backend.connectors import ConnectorError
    with pytest.raises(ConnectorError, match="pasted 2 times"):
        be.connect(uid, "garmin_personal", {"api_key": "GCDC_a.b.c.1GCDC_a.b.c.1"})
    assert garmin.token_calls == 0


def test_rebuild_and_excluded_in_api(env):
    be, uid, client, _ = env
    client.post("/v1/uploads/apple_health", content=json.dumps(phone_json()))
    assert be.rebuild_all(uid) == 1
    d = client.get("/v1/rides").json()[0]
    assert d["excluded"] == []


def test_rides_hide_false_starts_unless_asked(env):
    be, uid, client, _ = env
    tiny = phone_json(start=T0 - 30 * 60, minutes=3)
    tiny["origin"] = "healthkit:tiny"
    tiny["totals"] = {"distance_m": 900.0}
    client.post("/v1/uploads/apple_health", content=json.dumps(tiny))
    client.post("/v1/uploads/apple_health", content=json.dumps(phone_json()))
    assert len(client.get("/v1/rides").json()) == 1
    every = client.get("/v1/rides?include_hidden=true").json()
    assert sorted(str(d["hidden"]) for d in every) == ["None", "false_start"]
    # Both belong to one effort, named after the real ride; the false start is folded into it.
    main = next(d["ride_id"] for d in every if d["hidden"] is None)
    assert {d["effort"] for d in every} == {main}
    e = client.get(f"/v1/efforts/{every[-1]['ride_id']}").json()
    assert e["effort_id"] == main and [f["reason"] for f in e["folded"]] == ["false_start"]
    assert e["lines"][0].startswith("A false start") and "phases" in e["parts"][0]
    assert client.get("/v1/efforts/123").status_code == 404


def test_you_and_ride_notes(env):
    be, uid, client, _ = env
    client.put("/v1/connections/garmin_personal?since=2026-01-01", json={"api_key": API_KEY})
    y = client.get("/v1/you").json()
    assert y["all"]["rides"] == 2 and y["all"]["km"] == 37.5
    assert {b["kind"] for b in y["bests"]} >= {"distance", "climbing"}
    assert [r["ride_id"] for r in y["recent"]] == [str(int(T0 + 86400)), str(int(T0))]
    rides = client.get("/v1/rides").json()
    assert all(isinstance(r["notes"], list) for r in rides)
    assert client.get(f"/v1/rides/{int(T0)}").json()["notes"] == []  # too few rides to compare yet


def test_new_token_replaces_the_old(env):
    be, uid, client, _ = env
    token = be.new_token(uid)
    assert client.get("/v1/rides").status_code == 401  # the old token no longer works
    assert client.get("/v1/rides", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_delete_ride_stays_deleted(env):
    be, uid, client, garmin = env
    client.put("/v1/connections/garmin_personal?since=2026-01-01", json={"api_key": API_KEY})
    up = client.post("/v1/uploads/apple_health", content=json.dumps(phone_json()))
    ride_id = up.json()["ride_id"]
    assert client.get(f"/v1/rides/{ride_id}").json()["sources"] == ["apple_watch", "garmin"]
    # Deleting the merged ride removes both recordings (Garmin's and the Watch's).
    r = client.delete(f"/v1/rides/{ride_id}")
    assert r.status_code == 200 and r.json()["recordings_deleted"] == 2
    assert client.get(f"/v1/rides/{ride_id}").status_code == 404
    assert [d["ride_id"] for d in client.get("/v1/rides").json()] == [str(int(T0 + 86400))]
    # It stays deleted: a re-sync doesn't download it, a re-upload is accepted but ignored.
    downloads = len(garmin.downloads)
    client.post("/v1/connections/garmin_personal/sync?since=2026-01-01")
    assert len(garmin.downloads) == downloads
    again = client.post("/v1/uploads/apple_health", content=json.dumps(phone_json()))
    assert again.status_code == 201 and again.json()["ride_id"] is None
    assert len(client.get("/v1/rides").json()) == 1
    assert client.delete("/v1/rides/123").status_code == 404
    # Insights forget it too.
    assert client.get("/v1/you").json()["all"]["rides"] == 1


def test_you_power_from_a_trainer_ride(env):
    be, uid, client, _ = env
    assert client.get("/v1/you").json()["power"] is None  # no measured power yet
    # An indoor Watch ride with a paired trainer: heart rate, plus power and cadence about once a second.
    start, minutes = T0 + 3 * 86400, 30
    samples = [{"t": start + i, "hr": 140} for i in range(0, minutes * 60, 5)]
    samples += [{"t": start + i * 1.05, "power": 0.0 if 600 <= i < 660 else 180.0, "cadence": 85}
                for i in range(int(minutes * 60 / 1.05))]
    rec = {"format": "rideengine.recording/1", "source": "apple_watch", "device": "Apple Watch", "start": start,
           "end": start + minutes * 60, "sport": "cycling", "indoor": True, "origin": "healthkit:TRAINER-1",
           "totals": {"distance_m": 15000.0, "calories": 400.0, "avg_hr": 140.0, "max_hr": 150.0,
                      "elapsed_s": minutes * 60.0}, "samples": samples}
    assert client.post("/v1/uploads/apple_health", content=json.dumps(rec)).status_code == 201
    be.insights.refresh(uid)
    p = client.get("/v1/you").json()["power"]
    assert p["latest"]["avg_power"] == 180.0            # pedalling time only: the minute at zero is left out
    assert p["best_60s"] == 180 and p["best_1200s"] == 171   # every 20 minutes includes the stopped minute
    assert p["ftp"] == {"watts": 162, "source": "estimated from your best 20 minutes"}
    y = client.get("/v1/you").json()
    assert y["all"]["km"] == y["all"]["indoor"]["km"]  # a trainer's km count, split out as indoor
    # The headline card: sustained power and punch measured; no goal, so targets are proposals.
    hl = {m["id"]: m for m in y["headline"]["metrics"]}
    assert hl["sustained"]["current"] == 162 and hl["sustained"]["target"] == 170 and hl["punch"]["current"] == 180
    assert y["headline"]["goal"] is None
    # With a goal, the targets are kept with it and don't move.
    client.put("/v1/goals/current", json={"objective": "faster", "aspiration": "keep_up_group"})
    stored = json.loads(be.db.execute("SELECT data FROM goals WHERE user_id = ? AND active = 1", (uid,)).fetchone()[0])
    assert stored["targets"]["sustained"] == {"baseline": 162, "target": 178, "unit": "W"}
    hl = {m["id"]: m for m in client.get("/v1/you").json()["headline"]["metrics"]}
    assert hl["sustained"]["target"] == 178 and hl["sustained"]["focus"] and hl["sustained"]["progress"] == 0


def test_course_upload_check_and_export(env, tmp_path):
    """A GPX from Ride with GPS: checked against a (fake) map, listed, exported for the Edge, deleted."""
    from rideengine.importers.fit import decode
    from rideengine.routes.course import gpx_course
    from test_routes import synthetic
    be, uid, client, _ = env
    route, data = synthetic()
    be.map_source = lambda r: data
    gpx = gpx_course(route, {"stops": []})
    r = client.post("/v1/courses", content=gpx)
    assert r.status_code == 202, r.text
    c = r.json()
    assert c["status"] == "ready" and c["name"] == "Test loop" and 19 <= c["km"] <= 21
    assert c["report"]["midway"]["name"] == "Corner Café" and c["singletrack_km"] >= 1.5
    assert c["shape"] and c["verdict"]
    listed = client.get("/v1/courses").json()["courses"]
    assert [x["id"] for x in listed] == [c["id"]] and "report" not in listed[0]
    fit = client.get(f"/v1/courses/{c['id']}/course.fit")
    assert fit.status_code == 200 and 'filename="Test_loop.fit"' in fit.headers["content-disposition"]
    assert any(m == 32 for m, _ in decode(fit.content))
    assert client.get(f"/v1/courses/{c['id']}/course.gpx").content.startswith(b"<?xml")
    assert client.patch(f"/v1/courses/{c['id']}", json={"name": "Goodwood gravel"}).json()["name"] == "Goodwood gravel"
    # The map being down keeps the route, marked failed, to check again later.
    be.map_source = lambda r: (_ for _ in ()).throw(RuntimeError("OpenStreetMap lookup failed: timed out"))
    bad = client.post("/v1/courses", content=gpx).json()
    assert bad["status"] == "failed" and "timed out" in bad["error"]
    be.map_source = lambda r: data
    assert client.post(f"/v1/courses/{bad['id']}/check").status_code == 202
    assert client.get(f"/v1/courses/{bad['id']}").json()["status"] == "ready"
    assert client.post("/v1/courses", content=b"<gpx></gpx>").status_code == 400
    assert client.delete(f"/v1/courses/{c['id']}").json() == {"deleted": c["id"]}
    assert client.get(f"/v1/courses/{c['id']}").status_code == 404


def test_course_tuning_versions_and_undo(env):
    """Tune a checked route (start, stop, shorter), see each change, undo back to the original."""
    from rideengine.routes.course import gpx_course
    from rideengine.routes.router import Graph
    from test_tune import Flat, grid, node, ring
    be, uid, client, _ = env
    ways = grid(n=11, gravel_rows=(5,))
    cafe = node(5, 10)
    data = {"ways": ways, "fetched": None,
            "pois": [{"id": "n1", "lat": cafe[0], "lon": cafe[1], "kind": "food", "name": "Canter Coffee",
                      "what": "cafe", "hours": ""}]}
    be.map_source = lambda r: data
    be.graph_source = lambda r, prefs: Graph(ways, prefs)
    be.heights = Flat()
    route = ring(1, 1, 9, 9)
    c = client.post("/v1/courses", content=gpx_course(route, {})).json()
    assert c["status"] == "ready" and c["changes"] == []
    opts = client.get(f"/v1/courses/{c['id']}/options").json()
    assert [s["name"] for s in opts["stops"]] == ["Canter Coffee"] and opts["stops"][0]["off_m"] > 900
    assert "fills_gap" in opts["stops"][0] and "gap" in opts
    r = client.post(f"/v1/courses/{c['id']}/tune", json={"op": "stop", "lat": cafe[0], "lon": cafe[1],
                                                         "name": "Canter Coffee"})
    assert r.status_code == 200, r.text
    t1 = r.json()
    assert t1["km"] > c["km"] + 1.5 and "Canter Coffee" in t1["changes"][0]["change"]
    assert t1["report"]["stops"][0]["items"][0]["name"] == "Canter Coffee"
    t2 = client.post(f"/v1/courses/{c['id']}/tune", json={"op": "length", "km": -10}).json()
    assert t1["km"] - 13 < t2["km"] < t1["km"] - 7 and len(t2["changes"]) == 2
    assert t2["report"]["stops"], "the added stop survives the shortcut"
    assert client.get(f"/v1/courses/{c['id']}/course.fit").status_code == 200
    bad = client.post(f"/v1/courses/{c['id']}/tune", json={"op": "length", "km": 0.2})
    assert bad.status_code == 422 and "at least 1 km" in bad.json()["detail"]
    assert client.post(f"/v1/courses/{c['id']}/tune", json={"op": "fly"}).status_code == 422
    u1 = client.post(f"/v1/courses/{c['id']}/undo").json()
    assert u1["km"] == t1["km"] and len(u1["changes"]) == 1
    u0 = client.post(f"/v1/courses/{c['id']}/undo").json()
    assert u0["km"] == c["km"] and u0["changes"] == []
    assert client.post(f"/v1/courses/{c['id']}/undo").json()["km"] == c["km"]   # nothing left to undo
    client.post(f"/v1/courses/{c['id']}/tune", json={"op": "length", "km": 5})
    assert client.delete(f"/v1/courses/{c['id']}").status_code == 200
    import os
    assert not [f for f in os.listdir(os.path.join(be.settings.raw_dir, str(uid), "courses"))]


def test_plan_routes_from_a_description(env):
    """Words in, questions for what's missing, then three loops saved and checked like any route."""
    from rideengine.routes.router import Graph
    from test_tune import Flat, grid, node
    be, uid, client, _ = env
    ways = grid(n=26, gravel_rows=tuple(range(0, 26, 2)))
    cafe = node(12, 16)
    stops = [{"id": "n1", "lat": cafe[0], "lon": cafe[1], "kind": "food", "name": "Canter Coffee", "what": "cafe",
              "hours": ""}]
    be.area_source = lambda bbox, prefs: (Graph(ways, prefs), stops, [])
    be.map_source = lambda r: {"ways": ways, "pois": stops, "fetched": None}
    be.heights = Flat()
    be.gravel_grid = {}          # no gravel map: no "not much gravel here" question
    r = client.post("/v1/courses/plan", json={"text": "40-50 km gravel loop, coffee halfway"})
    assert r.status_code == 200, r.text
    first = r.json()
    assert [q["key"] for q in first["questions"]] == ["start"] and "courses" not in first
    start = node(12, 4)
    r = client.post("/v1/courses/plan", json={"ask": first["ask"],
                                              "answers": {"start": {"name": "Goodwood", "lat": start[0], "lon": start[1]}}})
    assert r.status_code == 200, r.text
    made = r.json()
    assert "FROM GOODWOOD" in made["ask"]["tags"] and len(made["courses"]) >= 2
    c = made["courses"][0]
    assert c["source"] == "generated" and c["status"] == "ready" and 38 <= c["km"] <= 52
    assert c["plan"]["stop"]["name"] == "Canter Coffee" and c["plan"]["why"]
    assert {x["id"] for x in client.get("/v1/courses").json()["courses"]} >= {x["id"] for x in made["courses"]}
    bad = client.post("/v1/courses/plan", json={"ask": first["ask"], "answers": {"start": {"name": "Sea", "lat": 0.0, "lon": 0.0}}})
    assert bad.status_code == 422
    # A street address we can't place ourselves: asked about, with the words, for the app to look up.
    one = client.post("/v1/courses/plan", json={"text": "One-way from Goodwood to 48 Sample Cres in Markham. Road ride."}).json()
    assert one["ask"]["shape"] == "oneway" and [q["key"] for q in one["questions"]][0] == "end"
    assert one["questions"][0]["guess"] == "48 Sample Cres, Markham"
    end = node(12, 14)
    r = client.post("/v1/courses/plan", json={"ask": {**first["ask"], **one["ask"], "start": made["ask"]["start"]},
                                              "answers": {"end": {"name": "48 Sample Cres", "lat": end[0], "lon": end[1]}}})
    assert r.status_code == 200, r.text
    assert r.json()["ask"]["guess"] == {} and r.json()["courses"][0]["name"].startswith("Goodwood to 48 Sample Cres")
    # The café asked for is the route's rest stop.
    assert any(p["name"] == "Canter Coffee" for p in client.get(f"/v1/courses/{c['id']}").json()["report"]["rest"])
    # A gravel loop from somewhere with all paved roads around: asked first, and "anyway" makes them.
    from rideengine.routes import osm
    be.gravel_grid = {(i, j): {"paved": 50000} for i in range(1090, 1110) for j in range(-1600, -1570)}
    goodwood = made["ask"]["start"]
    q = client.post("/v1/courses/plan", json={"ask": {**first["ask"], "start": goodwood}, "answers": {}}).json()
    assert q["questions"][0]["key"] == "gravel_start" and "Not much gravel" in q["questions"][0]["q"]
    assert q["questions"][0]["choices"][-1] == {"label": "From Goodwood anyway", "value": "stay"} and "courses" not in q
    r = client.post("/v1/courses/plan", json={"ask": q["ask"], "answers": {"gravel_start": "stay"}})
    assert r.status_code == 200 and r.json()["courses"]


def test_home_set_by_the_rider_or_from_rides(env):
    """Home is where most of the past year's rides start, unless the rider sets it."""
    be, uid, client, _ = env
    be.gravel_grid = {}
    first = client.get("/v1/home").json()
    assert first["source"] in (None, "rides")
    r = client.put("/v1/home", json={"lat": 43.70, "lon": -79.37, "label": "12 Example St"})
    assert r.status_code == 200 and r.json() == {"lat": 43.7, "lon": -79.37, "label": "12 Example St",
                                                 "source": "set", "rides": None}
    assert be.home_point(uid) == (43.7, -79.37)
    ask = client.post("/v1/courses/plan", json={"text": "gravel loop from home"}).json()["ask"]
    assert (ask["start"]["lat"], ask["start"]["lon"]) == (43.7, -79.37)
    assert client.put("/v1/home", json={"lat": 123, "lon": 0}).status_code == 400
    back = client.delete("/v1/home").json()
    assert back["source"] != "set" and be.home_set(uid) is None


def test_new_garmin_rides_arrive_without_tapping_sync(env):
    """The app asks when it opens (/v1/refresh), and the server polls: Garmin is pulled, not pushed."""
    be, uid, client, garmin = env
    client.put("/v1/connections/garmin_personal?since=2026-01-01", json={"api_key": API_KEY})
    assert len(client.get("/v1/rides").json()) == 2
    garmin.rides[333] = write_fit(line_ride(40, start=T0 + 2 * 86400).samples, {"distance_m": 15000, "elapsed_s": 2400})
    assert client.post("/v1/refresh").json() == {"synced": {}}          # synced moments ago: not yet
    be.db.execute("UPDATE connections SET last_sync_at = last_sync_at - 600")
    assert client.post("/v1/refresh").json() == {"synced": {"garmin_personal": 1}}
    assert len(client.get("/v1/rides").json()) == 3
    # The server's poller does the same for every rider.
    be.db.execute("UPDATE connections SET last_sync_at = last_sync_at - 3600")
    garmin.rides[444] = write_fit(line_ride(20, start=T0 + 3 * 86400).samples, {"distance_m": 8000, "elapsed_s": 1200})
    be.start_polling(interval_s=0.05)
    import time
    for _ in range(100):
        if 444 in garmin.downloads:
            break
        time.sleep(0.05)
    be._stop.set()
    assert 444 in garmin.downloads
