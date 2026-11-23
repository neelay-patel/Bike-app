"""Train, step 2: today's session or rest, the week ahead, and the coach's feedback (synthetic, no personal data)."""
import json
from datetime import date, timedelta

from backend.service import Backend
from rideengine.analysis import feedback, train
from rideengine.analysis import today as td
from test_backend import env, line_ride, T0  # noqa: F401  (pytest fixture)
from test_effort import trainer

MON = date(2026, 11, 23)


def week(statuses=None):
    """A week like Neelay's: surges Mon, sweet spot Tue, endurance Wed, group Fri, strength Sat."""
    plan = [("surges", 0, 3600, "Surges", [{"set": "6 × 1 min hard / 2 min easy"}]),
            ("steady", 1, 3600, "Sweet spot", [{"set": "3 × 12 min sweet spot / 5 min easy"}]),
            ("endurance", 2, 4500, "Endurance", []),
            ("group", 4, 3600, "Group ride", []),
            ("strength", 5, 1200, "Strength and mobility", [])]
    out = []
    for kind, day, secs, title, steps in plan:
        out.append({"id": f"s-{kind}", "kind": kind, "title": title, "date": (MON + timedelta(days=day)).isoformat(),
                    "seconds": secs, "steps": steps, "off_bike": kind == "strength",
                    "status": (statuses or {}).get(kind, "upcoming")})
    return out


def rides(*days_kinds):
    return [{"date": MON + timedelta(days=d), "kind": k, "minutes": 60} for d, k in days_kinds]


def test_monday_the_planned_session_and_what_comes_next():
    t = td.plan_today(week(), rides((-6, "surges"), (-5, "steady"), (-4, "threshold"), (-2, "steady")), MON, MON, "good")
    assert t["state"] == "session" and t["session_id"] == "s-surges"
    assert t["why"] == td.WHY["surges"]
    # No hard days back to back: sweet spot moves from Tuesday to Wednesday, endurance to Thursday.
    assert t["then"].startswith("Tomorrow: rest. Wednesday: Sweet spot, 3 × 12 min.")
    assert {m["id"]: m["to"] for m in t["moved"]} == {"s-steady": "2026-11-25", "s-endurance": "2026-11-26"}
    assert "Strength and mobility is still open" in t["then"]


def test_after_a_hard_day_today_is_easy_or_rest():
    w = week({"surges": "done"})
    t = td.plan_today(w, rides((0, "surges")), MON + timedelta(days=1), MON, "good")
    assert t["state"] == "rest" or t["session_id"] == "s-endurance"
    assert "Yesterday was hard" in t["why"] or "Rest today" in t["why"]


def test_recovery_low_means_easy_or_rest():
    t = td.plan_today(week(), [], MON, MON, "strained")
    assert t["state"] == "session" and t["session_id"] == "s-endurance"
    assert "recovery is lower than usual" in t["why"]
    done_easy = week({"endurance": "done"})
    t = td.plan_today(done_easy, [], MON, MON, "strained")
    assert t["state"] == "rest" and "today is rest" in t["why"]


def test_three_days_in_a_row_then_rest_if_the_week_allows():
    w = week({"surges": "done", "steady": "done", "endurance": "done"})
    t = td.plan_today(w, rides((0, "surges"), (1, "endurance"), (2, "steady")), MON + timedelta(days=3), MON, "good")
    assert t["state"] == "rest" and t["why"].startswith("3 days of riding in a row")


def test_rest_on_a_day_off_when_the_week_still_fits():
    t = td.plan_today(week({"surges": "done"}), rides((0, "surges")), MON + timedelta(days=2), MON, "good")
    # Wednesday: the endurance session is planned today, so it's on.
    assert t["session_id"] == "s-endurance"
    t = td.plan_today(week({"surges": "done", "steady": "done", "endurance": "done"}),
                      rides((0, "surges"), (1, "steady"), (2, "endurance")), MON + timedelta(days=3), MON, "good")
    assert t["state"] == "rest"                                  # Thursday off, group ride Friday


def test_ridden_today_and_a_finished_week():
    t = td.plan_today(week({"surges": "done"}), rides((0, "surges")), MON, MON, "good")
    assert t["state"] == "done" and t["then"].startswith("Tomorrow: rest.")
    all_done = week({k: "done" for k in ("surges", "steady", "endurance", "group", "strength")})
    t = td.plan_today(all_done, [], MON + timedelta(days=5), MON, "good")
    assert t["state"] == "rest" and t["why"].startswith("Every session this week is done")
    assert t["then"] == "Tomorrow: rest. A new week starts on Monday."


def test_greeting():
    r = rides((-6, "surges"), (-5, "steady"), (-4, "threshold"), (-2, "steady"))
    assert td.greeting(r, MON, "good", "session") == ("You rode 4 days in the last week and rested yesterday. "
                                                      "Your recovery looks normal, so today's session is on.")
    assert td.greeting([], MON, "unknown", "rest") == "No rides in the last week."


# --- the coach's one thing to try ---------------------------------------------------------------------

FTP = 150


def test_climbing_in_too_big_a_gear():
    parts = [(10 * 60, 110, 85, 25)]
    for _ in range(3):
        parts += [(4 * 60, 110, 85, 25), (2 * 60, 160, 52, 25)]    # the trainer's climbs: cadence down to 52
    parts += [(10 * 60, 105, 85, 25)]
    w = train.work(trainer(T0, parts))
    tips = feedback.pointers(w, train.classify(w, FTP), FTP)
    climb = next(t for t in tips if t["id"] == "climb_cadence")
    assert climb["evidence"]["lowest_rpm"] < 65 and climb["evidence"]["climbs"] >= 2 and "lighter gear" in climb["text"]


def test_easy_day_ridden_hard_comes_first():
    w = train.work(trainer(T0, [(10 * 60, 100, 85, 10), (40 * 60, 135, 85, 8), (10 * 60, 100, 85, 10)]))
    cls = train.classify(w, FTP)
    tips = feedback.pointers(w, cls, FTP, intent="endurance")
    assert tips[0]["id"] == "easy_too_hard" and "pace you could chat at" in tips[0]["text"]
    assert not any(t["id"] == "warm_up" for t in tips)            # no warm-up nagging on an easy day
    assert feedback.pointers(w, cls, FTP, intent="steady") == [] or tips[0]["id"] != "steady_too_hard"


def test_going_out_too_hard_on_the_first_surges():
    parts = [(10 * 60, 100, 85, 10)]
    for watts in (260, 255, 230, 215, 200, 195):
        parts += [(60, watts, 95, 5), (120, 100, 85, 8)]
    parts += [(10 * 60, 100, 85, 10)]
    w = train.work(trainer(T0, parts))
    tips = feedback.pointers(w, train.classify(w, FTP), FTP, intent="surges")
    pace = next(t for t in tips if t["id"] == "pacing")
    assert pace["evidence"]["first_w"] > pace["evidence"]["last_w"] * 1.12


def test_low_cadence_overall_and_nothing_to_say():
    w = train.work(trainer(T0, [(60 * 60, 110, 68, 10)]))
    tips = feedback.pointers(w, train.classify(w, FTP), FTP)
    assert [t["id"] for t in tips] == ["low_cadence"]
    w = train.work(trainer(T0, [(60 * 60, 105, 88, 10)]))
    assert feedback.pointers(w, train.classify(w, FTP), FTP, intent="endurance") == []


def test_contribution_new_bests():
    feat = {"power_curve": {"60": 273, "300": 180, "1200": 150}, "work": {}}
    earlier = [{"power_curve": {"60": 250, "300": 190, "1200": 155}}]
    c = feedback.contribution(feat, earlier, FTP)
    assert c["bests"] == [{"id": "60", "watts": 273, "text": "Best minute: 273 W, your best yet."}]
    assert feedback.contribution(feat, [], FTP)["bests"] == []    # nothing to beat on the first ride with power


# --- the endpoints ------------------------------------------------------------------------------------

def w_first(client):
    return next(s for s in client.get("/v1/train/week").json()["sessions"] if not s["off_bike"])


def test_guide_and_cadence():
    from rideengine.analysis import plan
    w = plan.targets(plan.workout("surges", 0, 60, True), 300, None)
    hard = w["steps"][1]["steps"][0]["target"]
    assert hard["rpm"] == [95, 105] and "rpm" in w["steps"][0]["target"]
    sprint = plan.targets(plan.workout("sprint", 0, 60, True), 300, None)
    assert "rpm" not in sprint["steps"][1]["steps"][0]["target"]          # wind it up: no cadence for a sprint
    g = td.guide({**w, "id": "x"})
    assert g["warm"].startswith("Start easy") and g["cool"] and len(g["main"]) == 3 and g["after"]
    long = td.guide(plan.targets(plan.workout("long", 0, 150, False), None, None))
    assert any("carbs" in b for b in long["bring"]) and long["after"] is None
    for words in (g, long):
        assert not any(bad in json.dumps(words) for bad in ("FTP", "TSS", "ERG", "load", "Z2"))


def test_train_endpoints(env):
    be, uid, client, _ = env
    assert client.get("/v1/train/today").json() == {"state": "no_plan"}
    assert client.get("/v1/train/week").status_code == 404
    client.post("/v1/sync/garmin_personal")
    client.put("/v1/goals/current", json={"objective": "faster", "aspiration": "keep_up_group"})
    t = client.get("/v1/train/today").json()
    assert t["state"] in ("session", "rest", "done") and t["greeting"] and t["goal"]["title"]
    assert {m["id"] for m in t["goal"]["markers"]} <= {"sustained", "punch"}
    # What's Next names its sessions, and each opens its own page: how to ride it, part by part.
    for n in t["next"]:
        assert n["when"] and n["session"]["steps"] and n["date"] > t["date"]
    sid = (t["next"][0]["session"] if t["next"] else t["session"] or w_first(client))["id"]
    brief = client.get(f"/v1/plan/sessions/{sid}").json()
    g = brief["guide"]
    assert g["why"] and g["bring"] and (g["main"] or brief["off_bike"])
    if not brief["off_bike"]:
        assert g["feel"] and "FTP" not in json.dumps(g)
    w = client.get("/v1/train/week").json()
    assert w["sessions"] and "rides" in w and "schedule" in w
    rid = json.loads(be.db.execute("SELECT data FROM ride_features WHERE user_id = ? LIMIT 1", (uid,)).fetchone()[0])["ride_id"] \
        if be.db.execute("SELECT 1 FROM ride_features WHERE user_id = ?", (uid,)).fetchone() else None
    if rid:
        n = client.get(f"/v1/train/rides/{rid}").json()
        assert {"did", "kind", "counted", "means", "next", "try", "jobs"} <= set(n)
    assert client.get("/v1/train/rides/nope").status_code == 404


def test_coach_inbox(env):
    be, uid, client, _ = env
    assert client.get("/v1/train/inbox").json() == {"items": [], "scheduled": []}   # no plan, nothing to say
    client.post("/v1/sync/garmin_personal")
    client.put("/v1/goals/current", json={"objective": "faster", "aspiration": "keep_up_group"})
    box = client.get("/v1/train/inbox").json()
    assert set(box) == {"items", "scheduled"}
    brief = box["scheduled"][-1]
    assert brief["kind"] == "brief" and brief["id"].startswith("brief:") and brief["opens"] == {"screen": "today"}
    assert brief["at"][11:16] == "07:30" and brief["title"]
    # Messages reach the lock screen: never recovery numbers.
    for m in box["items"] + box["scheduled"]:
        words = (m["title"] + " " + m["body"]).lower()
        assert "hrv" not in words and "bpm" not in words and "resting heart" not in words


def test_how_a_hard_session_felt_moves_the_targets(env):
    """Felt easy: the next hard sessions start 5% higher than that session did; good or hard keeps them there;
    wrecked eases them back; never below the estimate or more than 15% above it. Changing the tap undoes it."""
    from zoneinfo import ZoneInfo
    be, uid, _, _ = env
    tz = ZoneInfo("America/Toronto")
    est = {"watts": 151, "source": "estimated from your best 20 minutes"}
    assert be._aim(uid, est, tz)["watts"] == 151

    def tap(ride_id, feel, ftp_w):
        be.db.execute("INSERT OR REPLACE INTO ride_feel (user_id, ride_id, feel, hurts, at, ftp_w) VALUES (?, ?, ?, 0, 0, ?)",
                      (uid, ride_id, feel, ftp_w))

    tap("1795444201", "easy", 151)                        # Monday 23 Nov 2026
    a = be._aim(uid, est, tz)
    assert a["watts"] == 159 and a["base"] == 151 and "Monday's hard session felt easy" in a["source"] and a["source"].startswith("estimated")
    nxt = {"date": "2026-11-25", "title": "Sweet spot", "steps": [
        {"zone": "Z1", "target": {"watts": [64, 87]}},
        {"set": "2 × 10 min", "steps": [{"zone": "SS", "target": {"watts": [140, 149]}}, {"zone": "Z1"}]}]}
    note = be._feel_note(a, "1795444201", {"feel": "easy", "hurts": False, "from_w": 151}, nxt, "Wednesday")
    assert note == ("You said it felt easy, so I've raised the watts of your hard sessions by 5%. "
                    "Wednesday's sweet spot: about 140–149 W. Tell me how that one feels.")
    tap("1795617001", "good", 159)                        # Wednesday: felt right at the raised watts
    assert be._aim(uid, est, tz)["watts"] == 159
    tap("1795617001", "wrecked", 159)
    assert be._aim(uid, est, tz)["watts"] == 151          # 5% below 159, but never below the estimate
    tap("1795617001", "easy", 170)
    assert be._aim(uid, est, tz)["watts"] == round(151 * 1.15)
    be.db.execute("DELETE FROM ride_feel WHERE user_id = ?", (uid,))
    assert be._aim(uid, est, tz)["watts"] == 151


def test_jobs_are_judged_against_the_weeks_plan():
    from rideengine.analysis import plan as p
    week = {"sessions": [{"id": "a", **p.workout("surges", 0.0, 55, True)},
                         {"id": "b", **p.workout("steady", 0.0, 55, True)},
                         {"id": "c", **p.workout("group", 0.0, 120, True)}]}
    want, long_min = Backend._job_wants(week)
    assert want == {"punch": 7.5, "hold": 20.0} and long_min == 120
    assert Backend._job_wants(None) == ({}, None)
