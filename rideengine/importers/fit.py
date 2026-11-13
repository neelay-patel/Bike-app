"""Minimal, dependency-free .FIT decoder for activity files (Garmin, Wahoo, Zwift...).

Reads `record` (global message 20) samples and the `session` (18) summary.
Developer fields are skipped. Compressed-timestamp headers are supported.
"""
from __future__ import annotations

import struct
from datetime import datetime, timezone

from ..model import Recording, Sample

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc).timestamp()
SEMI = 180 / 2**31

_FMT = {0x00: "B", 0x01: "b", 0x02: "B", 0x83: "h", 0x84: "H", 0x85: "i", 0x86: "I",
        0x88: "f", 0x89: "d", 0x0A: "B", 0x8B: "H", 0x8C: "I", 0x8E: "q", 0x8F: "Q", 0x90: "Q"}
_INVALID = {"B": 0xFF, "b": 0x7F, "H": 0xFFFF, "h": 0x7FFF, "I": 0xFFFFFFFF, "i": 0x7FFFFFFF,
            "Q": 0xFFFFFFFFFFFFFFFF, "q": 0x7FFFFFFFFFFFFFFF}


def _read_fields(buf: bytes, i: int, d: dict) -> tuple[dict, int]:
    vals = {}
    for num, size, base in d["fields"]:
        raw = buf[i:i + size]
        i += size
        f = _FMT.get(base)
        if f and struct.calcsize(f) == size:
            v = struct.unpack(d["endian"] + f, raw)[0]
            if f in _INVALID and v == _INVALID[f]:
                v = None
            if base == 0x0A and v == 0:
                v = None
            vals[num] = v
        else:
            vals[num] = raw
    return vals, i + d["dev_size"]


def decode(buf: bytes) -> list[tuple[int, dict]]:
    """Return (global_message_number, {field_number: value}) for every data message."""
    header_size = buf[0]
    data_size = struct.unpack("<I", buf[4:8])[0]
    i, end = header_size, header_size + data_size
    defs: dict[int, dict] = {}
    out: list[tuple[int, dict]] = []
    last_ts = None
    while i < end:
        h = buf[i]
        i += 1
        if h & 0x80:  # compressed timestamp header
            local = (h >> 5) & 0x3
            offset = h & 0x1F
            vals, i = _read_fields(buf, i, defs[local])
            if last_ts is not None:
                ts = (last_ts & ~0x1F) + offset
                if ts < last_ts:
                    ts += 0x20
                vals[253] = ts
                last_ts = ts
            out.append((defs[local]["global"], vals))
            continue
        local = h & 0x0F
        if h & 0x40:  # definition message
            endian = "<" if buf[i + 1] == 0 else ">"
            glob = struct.unpack(endian + "H", buf[i + 2:i + 4])[0]
            n = buf[i + 4]
            i += 5
            fields = []
            for _ in range(n):
                fields.append((buf[i], buf[i + 1], buf[i + 2]))
                i += 3
            dev_size = 0
            if h & 0x20:
                nd = buf[i]
                i += 1
                for _ in range(nd):
                    dev_size += buf[i + 1]
                    i += 3
            defs[local] = {"global": glob, "endian": endian, "fields": fields, "dev_size": dev_size}
        else:
            d = defs[local]
            vals, i = _read_fields(buf, i, d)
            if vals.get(253) is not None:
                last_ts = vals[253]
            out.append((d["global"], vals))
    return out


def read_fit(path: str, source: str = "garmin", device: str = "Garmin (FIT)") -> Recording:
    msgs = decode(open(path, "rb").read())
    samples: list[Sample] = []
    for g, v in msgs:
        if g != 20 or v.get(253) is None:
            continue
        ele = None
        if v.get(78) is not None:
            ele = v[78] / 5 - 500
        elif v.get(2) is not None:
            ele = v[2] / 5 - 500
        speed = None
        if v.get(73) is not None:
            speed = v[73] / 1000
        elif v.get(6) is not None:
            speed = v[6] / 1000
        samples.append(Sample(
            t=FIT_EPOCH + v[253],
            lat=v[0] * SEMI if v.get(0) is not None else None,
            lon=v[1] * SEMI if v.get(1) is not None else None,
            ele=ele,
            speed=speed,
            hr=v.get(3),
            cadence=v.get(4),
            power=v.get(7),
            temp=v.get(13),
        ))
    sessions = [v for g, v in msgs if g == 18]
    totals: dict = {}
    indoor = False
    if sessions:
        s = sessions[0]
        def put(key, val, scale=1.0):
            if val is not None and not isinstance(val, bytes):
                totals[key] = val * scale
        put("distance_m", s.get(9), 0.01)
        put("elapsed_s", s.get(7), 0.001)
        put("moving_s", s.get(8), 0.001)
        put("calories", s.get(11))
        put("ascent_m", s.get(22))
        put("descent_m", s.get(23))
        put("avg_hr", s.get(16))
        put("max_hr", s.get(17))
        put("avg_power", s.get(20))
        put("max_power", s.get(21))
        put("max_speed_ms", s.get(125) if s.get(125) is not None else s.get(15), 0.001)
        # sub_sport 6 = indoor cycling, 58 = virtual activity
        indoor = s.get(6) in (6, 58)
    if not samples:
        raise ValueError(f"No records in {path}")
    if not any(x.lat is not None for x in samples) and any(x.power is not None for x in samples):
        indoor = True
    return Recording(source=source, device=device, start=samples[0].t, end=samples[-1].t,
                     indoor=indoor, samples=samples, totals=totals, origin=path)
