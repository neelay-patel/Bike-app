"""Goals engine (rideengine/analysis/goals.py) and the goals API. Synthetic data only."""
from datetime import date, datetime, timedelta, timezone

import pytest

from rideengine.analysis import goals, headline, records
from rideengine.model import Sample

UTC = timezone.utc
TODAY = date(2026, 11, 15)


def feat(day: date, km: float, kmh: float = 25.0, up: float = 100, indoor: bool = False, hr: float | None = 135):
    t = datetime(day.year, day.month, day.day, 9, tzinfo=UTC).timestamp()
    return {"ride_id": str(int(t)), "start": t, "km": 0.0 if indoor else km, "ascent_m": None if indoor else up,
            "moving_s": (0.75 if indoor else km / kmh) * 3600, "kmh": None if indoor else kmh, "power": None,
            "indoor": indoor, "avg_hr": hr}


def entries(fs):
    return records.entries_from_features(fs, UTC)


def two_seasons():
    """Outdoor May to September, indoor November to March, for two years."""
    fs = []
    d = date(2024, 11, 18)
    while d < TODAY:
        if d.month in (5, 6, 7, 8, 9):
            fs.append(feat(d, 40, kmh=25 + (d.month - 5) * 0.2))
        elif d.month in (11, 12, 1, 2, 3):
            fs.append(feat(d, 0, indoor=True))
        d += timedelta(days=4)
    return fs


def test_seasons_from_history():
    s = goals.seasons(entries(two_seasons()), TODAY)
    assert s["now"] == "indoor" and s["outdoor_months"] == [5, 6, 7, 8, 9]
    assert s["outdoor_from"] == "2027-05-01"
    summer = goals.seasons(entries(two_seasons()), date(2026, 7, 1))
    assert summer["now"] == "outdoor" and summer["outdoor_until"] == "2026-09-30"


def test_solo_pace_ignores_hills_and_short_rides():
    fs = [feat(TODAY - timedelta(days=i * 3), 40, kmh=26) for i in range(1, 6)]
    fs += [feat(TODAY - timedelta(days=2), 15, kmh=35), feat(TODAY - timedelta(days=1), 40, kmh=19, up=900)]
    assert goals.solo_pace(entries(fs), TODAY)["typical"] == 26.0


def test_drafting_and_heart_rate_scaling():
    assert 1.05 < goals.draft_ratio(26, 30) < 1.2          # ~10% more power to sit in at 30
    assert goals.draft_ratio(30, 30) < 1                   # the same speed is easier in the draft
    assert goals.speed_at_hr(25, 140, 55, 140) == 25       # at the reference, unchanged
    assert goals.speed_at_hr(25, 150, 55, 140) < 25        # working harder: worth less at the reference
    assert goals.speed_at_hr(25, 60, 55, 140) is None      # too close to resting to say


def test_power_curve_from_measured_power():
    t0 = 1_790_000_000.0
    samples = [Sample(t=t0 + i, power=150) for i in range(600)]
    samples[100:160] = [Sample(t=t0 + 100 + i, power=400) for i in range(60)]
    pc = goals.power_curve(samples, durations=(5, 60, 300, 1200))
    assert pc["5"] == 400 and pc["60"] == 400 and pc["300"] == 200 and "1200" not in pc
    best = goals.best_power_curve([{"start": t0, "power_curve": pc}, {"start": t0, "power_curve": {"60": 420}}])
    assert best["60"] == 420 and best["5"] == 400


def found_with_home_loop(fs):
    laps = [{"ride_id": f["ride_id"], "start": f["start"], "kmh": f["kmh"], "avg_hr": f["avg_hr"]} for f in fs if f["kmh"]]
    return {"routes": [{"id": "r1", "name": "Home loop", "home": True, "laps": laps}], "climbs": []}


def test_reveal_and_markers_for_keeping_up():
    fs = [feat(TODAY - timedelta(days=60 + i * 4), 40, kmh=25.5 + i * 0.1, hr=136) for i in range(12)]
    es, found = entries(fs), found_with_home_loop(fs)
    g = {"objective": "faster", "aspiration": "keep_up_group", "params": {"group_kmh": 30, "terrain": "rolling"}}
    r = goals.reveal(g, es, found, TODAY, 55)
    assert r["figures"]["group_kmh"] == 30 and 5 < r["figures"]["draft_power_pct"] < 20
    assert [b["id"] for b in r["build"]][:2] == ["surges", "sustained"] and "rises" in r["build"][0]["line"]
    # The markers are the four headline numbers with the goal's targets (no route-specific ones).
    four = headline.four(fs, TODAY, g)
    ms = {m["id"]: m for m in goals.markers(g, es, TODAY, four["metrics"])}
    assert list(ms) == ["sustained", "punch", "efficiency", "durability"]
    assert ms["punch"]["pending"] and ms["sustained"]["current"] is None and ms["punch"]["focus"]
    fs[-1]["power_curve"] = {"60": 410, "1200": 230}
    four = headline.four(fs, TODAY, g)
    ms = {m["id"]: m for m in goals.markers(g, es, TODAY, four["metrics"])}
    assert ms["punch"]["current"] == 410 and ms["punch"]["target"] == 451  # a focus: +10%
    assert ms["sustained"]["current"] == 218 and four["targets_changed"]


def test_headline_targets_stay_put_as_the_rider_improves():
    fs = [feat(TODAY - timedelta(days=30 - i), 40) for i in range(10)]
    for i, f in enumerate(fs):
        f["m_per_beat"] = 3.0 + i * 0.01
    fs[0]["power_curve"] = {"60": 300, "1200": 200}
    g = {"aspiration": "first_distance"}
    first = headline.four(fs, TODAY, g)
    m = {x["id"]: x for x in first["metrics"]}
    assert m["sustained"]["current"] == 190 and m["sustained"]["target"] == 200    # not a focus: +5%
    assert m["efficiency"]["unit"] == "m/beat" and m["efficiency"]["target"] == round(m["efficiency"]["current"] * 1.06, 2)
    assert m["durability"]["pending"] and m["durability"]["target"] is None
    # Later, with the targets kept: a better 20 minutes moves progress, not the target.
    fs[-1]["power_curve"] = {"60": 310, "1200": 205}
    later = headline.four(fs, TODAY, {**g, "targets": first["targets"]})
    s = {x["id"]: x for x in later["metrics"]}["sustained"]
    assert s["current"] == 195 and s["target"] == 200 and s["progress"] == 0.5 and not later["targets_changed"]
    # A long ride gives durability its target then.
    fs[-1]["hold"] = 96.0
    third = headline.four(fs, TODAY, {**g, "targets": first["targets"]})
    d = {x["id"]: x for x in third["metrics"]}["durability"]
    assert d["current"] == 96 and d["target"] == 100 and third["targets_changed"]
    assert third["next"]["id"] in ("durability", "efficiency")    # a focus metric comes first


def test_efficiency_from_power_when_the_rider_has_it_lately():
    fs = [feat(TODAY - timedelta(days=100 - i), 40) for i in range(5)]
    for f in fs:
        f["m_per_beat"] = 3.1
    assert {x["id"]: x for x in headline.current(fs, TODAY)}["efficiency"]["unit"] == "m/beat"
    trainer = feat(TODAY - timedelta(days=2), 0, indoor=True)
    trainer["w_per_beat"] = 1.05
    eff = {x["id"]: x for x in headline.current(fs + [trainer], TODAY)}["efficiency"]
    assert eff["unit"] == "W/beat" and eff["current"] == 1.05


def test_watts_per_beat_and_durability_from_samples():
    from rideengine.model import Ride
    t0 = 1_790_000_000.0
    n = 3 * 3600
    # Steady 150 W; heart rate drifts from 125 to 140 bpm over the last quarter: a fade.
    samples = [Sample(t=t0 + i, power=150, hr=125 if i < 0.75 * n else 140) for i in range(n)]
    ride = Ride(start=t0, end=t0 + n, sport="cycling", indoor=True, samples=samples, totals={},
                provenance={"channel:power": "kickr"}, recordings=[])
    assert headline.watts_per_beat(ride) == 1.2
    assert headline.hold(ride) == round(100 * 125 / 140, 1)
    short = Ride(start=t0, end=t0 + 3600, sport="cycling", indoor=True, samples=samples[:3600], totals={},
                 provenance={"channel:power": "kickr"}, recordings=[])
    assert headline.hold(short) is None


def test_options_quote_the_riders_bests():
    fs = [feat(TODAY - timedelta(days=i * 5), 60 + i, kmh=25) for i in range(6)]
    opts = {o["id"]: o for o in goals.options(entries(fs), found_with_home_loop(fs), TODAY)}
    further = opts["further"]["aspirations"][0]
    assert further["target_km"] == 80 and "65.0 km" in further["line"]
    assert "Home loop" not in opts["faster"]["aspirations"][1]["title"]


# --- API -------------------------------------------------------------------------------------
def test_goals_api(tmp_path, monkeypatch):
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

    opts = client.get("/v1/goals/options").json()
    assert [o["id"] for o in opts["objectives"]] == ["faster", "further", "stronger", "event"]
    assert client.get("/v1/goals/current").status_code == 404

    goal = {"objective": "faster", "aspiration": "keep_up_group", "words": "I keep getting dropped on Saturdays",
            "tags": ["faster", "keep up with a group"], "params": {"group_kmh": 30, "terrain": "hilly"}}
    preview = client.post("/v1/goals/preview", json=goal).json()
    assert preview["goal"]["title"] == "Keep up with the fast group" and preview["reveal"]["build"]
    assert client.get("/v1/goals/current").status_code == 404  # preview saves nothing

    first = client.put("/v1/goals/current", json=goal).json()
    assert first["goal"]["words"] == "I keep getting dropped on Saturdays" and first["markers"]
    second = client.put("/v1/goals/current", json={"objective": "further", "aspiration": "first_distance"}).json()
    assert second["goal"]["params"]["target_km"] and second["goal"]["id"] != first["goal"]["id"]
    assert client.get("/v1/goals/current").json()["goal"]["aspiration"] == "first_distance"
    assert be.db.execute("SELECT COUNT(*) FROM goals WHERE user_id = ?", (uid,)).fetchone()[0] == 2  # history kept

    for bad in ({"objective": "faster", "aspiration": "nope"}, {"objective": "faster", "aspiration": "keep_up_group",
                                                              "params": {"group_kmh": 90}},
                {"objective": "event", "aspiration": "event", "ready_by": "someday"}):
        assert client.put("/v1/goals/current", json=bad).status_code == 400
    assert client.delete("/v1/goals/current").json() == {"ended": True}
    assert client.get("/v1/goals/current").status_code == 404
