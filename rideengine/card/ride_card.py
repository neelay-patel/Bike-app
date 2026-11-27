"""The collectible ride card (look D, docs/design.md), from a merged Ride.

    html = ride_card(ride, number=34, name="Durham Forest", headline="Lunch in Uxbridge, earned.")

Writes one self-contained HTML page, 360 CSS px wide: the name, the route on its map (outdoors), the
numbers in dot-matrix on graphite (indoors with the app's indoor icon in the corner), the colour ribbon and the
headline (19 Nov 2026). An outdoor card comes out about 9:16; an indoor one, with no map, is shorter.
Fonts come from Google Fonts, or (fonts="local") from files beside the page: the iPhone app loads it
with its own bundled fonts.
hide_near: points (home) whose surroundings are cut from the drawn route, so a shared card doesn't
show where the rider lives (PRIVACY_M around each).
Colours and fonts come from design/tokens.json. Everything shown is the ride's own data: the route
is the real track filling the map, the dots behind it are a real-distance grid (1 km apart, wider
steps on long rides; no legend: dense dots mean a big ride), the heart-rate peak is where the merged
heart rate was highest, and the towns are where the route went (rideengine/places.py).
"""
from __future__ import annotations

import html
import json
import math
import os
from dataclasses import replace
from datetime import datetime

from ..analysis.basics import summary
from ..model import Ride, haversine

TOKENS = os.path.join(os.path.dirname(__file__), "..", "..", "design", "tokens.json")
W, MAP_H = 336, 262
PRIVACY_M = 500   # the route is cut this close to home

# Font files bundled in the iPhone app (ios/RideApp/RideApp/Fonts), for fonts="local".
LOCAL_FONTS = """@font-face{font-family:'Doto';font-weight:900;src:url('Doto-Black.ttf')}
@font-face{font-family:'Instrument Serif';src:url('InstrumentSerif-Regular.ttf')}
@font-face{font-family:'IBM Plex Mono';font-weight:400;src:url('IBMPlexMono-Regular.ttf')}
@font-face{font-family:'IBM Plex Mono';font-weight:500;src:url('IBMPlexMono-Medium.ttf')}"""
GOOGLE_FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Doto:ROND,wght@100,900'
                '&amp;family=Instrument+Serif&amp;family=IBM+Plex+Mono:wght@500&amp;display=swap">')


def trim_near(ride: Ride, points, radius: float = PRIVACY_M) -> Ride:
    """The ride without its samples within `radius` of any of `points` (for drawing only: totals stay)."""
    if not points:
        return ride
    kept = [s for s in ride.samples if s.lat is None or s.lon is None
            or all(haversine(s.lat, s.lon, a, b) > radius for a, b in points)]
    return replace(ride, samples=kept) if len(kept) >= 10 else ride


def _tokens() -> dict:
    with open(TOKENS, encoding="utf-8") as f:
        return json.load(f)


def _num(v: float, decimals: int = 0) -> str:
    return f"{v:,.{decimals}f}"


def _hero(v: float, decimals: int = 0) -> str:
    """Dot-matrix values: no thousands separator (its punctuation is wide)."""
    return f"{v:.{decimals}f}"


def _duration(seconds: float) -> str:
    m = round(seconds / 60)
    return f"{m // 60}:{m % 60:02d}"


MAP_PAD, MAP_TOP = 24, 40  # MAP_TOP keeps the date label clear of the route
LABEL_CHAR_PX = 8.2        # IBM Plex Mono 11 px with 1.5 px tracking


def _project(ride: Ride, geo: dict | None = None):
    """Track points as (x_km, y_km, metres along, hr), x east and y south, from the ride's top-left."""
    pts = [(s.lat, s.lon, s.hr) for s in ride.samples if s.lat is not None and s.lon is not None]
    if len(pts) < 2:
        return [], 0.0, 0.0
    lat0 = sum(p[0] for p in pts) / len(pts)
    k = math.cos(math.radians(lat0)) * 111.195
    minx = min(p[1] for p in pts) * k
    maxy = max(p[0] for p in pts) * 111.195
    if geo is not None:
        geo.update(k=k, minx=minx, maxy=maxy)
    out, d = [], 0.0
    step = max(1, len(pts) // 600)
    for i, (la, lo, hr) in enumerate(pts):
        if i:
            d += haversine(pts[i - 1][0], pts[i - 1][1], la, lo)
        if i % step == 0 or i == len(pts) - 1:
            out.append((lo * k - minx, maxy - la * 111.195, d, hr))
    w = max(p[0] for p in out)
    h = max(p[1] for p in out)
    return out, w, h


def route_path(ride: Ride, width: float = W, height: float = MAP_H, geo: dict | None = None) -> tuple[str, list, float, int]:
    """SVG path of the track (north up) filling the map, the projected points (x, y, metres along, hr),
    pixels per km, and the km between grid dots (1, 2, 5... so dots stay at least 6 px apart).
    geo, if given, is filled with what maps a lat/lon onto the map (for the app's scrub dot)."""
    km_pts, w, h = _project(ride, geo)
    if not km_pts:
        return "", [], 0.0, 1
    room_w, room_h = width - 2 * MAP_PAD, height - MAP_TOP - MAP_PAD
    ppk = min(room_w / max(w, 1e-6), room_h / max(h, 1e-6))
    dot_km = next((d for d in (1, 2, 5, 10, 20) if d * ppk >= 6), 20)
    ox = (width - w * ppk) / 2
    oy = MAP_TOP + (room_h - h * ppk) / 2
    proj = [(round(ox + x * ppk, 1), round(oy + y * ppk, 1), d, hr) for x, y, d, hr in km_pts]
    if geo is not None:
        geo.update(ppk=ppk, ox=ox, oy=oy)
    path = "M" + " L".join(f"{x} {y}" for x, y, _, _ in proj)
    return path, proj, ppk, dot_km


# A personal-best card: an iridescent header that slowly shimmers (still for reduced motion).
HOLO_CSS = """.holo{background:linear-gradient(115deg,#F7D6E6,#C9ECFF 22%,#FFF2B8 42%,#D9CCFF 62%,#BFF5DD 82%,#F7D6E6)!important;
background-size:300% 300%!important;animation:sheen 7s linear infinite}
@keyframes sheen{to{background-position:300% 0}}
@media (prefers-reduced-motion:reduce){.holo{animation:none}}"""


def _avatar_layer(spec: dict, cobalt: str, uid: str) -> str:
    """The rider's avatar, big and in tints of the map's blue, behind the km dots and the route."""
    from .avatar import _shade, avatar_svg
    k = MAP_H * 1.02 / 240
    x = W - 200 * k + 26
    y = MAP_H - 240 * k + 4
    inner = avatar_svg(spec, mono=_shade(cobalt, 1.1), standalone=False, uid=f"card{uid}")
    return f'<g transform="translate({x:.1f} {y:.1f}) scale({k:.3f})" opacity="0.5" aria-hidden="true">{inner}</g>'


def _grid(ppk: float, dot_km: int, color: str, uid: str = "g") -> str:
    """Dots on a real-distance grid: each dot is dot_km from the next (an SVG pattern, so it stays small)."""
    gap = round(ppk * dot_km, 2)
    return (f'<defs><pattern id="kmdots-{uid}" width="{gap}" height="{gap}" patternUnits="userSpaceOnUse">'
            f'<circle cx="{gap / 2:.2f}" cy="{gap / 2:.2f}" r="1.1" fill="{color}"></circle></pattern></defs>'
            f'<rect width="{W}" height="{MAP_H}" fill="url(#kmdots-{uid})" aria-hidden="true"></rect>')


def _place_label(x: float, y: float, text: str, taken: list) -> tuple[float, float, str]:
    """Where to put a label next to a point: first of right/left × above/below that stays inside the
    map and clear of labels already placed (`taken`, boxes as (x0, y0, x1, y1)). Returns x, y, anchor."""
    w = len(text) * LABEL_CHAR_PX
    for dx, dy, anchor in ((10, -9, "start"), (-10, -9, "end"), (10, 17, "start"), (-10, 17, "end")):
        tx, ty = x + dx, y + dy
        x0 = tx if anchor == "start" else tx - w
        box = (x0 - 2, ty - 11, x0 + w + 2, ty + 3)
        inside = box[0] >= 4 and box[2] <= W - 4 and box[1] >= MAP_TOP - 6 and box[3] <= MAP_H - 4
        clear = all(box[2] < b[0] or box[0] > b[2] or box[3] < b[1] or box[1] > b[3] for b in taken)
        if inside and clear:
            taken.append(box)
            return tx, ty, anchor
    taken.append((x + 8, y - 20, x + 8 + w, y - 6))
    return (x + 10, y - 9, "start") if x < W / 2 else (x - 10, y - 9, "end")


def ride_card(ride: Ride, number: int | None = None, name: str | None = None, headline: str | None = None,
              places: list | None = None, fonts: str = "google", hide_near=None, background: str = "#FFFFFF",
              avatar: dict | None = None, holo: bool = False) -> str:
    """places: None finds towns automatically (rideengine.places: where you stopped, else the biggest);
    or a list of [label, lat, lon] to mark instead; [] for none. fonts: "google" or "local".
    hide_near: [(lat, lon)] to keep off the drawn route (home). background: behind the card.
    avatar: the rider's avatar spec, drawn big and quiet behind the map (rideengine/card/avatar.py).
    holo: a personal-best ride: holographic header and a PB foil."""
    ride = trim_near(ride, hide_near)
    t = _tokens()
    c, f = t["color"], t["font"]
    s = summary(ride)
    when = datetime.fromtimestamp(ride.start).astimezone()
    km = s["km"]
    up = s["ascent_m"]
    indoor = s["indoor"] or km < 0.05  # a smart trainer reports a distance, but it's still indoors
    # An indoor ride is a bike ride too (27 Nov 2026): named for the day and where it was ridden, with the
    # same six numbers as any card, and its ride game's track as the map.
    from ..worlds import has_track, world_of
    world = world_of(ride) if indoor else None
    track = has_track(ride)
    if not name:
        name = (f"{when:%A} on {world[0]}" if world else f"{when:%A} virtual ride" if indoor and track else
                f"{when:%A} on the trainer" if indoor else f"{when:%A} ride")
    minutes = round((s["moving_h"] or 0) * 60)
    if indoor and km < 0.05:
        lead = f"{minutes} minutes on the trainer" + (f", {_num(up)} m climbed." if up and up >= 1 else ".")
    elif indoor:
        # A ride game's climbing (Zwift) is real work against gravity: it counts and is shown (19 Nov 2026).
        where = f", in {world[0]}’s {world[1]}" if world else ", indoors"
        lead = (f"{_num(up)} m in {round(km)} km{where}." if up and up >= 1 else f"{_num(km, 1)} km{where}.")
    else:
        lead = f"{_num(up)} m in {round(km)} km." if up else f"{_num(km, 1)} km."
    title = f"{lead} {headline}" if headline else lead

    geo: dict = {}
    path, proj, ppk, dot_km = route_path(ride, geo=geo) if track else ("", [], 0, 0)
    if indoor:
        places = []          # never the real places under a ride game's world
    if places is None:
        from ..places import places_on_route
        places = [[p["name"], p["lat"], p["lon"]] for p in places_on_route(ride)]
    taken: list = [(0, 0, 170, MAP_TOP - 8)]  # the date label
    dots, labels = "", ""
    peak = max((p for p in proj if p[3] is not None), key=lambda p: p[3], default=None)
    if peak:
        x, y = peak[0], peak[1]
        dots += f'<circle cx="{x}" cy="{y}" r="7" fill="#FFFFFF"></circle>'
        lx, ly, anchor = _place_label(x, y, f"♥ {round(peak[3])}", taken)
        labels += (f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" fill="#FFFFFF" stroke="{c["cobalt"]}" stroke-width="4" stroke-linejoin="round" paint-order="stroke" font-family="{f["label"]}, monospace" '
                   f'font-size="11" letter-spacing="1">♥ {round(peak[3])}</text>')
    for label, la, lo in places:
        # The route point closest to the place, found by distance along the ride.
        best = min(ride.samples, key=lambda q: (q.lat - la) ** 2 + (q.lon - lo) ** 2 if q.lat is not None else 9e9)
        along = _dist_to(ride, best)
        near = min(proj, key=lambda p: abs(p[2] - along), default=None)
        if near:
            x, y = near[0], near[1]
            text = label.upper()
            dots += f'<circle cx="{x}" cy="{y}" r="5" fill="{c["cobalt"]}" stroke="#FFFFFF" stroke-width="2"></circle>'
            lx, ly, anchor = _place_label(x, y, text, taken)
            labels += (f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" fill="#FFFFFF" stroke="{c["cobalt"]}" stroke-width="4" stroke-linejoin="round" paint-order="stroke" font-family="{f["label"]}, monospace" '
                       f'font-size="11" letter-spacing="1.5">{html.escape(text)}</text>')
    if world and proj:
        # The world's name, by the track's northernmost point.
        top = min(proj, key=lambda p: p[1])
        dots += f'<circle cx="{top[0]}" cy="{top[1]}" r="5" fill="{c["cobalt"]}" stroke="#FFFFFF" stroke-width="2"></circle>'
        lx, ly, anchor = _place_label(top[0], top[1], world[1].upper(), taken)
        labels += (f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" fill="#FFFFFF" stroke="{c["cobalt"]}" stroke-width="4" stroke-linejoin="round" paint-order="stroke" font-family="{f["label"]}, monospace" '
                   f'font-size="11" letter-spacing="1.5">{html.escape(world[1].upper())}</text>')
    marks = dots + labels

    # The same six numbers in the same places on every card, indoors or out (27 Nov 2026).
    no_km = km < 0.05
    stats = [("Distance", "indoor" if no_km else f"{_hero(km, 1)} km"),
             ("Climbing", f"{_hero(up or 0)} m"),
             ("Moving time", _duration((s["moving_h"] or 0) * 3600)),
             ("Avg heart rate", f"{round(s['avg_hr'])}" if s["avg_hr"] else "–", True),
             ("Avg speed", "indoor" if no_km or not s["avg_kmh"] else f"{_hero(s['avg_kmh'], 1)} km/h"),
             ("Calories", _hero(s["calories"]) if s["calories"] else "–")]
    stripes = "".join(f'<div style="height:4px;background:{x}"></div>' for x in c["stripes"])
    tag = f"★ PB · NO. {number}" if holo and number else (f"NO. {number}" if number else "")
    aria = f"Route of {html.escape(name)}, {_num(km, 1)} km" + (f", heart rate peaked at {round(peak[3])} bpm" if peak else "")
    hcolor, tcolor = (c["ink"], c["ink"]) if holo else ("#FFFFFF", "#E2DADC")
    label = f"font-family:'{f['label']}',monospace;font-size:11px;letter-spacing:0.14em"

    cells = "".join(
        f'<div><div style="{label};color:{c["panelLabel"]}">{st[0].upper()}</div>'
        f'<div style="font-family:\'{f["hero"]}\',monospace;font-size:34px;font-weight:900;line-height:1.05;margin-top:3px;'
        f'{"color:#F2A3B8;" if len(st) > 2 else ""}white-space:nowrap">{_split_unit(st[1], f)}</div></div>'
        for st in stats)
    # The indoor mark in the map's corner: the app swaps in its own icon (the one on the collection's small
    # cards), as it does the fonts.
    mark = (f'<img src="{INDOOR_MARK}" alt="Indoor ride" style="position:absolute;right:14px;bottom:12px;height:52px">'
            if indoor and fonts == "local" else "")
    scrub = (f'<circle id="scrub" r="7" fill="#FFFFFF" stroke="{c["cobalt"]}" stroke-width="3" style="display:none"></circle>'
             if geo.get("ppk") else "")
    if not track:
        effort = _effort_band(ride, c)
        route = f"""<div style="position:relative;background:{c['cobalt']};height:{MAP_H}px">
<svg width="{W}" height="{MAP_H}" viewBox="0 0 {W} {MAP_H}" role="img" aria-label="The ride's effort, minute by minute" style="position:absolute;left:0;top:0">{effort}</svg>
<p style="position:absolute;left:14px;top:12px;margin:0;{label};color:#E3E8F7">{when:%a %-d %b %Y}</p>
{mark}
</div>"""
    else:
        route = f"""<div style="position:relative;background:{c['cobalt']};height:{MAP_H}px">
<svg width="{W}" height="{MAP_H}" viewBox="0 0 {W} {MAP_H}" role="img" aria-label="{aria}" style="position:absolute;left:0;top:0;overflow:hidden">
{_avatar_layer(avatar, c['cobalt'], str(int(ride.start))) if avatar else ""}
{_grid(ppk, dot_km, c['cobaltLine'], str(int(ride.start))) if ppk else ""}
<path d="{path}" fill="none" stroke="#FFFFFF" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"></path>
{marks}
{scrub}
</svg>
<p style="position:absolute;left:14px;top:12px;margin:0;{label};color:#E3E8F7">{when:%a %-d %b %Y}</p>
{mark}
</div>"""
    dateline = ""

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(name)} · ride card</title>
{GOOGLE_FONTS if fonts == "google" else "<style>" + LOCAL_FONTS + "</style>"}
<style>body{{margin:0;background:{background};display:flex;justify-content:center}}{HOLO_CSS if holo else ""}</style></head>
<body>
<article style="width:360px;box-sizing:border-box;background:{background};padding:12px;display:flex;flex-direction:column;color:{c['ink']}">
<header class="{'holo' if holo else ''}" style="background:{c['strip']};color:{hcolor};border-radius:14px 14px 0 0;padding:10px 14px;display:flex;align-items:baseline;justify-content:space-between;gap:8px">
<h1 id="name" style="margin:0;font-family:'{f['heading']}',serif;font-size:30px;font-weight:400;line-height:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{html.escape(name)}</h1>
<span style="{label};color:{tcolor};white-space:nowrap">{tag}</span>
</header>
{route}
<div style="background:{c['panel']};color:#FFFFFF;padding:16px">
{dateline}
<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px 12px">{cells}</div>
</div>
<div aria-hidden="true" style="display:flex;flex-direction:column">{stripes}</div>
<p style="margin:0;background:{c['sand']};border-radius:0 0 14px 14px;padding:12px 14px 14px 14px;font-family:'{f['heading']}',serif;font-size:22px;line-height:1.15">{html.escape(title)}</p>
</article>
<script>{FIT_NAME}{_scrub_js(geo)}</script>
</body></html>
"""


INDOOR_MARK = "indoor-mark.png"  # filled in by the iPhone app (CardRenderer.embedFonts)


def _scrub_js(geo: dict) -> str:
    """kovaScrub(lat, lon) puts a dot on the map where the ride was (the app calls it as you drag across the
    ride's profiles); kovaScrub(null) hides it. Uses the map's own projection, so the dot sits on the route."""
    if not geo.get("ppk"):
        return ";window.kovaScrub=function(){}"
    g = {k: round(v, 6) for k, v in geo.items()}
    return (";window.kovaScrub=function(la,lo){var d=document.getElementById('scrub');if(!d)return;"
            "if(la==null){d.style.display='none';return}"
            f"var g={json.dumps(g)};"
            "d.setAttribute('cx',(g.ox+(lo*g.k-g.minx)*g.ppk).toFixed(1));"
            "d.setAttribute('cy',(g.oy+(g.maxy-la*111.195)*g.ppk).toFixed(1));d.style.display=''}")


def _effort_band(ride: Ride, c: dict) -> str:
    """A trainer ride with no track: the map is its effort (power, else heart rate) minute by minute."""
    from ..analysis.profile import profile
    p = profile(ride, step_s=60)
    vals = p["p"] if any(v for v in p["p"]) else p["h"]
    pts = [(i, v) for i, v in enumerate(vals) if v]
    if len(pts) < 2:
        return ""
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    n = max(1, len(vals) - 1)
    def xy(i, v):
        return f"{24 + i / n * (W - 48):.1f} {MAP_H - 30 - (v - lo) / ((hi - lo) or 1) * (MAP_H - MAP_TOP - 50):.1f}"
    line = "M" + " L".join(xy(i, v) for i, v in pts)
    area = line + f" L{24 + pts[-1][0] / n * (W - 48):.1f} {MAP_H - 30} L{24 + pts[0][0] / n * (W - 48):.1f} {MAP_H - 30} Z"
    return (f'<path d="{area}" fill="{c["cobaltLine"]}" opacity="0.55"></path>'
            f'<path d="{line}" fill="none" stroke="#FFFFFF" stroke-width="3" stroke-linejoin="round"></path>')

# A long name shrinks to fit the header (down to 20 px) before it is cut off with an ellipsis.
FIT_NAME = ("document.fonts.ready.then(function(){var h=document.getElementById('name'),s=30;"
            "while(h.scrollWidth>h.clientWidth&&s>20){s--;h.style.fontSize=s+'px'}})")


def _split_unit(value: str, f: dict) -> str:
    """'41.3 km' as a dot-matrix number with its unit small in Plex beside it (as in the app)."""
    num, _, unit = value.partition(" ")
    small = (f'<span style="font-family:\'{f["label"]}\',monospace;font-size:13px;font-weight:500;margin-left:4px">'
             f'{html.escape(unit)}</span>') if unit else ""
    return html.escape(num) + small


def _dist_to(ride: Ride, target) -> float:
    d, prev = 0.0, None
    for s in ride.samples:
        if s.lat is None:
            continue
        if prev is not None:
            d += haversine(prev.lat, prev.lon, s.lat, s.lon)
        if s is target:
            return d
        prev = s
    return d
