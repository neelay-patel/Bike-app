"""Fitness signals that work without a power meter.

- efficiency(): metres travelled per heartbeat on flat, steady minutes. Rising = fitter.
- trimp(): Edwards training load (minutes in heart-rate zones x zone number).
- fitness_fatigue(): 42-day (fitness) and 7-day (fatigue) weighted averages of daily load.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ..model import Ride
from .basics import distances


def efficiency_windows(ride: Ride, window_s: int = 60) -> list[tuple[float, float]]:
    """(seconds into the ride, metres per heartbeat) for each flat (<1.5%), steady (18-40 km/h) minute."""
    cum = distances(ride)
    s = ride.samples
    vals, i = [], 0
    while i < len(s) - 1:
        j = i
        while j < len(s) - 1 and s[j].t - s[i].t < window_s:
            j += 1
        dt, dd = s[j].t - s[i].t, cum[j] - cum[i]
        if dt < window_s or dt > window_s * 1.2 or dd < 300:
            i = j
            continue
        ea, eb = s[i].ele, s[j].ele
        kmh = dd / dt * 3.6
        flat = ea is not None and eb is not None and abs((eb - ea) / dd) < 0.015
        steady = all(
            (cum[k + 1] - cum[k]) / max(1e-6, s[k + 1].t - s[k].t) > 2 for k in range(i, j)
            if s[k + 1].t > s[k].t
        )
        hr = [x.hr for x in s[i:j + 1] if x.hr is not None]
        if flat and steady and 18 <= kmh <= 40 and len(hr) >= 3:
            vals.append((s[i].t - s[0].t, (dd / (dt / 60)) / (sum(hr) / len(hr))))
        i = j
    return vals


def efficiency(ride: Ride, window_s: int = 60, min_windows: int = 8) -> float | None:
    """Median metres per heartbeat over flat (<1.5%), steady (18-40 km/h) one-minute windows."""
    vals = sorted(v for _, v in efficiency_windows(ride, window_s))
    if len(vals) < min_windows:
        return None
    return round(vals[len(vals) // 2], 3)


def estimate_hrmax(rides: list[Ride], pct: float = 0.999) -> float:
    """Robust max: a high percentile of every ride heart-rate reading (ignores spikes)."""
    v = sorted(x.hr for r in rides for x in r.samples if x.hr is not None)
    return v[int(len(v) * pct)] if v else 190.0


def trimp(ride: Ride, hrmax: float) -> float:
    s = [x for x in ride.samples if x.hr is not None]
    total = 0.0
    for a, b in zip(s, s[1:] + [None]):
        dt = min((b.t - a.t) if b else 5, 60) / 60
        f = a.hr / hrmax
        zone = 0 if f < .5 else 1 if f < .6 else 2 if f < .7 else 3 if f < .8 else 4 if f < .9 else 5
        total += dt * zone
    return total


def fitness_fatigue(daily_load: dict[str, float], start: date, end: date, scale: float = 2.5) -> list[dict]:
    """Daily fitness (42-day) and fatigue (7-day) series. `scale` maps TRIMP to a TSS-like range."""
    out, ctl, atl, d = [], 0.0, 0.0, start
    while d <= end:
        load = daily_load.get(d.isoformat(), 0.0) / scale
        ctl += (load - ctl) / 42
        atl += (load - atl) / 7
        out.append({"date": d.isoformat(), "fitness": round(ctl, 1), "fatigue": round(atl, 1),
                    "form": round(ctl - atl, 1)})
        d += timedelta(days=1)
    return out


def daily_loads(rides: list[Ride], hrmax: float) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in rides:
        day = datetime.fromtimestamp(r.start).astimezone().date().isoformat()
        out[day] = out.get(day, 0.0) + trimp(r, hrmax)
    return out
