"""The Sunday review, Train step 6 (docs/train-method.md "Week to week"): the week in a few lines, and what next
week should change, as proposals in a fixed format the engine checks before anything moves.

    review(week, history, markers, feels, next_week, weekly_hours) -> {"week_start", "lines", "proposals"}
    check(proposal, next_week, weekly_hours)                       -> None if it may apply, else why not

A proposal: {"id", "type", "size": small | big, "change", "reason", "rules", "apply"}. Small ones apply on their own
and are said in a line; big ones (the week's hours, the mix of jobs, an easier week) wait for the rider's OK.
The rules, from the method:
- A job skipped two weeks running: offer another way to do it, not more of the same (small).
- A goal number that hasn't moved in four weeks: shift next week toward the job that builds it (big).
- Riding more than planned two weeks running, and nothing felt wrecked: grow the week, up to 10% (big).
- Feeling tired (wrecked or something hurting, or recovery low on several days): an easier week now (big).
The AI coach may say all of this in its own words; it never adds a change of its own here, and never removes one.
"""
from __future__ import annotations

from datetime import date, timedelta

from .plan import JOB_OF

GROW_MAX = 0.10                  # the week grows at most this much at a time
MORE_THAN_PLANNED = 1.10         # riding this much more than planned counts as "more"
STALL_WEEKS = 4                  # a goal number unmoved this long shifts the emphasis
MARKER_JOB = {"sustained": ("hold", "steady"), "punch": ("punch", "surges"), "durability": ("long", "long")}
JOB_WORDS = {"punch": "punch", "top_end": "top-end work", "hold": "steady work", "long": "the long ride",
             "easy": "easy riding"}
# Another way to do a job (docs/train-method.md: a skipped job gets a different way, not more of the same).
ANOTHER_WAY = {
    "punch": "a group ride, or hills taken hard outside: anything with hard efforts of 30 s to 2 min counts",
    "top_end": "a long climb ridden hard in 3 to 5 minute pieces, outside or on Zwift",
    "hold": "a long steady climb outside, or 2 × 10 min of steady work inside a longer ride you enjoy",
    "long": "a ride with friends or a café stop: time in the saddle at a chatting pace is all it asks",
    "easy": "a short spin, even 30 min: legs turning is enough",
}
SWAP_FROM = ["easy", "endurance", "group"]      # what gives way when the emphasis shifts, first to last


def _hm(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m} min" if m < 60 else f"{m // 60} h" + (f" {m % 60:02d}" if m % 60 else "")


def _planned(week: dict) -> float:
    return sum((s.get("seconds") or 0) / 60 for s in week["sessions"] if not s.get("off_bike"))


def _ridden(week: dict) -> float:
    return sum(r.get("minutes") or 0 for r in week.get("rides", []) if (r.get("minutes") or 0) >= 15)


def _skipped(week: dict) -> set:
    """Jobs the week asked for and no session of which was done, or even partly done."""
    def job(s):
        return s.get("job") or JOB_OF.get(s["kind"])
    on_bike = [s for s in week["sessions"] if not s.get("off_bike")]
    touched = {job(s) for s in on_bike if s.get("status") == "done" or s.get("progress")}
    return {job(s) for s in on_bike} - touched


def review(week: dict, history: list[dict], markers: list[dict], feels: list[dict], next_week: dict | None,
           weekly_hours: float, strained_days: int = 0) -> dict:
    """week: the plan view's week being reviewed; history: the weeks before it, oldest first; markers: the goal's
    numbers, each {"id", "name", "unit", "current", "then" (four weeks ago), "target"}; feels: [{"feel", "hurts"}]
    for the week's rides; next_week: the plan view's next week; strained_days: mornings with recovery lower than
    usual this week (its numbers never shown)."""
    ws = week["week_start"]
    on_bike = [s for s in week["sessions"] if not s.get("off_bike")]
    done = [s for s in on_bike if s.get("status") == "done"]
    lines = []
    if on_bike:
        jobs_done = [JOB_WORDS.get(s.get("job") or JOB_OF.get(s["kind"]), s["title"].lower()) for s in done]
        head = (f"{len(done)} of {len(on_bike)} jobs done" if done else "None of this week's jobs done")
        if jobs_done:
            uniq = []
            for j in jobs_done:
                n = jobs_done.count(j)
                w = f"{j} twice" if n == 2 else f"{j} {n} times" if n > 2 else j
                if w not in uniq:
                    uniq.append(w)
            head += ": " + (uniq[0] if len(uniq) == 1 else ", ".join(uniq[:-1]) + " and " + uniq[-1])
        lines.append(head + ".")
        gone = [s["title"].lower() for s in on_bike if s.get("dropped")]
        if gone:
            lines.append(f"Let go for lack of room: {', '.join(gone)}.")
    planned, ridden = _planned(week), _ridden(week)
    if planned:
        lines.append(f"{_hm(ridden)} ridden, against {_hm(planned)} planned.")
    for m in markers:
        if m.get("current") is None or m.get("then") is None:
            continue
        diff = m["current"] - m["then"]
        if abs(diff) >= 1:
            lines.append(f"Your {m['name'].lower()}: {m['current']} {m['unit']}, "
                         f"{'up' if diff > 0 else 'down'} {abs(round(diff))} {m['unit']} in four weeks.")
        else:
            lines.append(f"Your {m['name'].lower()}: {m['current']} {m['unit']}, the same as four weeks ago.")

    proposals = []
    nws = next_week["week_start"] if next_week else None
    # A job skipped two weeks running: another way to do it.
    if history:
        twice = _skipped(week) & _skipped(history[-1])
        for job in sorted(j for j in twice if j in ANOTHER_WAY):
            proposals.append({"id": f"{ws}:another_way:{job}", "type": "another_way", "size": "small",
                              "change": f"Next week, {JOB_WORDS[job]} can also be {ANOTHER_WAY[job]}.",
                              "reason": f"{JOB_WORDS[job].capitalize()} was skipped two weeks running.",
                              "rules": ["a skipped job gets another way, not more of the same"],
                              "apply": {"type": "another_way", "job": job, "text": ANOTHER_WAY[job]}})
    tired = (sum(1 for f in feels if f.get("feel") == "wrecked") >= 1 and
             sum(1 for f in feels if f.get("feel") in ("wrecked", "hard")) >= 2) or \
        any(f.get("hurts") for f in feels) or strained_days >= 2
    if next_week and tired and next_week.get("phase") not in ("recovery", "taper"):
        why = ("something hurt after a ride" if any(f.get("hurts") for f in feels) else
               "your recovery was lower than usual on several mornings" if strained_days >= 2 else
               "rides felt wrecked or hard more than once")
        proposals.append({"id": f"{ws}:ease", "type": "ease", "size": "big",
                          "change": "Make next week an easier one: shorter, and nothing hard.",
                          "reason": f"This week {why}. Fitness is built while you recover.",
                          "rules": ["an easier week early when you're tired"],
                          "apply": {"type": "ease", "week_start": nws}})
    # Riding more than planned two weeks running, nothing wrecked: grow the week a little.
    elif history and planned and _planned(history[-1]) and not tired and next_week:
        if ridden >= MORE_THAN_PLANNED * planned and _ridden(history[-1]) >= MORE_THAN_PLANNED * _planned(history[-1]):
            import math
            new = math.floor(weekly_hours * (1 + GROW_MAX) * 4 + 1e-9) / 4      # to the quarter hour, never over
            if new > weekly_hours:
                proposals.append({"id": f"{ws}:hours:{new}", "type": "hours", "size": "big",
                                  "change": f"Plan {new:g} hours a week from next week, up from {weekly_hours:g}.",
                                  "reason": f"You rode {_hm(_ridden(history[-1]))} and {_hm(ridden)} the last two "
                                            f"weeks, more than planned, and nothing felt wrecked.",
                                  "rules": ["the week grows at most 10% at a time"],
                                  "apply": {"type": "hours", "weekly_hours": new}})
    # A goal number that hasn't moved in four weeks: next week leans toward the job that builds it.
    if next_week and next_week.get("phase") not in ("recovery", "taper"):
        for m in markers:
            if m.get("current") is None or m.get("then") is None or m["id"] not in MARKER_JOB:
                continue
            if m.get("target") and m["current"] >= m["target"]:
                continue
            if m["current"] - m["then"] >= 1:
                continue
            job, kind = MARKER_JOB[m["id"]]
            has = sum(1 for s in next_week["sessions"] if (s.get("job") or JOB_OF.get(s["kind"])) == job)
            give = next((s for k in SWAP_FROM for s in next_week["sessions"]
                         if s["kind"] == k and k != kind and not s.get("off_bike")), None)
            if give is None or has >= 2:
                continue
            title = {"steady": "sweet spot", "surges": "surges", "long": "a long ride"}[kind]
            proposals.append({"id": f"{ws}:swap:{give['id']}:{kind}", "type": "swap", "size": "big",
                              "change": f"Next week, {title} in place of {give['title'].lower()}, to work on your "
                                        f"{m['name'].lower()}.",
                              "reason": f"Your {m['name'].lower()} has stayed at {m['current']} {m['unit']} for four "
                                        f"weeks.",
                              "rules": ["a goal number unmoved for four weeks shifts the emphasis",
                                        "no hard days back to back", "the week's hours stay the same"],
                              "apply": {"type": "swap", "session_id": give["id"], "to_kind": kind}})
            break                                   # one shift at a time
    return {"week_start": ws, "lines": lines, "proposals": proposals}


def check(p: dict, next_week: dict | None, weekly_hours: float) -> str | None:
    """None if the proposal keeps within the limits and may apply; else why not, in a few words."""
    from .today import schedule
    a = p.get("apply") or {}
    t = a.get("type")
    if t == "another_way":
        return None if a.get("job") in ANOTHER_WAY else "unknown job"
    if t == "hours":
        new = a.get("weekly_hours") or 0
        if new <= 0 or new > weekly_hours * (1 + GROW_MAX) + 1e-6:
            return "grows the week by more than 10%"
        return None
    if t == "ease":
        if not next_week or next_week["week_start"] != a.get("week_start"):
            return "not next week"
        return None if next_week.get("phase") not in ("recovery", "taper") else "next week is already easy"
    if t == "swap":
        if not next_week:
            return "no next week"
        sessions = [dict(s) for s in next_week["sessions"] if not s.get("off_bike")]
        hit = next((s for s in sessions if s["id"] == a.get("session_id")), None)
        if hit is None:
            return "no such session"
        hit["kind"] = a.get("to_kind")
        start = date.fromisoformat(next_week["week_start"])
        # The whole week must still fit its days with rest between hard days.
        if schedule(sessions, start, start + timedelta(days=7), set(), set()) is None:
            return "the week wouldn't fit with rest between hard days"
        return None
    return "unknown change"
