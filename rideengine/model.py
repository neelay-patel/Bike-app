"""Canonical ride format.

Every importer converts its source into a `Recording` (one device's view of one
activity). The merge step combines overlapping recordings into one `Ride`, where
every channel remembers which device it came from.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

# Channels a sample can carry. Units: degrees, metres, m/s, bpm, watts, rpm, deg C.
CHANNELS = ("lat", "lon", "ele", "speed", "hr", "power", "cadence", "temp")


@dataclass
class Sample:
    t: float  # unix seconds (UTC)
    lat: Optional[float] = None
    lon: Optional[float] = None
    ele: Optional[float] = None
    speed: Optional[float] = None
    hr: Optional[float] = None
    power: Optional[float] = None
    cadence: Optional[float] = None
    temp: Optional[float] = None


@dataclass
class Recording:
    """One device's recording of one activity, straight from an importer."""

    source: str  # e.g. "garmin", "apple_watch", "kickr"
    device: str  # free text, e.g. "Garmin Edge (FIT)", "Neelay's Apple Watch"
    start: float
    end: float
    sport: str = "cycling"
    indoor: bool = False
    samples: list[Sample] = field(default_factory=list)
    # Totals the device itself reports (preferred over values we derive).
    totals: dict = field(default_factory=dict)
    # Where it came from, for traceability (file path, workout id...).
    origin: str = ""
    # Heart rate in the minutes after the workout ended (Apple Watch keeps measuring), for recovery.
    after: list[Sample] = field(default_factory=list)

    def channels(self) -> set[str]:
        present = set()
        for c in CHANNELS:
            if any(getattr(s, c) is not None for s in self.samples):
                present.add(c)
        return present

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Ride:
    """A merged ride. `samples` is the base timeline; `provenance` says which
    source supplied each channel and each total."""

    start: float
    end: float
    sport: str
    indoor: bool
    samples: list[Sample]
    totals: dict
    provenance: dict  # {"channel:hr": "apple_watch", "total:calories": "apple_watch", ...}
    recordings: list[str]  # origins of the recordings merged into this ride
    # Stretches left out of the ride because they weren't riding (see clean.py), e.g.
    # [{"reason": "vehicle", "start": ..., "end": ..., "km": 41.3, "minutes": 52, "peak_kmh": 115.1}]
    excluded: list = field(default_factory=list)
    # Stretches added before or after the base recording, where another device was already (or still)
    # recording the riding (merge.py), e.g. a Watch started before Zwift:
    # [{"where": "before", "source": "apple_watch", "start": ..., "end": ..., "minutes": 4.7, "km": 2.3}]
    added: list = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(text: str) -> "Ride":
        d = json.loads(text)
        d["samples"] = [Sample(**s) for s in d["samples"]]
        return Ride(**d)

    @property
    def start_dt(self) -> datetime:
        return datetime.fromtimestamp(self.start).astimezone()


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres between two points."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# A power reading holds for up to this many seconds; longer gaps count as zero (a dropout or a stop).
POWER_HOLD_S = 3


def power_series(samples) -> tuple[int, list[float]]:
    """Measured power on 1 s steps: (first second, watts per second). Each reading holds until the
    next one, for up to POWER_HOLD_S; sensors report about once a second, never exactly on the beat."""
    pts = sorted((s.t, s.power) for s in samples if s.power is not None)
    if len(pts) < 2:
        return 0, []
    t0 = int(pts[0][0])
    series = [0.0] * (int(pts[-1][0]) - t0 + 1)
    for (t, p), nxt in zip(pts, pts[1:] + [(pts[-1][0] + 1, None)]):
        start = int(t) - t0
        end = min(int(nxt[0]) - t0, start + POWER_HOLD_S)
        for i in range(start, max(end, start + 1)):
            if i < len(series):
                series[i] = p
    return t0, series
