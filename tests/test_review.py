"""Train step 6: the Sunday review. The week in a few lines; proposals by fixed rules, in a fixed format, checked
by the engine before anything changes; small ones apply on their own, big ones wait for the rider's OK."""
from rideengine.analysis import review as rv


def wk(ws, sessions, rides=(), phase="build"):
    return {"week_start": ws, "phase": phase, "sessions": list(sessions), "rides": list(rides)}


def s(sid, kind, day, status="upcoming", minutes=60, **kw):
    job = {"surges": "punch", "steady": "hold", "endurance": "easy", "group": "punch", "long": "long"}[kind]
    return {"id": sid, "kind": kind, "job": job, "title": {"surges": "Surges", "steady": "Sweet spot",
            "endurance": "Endurance", "group": "Group ride", "long": "Long ride"}[kind],
            "date": day, "status": status, "seconds": minutes * 60, **kw}


def week_of(ws, statuses, ridden):
    days = ["23", "24", "25", "27"]
    kinds = ["surges", "steady", "endurance", "group"]
    return wk(ws, [s(f"{ws}-{k}", k, f"2026-11-{d}", st) for k, d, st in zip(kinds, days, statuses)],
              [{"minutes": m} for m in ridden])


def test_the_week_in_a_few_lines():
    w = week_of("2026-11-23", ["done", "done", "missed", "done"], [60, 75, 70])
    r = rv.review(w, [], [{"id": "sustained", "name": "Sustained power", "unit": "W", "current": 155, "then": 151,
                           "target": 162}], [], None, 4.0)
    assert r["lines"][0] == "3 of 4 jobs done: punch twice and steady work."
    assert r["lines"][1] == "3 h 25 ridden, against 4 h planned."
    assert r["lines"][2] == "Your sustained power: 155 W, up 4 W in four weeks."
    assert r["proposals"] == []


def test_a_job_skipped_twice_gets_another_way_and_it_is_small():
    before = week_of("2026-11-16", ["done", "done", "missed", "done"], [60, 60, 60])
    w = week_of("2026-11-23", ["done", "done", "missed", "done"], [60, 60, 60])
    nxt = week_of("2026-11-30", ["upcoming"] * 4, [])
    (p,) = rv.review(w, [before], [], [], nxt, 4.0)["proposals"]
    assert p["type"] == "another_way" and p["size"] == "small" and "short spin" in p["change"]
    assert rv.check(p, nxt, 4.0) is None


def test_riding_more_grows_the_week_at_most_ten_percent():
    before = week_of("2026-11-16", ["done"] * 4, [80, 80, 80, 40])
    w = week_of("2026-11-23", ["done"] * 4, [85, 80, 80, 40])
    nxt = week_of("2026-11-30", ["upcoming"] * 4, [])
    (p,) = rv.review(w, [before], [], [{"feel": "good"}], nxt, 4.0)["proposals"]
    assert p["type"] == "hours" and p["size"] == "big" and p["apply"]["weekly_hours"] == 4.25
    assert rv.check(p, nxt, 4.0) is None
    assert rv.check({**p, "apply": {"type": "hours", "weekly_hours": 4.5}}, nxt, 4.0) == "grows the week by more than 10%"


def test_tired_means_an_easier_week_not_more():
    before = week_of("2026-11-16", ["done"] * 4, [80, 80, 80, 40])
    w = week_of("2026-11-23", ["done"] * 4, [85, 80, 80, 40])
    nxt = week_of("2026-11-30", ["upcoming"] * 4, [])
    props = rv.review(w, [before], [], [{"feel": "wrecked"}, {"feel": "hard"}], nxt, 4.0)["proposals"]
    assert [p["type"] for p in props] == ["ease"] and props[0]["size"] == "big"
    assert rv.check(props[0], nxt, 4.0) is None
    assert rv.check(props[0], {**nxt, "phase": "recovery"}, 4.0) == "next week is already easy"


def test_a_stalled_goal_number_shifts_next_week_if_the_week_still_fits():
    w = week_of("2026-11-23", ["done"] * 4, [60, 60, 60, 60])
    nxt = week_of("2026-11-30", ["upcoming"] * 4, [])
    m = [{"id": "sustained", "name": "Sustained power", "unit": "W", "current": 151, "then": 151, "target": 162}]
    (p,) = rv.review(w, [], m, [], nxt, 4.0)["proposals"]
    assert p["type"] == "swap" and p["apply"] == {"type": "swap", "session_id": "2026-11-30-endurance", "to_kind": "steady"}
    assert p["reason"] == "Your sustained power has stayed at 151 W for four weeks."
    # Two hold sessions already: nothing to shift. A swap that would leave no rest between hard days is refused.
    crowded = wk("2026-11-30", [s("a", "surges", "2026-11-30"), s("b", "steady", "2026-12-01"),
                                s("c", "group", "2026-12-02"), s("d", "endurance", "2026-12-03"),
                                s("e", "surges", "2026-12-04"), s("f", "surges", "2026-12-05"),
                                s("g", "surges", "2026-12-06")])
    bad = {**p, "apply": {"type": "swap", "session_id": "d", "to_kind": "steady"}}
    assert rv.check(bad, crowded, 4.0) == "the week wouldn't fit with rest between hard days"


def test_a_job_done_once_isnt_skipped_even_if_another_of_its_sessions_was():
    w = week_of("2026-11-23", ["done", "done", "missed", "missed"], [60, 60])      # surges done, group ride missed
    before = week_of("2026-11-16", ["done", "done", "missed", "missed"], [60, 60])
    nxt = week_of("2026-11-30", ["upcoming"] * 4, [])
    assert [p["apply"]["job"] for p in rv.review(w, [before], [], [], nxt, 4.0)["proposals"]] == ["easy"]
