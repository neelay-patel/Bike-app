"""The look (docs/design.md): tokens stay in sync with the app, fonts ship, the ride card renders."""
import json
import os
import plistlib
import re

from rideengine.card.ride_card import ride_card
from rideengine.merge import build_rides
from test_engine import line_ride, watch, T0

ROOT = os.path.join(os.path.dirname(__file__), "..")
TOKENS = json.load(open(os.path.join(ROOT, "design", "tokens.json")))
APP = os.path.join(ROOT, "ios", "RideApp")


def test_swift_theme_matches_tokens():
    swift = open(os.path.join(APP, "RideApp", "Theme.swift")).read()
    found = dict(re.findall(r"static let (\w+) = Color\(hex: 0x([0-9A-Fa-f]{6})\)", swift))
    assert found, "no colours found in Theme.swift"
    for name, hexval in found.items():
        assert name in TOKENS["color"], f"{name} in Theme.swift but not in tokens.json"
        assert TOKENS["color"][name].lstrip("#").upper() == hexval.upper(), f"{name} differs"
    stripes = re.search(r"static let stripes = \[(.*?)\]", swift).group(1)
    assert re.findall(r"0x([0-9A-Fa-f]{6})", stripes) == [c.lstrip("#").upper() for c in TOKENS["color"]["stripes"]]


def test_bundled_fonts_exist_with_licences():
    info = plistlib.load(open(os.path.join(APP, "Config", "Info.plist"), "rb"))
    fonts_dir = os.path.join(APP, "RideApp", "Fonts")
    for f in info["UIAppFonts"]:
        assert os.path.exists(os.path.join(fonts_dir, f)), f
    licences = [f for f in os.listdir(fonts_dir) if f.startswith("OFL")]
    assert len(licences) == 4  # Instrument Serif, Plex Sans, Plex Mono, Doto


def test_ride_card_shows_the_ride():
    ride = build_rides([line_ride(60, climb=(5, 10, 120)), watch(T0, 60, bpm=150, calories=900)])[0]
    page = ride_card(ride, number=7, name="Test loop", headline="Nice.", places=[["Midway", 43.81, -79.37]])
    assert "Test loop" in page and "NO. 7" in page
    assert "Nice." in page and "MIDWAY" in page
    assert re.search(r'<path d="M[\d. L]+"', page)               # the real track
    assert "♥ 150" in page                                          # heart-rate peak marked
    assert "AVG HEART RATE" in page and "900" in page               # watch calories
    assert "None" not in page and "nan" not in page
    for hexval in (TOKENS["color"]["cobalt"], TOKENS["color"]["sand"]):
        assert hexval in page


def test_ride_card_without_heart_rate_or_climbing():
    ride = build_rides([line_ride(30)])[0]
    page = ride_card(ride, places=[])
    assert "AVG SPEED" in page and "AVG HEART RATE" not in page and "♥" not in page
    assert "None" not in page


def _extent(page):
    xy = [tuple(map(float, p.split())) for p in re.search(r'<path d="M([\d. L]+)"', page).group(1).split(" L")]
    return max(y for _, y in xy) - min(y for _, y in xy)


def test_route_fills_the_map_with_no_scale_legend_or_decoration():
    short = build_rides([line_ride(30)])[0]
    long = build_rides([line_ride(60, start=T0 + 86400)])[0]
    a, b = ride_card(short, places=[]), ride_card(long, places=[])
    assert abs(_extent(a) - _extent(b)) < 1          # both fill the box
    assert "KM</p>" not in a and "C70" not in a        # no legend, no wavy lines
    assert 'id="kmdots-' in a                           # the km dot grid


def test_labels_avoid_each_other():
    ride = build_rides([line_ride(60)])[0]
    page = ride_card(ride, places=[["Alpha", 43.80, -79.37], ["Beta", 43.801, -79.37]])
    found = re.findall(r'<text x="([\d.-]+)" y="([\d.-]+)" text-anchor="(\w+)"[^>]*letter-spacing="1.5"[^>]*>(\w+)<', page)
    assert len(found) == 2
    boxes = []
    for x, y, anchor, text in found:
        w = len(text) * 8.2
        x0 = float(x) if anchor == "start" else float(x) - w
        boxes.append((x0, float(y) - 11, x0 + w, float(y) + 3))
    a, b = boxes
    assert a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1]   # no overlap


def test_swift_bike_palette_matches_avatar():
    """BikeArt.swift draws the bike on the phone with copies of avatar.py's frame and tyre colours."""
    from rideengine.card import avatar
    swift = open(os.path.join(APP, "RideApp", "BikeArt.swift")).read()
    for table, colours in (("frame", avatar.FRAME), ("tyres", avatar.TYRES)):
        block = re.search(rf"static let {table}: \[String: UInt32\] = \[(.*?)\]", swift, re.S).group(1)
        found = {k: v.upper() for k, v in re.findall(r'"(\w+)": 0x([0-9A-Fa-f]{6})', block)}
        assert found == {k: v.lstrip("#").upper() for k, v in colours.items()}, table
    assert set(avatar.OPTIONS["bike"]) == {"road", "gravel", "mtb", "indoor"}
