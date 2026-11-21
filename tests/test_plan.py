"""Training plans (rideengine/analysis/plan.py) and the plan API. Synthetic data only."""
from datetime import date, datetime, timedelta, timezone

import pytest

from rideengine.analysis import plan

SEASON = {"months": {str(m): k for m, k in zip(range(1, 13), ["indoor", "indoor", "mixed", "mixed", "outdoor", "outdoor",
                                                            "outdoor", "outdoor", "outdoor", "mixed", "indoor", "indoor"])}}
GOAL = {"id": 1, "aspiration": "keep_up_group", "ready_by": "2027-05-01"}
DAYS = ["Mon", "Wed", "Fri", "Sun"]
TIMES = {"Mon": "10:45", "Wed": "10:00", "Fri": "10:15", "Sun": "07:45"}


def build(**kw):
    return plan.build_plan(GOAL, date(2026, 11, 15), SEASON, DAYS, TIMES, 4.5, start=date(2026, 11, 16), **kw)


def test_phases_and_weeks():
    p = build()
    ph = [w["phase"] for w in p["weeks"]]
    assert ph[0] == "base" and ph[-1] == "taper" and "build" in ph and "sharpen" in ph
    assert ph[3] == "recovery" and ph[7] == "recovery"                   # an easier week every fourth
    rec, normal = p["weeks"][3]["hours"], p["weeks"][2]["hours"]
    assert rec < normal * 0.8
    assert all(s["date"] <= "2027-05-01" for w in p["weeks"] for s in w["sessions"])


def test_sessions_on_the_riders_days_and_times():
    first = build()["weeks"][0]["sessions"]
    bike = [s for s in first if not s["off_bike"]]
    assert {datetime.fromisoformat(s["date"]).strftime("%a") for s in bike} == set(DAYS)
    longest = max(bike, key=lambda s: s["seconds"])
    assert longest["date"] == "2026-11-22" and longest["kind"] == "group" and longest["time"] == "07:45"
    assert longest["indoor"] and longest["title"] == "Group ride"     # the trainer's season; still the rider's choice
    assert any(s["kind"] == "strength" and s["off_bike"] for s in first)
    assert bike[0]["kind"] == "surges"                                    # the key session first


def test_surges_progress_and_have_structure():
    p = build()
    surges = [s for w in p["weeks"] for s in w["sessions"] if s["kind"] == "surges"]
    reps = [s["steps"][1]["repeat"] for s in surges]
    assert reps[0] == 5 and max(reps) == 8                                # more reps as the weeks go on
    s = surges[-2]
    assert s["steps"][0]["label"] == "Warm up" and s["steps"][-1]["label"] == "Cool down"
    assert s["seconds"] == sum(plan.flatten(s["steps"])[i]["seconds"] for i in range(len(plan.flatten(s["steps"]))))


def test_targets_watts_and_heart_rate():
    hrz = plan.hr_zones(180, 55)
    s = next(x for x in build()["weeks"][10]["sessions"] if x["kind"] == "surges")
    t = plan.targets(s, 250, hrz)
    hard = t["steps"][1]["steps"][0]["target"]
    assert hard["watts"] == [302, 375] and "hr" not in hard               # 1 min: too short to ride by heart rate
    warm = t["steps"][0]["target"]
    assert warm["watts"][0] == 100 and warm["hr"] == hrz["Z2"]
    no_ftp = plan.targets(s, None, hrz)["steps"][1]["steps"][0]["target"]
    assert "watts" not in no_ftp and no_ftp["pct_ftp"] == [121, 150]
    assert t["load"] > 30


def test_ftp_and_zones():
    assert plan.ftp_estimate(240, {"1200": 300}) == {"watts": 240, "source": "yours"}
    assert plan.ftp_estimate(None, {"1200": 300})["watts"] == 285
    assert plan.ftp_estimate(None, {})["watts"] is None
    assert plan.hr_zones(180, 55)["Z2"] == [130, 142]
    assert plan.max_hr_estimate([150] * 50 + [178, 181, 240]) == 178


def test_usual_days_spread_out():
    starts = [datetime(2026, 9, d, 10) for d in (7, 14, 21, 8, 15, 9, 16, 23, 30, 11, 18)]  # Mon, Tue, Wed, Fri
    assert plan.usual_days(starts, 3) == ["Mon", "Wed", "Fri"]
    assert plan.usual_times(starts)["Mon"] == "10:00"


def test_status():
    s = {"id": "x", "date": "2026-11-20", "seconds": 3600, "off_bike": False}
    assert plan.status(s, [{"moving_s": 2400}], date(2026, 11, 22), set()) == "done"
    assert plan.status(s, [{"moving_s": 1200}], date(2026, 11, 22), set()) == "missed"
    assert plan.status(s, [], date(2026, 11, 20), set()) == "today"
    assert plan.status({**s, "off_bike": True}, [], date(2026, 11, 22), {"x"}) == "done"


def test_exports():
    hrz = plan.hr_zones(180, 55)
    s = plan.targets(next(x for x in build()["weeks"][10]["sessions"] if x["kind"] == "surges"), 250, hrz)
    zwo = plan.to_zwo(s)
    assert '<IntervalsT Repeat="' in zwo and "<Warmup" in zwo and "<Cooldown" in zwo
    ics = plan.to_ics([s], timezone(timedelta(hours=-5)))
    assert ics.startswith("BEGIN:VCALENDAR") and "SUMMARY:Surges" in ics and ics.count("BEGIN:VEVENT") == 1
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))
    assert "DTSTART:20270125T154500Z" in ics or "DTSTART:" in ics


def test_plan_api(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("cryptography")
    from fastapi.testclient import TestClient

    from backend.app import create_app
    from backend.config import Settings
    from backend.connectors.apple_health import AppleHealth
    from backend.service import Backend
    from rideengine.analysis import repeats
    from test_insights import loops, upload
    monkeypatch.setattr(repeats, "load_places", lambda boxes: [])
    settings = Settings(data_dir=str(tmp_path), database=str(tmp_path / "db.sqlite3"), raw_dir=str(tmp_path / "raw"),
                        secret_key_file=str(tmp_path / "secret.key"), public_base_url="http://test")
    be = Backend(settings, registry={"apple_health": AppleHealth()})
    uid, token = be.create_user()
    client = TestClient(create_app(be), headers={"Authorization": f"Bearer {token}"})
    for n, r in enumerate(loops()):
        upload(client, r, n)

    assert client.get("/v1/plan").status_code == 404
    ready = (date.today() + timedelta(weeks=12)).isoformat()
    client.put("/v1/goals/current", json={"objective": "faster", "aspiration": "keep_up_group",
                                          "params": {"group_kmh": 30, "weekly_hours": 4.5}, "ready_by": ready})
    v = client.get("/v1/plan").json()
    assert v["weeks"] and v["ftp"]["watts"] is None and v["weekly_hours"] == 4.5
    s = next(x for w in v["weeks"] for x in w["sessions"] if x["kind"] == "surges")
    assert "pct_ftp" in s["steps"][1]["steps"][0]["target"] and s["summary"]

    assert client.put("/v1/me", json={"ftp": 240}).json()["ftp"] == 240
    s2 = client.get(f"/v1/plan/sessions/{s['id']}").json()
    assert s2["steps"][1]["steps"][0]["target"]["watts"] == [290, 360]
    assert client.put("/v1/me", json={"ftp": 5000}).status_code == 400

    r = client.put("/v1/plan/settings", json={"days": ["Tue", "Thu", "Sat"], "times": {"Sat": "08:00"}})
    days = {datetime.fromisoformat(x["date"]).strftime("%a") for w in r.json()["weeks"] for x in w["sessions"]
            if not x["off_bike"] and x["date"] >= date.today().isoformat()}
    assert days <= {"Tue", "Thu", "Sat"}
    assert client.put("/v1/plan/settings", json={"days": ["Funday"]}).status_code == 400

    strength = next(x for w in r.json()["weeks"] for x in w["sessions"] if x["off_bike"])
    assert client.put(f"/v1/plan/sessions/{strength['id']}/done").json()["done"]
    assert client.get(f"/v1/plan/sessions/{strength['id']}").json()["status"] == "done"
    zwo = client.get(f"/v1/plan/sessions/{s['id']}/zwift")
    assert zwo.status_code == 200 and "<workout_file>" in zwo.text

    cal = client.get("/v1/plan/calendar").json()
    assert cal["webcal"].startswith("webcal://") and cal["url"].endswith(".ics")
    feed = TestClient(client.app).get("/calendar/" + cal["url"].rsplit("/", 1)[1])   # no login
    assert feed.status_code == 200 and "BEGIN:VEVENT" in feed.text
    new = client.get("/v1/plan/calendar?reset=true").json()
    assert new["url"] != cal["url"]
    assert TestClient(client.app).get("/calendar/" + cal["url"].rsplit("/", 1)[1]).status_code == 404
    client.delete("/v1/goals/current")
    assert client.get("/v1/plan").status_code == 404


def test_no_empty_first_week():
    p = plan.build_plan(GOAL, date(2026, 11, 15), SEASON, ["Mon", "Wed", "Fri"], TIMES, 3, start=date(2026, 11, 15))
    assert p["weeks"][0]["week_start"] == "2026-11-16" and p["weeks"][0]["sessions"]
