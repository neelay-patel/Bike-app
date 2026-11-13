"""Checks against Neelay's real rides. Skipped unless the files are in data/ (never committed).

Expected values were cross-checked by hand on 12 Nov 2026 (Garmin totals, Apple Watch
workout summaries, and the share cards built from them).
"""
import os
import pickle

import pytest

from rideengine.importers.fit import read_fit
from rideengine.importers.gpx import read_gpx
from rideengine.merge import build_rides

D = os.path.join(os.path.dirname(__file__), "..", "data")
FIT = os.path.join(D, "durham_2026-10-03.fit")
GPX = os.path.join(D, "scugog_2026-10-19.gpx")
APPLE = os.path.join(D, "export.zip")
need = pytest.mark.skipif(not all(os.path.exists(p) for p in (FIT, GPX, APPLE)),
                          reason="real ride files not present in data/")


@pytest.fixture(scope="module")
def rides():
    from rideengine.importers.apple_health import read_export
    cache = os.path.join(D, ".apple_oct2026.pkl")
    if os.path.exists(cache):
        apple = pickle.load(open(cache, "rb"))
    else:
        apple = [r for r in read_export(APPLE, since="2026-10-01", routes_dir=os.path.join(D, "apple_routes"))
                 if r.start < 1792500000]
        pickle.dump(apple, open(cache, "wb"))
    g = read_fit(FIT)
    s = read_gpx(GPX, source="garmin")
    return {round(r.start): r for r in build_rides(apple + [g, s]) if len(r.recordings) == 2}


@need
def test_durham_forest_merge(rides):
    r = next(r for r in rides.values() if 68_000 < r.totals.get("distance_m", 0) < 69_000)
    assert r.totals["ascent_m"] == 1139           # Garmin barometric
    assert round(r.totals["calories"]) == 1973    # Apple Watch active kcal
    assert r.totals["max_hr"] == 173
    assert 143 <= r.totals["avg_hr"] <= 145
    assert r.provenance["channel:hr"] == "apple_watch"


@need
def test_scugog_merge(rides):
    r = next(r for r in rides.values() if 104_000 < r.totals.get("distance_m", 0) < 105_000)
    assert abs(r.totals["ascent_m"] - 633) <= 2   # from the Garmin track
    assert round(r.totals["calories"]) == 2463
    assert r.totals["max_hr"] == 170
