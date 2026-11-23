"""The coach's voice, Train step 5 (docs/train-method.md): what the coach is for is growth, earned encouragement
and teaching why, and this module holds the last two.

    learn(job, seed)                     -> one "why it works" line for a job, varied so it doesn't repeat day to
                                            day; each line's research is in docs/training-science.md under its key
    done_well(work, jobs, against, ftp, kind, minutes)
                                         -> one specific thing the ride did well, from its own numbers, or None

Praise follows docs/train-words.md: specific and earned, it names the thing and why it matters, never "Great job!",
never a comparison that shames. When there's nothing specific to say, there's no praise: the ride's jobs and what's
next say the rest. Everything here is calculated; the AI coach may retell it in its own words, never change it.
"""
from __future__ import annotations

# One line per idea; the key names its section in docs/training-science.md.
LEARN = {
    "punch": [
        ("punch-recover", "Short hard efforts with short rests teach you to recover while still riding: exactly "
                          "what a group's surges ask of you."),
        ("punch-repeat", "Repeating hard minutes raises how much you can give above your limit, and how fast you "
                         "bounce back after it: that's what closing a gap takes."),
        ("punch-rest-short", "The easy minutes between are short on purpose: recovering under pressure is a skill, "
                             "and it's trained like any other."),
    ],
    "top_end": [
        ("vo2-ceiling", "Efforts of 3 to 5 minutes near your limit raise the most oxygen your body can use: the "
                        "ceiling everything else sits under."),
        ("vo2-breathing", "Breathing hard for minutes at a time is the work itself: it's when your heart and lungs "
                          "are pushed to grow."),
    ],
    "hold": [
        ("hold-below", "Long steady blocks just below your limit raise what you can hold for an hour, without the "
                       "fatigue of going over it."),
        ("hold-even", "Even pacing matters here: the same watts from the first minute to the last trains your body to "
                      "keep up with what it produces at that effort."),
        ("hold-duration", "Ten minutes or more at a time is what teaches your body to keep going at a pace that used "
                          "to feel hard."),
    ],
    "long": [
        ("long-engine", "Hours at an easy pace grow the small blood vessels and the energy factories in your legs: "
                        "the engine everything else runs on."),
        ("long-fuel", "Long easy rides teach your body to burn more fat, saving its carbs for the hard moments."),
        ("long-eat", "Eating from the first hour isn't optional on long rides: you're training your stomach as well "
                     "as your legs."),
    ],
    "easy": [
        ("easy-most", "Most riding should be easy: it builds the base, and it lets the hard days be truly hard."),
        ("easy-chat", "Easy means easy: if you could chat all the way, you're doing it right."),
        ("recover-builds", "Fitness is built while you recover, not while you ride: easy days are when it happens."),
    ],
    "rest": [
        ("recover-builds", "Fitness is built while you recover, not while you ride: rest days are when it happens."),
        ("rest-sleep", "A rest day and a good night's sleep do more for tomorrow's session than an extra hour on the "
                       "bike."),
    ],
}
KIND_JOB = {"surges": "punch", "sprint": "punch", "group": "punch", "vo2": "top_end", "steady": "hold",
            "threshold": "hold", "over_unders": "hold", "long": "long", "endurance": "easy", "easy": "easy"}


def learn(job: str | None, seed: int) -> dict | None:
    """One "why it works" line for the job; seed (the day, or the ride) varies it, so the next day's is another."""
    lines = LEARN.get(job or "")
    if not lines:
        return None
    key, text = lines[seed % len(lines)]
    return {"key": key, "text": text, "job": job}


def done_well(work: dict, jobs: dict | None, against: dict | None, ftp: float | None, kind: str | None,
              minutes: float | None = None, tips: list | None = None) -> dict | None:
    """One specific thing the ride did well, from its own numbers, most telling first. None when there's nothing
    specific: then there's no praise. `tips`: the ride's things to try, so nothing they ask to change is praised."""
    tip_ids = {t.get("id") for t in tips or []}
    sets = work.get("sets") or []
    hard = [x for x in sets if ftp and x["power"] >= 1.05 * ftp and x["seconds"] <= 480]
    # 1. A set paced well: the last hard effort as strong as the first.
    if hard and "pacing" not in tip_ids:
        x = max(hard, key=lambda x: x["repeat"])
        reps = [r[1] for r in x["reps"]]
        if len(reps) >= 4 and reps[-1] >= reps[0] - 2:
            length = "minute" if x["seconds"] == 60 else "effort"
            return {"key": "paced-set",
                    "text": f"Your last hard {length} ({reps[-1]} W) was as strong as your first ({reps[0]} W): you "
                            f"paced the whole set, not just the start. That's what lets you answer the last surge, "
                            f"not only the first."}
    # 2. More than the job asked.
    more = next((j for j in (jobs or {}).get("jobs", []) if j.get("status") == "more" and j.get("basis") == "power"),
                None)                    # never praise a rough read from heart rate alone
    if more and more["job"] in ("punch", "top_end", "hold"):
        what = "of hard efforts" if more["job"] != "hold" else "of steady work"
        return {"key": "more",
                "text": f"{_m(more['have_min'])} {what}, where the week asked for {_m(more['want_min'])}: extra work, "
                        f"banked toward the goal."}
    # 3. Even pacing across steady blocks.
    steady = [x for x in sets if x["seconds"] >= 300 and len(x["reps"]) >= 2]
    if steady and ftp and "steady_too_hard" not in tip_ids:
        x = steady[0]
        ws = [r[1] for r in x["reps"]]
        spread = max(ws) - min(ws)
        if spread <= max(4, 0.03 * x["power"]):
            return {"key": "even-blocks",
                    "text": f"Your {x['repeat']} steady blocks were within {spread} W of each other: even pacing is what "
                            f"lifts the power you can hold for the whole ride."}
    # 4. Quick legs through the hard efforts.
    c30 = work.get("c30") or []
    if hard and c30 and "low_cadence" not in tip_ids and "climb_cadence" not in tip_ids:
        rpm = [c30[k] for x in hard for k in range(x["start_s"] // 10, min(len(c30), x["end_s"] // 10))
               if c30[k] is not None]
        if rpm and sum(rpm) / len(rpm) >= 90:
            return {"key": "quick-legs",
                    "text": f"You kept {round(sum(rpm) / len(rpm))} rpm through the hard efforts: quick legs save your "
                            f"muscles for the next one."}
    # 5. A long ride that held together: heart rate barely drifting late on.
    drift = work.get("drift")
    if drift is not None and minutes and minutes >= 90 and drift <= 3 and "drift" not in tip_ids:
        return {"key": "low-drift",
                "text": f"Your heart rate rose only {drift} bpm late in the ride at the same effort: your endurance "
                        f"is holding up."}
    # 6. An easy day kept easy.
    p30 = [v for v in work.get("p30") or [] if v is not None]
    easy = any(j["job"] == "easy" for j in (jobs or {}).get("jobs", []))
    if easy and ftp and p30 and sum(p30) / len(p30) <= 0.7 * ftp and "easy_too_hard" not in tip_ids:
        return {"key": "kept-easy",
                "text": f"You kept it easy all the way, {round(sum(p30) / len(p30))} W on average: that's what lets "
                        f"the hard days be hard."}
    return None


def _m(x: float) -> str:
    return f"{round(x * 2) / 2:g} min"
