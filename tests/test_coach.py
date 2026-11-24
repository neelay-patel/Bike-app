"""Train step 5: the AI coach's words on top of the engine (backend/coach.py). A fake Claude: no network, no key."""
import json
from datetime import date, timedelta
from types import SimpleNamespace

from backend import coach as coach_mod
from rideengine.analysis import today as td
from test_backend import API_KEY, env  # noqa: F401  (pytest fixture)
from test_today import MON, rides, week


class FakeClaude:
    def __init__(self, reply=None, stop="end_turn"):
        self.reply = reply or {"headline": "A steady endurance hour", "story": "Steady work, as planned."}
        self.stop = stop
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason=self.stop, model=kw["model"],
                               content=[SimpleNamespace(type="text", text=json.dumps(self.reply))],
                               usage=SimpleNamespace(input_tokens=1200, output_tokens=80, cache_read_input_tokens=0,
                                                     cache_creation_input_tokens=0))


def test_number_check():
    facts = {"ride": {"km": 35.6, "ascent_m": 392, "best_minute": 273}, "goal": {"target": 223, "weeks_left": 23},
             "new_bests": ["Best minute: 273 W, your best yet."], "big": 1139}
    assert coach_mod.check_numbers("273 W is past the 223 W you aimed for, with 23 weeks to go.", facts) == []
    assert coach_mod.check_numbers("35.6 km and 392 m, 1,139 m all told.", facts) == []
    assert coach_mod.check_numbers("That's 50 W more than you aimed for.", facts) == ["50"]   # worked out, not given
    assert coach_mod.check_numbers("No numbers at all.", facts) == []


def ride_with_note(be, uid, client):
    client.put("/v1/connections/garmin_personal?since=2026-01-01", json={"api_key": API_KEY})
    client.put("/v1/goals/current", json={"objective": "faster", "aspiration": "keep_up_group"})
    rid = be.db.execute("SELECT ride_id FROM rides WHERE user_id = ? ORDER BY start_t DESC LIMIT 1", (uid,)).fetchone()[0]
    return rid


def test_no_ai_unless_the_rider_turned_it_on(env, monkeypatch):
    be, uid, client, _ = env
    fake = FakeClaude()
    be.coach._client = fake
    rid = ride_with_note(be, uid, client)
    n = client.get(f"/v1/train/rides/{rid}").json()
    assert "story" not in n and fake.calls == []               # off by default: nothing sent anywhere


def test_story_written_checked_saved_and_costed(env):
    be, uid, client, _ = env
    fake = FakeClaude()
    be.coach._client = fake
    rid = ride_with_note(be, uid, client)
    c = be._plan_context(uid)
    note = be.train_ride_note(uid, rid)          # before switching it on, so no background story starts
    be.coach.set_allowed(uid, True)
    facts = be._story_facts(c, next(f for f in c["feats"] if f["ride_id"] == rid),
                            date.fromisoformat(note["date"]), note, be._goal_markers(uid, c))
    # What the AI may know: no GPS, no place names, no recovery data.
    flat = json.dumps(facts)
    for banned in ("lat", "lon", "hrv", "resting", "cells", "bbox", "first", "track"):
        assert f'"{banned}' not in flat.lower()
    story = be.coach.ride_story(uid, rid, facts, wait=True)
    assert story == {"ok": True, "headline": "A steady endurance hour", "story": "Steady work, as planned.", "by": "ai",
                     "model": coach_mod.MODEL}
    call = fake.calls[-1]
    assert call["model"] == "claude-opus-5-5" and call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default" and "Don't repeat" in call["system"][0]["text"]
    # Saved: the same facts don't call again.
    n = len(fake.calls)
    assert be.coach.ride_story(uid, rid, facts) == story and len(fake.calls) == n
    assert be.coach.spend(uid)["calls"] == 1 and be.coach.spend(uid)["usd"] > 0


def test_rejected_replies_keep_the_engines_words(env):
    be, uid, client, _ = env
    be.coach.set_allowed(uid, True)
    rid = ride_with_note(be, uid, client)
    facts = {"ride": {"km": 25.0}}
    be.coach._client = FakeClaude({"headline": "Up 12% on last week", "story": "Made-up numbers."})
    assert be.coach.ride_story(uid, rid, facts, wait=True) is None           # 12 isn't in the facts
    out = json.loads(be.db.execute("SELECT output FROM coach_texts WHERE key = ?", (f"ride:{rid}",)).fetchone()[0])
    assert out == {"ok": False, "why": "numbers", "bad": ["12"]}
    be.coach._client = FakeClaude(stop="refusal")
    assert be.coach.ride_story(uid, rid, {"ride": {"km": 26.0}}, wait=True) is None


def test_how_it_felt(env):
    be, uid, client, _ = env
    rid = ride_with_note(be, uid, client)
    assert client.put(f"/v1/train/rides/{rid}/feel", json={"feel": "meh"}).status_code == 400
    assert client.put("/v1/train/rides/nope/feel", json={"feel": "good"}).status_code == 404
    n = client.put(f"/v1/train/rides/{rid}/feel", json={"feel": "wrecked"}).json()
    assert n["feel"] == {"feel": "wrecked", "hurts": False}


def test_feel_shapes_the_next_days():
    w = week({"surges": "done"})
    wrecked = [{**r, "feel": "wrecked"} for r in rides((0, "surges"))]
    t = td.plan_today(w, wrecked, MON + timedelta(days=1), MON, "good")
    assert t["session_id"] == "s-endurance" or t["state"] == "rest"
    assert "left you wrecked" in t["why"]
    hurt = [{**r, "hurts": True} for r in rides((0, "surges"))]
    t = td.plan_today(w, hurt, MON + timedelta(days=1), MON, "good")
    assert t["state"] == "rest" and "see a physio or doctor" in t["why"]


def test_the_review_words_keep_every_change_and_only_the_facts_numbers():
    from backend.coach import _check_review
    facts = {"week": ["3 of 4 jobs done.", "3 h 25 ridden, against 4 h planned."],
             "proposals": [{"id": "w:ease", "change": "Make next week an easier one.", "reason": "Rides felt wrecked."}]}
    ok = _check_review({"summary": "Three of four done, 3 h 25 in all.", "proposals": [{"id": "w:ease", "why": "Rest builds it."}]}, facts)
    assert ok["ok"] and ok["proposals"] == {"w:ease": "Rest builds it."}
    assert _check_review({"summary": "Fine.", "proposals": []}, facts)["why"] == "proposals"      # can't drop one
    assert _check_review({"summary": "Fine.", "proposals": [{"id": "w:ease", "why": "x"}, {"id": "w:more", "why": "y"}]},
                         facts)["why"] == "proposals"                                              # can't add one
    assert _check_review({"summary": "You rode 5 h.", "proposals": [{"id": "w:ease", "why": "x"}]}, facts)["why"] == "numbers"


def test_the_morning_brief_is_the_engines_day_in_the_coachs_words(env):
    be, uid, client, _ = env
    fake = FakeClaude({"title": "Sweet spot: 2 × 11 min", "body": "Hold 140–149 W, steady: it lifts what you can hold."})
    be.coach._client = fake
    ride_with_note(be, uid, client)
    c = be._plan_context(uid)
    t = {"state": "session", "why": "It raises the power you can hold.", "done": 1, "total": 5,
         "session": {"title": "Sweet spot", "kind": "steady", "job": "hold", "seconds": 3000,
                     "steps": [{"set": "2 × 11 min", "repeat": 2, "steps": [{"zone": "SS", "target": {"watts": [140, 149]}}]}]},
         "next": [], "goal": {"title": "Keep up with the fast group", "weeks_left": 22}, "latest": None}
    f = be._brief_facts(c, c["today"], t, "Sweet spot today", "Sweet spot, 2 × 11 min.")
    assert f["session"]["watts"] == "140–149 W" and f["rest_day"] is False
    assert "readiness" not in str(f) and "hrv" not in str(f).lower()
    # A day eased because recovery was low: no AI brief at all.
    assert be._brief_facts(c, c["today"], {**t, "why": "Your recovery is lower than usual this morning, so today is easy."},
                           "Easy", "Easy.") is None
    # Written by the coach once allowed, checked, saved; Today reads the saved words without a new call.
    be.coach.set_allowed(uid, True)
    out = be.coach.ride_story(uid, c["today"].isoformat(), f, wait=True, key=f"brief:{c['today'].isoformat()}")
    assert out["title"] == "Sweet spot: 2 × 11 min" and len(fake.calls) == 1
    assert be.coach.saved(uid, f"brief:{c['today'].isoformat()}")["body"].startswith("Hold 140–149 W")
    assert "recovery" not in fake.calls[0]["messages"][0]["content"].lower()
    # A number that isn't in the facts: refused, the engine's words stay.
    be.coach._client = FakeClaude({"title": "Sweet spot", "body": "Hold 160 W."})
    assert be.coach.ride_story(uid, "x", f, wait=True, key="brief:2030-01-01") is None
