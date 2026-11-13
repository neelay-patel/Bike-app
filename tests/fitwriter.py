"""Tiny .FIT writer for tests: just enough (record + session messages) for rideengine's decoder."""
from __future__ import annotations

import struct

from rideengine.importers.fit import FIT_EPOCH, SEMI

# (field number, size, base type, struct format, invalid value)
_RECORD = [(253, 4, 0x86, "I", 0xFFFFFFFF), (0, 4, 0x85, "i", 0x7FFFFFFF), (1, 4, 0x85, "i", 0x7FFFFFFF),
           (2, 2, 0x84, "H", 0xFFFF), (3, 1, 0x02, "B", 0xFF), (6, 2, 0x84, "H", 0xFFFF),
           (7, 2, 0x84, "H", 0xFFFF)]
_SESSION = [(253, 4, 0x86, "I", 0xFFFFFFFF), (9, 4, 0x86, "I", 0xFFFFFFFF), (7, 4, 0x86, "I", 0xFFFFFFFF),
            (8, 4, 0x86, "I", 0xFFFFFFFF), (11, 2, 0x84, "H", 0xFFFF), (22, 2, 0x84, "H", 0xFFFF)]


def _definition(local: int, glob: int, fields) -> bytes:
    out = bytes([0x40 | local, 0, 0]) + struct.pack("<H", glob) + bytes([len(fields)])
    for num, size, base, _, _ in fields:
        out += bytes([num, size, base])
    return out


def _data(local: int, fields, values: dict) -> bytes:
    out = bytes([local])
    for num, _, _, fmt, invalid in fields:
        v = values.get(num)
        out += struct.pack("<" + fmt, invalid if v is None else int(round(v)))
    return out


def write_fit(samples, totals: dict | None = None) -> bytes:
    """samples: rideengine Samples (lat/lon/ele/hr/speed/power used). totals: distance_m, elapsed_s,
    moving_s, calories, ascent_m."""
    body = _definition(0, 20, _RECORD)
    for s in samples:
        body += _data(0, _RECORD, {
            253: s.t - FIT_EPOCH,
            0: s.lat / SEMI if s.lat is not None else None,
            1: s.lon / SEMI if s.lon is not None else None,
            2: (s.ele + 500) * 5 if s.ele is not None else None,
            3: s.hr, 6: s.speed * 1000 if s.speed is not None else None, 7: s.power})
    if totals:
        body += _definition(1, 18, _SESSION)
        body += _data(1, _SESSION, {
            253: samples[-1].t - FIT_EPOCH,
            9: totals.get("distance_m") and totals["distance_m"] * 100,
            7: totals.get("elapsed_s") and totals["elapsed_s"] * 1000,
            8: totals.get("moving_s") and totals["moving_s"] * 1000,
            11: totals.get("calories"), 22: totals.get("ascent_m")})
    header = bytes([14, 0x10]) + struct.pack("<H", 2132) + struct.pack("<I", len(body)) + b".FIT" + b"\0\0"
    return header + body + b"\0\0"
