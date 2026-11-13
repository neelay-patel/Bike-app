"""Apple Health export importer (the export.zip from Health > profile > Export All Health Data).

Only reads what a ride needs: cycling workouts, their summary statistics, their GPS
routes, and the heart-rate samples recorded *during* those workouts. Everything else
in the export (sleep, resting HR, other workouts...) is ignored on purpose.

The export is large (GBs), so export.xml is streamed twice: once for workouts (which
sit after all the records), then once for heart rate inside those workout windows.
"""
from __future__ import annotations

import bisect
import io
import os
import re
import zipfile
from datetime import datetime

from ..model import Recording, Sample
from .gpx import read_gpx

_ATTR = re.compile(r'(\w+)="([^"]*)"')
_HR = re.compile(r'startDate="([^"]*)" endDate="[^"]*" value="([^"]*)"')
_TS = "%Y-%m-%d %H:%M:%S %z"  # export times carry the offset at export time; parse with it


def _t(s: str) -> float:
    return datetime.strptime(s, _TS).timestamp()


def _source_key(name: str) -> str:
    n = name.replace(" ", " ")
    if "Watch" in n:
        return "apple_watch"
    if "iPhone" in n:
        return "iphone"
    if n == "Connect":
        return "garmin_connect"
    if "ELEMNT" in n:
        return "wahoo"
    return n.lower().replace(" ", "_")


def _xml_lines(zf: zipfile.ZipFile):
    name = next(n for n in zf.namelist() if n.endswith("/export.xml") or n == "export.xml")
    with zf.open(name) as f:
        yield from io.TextIOWrapper(f, encoding="utf-8")


def read_workouts(zf: zipfile.ZipFile, since: str | None = None) -> list[dict]:
    """Cycling workouts as dicts (no samples yet)."""
    out, buf, inside = [], [], False
    for line in _xml_lines(zf):
        if "<Workout " in line:
            inside, buf = True, [line]
            continue
        if inside:
            buf.append(line)
            if "</Workout>" in line:
                inside = False
                head = dict(_ATTR.findall(buf[0]))
                if "HKWorkoutActivityTypeCycling" not in head.get("workoutActivityType", ""):
                    continue
                if since and head["startDate"][:10] < since:
                    continue
                block = "".join(buf)
                w = {"source_name": head.get("sourceName", ""), "start": _t(head["startDate"]),
                     "end": _t(head["endDate"]), "totals": {}, "indoor": False, "route": None}
                for st in re.findall(r"<WorkoutStatistics ([^>]*)/?>", block):
                    a = dict(_ATTR.findall(st))
                    kind = a["type"].replace("HKQuantityTypeIdentifier", "")
                    if kind == "DistanceCycling":
                        km_factor = 1609.344 if a.get("unit") == "mi" else 1000.0
                        w["totals"]["distance_m"] = float(a["sum"]) * km_factor
                    elif kind == "ActiveEnergyBurned":
                        w["totals"]["calories"] = float(a["sum"])  # active kcal
                    elif kind == "HeartRate":
                        w["totals"]["avg_hr"] = float(a["average"])
                        w["totals"]["max_hr"] = float(a["maximum"])
                m = re.search(r'key="HKIndoorWorkout" value="(\d)"', block)
                w["indoor"] = bool(m and m.group(1) == "1")
                m = re.search(r'key="HKElevationAscended" value="([\d.]+) (\w+)"', block)
                if m:
                    w["totals"]["ascent_m"] = float(m.group(1)) / (100 if m.group(2) == "cm" else 1)
                m = re.search(r'<FileReference path="([^"]*)"', block)
                w["route"] = m.group(1) if m else None
                out.append(w)
    out.sort(key=lambda w: w["start"])
    return out


def read_heart_rate(zf: zipfile.ZipFile, windows: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
    """Heart-rate samples falling inside each (start, end) window, Apple Watch only."""
    order = sorted(range(len(windows)), key=lambda i: windows[i][0])
    starts = [windows[i][0] for i in order]
    result: list[list[tuple[float, float]]] = [[] for _ in windows]
    for line in _xml_lines(zf):
        if 'HKQuantityTypeIdentifierHeartRate"' not in line or "<Record" not in line:
            continue
        if "Watch" not in line:
            continue
        m = _HR.search(line)
        if not m:
            continue
        t = _t(m.group(1))
        k = bisect.bisect_right(starts, t) - 1
        if k >= 0:
            idx = order[k]
            if t <= windows[idx][1]:
                result[idx].append((t, float(m.group(2))))
    for r in result:
        r.sort()
    return result


def read_export(zip_path: str, since: str | None = None, routes_dir: str | None = None) -> list[Recording]:
    """Cycling workouts from an Apple Health export as Recordings.

    since: "YYYY-MM-DD" to skip older workouts.
    routes_dir: where to unpack route GPX files (defaults next to the zip).
    """
    zf = zipfile.ZipFile(zip_path)
    workouts = read_workouts(zf, since)
    hr = read_heart_rate(zf, [(w["start"], w["end"]) for w in workouts])
    routes_dir = routes_dir or os.path.join(os.path.dirname(os.path.abspath(zip_path)), "apple_routes")
    os.makedirs(routes_dir, exist_ok=True)
    names = set(zf.namelist())
    recs: list[Recording] = []
    for w, h in zip(workouts, hr):
        samples: list[Sample] = []
        if w["route"]:
            member = "apple_health_export" + w["route"]
            if member in names:
                dest = os.path.join(routes_dir, os.path.basename(w["route"]))
                if not os.path.exists(dest):
                    with zf.open(member) as src, open(dest, "wb") as out:
                        out.write(src.read())
                samples = read_gpx(dest).samples
        # Heart rate becomes its own samples; the merge step aligns it with the route.
        samples += [Sample(t=t, hr=v) for t, v in h]
        samples.sort(key=lambda s: s.t)
        recs.append(Recording(
            source=_source_key(w["source_name"]), device=w["source_name"].replace(" ", " "),
            start=w["start"], end=w["end"], indoor=w["indoor"], samples=samples,
            totals=w["totals"], origin=f"apple_health:{w['start']:.0f}"))
    return recs
