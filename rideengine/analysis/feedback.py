"""Train, step 2: what a ride did for the goal, and one thing to try next time (docs/train-tab.md).

    contribution(feat, earlier, ftp) -> {"load", "bests": [{"id", "watts", "text"}]}
    pointers(work, ride_class, ftp, intent) -> [{"id", "title", "text", "evidence"}], most useful first

The pointers are constructive coaching from what the ride contained: cadence on the climbs and on steady riding,
pacing across hard efforts, easy days ridden too hard, a sweet spot drifting into threshold, heart rate climbing
at the same power late in long rides, no warm-up before hard work. Each says what we saw (with the numbers), what
to try, and why it makes you a better rider, in plain words (docs/train-words.md). Training guidance from the
rider's own data, not medical advice.
"""
from __future__ import annotations

from .train import STEP_S, _efforts

CLIMB_RPM = 65           # pushes (climbs) below this cadence
CLIMB_RPM_TRY = 75
LOW_RPM = 75             # median cadence on steady riding below this
HIGH_RPM = 105
FADE = 1.12              # first hard efforts this much above the last ones
DRIFT_BPM = 6            # heart rate this much higher at the same power, late against early
EASY_TOO_HARD = 0.25     # an easy session with this share of its time at sweet spot or above
WARM_UP_S = 5 * 60       # a hard effort sooner than this into a hard session
EASY_INTENT = {"endurance", "long", "easy"}
BEST_NAMES = {"60": "Best minute", "300": "Best 5 minutes", "1200": "Best 20 minutes"}


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def pointers(w: dict, cls: dict, ftp: float | None, intent: str | None = None) -> list[dict]:
    """One thing (or a few, best first) to try next time, from what the ride contained. `intent` is the kind of
    the planned session the ride counted as, when it counted as one."""
    out = []
    facts = cls.get("facts") or {}
    minutes = facts.get("minutes") or w.get("minutes") or 0
    kind = cls.get("kind")

    # An easy day ridden hard: the commonest way riders stall.
    if intent in EASY_INTENT and ftp and w.get("basis") == "power":
        near = (facts.get("sweet_spot_min") or 0) + (facts.get("threshold_min") or 0)
        if minutes and near >= EASY_TOO_HARD * minutes:
            out.append({"id": "easy_too_hard", "title": "Keep easy days easy",
                        "text": f"This counted as your {intent} ride, but {round(near)} of its {minutes} minutes were at "
                                f"or just below what you could hold for an hour. Next time keep it to a pace you could "
                                f"chat at (under about {round(0.75 * ftp)} W): easy days let you go properly hard on the "
                                f"hard ones, and that's where the gains come from.",
                        "evidence": {"minutes_near_limit": round(near), "minutes": minutes}})

    # Pacing across hard efforts: going out too hard on the first ones.
    if ftp and w.get("p30") and kind in ("surges", "vo2"):
        efforts = [e for e in _efforts(w["p30"], ftp) if e["seconds"] >= 20]
        if len(efforts) >= 4:
            first = sum(e["watts"] for e in efforts[:2]) / 2
            last = sum(e["watts"] for e in efforts[-2:]) / 2
            if first >= FADE * last:
                out.append({"id": "pacing", "title": "Start the hard efforts a little easier",
                            "text": f"Your first hard efforts averaged {round(first)} W and the last ones {round(last)} W. "
                                    f"Start a touch easier so the last match the first: the repeats at the end are where "
                                    f"the training comes from, and it's how you'll answer the group's fifth surge, not "
                                    f"just its first.",
                            "evidence": {"first_w": round(first), "last_w": round(last)}})

    # Cadence on the climbs (indoors, the trainer's climbs show as harder pushes with cadence dropping).
    slow = [p for p in w.get("pushes") or [] if p[1] >= 60 and p[3] and p[3] < CLIMB_RPM]
    if len(slow) >= 2:
        low = min(p[3] for p in slow)
        out.append({"id": "climb_cadence", "title": "Spin a lighter gear on the climbs",
                    "text": f"On {len(slow)} of the climbs your cadence dropped to as low as {low} rpm. Try a lighter "
                            f"gear and keep it at {CLIMB_RPM_TRY} rpm or more: grinding a big gear tires your legs "
                            f"faster, while a quicker cadence shares the work with your heart and lungs, so you've more "
                            f"left at the top and late in the ride.",
                    "evidence": {"climbs": len(slow), "lowest_rpm": low}})

    # Sweet spot that turned into threshold.
    if intent == "steady" and kind == "threshold" and ftp:
        out.append({"id": "steady_too_hard", "title": "Sweet spot is just below your limit",
                    "text": f"This counted as sweet spot, but you held it right at what you could hold for an hour. "
                            f"Aim for {round(0.88 * ftp)}–{round(0.94 * ftp)} W: a little easier means you can do more "
                            f"of it, and more of it is what raises the power you can hold.",
                    "evidence": {"aim_w": [round(0.88 * ftp), round(0.94 * ftp)]}})

    # Heart rate rising at the same power late in a long ride: fuel and drink.
    if (w.get("drift") or 0) >= DRIFT_BPM and minutes >= 75:
        out.append({"id": "drift", "title": "Drink and eat from the first hour",
                    "text": f"By the end your heart rate was {w['drift']} beats higher at the same power than at the "
                            f"start. Drinking from the start (about a bottle an hour) and eating some carbohydrate "
                            f"after the first hour helps you hold your pace late in long rides, exactly when the group "
                            f"gets faster.",
                    "evidence": {"drift_bpm": w["drift"]}})

    # Straight into hard work without a warm-up.
    if ftp and w.get("p30") and kind in ("surges", "vo2", "threshold", "steady") and intent not in EASY_INTENT:
        efforts = _efforts(w["p30"], ftp)
        first_hard = next((k for k, v in enumerate(w["p30"]) if v is not None and v >= 0.95 * ftp), None)
        if efforts and first_hard is not None and first_hard * STEP_S < WARM_UP_S:
            out.append({"id": "warm_up", "title": "Warm up for ten minutes first",
                        "text": f"Your first hard riding came {max(1, round(first_hard * STEP_S / 60))} minutes in. "
                                f"Ten easy minutes first, with a couple of short pick-ups, gets more out of the session "
                                f"and is kinder to your legs.",
                        "evidence": {"first_hard_min": round(first_hard * STEP_S / 60)}})

    # Cadence on steady riding.
    cs = [c for c in w.get("c30") or [] if c is not None and c >= 40]
    med = _median(cs)
    if med and len(cs) * STEP_S >= 20 * 60:
        if med < LOW_RPM:
            out.append({"id": "low_cadence", "title": "Try a slightly quicker cadence",
                        "text": f"You pedalled at about {med} rpm on average. Most riders last longer at the same "
                                f"effort around 80–90 rpm: try one gear lighter on steady stretches and let your legs "
                                f"spin.",
                        "evidence": {"median_rpm": med}})
        elif med > HIGH_RPM:
            out.append({"id": "high_cadence", "title": "Try a slightly heavier gear",
                        "text": f"You pedalled at about {med} rpm on average. That fast, a lot of the effort goes into "
                                f"moving your legs: one gear heavier, around 85–95 rpm, usually turns the same effort "
                                f"into more speed.",
                        "evidence": {"median_rpm": med}})
    return out


def contribution(feat: dict, earlier: list[dict], ftp: float | None) -> dict:
    """What the ride added: its training load (internal, for the plan) and any new bests, in words."""
    from .train import classify
    load = None
    w = feat.get("work") or {}
    if ftp and w.get("basis") == "power":
        c = classify(w, ftp)
        np_ = (c.get("facts") or {}).get("np_w")
        minutes = (c.get("facts") or {}).get("minutes") or 0
        if np_:
            load = round(minutes * (np_ / ftp) ** 2 * 100 / 60)
    bests = []
    pc = feat.get("power_curve") or {}
    for key, name in BEST_NAMES.items():
        v = pc.get(key)
        if not v:
            continue
        before = [f["power_curve"][key] for f in earlier if (f.get("power_curve") or {}).get(key)]
        if not before:
            continue                     # the first ride with power sets the mark; nothing to beat yet
        if v > max(before):
            bests.append({"id": key, "watts": v, "text": f"{name}: {v} W, your best yet."})
    return {"load": load, "bests": bests}
