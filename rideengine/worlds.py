"""Ride games' worlds, found from where a virtual ride's track sits (stdlib only, no lookups).

Zwift files carry a track: each of its worlds is laid on real coordinates (Watopia off the Solomon
Islands, New York on Central Park), so an indoor ride's GPS says which world it was. Used to name
indoor rides ("Thursday on Zwift") and label their map with the world, never with the real
places underneath (27 Nov 2026).
"""
from __future__ import annotations

# (game, world, south, north, west, east)
WORLDS = [
    ("Zwift", "Watopia", -11.75, -11.55, 166.85, 167.05),
    ("Zwift", "Makuri Islands", -10.86, -10.70, 165.74, 165.92),
    ("Zwift", "France", -21.76, -21.60, 166.10, 166.26),
    ("Zwift", "New York", 40.73, 40.83, -74.03, -73.91),
    ("Zwift", "London", 51.44, 51.54, -0.22, 0.00),
    ("Zwift", "Richmond", 37.50, 37.58, -77.50, -77.39),
    ("Zwift", "Innsbruck", 47.20, 47.30, 11.33, 11.47),
    ("Zwift", "Yorkshire", 53.94, 54.02, -1.60, -1.49),
    ("Zwift", "Paris", 48.82, 48.90, 2.24, 2.37),
    ("Zwift", "Scotland", 55.60, 55.70, -5.32, -5.18),
    ("Zwift", "Crit City", -10.40, -10.37, 165.79, 165.82),
]


def world_at(lat: float, lon: float) -> tuple[str, str] | None:
    """(game, world) whose box holds this point, else None."""
    return next(((g, w) for g, w, s, n, we, e in WORLDS if s <= lat <= n and we <= lon <= e), None)


def world_of(ride) -> tuple[str, str] | None:
    """(game, world) for an indoor ride whose track lies in a known ride game's world, else None."""
    if not getattr(ride, "indoor", False):
        return None
    pts = [(s.lat, s.lon) for s in ride.samples if s.lat is not None and s.lon is not None]
    if len(pts) < 10:
        return None
    lat = sorted(p[0] for p in pts)[len(pts) // 2]
    lon = sorted(p[1] for p in pts)[len(pts) // 2]
    return world_at(lat, lon)


def has_track(ride) -> bool:
    return sum(1 for s in ride.samples if s.lat is not None and s.lon is not None) >= 10
