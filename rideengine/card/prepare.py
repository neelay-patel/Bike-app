"""Turn a merged Ride into the inputs make_card.py expects."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ..analysis.basics import distances
from ..analysis.simpower import simulate
from ..model import Ride


def export_points(ride: Ride, path: str) -> float:
    """Writes the point list (lat, lon, ele, t, d, hr...) and returns the track length in km."""
    cum = distances(ride)
    pts, prev = [], None
    for s, d in zip(ride.samples, cum):
        if s.lat is None or s.ele is None:
            continue
        pts.append({"lat": s.lat, "lon": s.lon, "ele": s.ele, "hr": s.hr, "temp": s.temp, "d": d,
                    "t": datetime.fromtimestamp(s.t, timezone.utc).isoformat(),
                    "dt": (s.t - prev.t) if prev else 0, "dd": (d - prev_d) if prev else 0})
        prev, prev_d = s, d
    json.dump(pts, open(path, "w"))
    return cum[-1] / 1000


def power_bins(ride: Ride, dist_km: float, path: str, step_km: float = 0.5) -> dict:
    """Power per `step_km` along the ride. Uses real power if the ride has it, else SIMULATED."""
    cum = distances(ride)
    real = [(d, s.power) for s, d in zip(ride.samples, cum) if s.power is not None]
    series = real if real else simulate(ride)
    scale = dist_km / (cum[-1] / 1000)
    nb = int(dist_km / step_km) + 1
    acc = [[0.0, 0] for _ in range(nb)]
    for d, p in series:
        b = min(nb - 1, int(d / 1000 * scale / step_km))
        acc[b][0] += p
        acc[b][1] += 1
    vals = [p for _, p in series]
    roll = [sum(vals[max(0, i - 5):i + 1]) / len(vals[max(0, i - 5):i + 1]) for i in range(len(vals))]
    out = {"bins": [round(s / n) if n else 0 for s, n in acc], "step": step_km,
           "avg": round(sum(p for p in vals if p > 0) / max(1, sum(1 for p in vals if p > 0))),
           "max": round(max(roll)), "simulated": not real}
    json.dump(out, open(path, "w"))
    return out
