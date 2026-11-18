"""Export a checked route to a bike computer: a FIT course (Garmin Edge, Wahoo, Hammerhead) with course
points for the stops and climbs, and a GPX with waypoints for anything else.

The Edge 840 shows course points in "Up Ahead" (Café, km 34) and uses the course's elevation for
ClimbPro. Turn prompts come from the Edge's own maps, so turns aren't written as course points.

    fit_course(route, report)  ->  bytes (a .fit file)
    gpx_course(route, report)  ->  bytes (a .gpx file)
"""
from __future__ import annotations

import struct
import time
from xml.sax.saxutils import escape

from ..importers.fit import FIT_EPOCH, SEMI
from .route import Route

# FIT base types
ENUM, UINT8, UINT16, SINT32, UINT32, STRING, UINT32Z = 0x00, 0x02, 0x84, 0x85, 0x86, 0x07, 0x8C
_FMT = {ENUM: "B", UINT8: "B", UINT16: "H", SINT32: "i", UINT32: "I", UINT32Z: "I"}
_INVALID = {ENUM: 0xFF, UINT8: 0xFF, UINT16: 0xFFFF, SINT32: 0x7FFFFFFF, UINT32: 0xFFFFFFFF, UINT32Z: 0}
_SIZE = {ENUM: 1, UINT8: 1, UINT16: 2, SINT32: 4, UINT32: 4, UINT32Z: 4}
NAME_LEN = 16

# course_point types (FIT profile)
CP_GENERIC, CP_SUMMIT, CP_WATER, CP_FOOD, CP_DANGER = 0, 1, 3, 4, 5

_CRC = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
        0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]


def crc16(data: bytes, crc: int = 0) -> int:
    for byte in data:
        tmp = _CRC[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _CRC[byte & 0xF]
        tmp = _CRC[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _CRC[(byte >> 4) & 0xF]
    return crc


class _Writer:
    def __init__(self):
        self.body = bytearray()
        self.defs: dict[int, list] = {}

    def define(self, local: int, glob: int, fields: list[tuple[int, int, int]]):
        """fields: (field number, base type, size for strings)"""
        self.defs[local] = fields
        self.body += bytes([0x40 | local, 0, 0]) + struct.pack("<H", glob) + bytes([len(fields)])
        for num, base, size in fields:
            self.body += bytes([num, size or _SIZE[base], base])

    def write(self, local: int, values: dict):
        self.body += bytes([local])
        for num, base, size in self.defs[local]:
            v = values.get(num)
            if base == STRING:
                raw = (v or "").encode("utf-8")[:size - 1]
                self.body += raw + b"\0" * (size - len(raw))
            else:
                self.body += struct.pack("<" + _FMT[base], _INVALID[base] if v is None else int(round(v)))

    def file(self) -> bytes:
        header = bytes([14, 0x20]) + struct.pack("<H", 2140) + struct.pack("<I", len(self.body)) + b".FIT"
        header += struct.pack("<H", crc16(header))
        out = header + bytes(self.body)
        return out + struct.pack("<H", crc16(out))


def _semi(deg: float) -> int:
    return int(round(deg / SEMI))


def course_points(report: dict) -> list[dict]:
    """Stops and climb tops as course points, in km order: {"km", "lat", "lon", "type", "name"}."""
    out = []
    mid = report.get("midway") or {}
    for st in report.get("stops", []):
        if st.get("view") or not (st["food"] or st["shop"] or st["water"]):
            continue
        top = st["items"][0]
        kind = CP_FOOD if (st["food"] or st["shop"]) else CP_WATER
        label = top["name"] if st["km"] == mid.get("km") or top["kind"] == "food" else (st.get("place") or top["name"])
        out.append({"km": st["km"], "lat": top["lat"], "lon": top["lon"], "type": kind, "name": label})
    for c in report.get("climbs", []):
        if c["gain_m"] >= 40:
            out.append({"km": round(c["km"] + c["length_m"] / 1000, 1), "lat": c["top"][0], "lon": c["top"][1],
                        "type": CP_SUMMIT, "name": f"Top {c['gain_m']}m {c['grade']}%"})
    last_st = -99.0
    for s in report.get("singletrack", []):
        # One warning per stretch of trail riding: pieces within 2 km of the last warning are the same bit.
        if s["from_km"] - last_st >= 2:
            out.append({"km": s["from_km"], "lat": None, "lon": None, "type": CP_DANGER, "name": "Singletrack"})
        last_st = s["to_km"]
    out.sort(key=lambda p: p["km"])
    # Thin out stops in towns: at most one course point per 2 km.
    thin, last = [], -99.0
    for p in out:
        if p["type"] in (CP_SUMMIT, CP_DANGER) or p["km"] - last >= 2 or p["km"] == mid.get("km"):
            thin.append(p)
            if p["type"] not in (CP_SUMMIT, CP_DANGER):
                last = p["km"]
    return thin


def _along(route: Route):
    d = route.distances()
    return d, d[-1]


def fit_course(route: Route, report: dict, kmh: float | None = None, start_t: float | None = None) -> bytes:
    """A FIT course file. kmh: planned speed for the virtual partner (from the report's time if not given)."""
    d, total = _along(route)
    secs = report.get("time_s") or total / (22 / 3.6)
    speed = (kmh / 3.6) if kmh else max(1.0, total / secs)
    t0 = int((start_t or time.time()) - FIT_EPOCH)
    step = max(1, len(route.points) // 10000)          # keep files light for the device
    idx = list(range(0, len(route.points), step))
    if idx[-1] != len(route.points) - 1:
        idx.append(len(route.points) - 1)
    pts = [(route.points[i], d[i]) for i in idx]
    ascent = report.get("ascent_m")
    descent = report.get("descent_m")
    end_t = t0 + int(total / speed)

    w = _Writer()
    w.define(0, 0, [(0, ENUM, 0), (1, UINT16, 0), (2, UINT16, 0), (3, UINT32Z, 0), (4, UINT32, 0)])
    w.write(0, {0: 6, 1: 255, 2: 1, 3: 20261117, 4: t0})                       # file_id: course
    w.define(1, 31, [(4, ENUM, 0), (5, STRING, NAME_LEN)])
    w.write(1, {4: 2, 5: route.name})                                            # course: cycling
    w.define(2, 19, [(253, UINT32, 0), (2, UINT32, 0), (3, SINT32, 0), (4, SINT32, 0), (5, SINT32, 0),
                     (6, SINT32, 0), (7, UINT32, 0), (8, UINT32, 0), (9, UINT32, 0), (21, UINT16, 0),
                     (22, UINT16, 0)])
    first, last = route.points[0], route.points[-1]
    w.write(2, {253: end_t, 2: t0, 3: _semi(first[0]), 4: _semi(first[1]), 5: _semi(last[0]), 6: _semi(last[1]),
                7: (end_t - t0) * 1000, 8: (end_t - t0) * 1000, 9: total * 100, 21: ascent, 22: descent})
    w.define(3, 21, [(253, UINT32, 0), (0, ENUM, 0), (1, ENUM, 0), (4, UINT8, 0)])
    w.write(3, {253: t0, 0: 0, 1: 0, 4: 0})                                       # timer start
    w.define(4, 20, [(253, UINT32, 0), (0, SINT32, 0), (1, SINT32, 0), (5, UINT32, 0), (2, UINT16, 0)])
    w.define(5, 32, [(254, UINT16, 0), (1, UINT32, 0), (2, SINT32, 0), (3, SINT32, 0), (4, UINT32, 0),
                     (5, ENUM, 0), (6, STRING, NAME_LEN)])
    cps = course_points(report)
    # Course points without a position (singletrack starts) take the route's position at that km.
    j = 0
    for cp in cps:
        if cp["lat"] is None:
            while j < len(d) - 1 and d[j] < cp["km"] * 1000:
                j += 1
            cp["lat"], cp["lon"] = route.points[j][0], route.points[j][1]
    ci = 0
    for (lat, lon, ele), dist in pts:
        while ci < len(cps) and cps[ci]["km"] * 1000 <= dist:
            cp = cps[ci]
            w.write(5, {254: ci, 1: t0 + int(cp["km"] * 1000 / speed), 2: _semi(cp["lat"]), 3: _semi(cp["lon"]),
                        4: cp["km"] * 1000 * 100, 5: cp["type"], 6: cp["name"]})
            ci += 1
        w.write(4, {253: t0 + int(dist / speed), 0: _semi(lat), 1: _semi(lon), 5: dist * 100,
                    2: (ele + 500) * 5 if ele is not None else None})
    for cp in cps[ci:]:
        w.write(5, {254: ci, 1: end_t, 2: _semi(cp["lat"]), 3: _semi(cp["lon"]), 4: total * 100, 5: cp["type"],
                    6: cp["name"]})
        ci += 1
    w.write(3, {253: end_t, 0: 0, 1: 9, 4: 0})                                    # timer stop_disable_all
    return w.file()


def gpx_course(route: Route, report: dict) -> bytes:
    """The route as GPX 1.1 with the stops as waypoints (for apps and devices that prefer GPX)."""
    sym = {0: "Flag, Blue", 1: "Summit", 3: "Drinking Water", 4: "Restaurant", 5: "Danger Area"}
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" creator="rideengine" xmlns="http://www.topografix.com/GPX/1/1">',
             f"  <metadata><name>{escape(route.name)}</name></metadata>"]
    d, _ = _along(route)
    for cp in course_points(report):
        if cp["lat"] is None:
            j = next((i for i, x in enumerate(d) if x >= cp["km"] * 1000), len(d) - 1)
            cp["lat"], cp["lon"] = route.points[j][0], route.points[j][1]
        lines.append(f'  <wpt lat="{cp["lat"]:.6f}" lon="{cp["lon"]:.6f}"><name>{escape(cp["name"])}</name>'
                     f'<desc>km {cp["km"]}</desc><sym>{sym.get(cp["type"], "Flag, Blue")}</sym></wpt>')
    lines.append(f"  <trk><name>{escape(route.name)}</name><trkseg>")
    for lat, lon, ele in route.points:
        e = f"<ele>{ele:.1f}</ele>" if ele is not None else ""
        lines.append(f'    <trkpt lat="{lat:.6f}" lon="{lon:.6f}">{e}</trkpt>')
    lines.append("  </trkseg></trk>")
    lines.append("</gpx>")
    return ("\n".join(lines) + "\n").encode("utf-8")
