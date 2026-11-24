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
    # No hard days back to back: the fresh layout puts sweet spot on Wednesday and endurance on Thursday.
    assert t["then"].startswith("Tomorrow: rest. Wednesday: Sweet spot, 3 × 12 min.")
    assert t["schedule"]["s-steady"] == "2026-11-25" and t["schedule"]["s-endurance"] == "2026-11-26"
    assert "moved" not in t
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
    assert brief["at"][11:16] == "06:00" and brief["title"]               # early: riders go out early
    # The rider's own time: kept, and the brief comes then; nonsense or the middle of the night is refused.
    assert client.get("/v1/me").json()["brief_at"] == "06:00"
    assert client.put("/v1/me", json={"brief_at": "5:45"}).json()["brief_at"] == "05:45"
    assert client.get("/v1/train/inbox").json()["scheduled"][-1]["at"][11:16] == "05:45"
    for bad in ("02:00", "13:00", "6:75", "soon", None):
        assert client.put("/v1/me", json={"brief_at": bad}).status_code == 400
    assert client.get("/v1/me").json()["brief_at"] == "05:45"
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
                         {"id": "c", **p.workout("long", 0.0, 120, True)}]}
    want, long_min = Backend._job_wants(week)
    assert want == {"punch": 7.5, "hold": 20.0} and long_min == 120
    assert Backend._job_wants(None) == ({}, None)


def test_sessions_grow_from_the_evidence():
    """Done in full and felt fine: the next session of that job steps up, and says why; hard holds it; wrecked
    steps it back. Never past the phase's cap."""
    from rideengine.analysis import plan as p
    def week(ws, day):
        return {"week_start": ws, "phase": "build",
                "sessions": [{"id": f"{day}-s", "date": day, "time": "07:00", **p.workout("surges", 0.0, 55, True)}]}
    score, last = {}, {}
    w1 = week("2026-11-23", "2026-11-23")
    w1 = {**w1, "sessions": [Backend._grow(s, "build", score, last) for s in w1["sessions"]]}
    assert p.job_minutes(w1["sessions"][0]) == {"punch": 7.5} and "grew" not in w1["sessions"][0]
    counted = {"counted": {"2026-11-23-s": {"ride_id": "r1", "date": "2026-11-23"}}, "progress": {}}
    Backend._learn(w1, counted, set(), {"r1": ("easy", False)}, date(2026, 11, 30), score, last)
    assert score == {"punch": 1}
    g = Backend._grow(week("2026-11-30", "2026-11-30")["sessions"][0], "build", score, last)
    assert p.job_minutes(g) == {"punch": 9.0} and g["level"] == 0.25
    assert g["grew"] == ("A step up: 9 min of hard efforts, from 7.5 min, because you did last Monday's surges in "
                         "full and felt easy.")
    # Felt hard: held. Wrecked: a step back, said. Missed or partly done: held, never punished.
    assert p.grow_score(1, "hard") == 1 and p.grow_score(1, "part") == 1 and p.grow_score(1, "missed") == 1
    w2 = {"week_start": "2026-11-30", "phase": "build", "sessions": [g]}
    counted = {"counted": {g["id"]: {"ride_id": "r2", "date": "2026-11-30"}}, "progress": {}}
    Backend._learn(w2, counted, set(), {"r2": ("wrecked", False)}, date(2026, 12, 7), score, last)
    assert score == {"punch": 0}
    g = Backend._grow(week("2026-12-07", "2026-12-07")["sessions"][0], "build", score, last)
    assert p.job_minutes(g) == {"punch": 7.5} and g["grew"].startswith("A step back") and "felt wrecked" in g["grew"]
    assert "because last Monday's surges" in g["grew"]
    # Older than last week: said with its date, not a weekday that reads as this week's.
    score2, last2 = {"punch": 1}, {"surges": {"minutes": 7.5, "date": "2026-11-23", "feel": None, "title": "Surges",
                                              "why": "felt hard"}}
    g = Backend._grow(week("2026-12-14", "2026-12-16")["sessions"][0], "build", score2, last2)
    assert "the surges on 23 Nov in full" in g["grew"]
    # Base weeks grow at most halfway; easy, long and group rides don't grow.
    assert p.grown({"kind": "surges", "seconds": 3300, "indoor": True}, 8, "base")["level"] == 0.5
    assert p.grown({"kind": "long", "seconds": 7200}, 8, "build") is None


def test_leftovers_join_a_planned_ride_and_what_doesnt_fit_is_let_go():
    """Step 3 (docs/train-method.md): a job with half or less left joins the next hard day or the long ride;
    when the week can't fit everything, what matters least for the goal goes, and both are said."""
    ws = date(2026, 11, 23)
    def s(sid, kind, day, status="upcoming", **kw):
        return {"id": sid, "kind": kind, "title": {"surges": "Surges", "steady": "Sweet spot", "long": "Long ride",
                                                   "endurance": "Endurance"}[kind],
                "date": (ws + timedelta(days=day)).isoformat(), "status": status, "steps": [], **kw}
    part = {"job": "punch", "have_min": 5.0, "want_min": 7.5, "left_min": 2.5, "line": "Punch: 5 of 7.5 min done."}
    week = [s("mon", "surges", 0, "open", progress=part), s("wed", "steady", 2), s("sat", "long", 5),
            s("sun", "endurance", 6)]
    recent = [{"date": ws, "kind": "surges", "minutes": 60}]
    t = td.plan_today(week, recent, ws + timedelta(days=1), ws)
    assert "mon" not in t["schedule"]                         # not redone as a whole session
    (f,) = t["folded"]
    assert f["into"] == "wed" and f["line"] == "2.5 min of punch left from surges: added to tomorrow's sweet spot."
    # More than half left: it stays a session of its own.
    big = {**part, "have_min": 2.0, "left_min": 5.5}
    t = td.plan_today([s("mon", "surges", 0, "open", progress=big)] + week[1:], recent, ws + timedelta(days=1), ws)
    assert "mon" in t["schedule"] and not t["folded"]
    # Saturday, three sessions left and two days: the endurance ride goes, and it's said.
    late = [s("thu", "surges", 3, "open"), s("sat", "long", 5), s("sun", "endurance", 6)]
    t = td.plan_today(late, [], ws + timedelta(days=5), ws)
    assert [d["id"] for d in t["dropped"]] == ["sun"] and "let go" in t["dropped"][0]["line"]
    assert set(t["schedule"]) == {"thu", "sat"} or set(t["schedule"]) == {"sat", "thu"}


def test_a_new_layout_is_said_once_with_its_reason(env):
    """The week is laid out fresh each time; when a session lands on another day than last shown, one plain line
    says the week as it is now, and why. A ride that just did a session isn't news. Seen once, not again."""
    be, uid, client, _ = env
    ws = "2026-11-23"
    week = {"week_start": ws, "rides": [],
            "sessions": [{"id": "wed", "title": "Sweet spot", "kind": "steady"},
                         {"id": "sat", "title": "Long ride", "kind": "long"},
                         {"id": "sun", "title": "Endurance", "kind": "endurance"}]}
    c = {"today": date(2026, 11, 24)}
    t = {"schedule": {"wed": "2026-11-25", "sat": "2026-11-28", "sun": "2026-11-29"}, "folded": [], "dropped": []}
    assert be._plan_changes(uid, c, week, t) == []                 # the first layout: nothing to compare with
    assert be._plan_changes(uid, c, week, t) == []                 # the same again: still nothing
    # Wednesday's ride did the punch; the sweet spot is now on Thursday.
    week["rides"] = [{"ride_id": "r", "start": 4102444800, "date": "2026-11-25",
                      "jobs": {"jobs": [{"job": "punch", "status": "done"}]}}]
    t = {"schedule": {"wed": "2026-11-26", "sat": "2026-11-28", "sun": "2026-11-29"}, "folded": [], "dropped": []}
    (ch,) = be._plan_changes(uid, {"today": date(2026, 11, 25)}, week, t)
    assert ch["line"] == "Your week now: sweet spot Thursday, long ride Saturday, endurance Sunday."
    assert ch["reason"] == "Today's ride did the punch." and not ch["big"]
    assert client.post("/v1/train/changes/seen", json={"ids": [ch["id"]]}).json() == {"ok": True}
    assert be._plan_changes(uid, {"today": date(2026, 11, 25)}, week, t) == []
    # Thursday's ride did the sweet spot: it just leaves the layout, nothing to say.
    t = {"schedule": {"sat": "2026-11-28", "sun": "2026-11-29"}, "folded": [], "dropped": []}
    assert be._plan_changes(uid, {"today": date(2026, 11, 26)}, week, t) == []
    # The long ride on another day, or a session let go: bigger, so a notification too.
    t = {"schedule": {"sat": "2026-11-29"}, "folded": [],
         "dropped": [{"id": "sun", "title": "Endurance", "line": "No room for endurance this week, so it's let go."}]}
    (ch,) = be._plan_changes(uid, {"today": date(2026, 11, 28)}, week, t)
    assert ch["big"] and ch["line"] == ("Your week now: long ride Sunday. No room for endurance this week, so it's "
                                        "let go. Next week starts fresh.")


def test_a_session_is_on_the_day_it_was_ridden_or_laid_out(env):
    """24 Nov 2026: a done session sits on the day it was ridden, one still open on the day this week's layout
    puts it, and its status follows that day; no ride note says where a session was first planned."""
    be, uid, client, _ = env
    client.post("/v1/sync/garmin_personal")
    client.put("/v1/goals/current", json={"objective": "faster", "aspiration": "keep_up_group"})
    view = be.plan_view(uid)
    today = be._plan_context(uid)["today"].isoformat()
    for w in view["weeks"]:
        sched = (w.get("replan") or {}).get("schedule", {})
        for s in w["sessions"]:
            assert s["on"] == (s["counted"]["date"] if s.get("counted") else sched.get(s["id"], s["date"]))
            if w.get("replan") and s["status"] in ("today", "upcoming", "open"):
                assert s["status"] == ("today" if s["on"] == today else "upcoming" if s["on"] > today else "open")
            if s.get("counted"):
                note = be.train_ride_note(uid, s["counted"]["ride_id"])
                assert note["counted"] and "planned_for" not in note["counted"]


def test_what_the_rider_sees_after_re_planning(env):
    """Step 4: the job's shape for any workout, what's left this week, and only the suggested workout graded."""
    from rideengine.analysis import plan as p
    assert p.shape(p.workout("surges", 0.0, 55, True)).startswith("Or any ride with 7.5 min or more of hard efforts")
    assert "Zwift" not in p.shape(p.workout("surges", 0.0, 55, True))
    assert "140–149 W" in p.shape(p.workout("steady", 0.0, 55, True), [140, 149])
    week = {"replan": {"schedule": {"wed": "2026-11-25", "fri": "2026-11-27"}},
            "sessions": [{"id": "mon", "job": "punch", "title": "Surges", "status": "done"},
                         {"id": "wed", "job": "hold", "title": "Sweet spot", "status": "upcoming"},
                         {"id": "fri", "job": "punch", "title": "Group ride", "status": "upcoming"}]}
    assert Backend._left_this_week({"today": date(2026, 11, 24)}, week) == \
        "Still to come this week: steady work tomorrow and punch on Friday."
    week["sessions"][1]["status"] = week["sessions"][2]["status"] = "done"
    week["replan"]["schedule"] = {}
    assert Backend._left_this_week({"today": date(2026, 11, 28)}, week) == "That's every job this week done."


def test_review_changes_show_in_the_plan(env):
    """Step 6: a change the review made (another way, a swap, an easier week) shows in the plan's sessions."""
    be, uid, client, _ = env
    client.post("/v1/sync/garmin_personal")
    client.put("/v1/goals/current", json={"objective": "faster", "aspiration": "keep_up_group"})
    view = be.plan_view(uid)
    w1, w2 = view["weeks"][1], view["weeks"][2]
    easy = next(s for s in w1["sessions"] if s["kind"] in ("endurance", "easy"))
    be._apply_proposal(uid, {"apply": {"type": "swap", "session_id": easy["id"], "to_kind": "steady"}}, w1)
    be._apply_proposal(uid, {"apply": {"type": "another_way", "job": "punch", "text": "a group ride"}}, w1)
    be._apply_proposal(uid, {"apply": {"type": "ease", "week_start": w2["week_start"]}}, w2)
    view = be.plan_view(uid)
    s = next(x for x in view["weeks"][1]["sessions"] if x["id"] == easy["id"])
    assert s["kind"] == "steady" and s["swapped_from"] == easy["title"] and s["job"] == "hold"
    assert any(x.get("another_way") == "a group ride" for x in view["weeks"][1]["sessions"] if x["job"] == "punch")
    eased = view["weeks"][2]
    assert eased["eased"] and all(x["kind"] in ("easy", "endurance", "long") for x in eased["sessions"] if not x["off_bike"])
    # A change that can't be made now is refused; an unknown week has no review.
    assert client.post("/v1/train/review/proposals/nope:ease", json={"accept": True}).status_code == 409
    assert client.get("/v1/train/review", params={"week": "1999-01-04"}).status_code == 404
    r = client.get("/v1/train/review", params={"week": view["weeks"][0]["week_start"]}).json()
    assert r["lines"] and isinstance(r["proposals"], list)


def test_a_big_change_waits_for_the_rider_and_stays_on_the_review(env, monkeypatch):
    from rideengine.analysis import review as rv
    be, uid, client, _ = env
    client.post("/v1/sync/garmin_personal")
    client.put("/v1/goals/current", json={"objective": "faster", "aspiration": "keep_up_group"})
    view = be.plan_view(uid)
    w0, w1 = view["weeks"][0], view["weeks"][1]
    real = rv.review

    def fake(week, history, markers, feels, next_week, hours, strained_days=0):
        out = real(week, history, markers, feels, next_week, hours)
        if next_week and next_week.get("phase") not in ("recovery", "taper") and week["week_start"] == w0["week_start"]:
            out["proposals"].append({"id": f"{w0['week_start']}:ease", "type": "ease", "size": "big",
                                     "change": "Make next week an easier one.", "reason": "Something hurt.",
                                     "rules": ["an easier week early when you're tired"],
                                     "apply": {"type": "ease", "week_start": w1["week_start"]}})
        return out
    monkeypatch.setattr(rv, "review", fake)
    r = client.get("/v1/train/review", params={"week": w0["week_start"]}).json()
    (p,) = [x for x in r["proposals"] if x["type"] == "ease"]
    assert p["status"] == "open"                                  # waits for the rider
    assert not be.plan_view(uid)["weeks"][1].get("eased")
    r = client.post(f"/v1/train/review/proposals/{p['id']}", json={"accept": True}).json()
    assert be.plan_view(uid)["weeks"][1]["eased"]                 # applied
    # The rule no longer fires (next week is easy now), but the decision stays on the review.
    assert [x["status"] for x in r["proposals"] if x["type"] == "ease"] == ["accepted"]
    assert client.post(f"/v1/train/review/proposals/{p['id']}", json={"accept": True}).status_code == 409
