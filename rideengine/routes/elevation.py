"""Ground height anywhere, for stretches of route the rider's file doesn't cover (a new start, a detour, a
shortcut, a generated loop).

From the public "Terrarium" elevation tiles (AWS Open Data: SRTM and other open terrain models merged by
Mapzen; ~27 m pixels at zoom 12 in southern Ontario). Only tile numbers are requested, nothing about the
rider; tiles are cached under data/dem/ (git-ignored). PNG decoding is done here, standard library only.

    heights([(lat, lon), ...])  ->  [metres, ...]
"""
from __future__ import annotations

import math
import os
import struct
import urllib.request
import zlib

URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
ZOOM = 12
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "dem")
CREDIT = "Elevation: Mapzen Terrarium tiles (SRTM, USGS and others) on AWS Open Data"
USER_AGENT = "rideengine-route-check/0.1"


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def decode_png(data: bytes) -> tuple[int, int, int, bytearray]:
    """(width, height, bytes per pixel, raw pixel bytes) for 8-bit RGB or RGBA PNGs, not interlaced."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    i, idat = 8, bytearray()
    w = h = bpp = 0
    while i < len(data):
        n, kind = struct.unpack(">I4s", data[i:i + 8])
        chunk = data[i + 8:i + 8 + n]
        if kind == b"IHDR":
            w, h, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
            if depth != 8 or color not in (2, 6) or interlace:
                raise ValueError("unsupported PNG")
            bpp = 3 if color == 2 else 4
        elif kind == b"IDAT":
            idat += chunk
        elif kind == b"IEND":
            break
        i += 12 + n
    raw = zlib.decompress(bytes(idat))
    stride = w * bpp
    out = bytearray(h * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(h):
        f = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if f == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 0xFF
        elif f == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif f == 3:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 0xFF
        elif f == 4:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                up_left = prev[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + _paeth(left, prev[x], up_left)) & 0xFF
        out[y * stride:(y + 1) * stride] = line
        prev = line
    return w, h, bpp, out


class _Tile:
    def __init__(self, png: bytes):
        self.w, self.h, self.bpp, self.px = decode_png(png)

    def at(self, x: int, y: int) -> float:
        x, y = min(max(x, 0), self.w - 1), min(max(y, 0), self.h - 1)
        k = (y * self.w + x) * self.bpp
        r, g, b = self.px[k], self.px[k + 1], self.px[k + 2]
        return r * 256 + g + b / 256 - 32768


def _pixel(lat: float, lon: float, z: int = ZOOM) -> tuple[float, float]:
    n = 2 ** z * 256
    x = (lon + 180) / 360 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


class Heights:
    def __init__(self, cache_dir: str = CACHE_DIR, fetch=None):
        self.cache_dir = cache_dir
        self.tiles: dict[tuple[int, int], _Tile] = {}
        self.fetch = fetch or self._download

    def _download(self, z: int, x: int, y: int) -> bytes:
        path = os.path.join(self.cache_dir, str(z), str(x), f"{y}.png")
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
        req = urllib.request.Request(URL.format(z=z, x=x, y=y), headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".part", "wb") as f:
            f.write(data)
        os.replace(path + ".part", path)
        return data

    def _tile(self, tx: int, ty: int) -> _Tile:
        if (tx, ty) not in self.tiles:
            self.tiles[(tx, ty)] = _Tile(self.fetch(ZOOM, tx, ty))
        return self.tiles[(tx, ty)]

    def _raw(self, px: int, py: int) -> float:
        t = self._tile(px // 256, py // 256)
        return t.at(px % 256, py % 256)

    def height(self, lat: float, lon: float) -> float:
        """Bilinear between the four nearest pixels."""
        x, y = _pixel(lat, lon)
        x, y = x - 0.5, y - 0.5
        x0, y0 = math.floor(x), math.floor(y)
        fx, fy = x - x0, y - y0
        a, b = self._raw(x0, y0), self._raw(x0 + 1, y0)
        c, d = self._raw(x0, y0 + 1), self._raw(x0 + 1, y0 + 1)
        return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def heights(points, source: Heights | None = None) -> list[float]:
    h = source or Heights()
    return [round(h.height(la, lo), 1) for la, lo in points]
