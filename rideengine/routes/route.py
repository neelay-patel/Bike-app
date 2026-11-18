"""A planned route: a line on the map with elevation, read from a GPX (Ride with GPS, Komoot, Garmin
Connect...). Unlike a Recording it has no times: it's a plan, not a ride.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from ..model import haversine


@dataclass
class Route:
    name: str
    points: list[tuple[float, float, float | None]]      # (lat, lon, ele)
    source: str = "gpx"                                   # "ridewithgps", "komoot", "gpx"...
    link: str = ""                                        # where it came from, when the file says
    waypoints: list[dict] = field(default_factory=list)   # [{"lat", "lon", "name"}] from the file

    def distances(self) -> list[float]:
        """Metres along the route at each point."""
        out, d = [0.0], 0.0
        for a, b in zip(self.points, self.points[1:]):
            d += haversine(a[0], a[1], b[0], b[1])
            out.append(d)
        return out

    @property
    def km(self) -> float:
        return self.distances()[-1] / 1000 if len(self.points) > 1 else 0.0

    @property
    def is_loop(self) -> bool:
        a, b = self.points[0], self.points[-1]
        return haversine(a[0], a[1], b[0], b[1]) < 500

    def resample(self, step_m: float = 20.0) -> list[tuple[float, float, float | None, float]]:
        """Points every `step_m` along the line: (lat, lon, ele, metres along)."""
        d = self.distances()
        out, j = [], 0
        n = int(d[-1] // step_m) + 1
        for i in range(n + 1):
            target = min(i * step_m, d[-1])
            while j < len(d) - 2 and d[j + 1] < target:
                j += 1
            a, b = self.points[j], self.points[j + 1]
            span = d[j + 1] - d[j]
            f = 0.0 if span <= 0 else (target - d[j]) / span
            ele = None if a[2] is None or b[2] is None else a[2] + f * (b[2] - a[2])
            out.append((a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), ele, target))
            if target >= d[-1]:
                break
        return out


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def read_route(data: bytes | str, name: str | None = None) -> Route:
    """A Route from GPX bytes (or a path): track points, else route points. Times are ignored, so a
    recorded ride's GPX works as a route too."""
    root = ET.parse(data).getroot() if isinstance(data, str) else ET.fromstring(data)
    pts: list[tuple[float, float, float | None]] = []
    title, link, creator = None, "", root.get("creator") or ""
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "name" and title is None and el.text:
            title = el.text.strip()
        elif tag == "link" and not link:
            link = el.get("href") or ""
    for kind in ("trkpt", "rtept"):
        for p in root.iter():
            if _local(p.tag) != kind:
                continue
            ele = next((c.text for c in p if _local(c.tag) == "ele"), None)
            pts.append((float(p.get("lat")), float(p.get("lon")), float(ele) if ele else None))
        if pts:
            break
    wpts = []
    for p in root:
        if _local(p.tag) == "wpt":
            nm = next((c.text for c in p if _local(c.tag) == "name"), None)
            wpts.append({"lat": float(p.get("lat")), "lon": float(p.get("lon")), "name": (nm or "").strip()})
    # Drop repeated points (some exporters double up), which would make zero-length segments.
    clean = [pts[0]] if pts else []
    for p in pts[1:]:
        if haversine(clean[-1][0], clean[-1][1], p[0], p[1]) > 0.5:
            clean.append(p)
    if len(clean) < 2:
        raise ValueError("No route in this file: it needs a track or route with at least two points.")
    src = "ridewithgps" if "ridewithgps" in (creator + link) else "komoot" if "komoot" in (creator + link) \
        else "garmin" if "garmin" in creator.lower() else "gpx"
    return Route(name=name or title or "Route", points=clean, source=src, link=link, waypoints=wpts)


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compass bearing in degrees from point 1 to point 2."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def from_samples(samples, name: str = "Ride") -> Route:
    """A ride's track as a route (ride it again, or check it)."""
    pts = [(s.lat, s.lon, s.ele) for s in samples if s.lat is not None and s.lon is not None]
    clean = [pts[0]]
    for p in pts[1:]:
        if haversine(clean[-1][0], clean[-1][1], p[0], p[1]) > 3:
            clean.append(p)
    return Route(name=name, points=clean, source="ride")
