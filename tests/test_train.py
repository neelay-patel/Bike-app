"""Train, step 1: what kind of training a ride was, and which planned session it counts as (synthetic rides,
no personal data). Neelay's own week is checked in test_real_rides.py when data/ is present."""
from datetime import date, datetime, timezone

from backend.service import Backend
from rideengine.analysis import features, train
from rideengine.model import Ride, Sample
from test_effort import T0, trainer

FTP = 150


def warm(minutes=10, watts=100):
    return [(minutes * 60, watts, 85, 10)]


def kind(ride, ftp=FTP):
    return train.classify(train.work(ride), ftp, 180, 50)


def test_surges():
    parts = warm()
    for _ in range(6):
        parts += [(60, 240, 95, 8), (120, 105, 85, 8)]
    parts += [(25 * 60, 110, 85, 12)]
    c = kind(trainer(T0, parts))
    assert c["kind"] == "surges" and c["confidence"] >= 0.8 and c["facts"]["surges"] == 6
    assert c["reason"].startswith("6 hard efforts of") and "easier riding between" in c["reason"]


def test_sweet_spot_blocks_set_by_the_trainer():
    parts = warm()
    for _ in range(3):
        parts += [(12 * 60, 135, 90, 1.5), (5 * 60, 85, 88, 1.5)]
    parts += [(8 * 60, 80, 80, 10)]
    c = kind(trainer(T0, parts))
    assert c["kind"] == "steady" and "3 steady blocks, 36 minutes" in c["reason"]
    assert "just below what you could hold for an hour" in c["reason"]
    assert "FTP" not in c["reason"]                  # plain words (docs/train-words.md)


def test_threshold_held_on_your_own():
    c = kind(trainer(T0, warm() + [(40 * 60, 150, 88, 12), (8 * 60, 90, 80, 8)]))
    assert c["kind"] == "threshold" and "right around what you could hold for an hour" in c["reason"]


def test_endurance_long_and_easy():
    assert kind(trainer(T0, [(90 * 60, 105, 85, 20)]))["kind"] == "endurance"
    assert kind(trainer(T0, [(170 * 60, 105, 85, 20)]))["kind"] == "long"
    assert kind(trainer(T0, [(40 * 60, 80, 80, 10)]))["kind"] == "easy"


def test_too_short_counts_as_nothing():
    c = kind(trainer(T0, [(10 * 60, 200, 90, 10)]))
    assert c["kind"] is None and c["reason"] == "Too short to count as a session."


def hr_ride(minutes, hr):
    samples = [Sample(t=T0 + i, hr=hr) for i in range(minutes * 60)]
    return Ride(start=T0, end=T0 + minutes * 60 - 1, sport="cycling", indoor=False, samples=samples, totals={},
                provenance={"channel:hr": "apple_watch"}, recordings=["test"])


def test_heart_rate_only_rides():
    w = train.work(hr_ride(80, 125))
    assert w["basis"] == "heart_rate" and w["p30"] == [] and w["minutes"] == 80
    assert train.classify(w, FTP, 180, 50)["kind"] == "endurance"
    assert train.classify(train.work(hr_ride(200, 135)), FTP, 180, 50)["kind"] == "long"
    hard = train.classify(train.work(hr_ride(60, 178)), FTP, 180, 50)
    assert hard["kind"] == "mixed" and "without power" in hard["reason"]
    # Outdoors without a power meter, long steady stretches still show by heart rate (indoors or out is the
    # rider's choice, so outdoor rides must be able to count as these sessions too).
    thr = train.classify(train.work(hr_ride(60, 165)), FTP, 180, 50)
    assert thr["kind"] == "threshold" and "judged by heart rate" in thr["reason"]
    assert train.classify(train.work(hr_ride(60, 155)), FTP, 180, 50)["kind"] == "steady"
    # No max or resting heart rate known: still a ride, just can't say what kind.
    assert train.classify(w, None, None, None)["kind"] == "mixed"


def test_features_store_the_work_once():
    f = features.extract(trainer(T0, warm() + [(40 * 60, 150, 88, 12)]))
    assert f["v"] == features.VERSION and f["work"]["basis"] == "power" and len(f["work"]["p30"]) > 250
    assert train.classify(f["work"], FTP)["kind"] == "threshold"


WEEK = [{"id": "w1-mon", "kind": "surges", "seconds": 3600, "date": "2026-11-16"},
        {"id": "w1-tue", "kind": "steady", "seconds": 3600, "date": "2026-11-17"},
        {"id": "w1-wed", "kind": "endurance", "seconds": 4500, "date": "2026-11-18"},
        {"id": "w1-fri", "kind": "group", "seconds": 3600, "date": "2026-11-20"},
        {"id": "w1-sat", "kind": "strength", "seconds": 1200, "date": "2026-11-21", "off_bike": True}]


def ride(rid, k, minutes=60, conf=0.9):
    return {"ride_id": rid, "minutes": minutes, "class": {"kind": k, "confidence": conf, "reason": f"{k} reason"}}


def test_each_ride_counts_as_the_session_it_fits_whatever_the_day():
    # Neelay's real week 1, by kind: Tue surges, Wed sweet spot, Thu threshold, Sat endurance.
    m = train.match_week(WEEK, [ride("tue", "surges"), ride("wed", "steady"), ride("thu", "threshold"),
                                ride("sat", "endurance", 85)])
    got = {sid: x["ride_id"] for sid, x in m["counted"].items()}
    assert got == {"w1-mon": "tue", "w1-tue": "wed", "w1-fri": "thu", "w1-wed": "sat"} and m["extra"] == []
    assert m["counted"]["w1-mon"]["reason"] == "surges reason"


def test_extra_rides_too_short_rides_and_moved_rides():
    m = train.match_week(WEEK, [ride("a", "surges"), ride("b", "surges"), ride("c", None)])
    assert m["counted"]["w1-mon"]["ride_id"] in ("a", "b")
    assert m["counted"]["w1-fri"]["ride_id"] in ("a", "b")       # a second surges ride does the group's job
    assert m["extra"] == ["c"]
    # Moved by hand: "a" counts as the endurance session, "b" as nothing.
    m = train.match_week(WEEK, [ride("a", "surges"), ride("b", "surges")], {"a": "w1-wed", "b": None})
    assert m["counted"] == {"w1-wed": {"ride_id": "a", "fit": None, "reason": "surges reason", "by_hand": True}}
    # A ride far too short for the session fits less well, so the long one wins it.
    m = train.match_week(WEEK, [ride("short", "endurance", 30), ride("long", "endurance", 80)])
    assert m["counted"]["w1-wed"]["ride_id"] == "long"


def test_the_week_in_the_plan_view():
    tz = timezone.utc
    tue = datetime(2026, 11, 17, 9, tzinfo=tz).timestamp()
    parts = warm()
    for _ in range(6):
        parts += [(60, 240, 95, 8), (120, 105, 85, 8)]
    parts += [(25 * 60, 110, 85, 12)]
    f = features.extract(trainer(tue, parts))
    old = {"ride_id": "old", "start": tue + 86400, "moving_s": 3600}   # features not refreshed yet: time only
    c = {"tz": tz, "today": date(2026, 11, 19), "feats": [f, old], "ftp": {"watts": FTP}, "max_hr": 180,
         "resting_hr": 50}
    week = {"week_start": "2026-11-16", "sessions": WEEK}
    counted = Backend._count_week(None, c, week, {})
    assert counted["counted"]["w1-mon"]["ride_id"] == f["ride_id"]
    assert counted["counted"]["w1-mon"]["kind_title"] == "Surges"
    assert counted["counted"]["w1-fri"]["ride_id"] == "old"           # mixed riding fits the group ride
    status = {s["id"]: Backend._session_status(s, counted, set(), week, c["today"]) for s in WEEK}
    assert status == {"w1-mon": "done", "w1-tue": "open", "w1-wed": "open", "w1-fri": "done",
                      "w1-sat": "upcoming"}
    # Once the week is over, what's left is missed; a session ticked by hand is done.
    status = {s["id"]: Backend._session_status(s, counted, {"w1-sat"}, week, date(2026, 11, 23)) for s in WEEK}
    assert status["w1-tue"] == "missed" and status["w1-sat"] == "done"
