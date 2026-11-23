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
    assert c["reason"] == "Hard efforts: 6 × 1 min at about 240 W, with easy riding between."
    assert c["facts"]["sets"] == [{"repeat": 6, "seconds": 60, "rest_s": 120, "power": 240}]


def test_sweet_spot_blocks_set_by_the_trainer():
    parts = warm()
    for _ in range(3):
        parts += [(12 * 60, 135, 90, 1.5), (5 * 60, 85, 88, 1.5)]
    parts += [(8 * 60, 80, 80, 10)]
    c = kind(trainer(T0, parts))
    assert c["kind"] == "steady" and c["reason"].startswith("3 × 12 min at about 135 W")
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
    # Counted by jobs: the surges did the punch job. A ride whose work isn't read yet does no job until it is.
    assert counted["counted"]["w1-mon"]["reason"].startswith("Punch")
    assert [x["ride_id"] for x in counted["extra"]] == ["old"]
    status = {s["id"]: Backend._session_status(s, counted, set(), week, c["today"]) for s in WEEK}
    assert status == {"w1-mon": "done", "w1-tue": "open", "w1-wed": "open", "w1-fri": "upcoming",
                      "w1-sat": "upcoming"}
    # Once the week is over, what's left is missed; a session ticked by hand is done.
    status = {s["id"]: Backend._session_status(s, counted, {"w1-sat"}, week, date(2026, 11, 23)) for s in WEEK}
    assert status["w1-tue"] == "missed" and status["w1-sat"] == "done"


# --- interval sets: the ride's own page and Train read them the same way ---------------------------------

def surges_as_planned():
    """Monday's surges as ridden: warm-up, 5 x 1 min hard / 2 min easy, 5 min easy, 5 x 30 s / 30 s, then 25
    minutes of steadier riding and a short cool-down."""
    parts = warm(8, 90)
    for _ in range(5):
        parts += [(60, 220, 95, 8), (120, 110, 88, 8)]
    parts += [(5 * 60, 115, 88, 8)]
    for _ in range(5):
        parts += [(30, 255, 98, 8), (30, 105, 88, 8)]
    parts += [(25 * 60, 150, 90, 12), (3 * 60, 70, 80, 5)]
    return trainer(T0, parts)


def test_sets_found_and_told_the_same_everywhere():
    from rideengine.analysis import effort
    ride = surges_as_planned()
    ph = effort.phases(ride)
    sets = [(x["repeat"], x["seconds"], x["rest_s"]) for x in ph["sets"]]
    assert sets == [(5, 60, 120), (5, 30, 30)]
    assert 215 <= ph["sets"][0]["power"] <= 225 and 248 <= ph["sets"][1]["power"] <= 262
    kinds = [p["kind"] for p in ph["phases"]]
    assert kinds[:4] == ["warm_up", "intervals", "riding", "intervals"]
    lines = " ".join(ph["lines"])
    assert "5 × 1 min hard at" in lines and "2 min easy between" in lines and "5 × 30 s hard at" in lines
    assert "Easy between the sets, 7 min" in lines and "Then your own riding" in lines
    assert "likely the climbs" not in lines                       # the efforts aren't mistaken for climbs
    c = kind(ride)
    assert c["kind"] == "surges"
    assert c["reason"].startswith("Hard efforts: 5 × 1 min at about 2") and "and 5 × 30 s at about 2" in c["reason"]


def test_ride_against_the_session():
    from rideengine.analysis import plan as p
    w = train.work(surges_as_planned())
    s = p.targets(p.workout("surges", 0.0, 55, True), FTP, None)
    a = train.against(s, w)
    assert [(r["set"], r["done"], r["planned"]) for r in a["sets"]] == [("5 × 1 min hard", 5, 5), ("5 × 30 s hard", 5, 5)]
    assert a["lines"][0].startswith("5 × 1 min hard: all 5, ") and "W planned" in a["lines"][0]
    assert a["summary"].startswith("Ridden as planned") and a["short"] == "5 × 1 min and 5 × 30 s hard, as planned."
    assert any(x.startswith("Then 2") and "where the plan had" in x for x in a["lines"])   # steady, not easy
    # Two of the five minutes missed: said plainly.
    parts = warm(8, 90)
    for _ in range(3):
        parts += [(60, 220, 95, 8), (120, 110, 88, 8)]
    parts += [(30 * 60, 110, 88, 8)]
    a = train.against(s, train.work(trainer(T0, parts)))
    assert a["sets"][0]["done"] == 3 and a["lines"][0].startswith("5 × 1 min hard: 3 of 5")
    assert a["summary"].startswith("Part of the session") and a["short"].endswith(": 3 of the 10 planned.")


# --- which jobs a ride did (docs/train-method.md) -------------------------------------------------------

def jobs(ride, ftp=FTP, **kw):
    return train.jobs_done(train.work(ride), ftp, 180, 50, **kw)


def test_jobs_from_the_sessions_as_ridden():
    from rideengine.analysis import plan as p
    # The surges as planned do the punch job, exactly as much as the lightest surges ask: done, not more.
    want = p.job_minutes(p.workout("surges", 0.0, 55, True))
    assert want == {"punch": 7.5}
    j = jobs(surges_as_planned(), want=want)
    assert [(x["job"], x["status"]) for x in j["jobs"]] == [("punch", "done")]
    assert j["jobs"][0]["line"] == "Punch: done. 5 × 1 min and 5 × 30 s, 7.5 min of hard efforts."
    assert j["summary"] == "Punch, done."
    # Sweet spot blocks: hold.
    parts = warm()
    for _ in range(3):
        parts += [(12 * 60, 135, 90, 1.5), (5 * 60, 85, 88, 1.5)]
    j = jobs(trainer(T0, parts + [(8 * 60, 80, 80, 10)]))
    assert j["jobs"][0]["job"] == "hold" and j["jobs"][0]["line"].startswith("Hold, and then some: 3 × 12 min at about 135 W")
    # 3-minute efforts: top end.
    parts = warm(12)
    for _ in range(5):
        parts += [(180, 185, 95, 6), (180, 90, 85, 6)]
    j = jobs(trainer(T0, parts + [(10 * 60, 100, 85, 8)]))
    assert [x["job"] for x in j["jobs"]] == ["top_end"] and "5 × 3 min" in j["jobs"][0]["line"]
    # Over-unders: the "under" is still sweet spot, so it's hold work all the way through.
    parts = warm(12)
    for _ in range(3):
        for _ in range(4):
            parts += [(60, 175, 92, 3), (60, 135, 90, 3)]
        parts += [(5 * 60, 85, 85, 5)]
    j = jobs(trainer(T0, parts + [(8 * 60, 80, 80, 5)]))
    assert [x["job"] for x in j["jobs"]] == ["hold"] and j["jobs"][0]["have_min"] == 24
    # Easy riding, and a long ride.
    assert [x["job"] for x in jobs(trainer(T0, [(40 * 60, 80, 80, 10)]))["jobs"]] == ["easy"]
    assert [x["job"] for x in jobs(trainer(T0, [(170 * 60, 105, 85, 20)]))["jobs"]] == ["long"]


def test_partly_done_leaves_the_rest_open():
    parts = warm(8, 90)
    for _ in range(3):
        parts += [(60, 220, 95, 8), (120, 110, 88, 8)]
    j = jobs(trainer(T0, parts + [(30 * 60, 110, 88, 8)]))
    (x,) = j["jobs"]
    assert x["job"] == "punch" and x["status"] == "part" and x["left_min"] == 2.0
    assert x["line"] == "Punch: 3 of 5 min done. 2 min more finishes it."
    assert j["summary"] == "Punch, partly done."


def test_one_ride_two_jobs_when_long_enough():
    # A long group ride with hard surges: punch, and the long job.
    parts = warm()
    for _ in range(12):
        parts += [(45, 240, 95, 10), (8 * 60, 120, 88, 15)]
    j = jobs(trainer(T0, parts + [(60 * 60, 115, 88, 15)]), long_min=130)
    assert [(x["job"], x["status"]) for x in j["jobs"]] == [("punch", "more"), ("long", "done")]
    assert j["jobs"][0]["line"].endswith("12 min in all, where the week asked for 5.")
    assert j["summary"] == "Punch, and then some; long, done."
    # The same surges in 90 minutes: punch only, the ride isn't long enough for the long job.
    parts = warm()
    for _ in range(8):
        parts += [(45, 240, 95, 10), (8 * 60, 120, 88, 15)]
    j = jobs(trainer(T0, parts + [(10 * 60, 100, 85, 10)]), long_min=130)
    assert [x["job"] for x in j["jobs"]] == ["punch"]
    # Easy never comes with a hard job; too short counts as nothing.
    assert jobs(trainer(T0, [(10 * 60, 200, 90, 10)]))["jobs"] == []


def test_jobs_by_heart_rate_are_said_to_be_rough():
    j = train.jobs_done(train.work(hr_ride(60, 165)), FTP, 180, 50)
    assert j["jobs"][0]["job"] == "hold" and "judged by heart rate" in j["jobs"][0]["line"]
    assert [x["job"] for x in train.jobs_done(train.work(hr_ride(80, 125)), FTP, 180, 50)["jobs"]] == ["easy"]
    assert [x["job"] for x in train.jobs_done(train.work(hr_ride(200, 135)), FTP, 180, 50)["jobs"]] == ["long"]


def test_every_workout_names_its_job():
    from rideengine.analysis import plan as p
    for k in ("surges", "sprint", "vo2", "steady", "threshold", "over_unders", "long", "group", "endurance", "easy"):
        assert k in p.JOB_OF and p.JOB_OF[k] in train.JOBS
        mins = p.job_minutes(p.workout(k, 0.5, 130 if k in ("long", "group") else 60, True))
        assert set(mins) <= {p.JOB_OF[k]}
    assert p.job_minutes(p.workout("over_unders", 0.0, 60, True)) == {"hold": 24.0}


def test_a_short_ride_does_one_hard_job_and_says_the_rest():
    # Monday's surges, then 25 steady minutes: punch leads; the steady riding is said, the hold job stays open.
    j = jobs(surges_as_planned(), want={"punch": 7.5})
    assert [x["job"] for x in j["jobs"]] == ["punch"]
    (a,) = j["also"]
    assert a["job"] == "hold" and a["line"].startswith("Also ") and "the week's hold job is still to come" in a["line"]


# --- the week as jobs (build step 2) --------------------------------------------------------------------

def _job(job, have, status="done", line=None):
    return {"job": job, "title": train.JOB_TITLES[job], "status": status, "have_min": have,
            "line": line or f"{train.JOB_TITLES[job]} line", "detail": "the work"}


def jr(rid, d, *jobs):
    return {"ride_id": rid, "date": d, "jobs": {"jobs": list(jobs)}}


def test_rides_fill_the_weeks_jobs_whatever_the_workout():
    from rideengine.analysis import plan as p
    week = [{"id": "mon", "date": "2026-11-23", **p.workout("surges", 0.0, 55, True)},      # punch, 7.5 min
            {"id": "wed", "date": "2026-11-25", **p.workout("steady", 0.0, 55, True)},      # hold, 20 min
            {"id": "fri", "date": "2026-11-27", **p.workout("group", 0.0, 75, True)},       # punch, any
            {"id": "sat", "date": "2026-11-28", **p.workout("long", 0.0, 150, False)},      # long, 120 min
            {"id": "sun", "date": "2026-11-29", **p.workout("endurance", 0.0, 50, False)}]  # easy
    # A different Zwift workout of short hard efforts on Tuesday does the punch job: Monday's, the nearest.
    m = train.count_jobs(week, [jr("tue", "2026-11-24", _job("punch", 9))])
    assert m["counted"]["mon"]["ride_id"] == "tue" and m["ride_jobs"]["tue"] == [{"job": "punch", "session_id": "mon"}]
    # A long group ride with surges on Saturday: punch (Friday's group ride, the nearest open punch) and long.
    m = train.count_jobs(week, [jr("tue", "2026-11-24", _job("punch", 9)),
                                jr("sat", "2026-11-28", _job("punch", 12), _job("long", 180))])
    assert set(m["counted"]) == {"mon", "fri", "sat"}
    # Partly done leaves the rest open, and a later ride finishes it.
    m = train.count_jobs(week, [jr("w1", "2026-11-25", _job("hold", 8.5, "part"))])
    assert "wed" not in m["counted"] and m["progress"]["wed"]["left_min"] == 11.5
    assert m["progress"]["wed"]["line"] == "Hold: 8.5 of 20 min done. 11.5 min more finishes it."
    m = train.count_jobs(week, [jr("w1", "2026-11-25", _job("hold", 8.5, "part")),
                                jr("w2", "2026-11-26", _job("hold", 12, "part"))])
    assert m["counted"]["wed"]["rides"] == ["w1", "w2"] and m["counted"]["wed"]["reason"] == "Hold: done. the work."
    # Easy riding does the easy job; a ride that did no job is extra; the rider's own call stands.
    m = train.count_jobs(week, [jr("e", "2026-11-29", _job("easy", 50)), jr("x", "2026-11-29")],
                         {"tue": "sun"})
    assert m["counted"]["sun"]["ride_id"] == "e" and m["extra"] == ["x"]
    m = train.count_jobs(week, [jr("tue", "2026-11-24", _job("punch", 9))], {"tue": "wed"})
    assert m["counted"] == {"wed": {"ride_id": "tue", "rides": ["tue"], "reason": None, "by_hand": True}}
