"""The fun bucket: avatar, badges, ratings, binder, holo and rider cards. Synthetic data only."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from rideengine.analysis import collection, records
from rideengine.card.avatar import DEFAULT, OPTIONS, avatar_svg, clean
from rideengine.card.ride_card import ride_card
from rideengine.card.rider_card import rider_card
from test_repeats import out_and_back

UTC = timezone.utc


def feat(day: str, km: float, up: float = 100, hours: float | None = None, hour: int = 9, indoor=False):
    t = datetime.fromisoformat(day).replace(hour=hour, tzinfo=UTC).timestamp()
    return {"ride_id": str(int(t)), "start": t, "km": km, "ascent_m": up,
            "moving_s": (hours if hours is not None else km / 25) * 3600, "kmh": 25.0,
            "power": None, "indoor": indoor, "hr_drop_60s": None}


def entries(feats):
    return records.entries_from_features(feats, UTC)


def weekly(n, start="2026-03-02", **kw):
    d0 = date.fromisoformat(start)
    return [feat((d0 + timedelta(weeks=i)).isoformat(), **kw) for i in range(n)]


# --- avatar ----------------------------------------------------------------------------------
def test_avatar_clean_and_draw():
    assert clean(None) == DEFAULT
    assert clean({"hair": "mohawk", "beard": "goatee", "extra": 1}) == {**DEFAULT, "beard": "goatee"}
    # Beard and moustache combine freely.
    assert clean({"beard": "stubble", "moustache": "handlebar"})["moustache"] == "handlebar"
    assert clean({"beard": "full", "moustache": "none"})["moustache"] == "none"
    # Avatars saved before they were separate look the same.
    assert clean({"beard": "moustache"}) == {**DEFAULT, "beard": "none", "moustache": "moustache"}
    assert clean({"beard": "full"})["moustache"] == "moustache"
    for k, opts in OPTIONS.items():
        for v in opts:  # every choice draws
            svg = avatar_svg({k: v})
            assert svg.startswith("<svg") and svg.endswith("</svg>")
    mono = avatar_svg({"jersey": "red"}, mono="#1D3A8C")
    assert "#D7263D" not in mono  # all tints of the one colour


# --- badges ----------------------------------------------------------------------------------
def test_badges_earned_on_the_right_ride():
    feats = weekly(12, km=40) + [feat("2026-06-01", 104, up=1100)]
    b = {x["id"]: x for x in collection.badges(entries(feats), {"routes": [], "climbs": []}, UTC)}
    assert b["ride_100"]["earned"] and b["ride_100"]["date"] == "2026-06-01"
    assert b["climb_1000"]["ride_id"] == feats[-1]["ride_id"]
    assert b["streak_10"]["earned"] and b["streak_10"]["date"] == "2026-05-04"
    assert not b["ride_150"]["earned"] and b["ride_150"]["progress"] == {"value": 104, "target": 150}
    assert b["km_1000"]["progress"]["value"] == 584  # 12 x 40 + 104
    assert not b["dawn"]["earned"]


def test_dawn_patrol_uses_local_time_away_from_home():
    home = (43.7, -79.4)
    toronto = {**feat("2026-07-01", 30, hour=10), "first": [43.7, -79.4]}       # 06:00 in Toronto (EDT)
    london = {**feat("2026-07-02", 30, hour=6), "first": [51.5, -0.1]}           # 07:00 in London (BST)
    local = collection.local_times([toronto, london], timezone(timedelta(hours=-4)), home)
    assert local[toronto["ride_id"]].hour == 6 and local[london["ride_id"]].hour == 7
    b = {x["id"]: x for x in collection.badges(entries([toronto, london]), {"routes": []}, UTC, local)}
    assert b["dawn"]["ride_id"] == toronto["ride_id"]


# --- ratings ---------------------------------------------------------------------------------
def test_ratings():
    r = collection.ratings(entries(weekly(26, start="2026-01-05", km=60, up=600, hours=2.5)), date(2026, 7, 1))
    assert set(r["ratings"]) == {"distance", "climbing", "speed", "endurance", "consistency"}
    assert all(1 <= v <= 99 for v in r["ratings"].values())
    assert r["ratings"]["consistency"] == 99 and r["type"] == "Metronome"
    assert collection.ratings([], date(2026, 7, 1))["overall"] <= 5


# --- binder ----------------------------------------------------------------------------------
def test_binder_pages_holo_and_gaps():
    feats = weekly(3, start="2026-03-02", km=40) + weekly(2, start="2026-04-06", km=40)  # 23 and 30 Mar missed
    es = entries(feats)
    notes = {feats[2]["ride_id"]: [{"kind": "distance", "text": "Your longest ride yet", "pb": True}],
             feats[3]["ride_id"]: [{"kind": "route", "text": "Your fastest home loop yet", "pb": True}]}
    page = collection.binder(es, notes, {feats[0]["ride_id"]: "Home loop"}, {}, date(2026, 4, 15))[0]
    assert page["year"] == 2026 and [c["number"] for c in page["cards"]] == [1, 2, 3, 4, 5]
    assert [c["holo"] for c in page["cards"]] == [False, False, True, False, False]  # a loop best isn't holo
    assert page["gaps"] == ["2026-03-23", "2026-03-30"]
    assert page["cards"][0]["name"] == "Home loop"


# --- cards -----------------------------------------------------------------------------------
def test_ride_card_with_avatar_and_holo():
    ride = out_and_back(0, 25)
    plain = ride_card(ride, number=3, places=[])
    fancy = ride_card(ride, number=3, places=[], avatar={"jersey": "red"}, holo=True)
    assert "holo" not in plain and "kit-card" not in plain
    assert "class=\"holo\"" in fancy and "★ PB · NO. 3" in fancy and "kit-card" in fancy
    assert "prefers-reduced-motion" in fancy


def test_silhouette_until_an_avatar_is_made():
    r = collection.ratings(entries(weekly(10, km=50)), date(2026, 5, 20))
    html = rider_card(r, None, name="Rider")
    assert "No avatar yet" in html and "kit-rider" not in html
    assert "kit-rider" in rider_card(r, {"beard": "full"})


def test_rider_card():
    r = collection.ratings(entries(weekly(10, km=50)), date(2026, 5, 20))
    html = rider_card(r, {"beard": "full"}, name="Neelay", badges_earned=5, badges_total=24)
    assert "Neelay" in html and f">{r['overall']}<" in html and "5/24 BADGES" in html


# --- API -------------------------------------------------------------------------------------
def test_api(tmp_path, monkeypatch):
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
    rides = loops()
    for n, r in enumerate(rides):
        upload(client, r, n)

    assert client.get("/v1/me").json()["avatar"] is None
    me = client.put("/v1/me", json={"name": "Neelay", "avatar": {"beard": "full", "hair": "mohawk"}}).json()
    assert me["name"] == "Neelay" and me["avatar"]["beard"] == "full" and me["avatar"]["hair"] == "short"
    assert "beard" in client.get("/v1/avatar/options").json()["options"]
    svg = client.post("/v1/avatar/preview", json={"glasses": "shades"})
    assert svg.headers["content-type"].startswith("image/svg+xml") and svg.text.startswith("<svg")

    c = client.get("/v1/collection").json()
    assert c["rider"]["name"] == "Neelay" and c["rider"]["badges_total"] == len(collection.BADGES)
    page = c["binder"][0]
    assert len(page["cards"]) == 5 and page["cards"][0]["name"] == "Home loop" and len(page["cards"][0]["shape"]) > 10

    card = client.get(f"/v1/rides/{int(rides[0].start)}/card").text
    assert "kit-card" in card  # the avatar behind the map
    assert "Neelay" in client.get("/v1/rider/card?fonts=local").text
    client.put("/v1/me", json={"avatar": None})
    assert client.get("/v1/me").json()["avatar"] is None


def test_indoor_session_without_distance():
    """Apple Watch indoor cycling: heart rate and calories, no GPS, no distance."""
    from rideengine.analysis.basics import summary
    from rideengine.model import Ride, Sample
    t0 = 1_790_000_000.0
    ride = Ride(start=t0, end=t0 + 1800, sport="cycling", indoor=True,
                samples=[Sample(t=t0 + i * 5, hr=120 + (i % 40)) for i in range(361)],
                totals={"elapsed_s": 1800, "calories": 300, "avg_hr": 135, "max_hr": 159},
                provenance={"channel:hr": "apple_watch"}, recordings=["healthkit:x"])
    s = summary(ride)
    assert s["km"] == 0 and s["moving_h"] == 0.5 and s["avg_kmh"] is None  # time from the workout, not 0
    html = ride_card(ride, places=[])
    # The same six numbers as any card (27 Nov 2026): distance and speed read "indoor" without a game's km.
    assert "30 minutes on the trainer." in html and "DISTANCE" in html and "AVG SPEED" in html
    assert ">indoor<" in html and "AVG HEART RATE" in html and "on the trainer</h1>" in html
    assert "The ride's effort" in html   # no track: the map is the effort


def test_indoor_mini_card_picture():
    """Indoor cards get a picture: the ride game's virtual route and world (Zwift), else the session's shape."""
    from rideengine.analysis import features
    from rideengine.model import Ride, Sample
    hr_only = Ride(start=0, end=3600, sport="cycling", indoor=True, totals={}, provenance={}, recordings=[],
                   samples=[Sample(t=float(i), hr=100 + i / 60) for i in range(0, 3600, 5)])
    f = features.extract(hr_only)
    assert f["trace_kind"] == "hr" and len(f["trace"]) == 48 and f["trace"][0] == 0 and f["trace"][-1] == 1
    assert not f.get("shape") and "world" not in f
    zwift = Ride(start=0, end=600, sport="cycling", indoor=True, totals={}, provenance={}, recordings=[],
                 samples=[Sample(t=float(i), lat=-11.65 + i * 1e-5, lon=166.95, hr=130) for i in range(600)])
    f = features.extract(zwift)
    assert f["world"] == "Watopia" and len(f["shape"]) == 49
    assert features.virtual_world(43.65, -79.38) is None  # Toronto is real
