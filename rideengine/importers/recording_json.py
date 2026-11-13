"""Recording JSON: the exchange format for recordings made outside this engine.

The iPhone app writes one file per Apple Health workout in this shape, and the backend accepts
the same JSON as an upload. It is `dataclasses.asdict(Recording)` plus a format marker:

    {"format": "rideengine.recording/1",
     "source": "apple_watch", "device": "Apple Watch", "start": 1791036720.0, "end": 1791051000.0,
     "sport": "cycling", "indoor": false, "origin": "healthkit:<workout uuid>",
     "totals": {"distance_m": 68712.0, "calories": 1973.0, "avg_hr": 144.0, ...},
     "samples": [{"t": 1791036720.0, "lat": 43.9, "lon": -79.1, "ele": 260.1, "speed": 6.2},
                 {"t": 1791036722.5, "hr": 131.0}, ...]}

Times are unix seconds (UTC). Heart rate may come as its own samples between route points, the
same way the Apple Health export importer does it; the merge step aligns it.
Unknown keys are ignored so the phone can add fields before the engine knows about them.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict

from ..model import CHANNELS, Recording, Sample

FORMAT = "rideengine.recording/1"
_SAMPLE_KEYS = ("t",) + CHANNELS


def _num(v, what: str) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{what} must be a finite number, got {v!r}")
    return float(v)


def recording_from_dict(d: dict) -> Recording:
    if not isinstance(d, dict):
        raise ValueError("recording JSON must be an object")
    fmt = d.get("format", FORMAT)
    if fmt != FORMAT:
        raise ValueError(f"unsupported recording format {fmt!r} (expected {FORMAT!r})")
    source = d.get("source")
    if not isinstance(source, str) or not source:
        raise ValueError("recording needs a 'source' string")
    raw_samples = d.get("samples") or []
    if not isinstance(raw_samples, list):
        raise ValueError("'samples' must be a list")
    samples = []
    for i, s in enumerate(raw_samples):
        if not isinstance(s, dict) or s.get("t") is None:
            raise ValueError(f"sample {i} needs a time 't'")
        samples.append(Sample(**{k: _num(s.get(k), f"samples[{i}].{k}") for k in _SAMPLE_KEYS}))
    samples.sort(key=lambda s: s.t)
    start = _num(d.get("start"), "start")
    end = _num(d.get("end"), "end")
    if start is None:
        start = samples[0].t if samples else None
    if end is None:
        end = samples[-1].t if samples else None
    if start is None or end is None or end < start:
        raise ValueError("recording needs a start and an end (end >= start)")
    totals = d.get("totals") or {}
    if not isinstance(totals, dict):
        raise ValueError("'totals' must be an object")
    totals = {k: _num(v, f"totals.{k}") for k, v in totals.items() if v is not None}
    return Recording(source=source, device=str(d.get("device") or source), start=start, end=end,
                     sport=str(d.get("sport") or "cycling"), indoor=bool(d.get("indoor", False)),
                     samples=samples, totals=totals, origin=str(d.get("origin") or ""))


def recording_to_dict(rec: Recording) -> dict:
    d = asdict(rec)
    d["samples"] = [{k: v for k, v in s.items() if v is not None} for s in d["samples"]]
    return {"format": FORMAT, **d}


def read_recording_json(path: str) -> Recording:
    with open(path, encoding="utf-8") as f:
        rec = recording_from_dict(json.load(f))
    rec.origin = rec.origin or path
    return rec
