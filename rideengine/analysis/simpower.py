"""SIMULATED power, for prototyping the power display before a power meter exists.

Physics model from speed and gradient. Never mix this into real totals: callers must
label it as simulated (the share card tags it "SIM").
"""
from __future__ import annotations

import random

from ..model import Ride
from .basics import distances


def simulate(ride: Ride, mass_kg: float = 85.0, crr: float = 0.008, cda: float = 0.40,
             rho: float = 1.2, seed: int = 7) -> list[tuple[float, float]]:
    """Returns (distance_m, watts) every ~5 s. Assumes rider+bike mass, gravel tyres, upright."""
    rnd = random.Random(seed)
    cum = distances(ride)
    pts = [(s.t, d, s.ele) for s, d in zip(ride.samples, cum) if s.ele is not None]
    res, nxt = [], pts[0][0]
    for p in pts:
        if p[0] >= nxt:
            res.append(p)
            nxt = p[0] + 5
    out = []
    for i in range(len(res)):
        a, b = res[max(0, i - 3)], res[min(len(res) - 1, i + 3)]
        dd, dt = b[1] - a[1], b[0] - a[0]
        v = dd / dt if dt else 0
        if v < 1.5:
            out.append((res[i][1], 0.0))
            continue
        grade = max(-0.15, min(0.15, (b[2] - a[2]) / dd if dd > 20 else 0))
        p = (mass_kg * 9.81 * v * (grade + crr) + 0.5 * rho * cda * v ** 3) / 0.97
        p = max(0.0, p) * rnd.uniform(0.85, 1.15)
        if grade < -0.02 and v > 9:
            p *= 0.2  # coasting downhill
        out.append((res[i][1], min(p, 850.0)))
    return out
