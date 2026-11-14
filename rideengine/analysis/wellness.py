"""Recovery and fitness: heart-rate recovery after each ride, and HRV, resting heart rate and VO2 max
trends from Apple Health (docs/recovery.md).

Rule-based, worked out against the rider's own usual range, never against population norms, and
always framed as training guidance, not medical advice. Recovery data is never shown to other people.

Metrics arrive as plain dicts: {"kind": ..., "t": unix seconds, "value": number, "source": ...}.
"""
from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta, tzinfo

from ..model import Recording

# kind: (unit, lowest believable, highest believable, higher is better, label)
KINDS = {
    "hrv_sdnn": ("ms", 5, 300, True, "HRV"),
    "resting_hr": ("bpm", 25, 130, False, "Resting heart rate"),
    "vo2max": ("ml/kg/min", 10, 95, True, "VO2 max"),
    "hr_recovery_1min": ("bpm", 0, 120, True, "Cardio Recovery"),  # Apple's own one-minute drop
}

END_WINDOW_S = 30        # heart rate "at the end" = average of the workout's last 30 s
AFTER_TOL_S = 15         # the reading nearest 60 s (120 s) after the end, within this
RECENT_DAYS = 7          # "lately": the last 7 days with a reading
BASELINE_DAYS = 60       # "usual": the 60 days before that
MIN_BASELINE = 14        # days of readings needed before saying what's usual
DISCLAIMER = "Training guidance from your own data, not medical advice."


# --- after each ride -------------------------------------------------------------------------
def ride_recovery(rec: Recording) -> dict:
    """How far heart rate fell in the first one and two minutes after the workout ended.
    Empty when the watch didn't keep measuring."""
    if not rec.after:
        return {}
    end = [s.hr for s in rec.samples if s.hr is not None and s.t >= rec.end - END_WINDOW_S]
    if not end:
        return {}
    hr_end = sum(end) / len(end)
    out = {"hr_end": round(hr_end)}
    for secs in (60, 120):
        near = [s for s in rec.after if abs(s.t - (rec.end + secs)) <= AFTER_TOL_S and s.hr is not None]
        if near:
            hr = min(near, key=lambda s: abs(s.t - (rec.end + secs))).hr
            out[f"hr_drop_{secs}s"] = round(hr_end - hr)
    return out if "hr_drop_60s" in out else {}


# --- metrics ---------------------------------------------------------------------------------
def valid(m: dict) -> bool:
    k = KINDS.get(m.get("kind"))
    v = m.get("value")
    return bool(k) and isinstance(v, (int, float)) and k[1] <= v <= k[2] and isinstance(m.get("t"), (int, float))


def daily(metrics: list[dict], kind: str, tz: tzinfo | None = None) -> list[tuple[date, float]]:
    """One value per day (the day's average), oldest first."""
    days: dict[date, list[float]] = {}
    for m in metrics:
        if m["kind"] == kind:
            days.setdefault(datetime.fromtimestamp(m["t"], tz).astimezone(tz).date(), []).append(m["value"])
    return [(d, sum(v) / len(v)) for d, v in sorted(days.items())]


def trend(series: list[tuple[date, float]], today: date, higher_is_better: bool) -> dict:
    """Lately (last RECENT_DAYS) against usual (the BASELINE_DAYS before), in the rider's own range.
    status: "usual" | "better" | "worse" | "unknown" (not enough readings yet)."""
    recent = [v for d, v in series if today - timedelta(days=RECENT_DAYS) < d <= today]
    base = [v for d, v in series
            if today - timedelta(days=RECENT_DAYS + BASELINE_DAYS) < d <= today - timedelta(days=RECENT_DAYS)]
    out = {"latest": round(series[-1][1], 1) if series else None,
           "latest_date": series[-1][0].isoformat() if series else None,
           "recent": round(sum(recent) / len(recent), 1) if recent else None,
           "usual": None, "low": None, "high": None, "status": "unknown"}
    if len(base) < MIN_BASELINE or not recent:
        return out
    mean = statistics.fmean(base)
    sd = max(statistics.pstdev(base), 0.03 * mean)  # a floor, so a very steady baseline isn't twitchy
    out.update(usual=round(mean, 1), low=round(mean - sd, 1), high=round(mean + sd, 1))
    r = out["recent"]
    if r < mean - sd:
        out["status"] = "worse" if higher_is_better else "better"
    elif r > mean + sd:
        out["status"] = "better" if higher_is_better else "worse"
    else:
        out["status"] = "usual"
    return out


def readiness(hrv: dict, rhr: dict) -> dict:
    """One line on how recovered the rider looks, from HRV and resting heart rate together."""
    worse = [x for x in (hrv, rhr) if x["status"] == "worse"]
    known = [x for x in (hrv, rhr) if x["status"] != "unknown"]
    if not known:
        return {"status": "unknown",
                "text": "Wear your watch overnight for two weeks or so, and this will show how recovered you are."}
    if len(worse) == 2:
        return {"status": "strained", "text": "HRV is below your usual range and resting heart rate above it: "
                                              "your body may still be recovering. An easier day could pay off."}
    if hrv["status"] == "worse":
        return {"status": "watch", "text": "HRV has been below your usual range this week. "
                                           "Keep an eye on sleep and how hard you go."}
    if rhr["status"] == "worse":
        return {"status": "watch", "text": "Resting heart rate has been above your usual range this week. "
                                           "That can mean fatigue, stress or a cold coming on."}
    return {"status": "good", "text": "HRV and resting heart rate are in your usual range: recovery looks normal."}


def summary(metrics: list[dict], rides: list[dict], today: date | None = None, tz: tzinfo | None = None,
            days: int = 180) -> dict:
    """Everything for the Recovery screen. rides: [{"ride_id", "start", "hr_drop_60s"}] for rides with
    post-ride heart rate. Series are trimmed to the last `days` days."""
    today = today or datetime.now(tz).astimezone(tz).date()
    cut = today - timedelta(days=days)
    out = {"disclaimer": DISCLAIMER}
    for kind, (unit, _, _, better_up, label) in KINDS.items():
        s = daily(metrics, kind, tz)
        t = trend(s, today, better_up)
        t.update(kind=kind, label=label, unit=unit, higher_is_better=better_up,
                 series=[{"date": d.isoformat(), "value": round(v, 1)} for d, v in s if d > cut])
        out[kind] = t
    vo2 = daily(metrics, "vo2max", tz)
    if vo2:
        old = [v for d, v in vo2 if d <= today - timedelta(days=90)]
        out["vo2max"]["change_90d"] = round(vo2[-1][1] - old[-1], 1) if old else None
        out["vo2max"]["note"] = "Apple Watch estimates VO2 max from outdoor walks, runs and hikes, not rides."
    out["readiness"] = readiness(out["hrv_sdnn"], out["resting_hr"])
    drops = [r for r in sorted(rides, key=lambda r: r["start"]) if r.get("hr_drop_60s") is not None]
    rr = {"count": len(drops), "latest": drops[-1] if drops else None,
          "best": max(drops, key=lambda r: r["hr_drop_60s"]) if drops else None,
          "series": [{"ride_id": r["ride_id"], "start": r["start"], "value": r["hr_drop_60s"]} for r in drops[-60:]]}
    if len(drops) >= 6:
        a = statistics.fmean(r["hr_drop_60s"] for r in drops[-3:])
        b = statistics.fmean(r["hr_drop_60s"] for r in drops[-6:-3])
        rr["trend"] = "faster" if a > b + 2 else "slower" if a < b - 2 else "steady"
    out["ride_recovery"] = rr
    return out
