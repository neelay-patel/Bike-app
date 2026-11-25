"""The coach you can ask anything (backend/coach_chat.py). A scripted fake Claude: no network, no key."""
import json
from types import SimpleNamespace

from backend import coach_chat as cc
from test_backend import API_KEY, env  # noqa: F401  (pytest fixture)


def text(t):
    return SimpleNamespace(type="text", text=t)


def tool(name, args, i):
    return SimpleNamespace(type="tool_use", name=name, input=args, id=f"tu{i}")


class Scripted:
    """Answers each call with the next scripted turn: a list of blocks (tool calls or text)."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.calls = []
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw, default=lambda o: getattr(o, "__dict__", str(o)))))
        blocks = self.turns.pop(0) if self.turns else [text("Done.")]
        stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
        return SimpleNamespace(stop_reason=stop, model=kw["model"], content=blocks,
                               usage=SimpleNamespace(input_tokens=3000, output_tokens=200, cache_read_input_tokens=0,
                                                     cache_creation_input_tokens=0))


def setup(env, *turns):
    be, uid, client, _ = env
    client.put("/v1/connections/garmin_personal?since=2026-01-01", json={"api_key": API_KEY})
    client.put("/v1/goals/current", json={"objective": "faster", "aspiration": "keep_up_group"})
    fake = Scripted(*turns)
    be.coach._client = fake
    return be, uid, client, fake


def ask(client, q, **kw):
    r = client.post("/v1/coach/ask", json={"text": q, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_number_check_reads_measured_numbers_only():
    allowed = cc.allowed_numbers({"best": 151, "pct": 27, "cad": 87})
    assert cc.claimed_numbers("Hold 151 W for 2 × 10 min, 27% of the way, at 87 rpm.") == ["151", "27", "87"]
    assert cc.check_answer("Hold 151 W for 2 × 10 min, 27% of the way, at 87 rpm.", allowed) == []
    assert cc.check_answer("About 150 W, then 85–90 rpm.", allowed) == []            # roundings of 151 and 87
    assert cc.check_answer("You could hold 162 W.", allowed) == ["162"]              # not from the tools
    assert cc.check_answer("Ride 3 times this week, 90 minutes each, on the 18th.", allowed) == []   # coaching, not data


def test_off_until_ai_is_on(env):
    be, uid, client, fake = setup(env)
    assert client.get("/v1/coach").json()["on"] is False
    assert client.post("/v1/coach/ask", json={"text": "Hi"}).status_code == 403
    assert fake.calls == []                                   # nothing sent anywhere


def test_an_answer_from_the_riders_own_data(env):
    be, uid, client, fake = setup(env)
    be.coach.set_allowed(uid, True)
    rid = be.db.execute("SELECT ride_id FROM rides WHERE user_id = ? ORDER BY start_t DESC LIMIT 1", (uid,)).fetchone()[0]
    ride = cc.Tools(be, uid, 0).t_ride(rid)
    km = ride["km"]
    fake.turns = [
        [tool("rides", {"limit": 5}, 1), tool("fitness", {}, 2), tool("recovery", {}, 3)],
        [tool("show", {"type": "trend", "measure": "km", "by": "ride", "since": "2026-01-01"}, 4),
         tool("give_advice", {"title": "Ride a little further", "do": "Add 10 minutes to Saturday.", "why": "Your rides are short.",
                              "measure": "km", "want": "up"}, 5),
         tool("remember", {"note": "Rides gravel, no power meter outdoors."}, 6)],
        [text(f"Your last ride was {km} km. **Add 10 minutes** on Saturday; I'll check back after it.")],
    ]
    out = ask(client, "What should I work on?")
    msgs = client.get(f"/v1/coach/messages?after={out['question'] - 1}").json()["messages"]
    assert [m["role"] for m in msgs[:2]] == ["rider", "coach"]
    a = msgs[1]
    assert a["status"] == "done" and f"{km} km" in a["text"]
    assert a["charts"][0]["type"] == "trend" and a["charts"][0]["unit"] == "km"
    assert a["advice"][0]["title"] == "Ride a little further"
    # What was sent: the rider's data through tools, never GPS.
    sent = json.dumps(fake.calls)
    for banned in ('"lat"', '"lon"', '"cells"', '"bbox"', '"shape"'):
        assert banned not in sent
    first = fake.calls[0]
    assert first["model"] == "claude-sonnet-5-5" and first["system"][0]["cache_control"]["type"] == "ephemeral"
    assert "Rides gravel" not in first["system"][1]["text"]           # remembered only from this answer on
    home = client.get("/v1/coach").json()
    assert home["on"] and home["one_thing"]["title"] == "Ride a little further" and home["remembers"] == 1
    knows = client.get("/v1/coach/knows").json()
    assert knows["memory"][0]["note"].startswith("Rides gravel")
    assert client.delete(f"/v1/coach/memory/{knows['memory'][0]['id']}").json() == {"ok": True}
    assert client.get("/v1/coach/knows").json()["memory"] == []
    spend = be.db.execute("SELECT COUNT(*), SUM(cost_usd) FROM coach_usage WHERE key LIKE 'chat:%'").fetchone()
    assert spend[0] == 3 and spend[1] > 0


def test_numbers_it_cant_back_up_are_sent_back_then_refused(env):
    be, uid, client, fake = setup(env)
    be.coach.set_allowed(uid, True)
    fake.turns = [[text("You can hold 287 W.")], [text("You're getting stronger.")]]
    ask(client, "How strong am I?")
    msgs = client.get("/v1/coach/messages").json()["messages"]
    assert msgs[-1]["text"] == "You're getting stronger."
    assert "287" in json.dumps(fake.calls[1]["messages"][-1])            # the check named the number
    fake.turns = [[text("You can hold 287 W.")], [text("Still 287 W.")]]
    ask(client, "Really?")
    assert client.get("/v1/coach/messages").json()["messages"][-1]["text"].startswith("I started to answer with numbers")


def test_plan_changes_wait_for_the_riders_ok(env):
    be, uid, client, fake = setup(env)
    be.coach.set_allowed(uid, True)
    hours = be.plan_view(uid)["weekly_hours"]
    t = cc.Tools(be, uid, 0)
    assert t.t_propose_change("hours", "More time.", weekly_hours=hours * 3)["why_not"]   # past the plan's limit
    less = round((hours - 0.5) * 4) / 4
    p = t.t_propose_change("hours", "A busy month.", weekly_hours=less)
    assert p["proposed"] and be.plan_view(uid)["weekly_hours"] == hours                     # nothing changed yet
    aid = t.actions[0]
    r = client.post(f"/v1/coach/actions/{aid}", json={"accept": True}).json()
    assert r["status"] == "accepted" and be.plan_view(uid)["weekly_hours"] == less
    assert client.post(f"/v1/coach/actions/{aid}", json={"accept": True}).status_code == 409   # once only


def test_advice_is_followed_up_after_each_ride(env):
    be, uid, client, fake = setup(env)
    be.coach.set_allowed(uid, True)
    rider = cc.Rider(be, uid)
    first = rider.feats[0]
    data = {"title": "Easy rides easier", "do": "Keep it in zone 2.", "why": "Easy rides ran hard.", "measure": "avg_kmh",
            "want": "down", "where": "any", "kind": None, "baseline": 90}
    f = be.coach_chat.follow_up(rider, data, first["start"])
    assert f["status"] == "working" and "down from 90 km/h" in f["check"]
    assert be.coach_chat.follow_up(rider, {**data, "baseline": 2}, first["start"])["status"] == "not_yet"
    km = be.coach_chat.follow_up(rider, {**data, "measure": "km", "want": "up", "baseline": 0.0}, first["start"])
    assert "km a week" in km["check"]
    assert be.coach_chat.follow_up(rider, data, rider.feats[-1]["start"] + 1)["status"] == "waiting"
    # Saved advice checks in once per new ride, in the conversation.
    aid = be.coach_chat.add_advice(uid, 0, data)
    be.db.execute("UPDATE coach_advice SET at = ? WHERE id = ?", (first["start"], aid))
    be.coach_chat.home(uid)
    be.coach_chat.home(uid)
    checkins = [m for m in be.coach_chat.messages(uid) if m["text"].startswith("Checking in")]
    assert len(checkins) == 1 and "Easy rides easier" in checkins[0]["text"]
    assert client.put(f"/v1/coach/advice/{aid}", json={"status": "done"}).json() == {"ok": True}
    assert client.get("/v1/coach").json()["one_thing"] is None


def test_the_daily_and_weekly_limits(env, monkeypatch):
    from datetime import datetime
    be, uid, client, fake = setup(env)
    be.coach.set_allowed(uid, True)
    u = client.get("/v1/coach/usage").json()
    assert u["day"]["used_pct"] == 0 and u["week"]["used_pct"] == 0 and not u["limited"] and u["line"] is None
    fake.turns = [[text("Ride easy today.")]]
    ask(client, "Should I ride hard?")
    used = client.get("/v1/coach").json()["usage"]
    assert used["day"]["used_pct"] > 0 and used["week"]["used_pct"] <= used["day"]["used_pct"]
    # Past today's allowance: the question isn't sent anywhere, and the rider is told when it resets.
    monkeypatch.setattr(cc, "DAY_LIMIT_USD", 0.001)
    n = len(fake.calls)
    r = client.post("/v1/coach/ask", json={"text": "And tomorrow?"})
    assert r.status_code == 429 and "resets at midnight" in r.json()["detail"] and len(fake.calls) == n
    assert client.get("/v1/coach/usage").json()["day"]["used_pct"] == 100
    # The week's limit says Monday; resets are in the rider's time zone.
    monkeypatch.setattr(cc, "DAY_LIMIT_USD", 1.0)
    monkeypatch.setattr(cc, "WEEK_LIMIT_USD", 0.001)
    u = be.coach_chat.usage(uid, now=datetime(2026, 11, 25, 15, 0, tzinfo=be.insights.tz(uid)))
    assert u["limited"] and "Monday" in u["line"] and u["week"]["resets_at"].startswith("2026-11-30T00:00")
    assert u["day"]["resets_at"].startswith("2026-11-26T00:00")


def test_every_tool_and_measure_runs(env):
    be, uid, client, fake = setup(env)
    t = cc.Tools(be, uid, 0)
    rid = t.rider.feats[-1]["ride_id"]
    for name, args in [("rides", {}), ("ride", {"ride_id": rid}), ("fitness", {}), ("recovery", {}), ("plan", {}),
                       ("climbs", {}), ("show", {"type": "ride", "ride_id": rid})]:
        out = t.run(name, args)
        assert "error" not in out, (name, out)
        json.dumps(out)
    for m in cc.MEASURES:
        for by in ("ride", "week", "month"):
            json.dumps(t.run("trend", {"measure": m, "by": by, "since": "2026-01-01"}))
    assert t.run("fitness", {})["power_zones_w"] is None or "Zone 2" in t.run("fitness", {})["power_zones_w"]
