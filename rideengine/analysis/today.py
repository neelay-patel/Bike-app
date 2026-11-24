"""Train, step 2 (docs/train-tab.md): today's session or rest, and how the rest of the week lays out.

The plan's dates are a guide (the rider's usual days); what's still open this week is a menu. Each day the best
next session is picked from it, given what's done, the last few days, recovery and the days left:

    plan_today(sessions, recent, today, week_start, readiness) ->
        {"state": "session" | "rest" | "done", "session_id", "why", "then", "schedule", "folded", "dropped"}

The week is laid out fresh each time from what's still open (24 Nov 2026): nothing is "moved" or remembered.

Limits no plan change (and no AI) can cross: no hard days back to back, no more than MAX_STREAK riding days in a
row, a rest day after STREAK_REST in a row when the week allows. Words follow docs/train-words.md.
"""
from __future__ import annotations

from datetime import date, timedelta

HARD = {"surges", "steady", "threshold", "vo2", "over_unders", "sprint", "group", "mixed"}
EASY = {"endurance", "long", "easy"}
FOLD_SHARE = 0.5         # a partly done job with this share or less left is added to a planned ride, not redone
HOSTS = {"surges", "steady", "threshold", "vo2", "over_unders", "sprint", "long"}   # rides a leftover can join
JOB_WORDS = {"punch": "punch", "top_end": "top-end work", "hold": "steady work", "long": "long riding",
             "easy": "easy riding"}
STREAK_REST = 3          # after this many riding days in a row, rest if the week allows
MAX_STREAK = 4           # never more than this many in a row
# Which open session comes first when several could: the goal's key work, then the rest.
PRIORITY = ["surges", "steady", "threshold", "vo2", "over_unders", "sprint", "group", "long", "endurance", "easy"]
WEEKDAY = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
# Why each session, tied to getting faster and keeping up (docs/train-words.md: WHY is the goal, in a sentence).
WHY = {"surges": "When the group speeds up, efforts like these keep you on the wheel.",
       "steady": "It raises the power you can hold for a whole ride: the base of keeping up.",
       "threshold": "It lifts the most you can hold for an hour.",
       "over_unders": "It teaches you to recover while still working, as you must in a hard group.",
       "vo2": "It raises your top end, so the hard moments feel less hard.",
       "sprint": "Snap for the moments that decide a ride.",
       "group": "Practice for the real thing: holding the wheel and answering the surges.",
       "endurance": "Easy hours build the engine everything else sits on.",
       "long": "Time in the saddle builds the endurance for longer, faster rides.",
       "easy": "It keeps your legs turning while you recover."}
# Where to ride it: indoors or out is always the rider's choice (Neelay, 21 Nov 2026); this is advice, never a rule.
WHERE = {k: "Indoors or out. The trainer makes the efforts easy to hit; outside, pick a quiet road or a steady "
            "climb, and without a power meter ride it by feel." for k in
         ("surges", "steady", "threshold", "over_unders", "vo2", "sprint")}
WHERE |= {"group": "A club ride outside, or a Zwift group ride.",
          "endurance": "Indoors or out. Outside is the better place for easy hours when the weather allows.",
          "long": "Indoors or out. Outside is the better place for long hours when the weather allows.",
          "easy": "Indoors or out: whichever is easiest today."}
# How each session should feel (docs/train-words.md, the glossary): feel words first; watts are added by the caller.
FEEL = {"surges": "Hard parts 8–9 out of 10, too hard to talk; everything else easy.",
        "steady": "7 out of 10: comfortably hard, short sentences only.",
        "threshold": "8 out of 10: hard but steady, a few words at a time.",
        "over_unders": "The overs hard, the unders just below: no real rest until the set ends.",
        "vo2": "9 out of 10 for each effort: breathing hard, no talking.",
        "sprint": "All out for the sprint itself, then completely easy.",
        "group": "Varied: sit in when you can, then answer the surges.",
        "endurance": "4 out of 10: you could chat all the way.",
        "long": "4 out of 10: you could chat all the way. Eat and drink from the first hour.",
        "easy": "2–3 out of 10: legs turning, nothing more."}

# How to ride each part of a session (the session's own page, reached from Today and What's Next; 22 Nov 2026).
# Plain words (docs/train-words.md): what to do, in order. Outside there's no power meter, so every hard part says
# how it feels as well as its watts.
WARM = {"default": "Start easy and build to steady over the warm-up, so the first effort isn't a shock.",
        "hard": "Start easy and build to steady. In the last few minutes, add two or three 10-second pick-ups so "
                "the first hard effort isn't a shock.",
        "sprint": "Start easy and build to steady. In the last few minutes, add three 10-second pick-ups, each "
                  "a little quicker, to wake your legs up for the sprints."}
MAIN = {
    "surges": ["Each hard minute: get up to speed in the first 10 seconds, seated, then hold it. Don't sprint "
               "the start; the last 20 seconds should be the hardest part to hold.",
               "The easy minutes between: keep pedalling lightly. They're short on purpose, like a group that "
               "doesn't wait.",
               "The 30-second efforts: the same, shorter. Keep the 30 seconds off moving, never stopped."],
    "steady": ["Settle into the target in the first minute and hold it: steady, not rising. Seated and smooth.",
               "Heart rate creeping up late in a block at the same effort is normal. If it passes the top of "
               "its range, ease off a little."],
    "threshold": ["Start each block at the low end of the target. You should finish wanting one more minute, "
                  "not hanging on.",
                  "Even pacing: the last minutes no harder than the first."],
    "over_unders": ["Overs: lift the effort and hold it. Unders: back to just below, but keep working; it should "
                    "never quite feel like rest until the easy minutes between sets."],
    "vo2": ["Reach the target in the first 20 to 30 seconds, then hold it. Your breathing will keep rising "
            "through each effort: that's the work.",
            "The easy minutes between: really easy, so the next effort is as good as the first."],
    "sprint": ["From a rolling start in a middle gear: out of the saddle, wind it up as fast as you can for 15 "
               "seconds, then sit and spin.",
               "Take the full easy minutes between. Fresh legs make every sprint count."],
    "group": ["Sit in a wheel whenever you can, and save your effort for the surges: when the group speeds up, "
              "answer straight away rather than chasing back on later."],
    "long": ["A pace you could chat at the whole way. If a hill pushes you hard, shift down and spin.",
             "Eat something every 30 to 45 minutes from the first hour, and drink to thirst."],
    "endurance": ["A pace you could chat at the whole way. Smooth pedalling; if a hill pushes you hard, shift "
                  "down and spin."],
    "easy": ["Very easy. If it starts to feel like training, ease off."],
}
COOL = "Spin easy until your breathing settles. A good time to drink."
CUT_SHORT = {k: "If you can't reach the target in the last efforts, stop the set there: how well you do them "
                "matters more than how many." for k in ("surges", "threshold", "over_unders", "vo2", "sprint")}


def guide(session: dict) -> dict:
    """How to ride a session: why, how it should feel, where, and what to do in each part (warm-up, main set,
    cool-down), plus what to have with you. Words only: the steps and their targets are the session's own."""
    kind = session.get("kind")
    if session.get("off_bike"):
        return {"why": session.get("purpose") or "", "feel": None, "where": None, "warm": None, "main": [],
                "cool": None, "after": None, "bring": []}
    minutes = round((session.get("seconds") or 0) / 60)
    bring = ["A bottle of water."]
    if minutes > 90:
        bring = ["Two bottles, one with carbs in it.", "Something to eat every 30 to 45 minutes."]
    if hard(kind):
        bring.append("Eat something 1 to 2 hours before: hard efforts go better with fuel in the tank.")
    steps = session.get("steps") or []
    warm_kind = "sprint" if kind == "sprint" else "hard" if hard(kind) and kind != "group" else "default"
    return {"why": WHY.get(kind) or session.get("purpose") or "",
            "feel": FEEL.get(kind),
            "where": WHERE.get(kind),
            "warm": WARM[warm_kind] if steps and steps[0].get("label") == "Warm up" else None,
            "main": MAIN.get(kind, []),
            "cool": COOL if steps and steps[-1].get("label") == "Cool down" else None,
            "after": CUT_SHORT.get(kind),
            "bring": bring}


def hard(kind: str | None) -> bool:
    return kind in HARD


def _mins_words(m: float) -> str:
    s = round(m * 2) / 2
    return f"{s:g} min"


def _days(d: date, today: date) -> str:
    """"today's", "tomorrow's", "Wednesday's"."""
    n = _day_name(d, today)
    return (n.lower() if n in ("Today", "Tomorrow") else n) + "'s"


def _day_name(d: date, today: date) -> str:
    if d == today:
        return "Today"
    if d == today + timedelta(days=1):
        return "Tomorrow"
    return WEEKDAY[d.weekday()]


def short(session: dict) -> str:
    """A session in a few words: its name and its main set ("Sweet spot, 3 × 12 min")."""
    name = session["title"]
    sets = [s["set"] for s in session.get("steps") or [] if "set" in s]
    if sets:
        main = sets[0].split(" / ")[0].split(" (")[0]
        main = main.replace(" sweet spot", "").replace(" hard", "").replace(" threshold", "")
        return f"{name}, {main}"
    minutes = round((session.get("seconds") or 0) / 60)
    return f"{name}, {minutes} min" if minutes and not session.get("off_bike") else name


def _streak(rode: set, before: date) -> int:
    n, d = 0, before - timedelta(days=1)
    while d in rode:
        n += 1
        d -= timedelta(days=1)
    return n


def schedule(open_sessions: list[dict], first: date, end: date, rode: set, hard_days: set) -> dict[str, date] | None:
    """Place the open sessions on days from `first` to before `end`: each on the earliest day on or after the
    later of its planned date and `first`, with no hard day next to another and no more than MAX_STREAK riding
    days in a row (counting rides already done). None if they don't all fit."""
    placed: dict[str, date] = {}
    riding, harder = set(rode), set(hard_days)
    order = sorted(open_sessions, key=lambda s: (s["date"], PRIORITY.index(s["kind"]) if s["kind"] in PRIORITY else 99))
    for s in order:
        d = max(first, date.fromisoformat(s["date"]))
        while d < end:
            ok = d not in riding
            if ok and hard(s["kind"]):
                ok = (d - timedelta(days=1)) not in harder and (d + timedelta(days=1)) not in harder
            if ok:
                riding.add(d)
                ok = _streak(riding, d + timedelta(days=1)) <= MAX_STREAK
                riding.discard(d)
            if ok:
                break
            d += timedelta(days=1)
        if d >= end:
            # Not after its planned date: try any free day from `first` (a session can come earlier).
            d = first
            while d < end and (d in riding or (hard(s["kind"]) and ((d - timedelta(days=1)) in harder or
                                                                    (d + timedelta(days=1)) in harder))):
                d += timedelta(days=1)
            if d >= end:
                return None
        placed[s["id"]] = d
        riding.add(d)
        if hard(s["kind"]):
            harder.add(d)
    return placed


def plan_today(sessions: list[dict], recent: list[dict], today: date, week_start: date,
               readiness: str = "unknown") -> dict:
    """sessions: this week's sessions, each with "status" (done | open | today | upcoming | missed).
    recent: rides of the last 7 days and today, [{"date": date, "kind": str | None, "minutes": int}].
    readiness: good | watch | strained | unknown (wellness.readiness)."""
    end = week_start + timedelta(days=7)
    # Partly done with little left (docs/train-method.md): the rest joins a ride already planned, so it's never
    # redone as a whole session.
    folding = [s for s in sessions if s.get("status") != "done" and not s.get("off_bike") and s.get("progress")
               and s["progress"]["left_min"] <= FOLD_SHARE * s["progress"]["want_min"]]
    sessions = [s for s in sessions if s not in folding]
    rides = [r for r in recent if r.get("kind") is not None or (r.get("minutes") or 0) >= 15]
    rode = {r["date"] for r in rides if r["date"] < today}
    hard_days = {r["date"] for r in rides if r["date"] < today and hard(r.get("kind"))}
    rode_today = [r for r in rides if r["date"] == today]
    open_ = [s for s in sessions if s.get("status") != "done" and not s.get("off_bike")]
    off_bike = [s for s in sessions if s.get("status") != "done" and s.get("off_bike")]
    yesterday = today - timedelta(days=1)
    streak = _streak(rode, today)
    out = {"state": "rest", "session_id": None, "why": "", "then": "", "schedule": {}, "folded": [],
           "dropped": []}

    def finish(start_from: date, today_session: dict | None) -> dict:
        riding, harder = set(rode), set(hard_days)
        if rode_today:
            riding.add(today)
            if any(hard(r.get("kind")) for r in rode_today):
                harder.add(today)
        rest = [s for s in open_ if not today_session or s["id"] != today_session["id"]]
        if today_session:
            riding.add(today)
            if hard(today_session["kind"]):
                harder.add(today)
        placed = schedule(rest, start_from, end, riding, harder)
        # No room for everything: let go of what matters least for the goal, one at a time, and say so.
        pool = sorted(rest, key=lambda s: -PRIORITY.index(s["kind"]) if s["kind"] in PRIORITY else -99)
        while placed is None and pool:
            gone = pool.pop(0)
            rest.remove(gone)
            out["dropped"].append({"id": gone["id"], "title": gone["title"], "kind": gone["kind"],
                                   "line": f"No room for {gone['title'].lower()} this week, so it's let go."})
            placed = schedule(rest, start_from, end, riding, harder)
        placed = placed or {}
        if today_session:
            placed[today_session["id"]] = today
        # The leftovers: onto the first planned ride that can take a few hard efforts (a hard day or the long
        # ride, never an easy day), else let go.
        by_id = {s["id"]: s for s in open_}
        hosts = sorted(((d, by_id[sid]) for sid, d in placed.items() if sid in by_id and by_id[sid]["kind"] in HOSTS),
                       key=lambda x: x[0])
        for f in folding:
            p = f["progress"]
            left = _mins_words(p["left_min"])
            what = JOB_WORDS.get(p.get("job") or "", "work")
            host = hosts[0] if hosts else None
            if host:
                d, h = host
                out["folded"].append({"id": f["id"], "into": h["id"], "date": d.isoformat(), "job": p.get("job"),
                                      "left_min": p["left_min"],
                                      "line": f"{left} of {what} left from {f['title'].lower()}: added to "
                                              f"{_days(d, today)} {h['title'].lower()}."})
            else:
                out["dropped"].append({"id": f["id"], "title": f["title"], "kind": f["kind"],
                                       "line": f"{left} of {what} left from {f['title'].lower()}, and no hard day "
                                               f"left this week to add it to, so it's let go."})
        out["schedule"] = {sid: d.isoformat() for sid, d in placed.items()}
        # What's next, in words: tomorrow (a session or rest), then the next session after it this week.
        by_day = {v: k for k, v in placed.items()}
        names = {s["id"]: s for s in open_}
        tomorrow = today + timedelta(days=1)
        if tomorrow >= end:
            out["then"] = "A new week starts tomorrow."
            return out
        sid = by_day.get(tomorrow)
        words = [f"Tomorrow: {short(names[sid]) if sid else 'rest'}."]
        later = sorted(d for d in by_day if d > tomorrow)
        if later:
            words.append(f"{_day_name(later[0], today)}: {short(names[by_day[later[0]]])}.")
        else:
            words.append(f"A new week starts {_day_name(end, today).lower() if end - today > timedelta(days=1) else 'tomorrow'}."
                         .replace("starts monday", "starts on Monday"))
        if off_bike:
            words.append(f"{off_bike[0]['title']} is still open this week.")
        out["then"] = " ".join(words)
        return out

    if rode_today:
        out["state"] = "done"
        out["why"] = "You've ridden today. Rest and eat well; the next session is set out below."
        return finish(today + timedelta(days=1), None)
    if not open_:
        out["why"] = ("Every session this week is done. Rest, or ride easy if you'd like to." if sessions else
                      "No sessions planned this week.")
        if off_bike:
            out["why"] += f" {off_bike[0]['title']} is still open: a good day for it."
        return finish(today + timedelta(days=1), None)

    # How the last rides felt (the rider's one tap): something hurting means rest; wrecked means easy.
    recent_days = {today - timedelta(days=1), today - timedelta(days=2)}
    hurt = next((r for r in rides if r.get("hurts") and r["date"] in recent_days), None)
    if hurt:
        out["why"] = (f"You said something hurt after {WEEKDAY[hurt['date'].weekday()]}'s ride. Rest today; if it "
                      f"still hurts in a day or two, see a physio or doctor before riding hard.")
        return finish(today + timedelta(days=1), None)
    wrecked = next((r for r in rides if r.get("feel") == "wrecked" and r["date"] in recent_days), None)
    easy_open = [s for s in open_ if not hard(s["kind"])]
    if wrecked and readiness != "strained":
        if easy_open:
            pick = easy_open[0]
            out.update(state="session", session_id=pick["id"],
                       why=f"You said {WEEKDAY[wrecked['date'].weekday()]}'s ride left you wrecked, so today is easy. "
                           f"The harder sessions move later in the week.")
            return finish(today + timedelta(days=1), pick)
        out["why"] = (f"You said {WEEKDAY[wrecked['date'].weekday()]}'s ride left you wrecked, so today is rest. "
                      f"The harder sessions move later in the week.")
        return finish(today + timedelta(days=1), None)
    if readiness == "strained":
        if easy_open:
            pick = easy_open[0]
            out.update(state="session", session_id=pick["id"],
                       why="Your recovery is lower than usual this morning, so today is easy. The harder sessions "
                           "move later in the week.")
            return finish(today + timedelta(days=1), pick)
        out["why"] = ("Your recovery is lower than usual this morning, so today is rest. The harder sessions move "
                      "later in the week.")
        return finish(today + timedelta(days=1), None)

    # Would the week still fit if today were rest?
    planned_today = [s for s in open_ if s["date"] == today.isoformat()]
    fits_after = schedule(open_, today + timedelta(days=1), end, rode, hard_days) is not None
    if streak >= MAX_STREAK or (streak >= STREAK_REST and fits_after):
        out["why"] = (f"{streak} days of riding in a row. Rest today: the fitness from them is built while you "
                      f"recover, and the next session will be better for it.")
        if off_bike:
            out["why"] += f" {off_bike[0]['title']} fits well today."
        return finish(today + timedelta(days=1), None)
    if not planned_today and fits_after:
        out["why"] = "Rest today: the rest of this week's sessions still fit on the days ahead."
        if off_bike:
            out["why"] += f" {off_bike[0]['title']} fits well today."
        return finish(today + timedelta(days=1), None)

    yesterday_hard = yesterday in hard_days
    choices = [s for s in open_ if not (yesterday_hard and hard(s["kind"]))]
    if not choices:
        if fits_after:
            out["why"] = "Yesterday was hard, so rest today; the harder sessions come later in the week."
            return finish(today + timedelta(days=1), None)
        choices = open_          # the week is short of days: the work comes first
    choices.sort(key=lambda s: (s["date"] != today.isoformat(),
                                PRIORITY.index(s["kind"]) if s["kind"] in PRIORITY else 99, s["date"]))
    pick = choices[0]
    out.update(state="session", session_id=pick["id"])
    if yesterday_hard and not hard(pick["kind"]):
        out["why"] = f"Yesterday was hard, so today is easy: {pick['title'].lower()}."
    elif pick["date"] == today.isoformat():
        out["why"] = WHY.get(pick["kind"]) or pick.get("purpose") or ""
    else:
        was = date.fromisoformat(pick["date"])
        when = "earlier this week" if was < today else WEEKDAY[was.weekday()]
        out["why"] = f"Planned for {when}; it's the one to do next. " + (WHY.get(pick["kind"]) or pick.get("purpose") or "")
    return finish(today + timedelta(days=1), pick)


def greeting(recent: list[dict], today: date, readiness: str, state: str) -> str:
    """The coach's opening line: the last week of riding, recovery, and what that means for today."""
    days = sorted({r["date"] for r in recent if today - timedelta(days=7) <= r["date"] < today})
    n = len(days)
    first = (f"You rode {n} {'day' if n == 1 else 'days'} in the last week" if n else "No rides in the last week")
    if n and (today - timedelta(days=1)) not in days:
        first += " and rested yesterday"
    first += "."
    rec = {"good": "Your recovery looks normal", "watch": "Your recovery is a little lower than usual",
           "strained": "Your recovery is lower than usual"}.get(readiness)
    if state == "session":
        tail = (f" {rec}, so today's session is on." if readiness in ("good", "unknown") and rec else
                f" {rec}." if rec else "")
    elif state == "done":
        tail = " Today's ride is in."
    else:
        tail = f" {rec}." if rec else ""
    return (first + tail).strip()
