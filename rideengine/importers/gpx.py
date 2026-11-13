"""GPX importer (Garmin exports, Apple Health workout routes, most other apps)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

from ..model import Recording, Sample

_NS = {"g": "http://www.topografix.com/GPX/1/1"}


def _ts(text: str) -> float:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def read_gpx(path: str, source: str = "gpx", device: str = "GPX file") -> Recording:
    root = ET.parse(path).getroot()
    samples: list[Sample] = []
    for p in root.iter(f"{{{_NS['g']}}}trkpt"):
        t = p.find("g:time", _NS)
        if t is None:
            continue
        e = p.find("g:ele", _NS)
        s = Sample(t=_ts(t.text), lat=float(p.get("lat")), lon=float(p.get("lon")),
                   ele=float(e.text) if e is not None else None)
        ext = p.find("g:extensions", _NS)
        if ext is not None:
            for node in ext.iter():
                name = _local(node.tag)
                if node.text is None:
                    continue
                try:
                    val = float(node.text)
                except ValueError:
                    continue
                if name == "speed":          # Apple Health routes
                    s.speed = val
                elif name in ("hr", "heartrate"):
                    s.hr = val
                elif name in ("cad", "cadence"):
                    s.cadence = val
                elif name in ("atemp", "temp"):
                    s.temp = val
                elif name == "power":
                    s.power = val
        samples.append(s)
    if not samples:
        raise ValueError(f"No timed track points in {path}")
    samples.sort(key=lambda s: s.t)
    return Recording(source=source, device=device, start=samples[0].t, end=samples[-1].t,
                     samples=samples, origin=path)
