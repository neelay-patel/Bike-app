"""Find climbs in a ride, and match the same climb across rides."""
from __future__ import annotations

from ..model import Ride, haversine
from .basics import distances

STEP_M = 50          # resample spacing
SMOOTH = 3           # +/- points in the moving average
MAX_DIP_M = 8        # a drop bigger than this ends the climb
MIN_GAIN_M = 25
MIN_LEN_M = 300
MAX_LEN_M = 6000     # longer "climbs" are usually false-flat drags merged together
MIN_GRADE = 0.009    # 0.9% average


def find_climbs(ride: Ride) -> list[dict]:
    cum = distances(ride)
    pts, nxt = [], 0.0
    for s, d in zip(ride.samples, cum):
        if s.ele is not None and s.lat is not None and d >= nxt:
            pts.append((d, s))
            nxt = d + STEP_M
    if len(pts) < 10:
        return []
    ele = [p[1].ele for p in pts]
    sm = [sum(ele[max(0, i - SMOOTH):i + SMOOTH + 1]) / len(ele[max(0, i - SMOOTH):i + SMOOTH + 1])
          for i in range(len(ele))]
    climbs, k = [], 0
    while k < len(sm) - 1:
        lo = hi = j = k
        while j < len(sm) - 1:
            j += 1
            if sm[j] > sm[hi]:
                hi = j
            if sm[hi] - sm[j] > MAX_DIP_M:
                break
        # Trim flat or downhill road before the climb really starts.
        while lo < hi and sm[lo + 1] <= sm[lo] + 0.3:
            lo += 1
        gain, length = sm[hi] - sm[lo], pts[hi][0] - pts[lo][0]
        if gain >= MIN_GAIN_M and MIN_LEN_M <= length <= MAX_LEN_M and gain / length >= MIN_GRADE:
            a, b = pts[lo][1], pts[hi][1]
            hr = [s.hr for s in ride.samples if a.t <= s.t <= b.t and s.hr is not None]
            pw = [s.power for s in ride.samples if a.t <= s.t <= b.t and s.power is not None]
            climbs.append({
                "start": (a.lat, a.lon), "end": (b.lat, b.lon),
                "km_into_ride": round(pts[lo][0] / 1000, 2),
                "length_m": round(length), "gain_m": round(gain),
                "grade": round(gain / length * 100, 1),
                "seconds": round(b.t - a.t),
                "vam": round(gain / ((b.t - a.t) / 3600)) if b.t > a.t else None,
                "avg_hr": round(sum(hr) / len(hr)) if len(hr) >= 3 else None,
                "avg_power": round(sum(pw) / len(pw)) if len(pw) >= 3 else None,
                "date_t": a.t,
            })
            k = hi
        else:
            k += 1
    return climbs


def match_climbs(all_climbs: list[dict], radius_m: float = 200) -> list[list[dict]]:
    """Group climbs whose start AND end are within `radius_m` of each other."""
    groups: list[list[dict]] = []
    for c in all_climbs:
        for g in groups:
            ref = g[0]
            if haversine(*ref["start"], *c["start"]) < radius_m and haversine(*ref["end"], *c["end"]) < radius_m:
                g.append(c)
                break
        else:
            groups.append([c])
    return sorted(groups, key=len, reverse=True)
