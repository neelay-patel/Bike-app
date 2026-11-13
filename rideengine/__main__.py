"""Command line.

  python -m rideengine import data/*.fit data/*.gpx            # Garmin / Wahoo / any FIT or GPX
  python -m rideengine import --apple data/export.zip --since 2025-01-01
  python -m rideengine rides                                    # merged rides, one line each
  python -m rideengine show <ride_id>                           # totals + where each value came from
  python -m rideengine trends                                   # efficiency, climbs, fitness
  python -m rideengine card <ride_id> --config card.json        # share card (.dc.html)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime

from .analysis.basics import stops, summary
from .analysis.climbs import find_climbs, match_climbs
from .analysis.fitness import daily_loads, efficiency, estimate_hrmax, fitness_fatigue
from .importers.apple_health import read_export
from .importers.fit import read_fit
from .importers.gpx import read_gpx
from .store import Store


def _day(t: float) -> str:
    return datetime.fromtimestamp(t).astimezone().strftime("%Y-%m-%d %H:%M")


def cmd_import(a):
    st = Store(a.store)
    recs = []
    for path in a.files:
        if path.lower().endswith(".fit"):
            recs.append(read_fit(path, source=a.source or "garmin"))
        elif path.lower().endswith(".gpx"):
            recs.append(read_gpx(path, source=a.source or "garmin", device="GPX file"))
        else:
            print(f"skipping {path} (not .fit or .gpx)")
    if a.apple:
        print("Reading Apple Health export (cycling workouts and their heart rate only)...")
        recs += read_export(a.apple, since=a.since, routes_dir=os.path.join(a.store, "apple_routes"))
    new = st.add(recs)
    rides = st.rebuild()
    merged = sum(1 for r in rides if len(r.recordings) > 1)
    print(f"{len(recs)} recordings read ({new} new). {len(rides)} rides, {merged} merged from 2+ devices.")


def cmd_rides(a):
    for r in Store(a.store).rides():
        s = summary(r)
        print(f"{int(r.start)}  {_day(r.start)}  {s['km']:6.1f} km  "
              f"{(s['avg_kmh'] or 0):4.1f} km/h  {s['avg_hr'] or '-':>5} bpm  " if s['km'] else f"{_day(r.start)[:0]}{'':>23}{s['avg_hr'] or '-':>5} bpm  "
              f"{'indoor ' if r.indoor else ''}{len(r.recordings)} source(s)")


def cmd_show(a):
    r = Store(a.store).ride(a.ride_id)
    print(json.dumps({"start": _day(r.start), "summary": summary(r), "provenance": r.provenance,
                      "recordings": r.recordings,
                      "stops": [{"km": round(s["km"], 1), "minutes": round(s["seconds"] / 60)} for s in stops(r)],
                      "climbs": find_climbs(r)}, indent=2, default=str))


def cmd_trends(a):
    rides = [r for r in Store(a.store).rides() if not r.indoor]
    hrmax = estimate_hrmax(rides)
    print(f"Estimated max HR: {hrmax:.0f}")
    print("\nEfficiency (m per heartbeat, flat steady riding):")
    for r in rides:
        e = efficiency(r)
        if e:
            print(f"  {_day(r.start)}  {e:.2f}")
    print("\nMost repeated climbs:")
    allc = [c for r in rides for c in find_climbs(r)]
    for g in match_climbs(allc)[:5]:
        if len(g) < 3:
            break
        best = min(g, key=lambda c: c["seconds"])
        print(f"  {g[0]['length_m']} m, {g[0]['gain_m']} m up: {len(g)} attempts, "
              f"best {best['seconds'] // 60}:{best['seconds'] % 60:02d} on {_day(best['date_t'])[:10]}")
    loads = daily_loads(rides, hrmax)
    if loads:
        series = fitness_fatigue(loads, date.fromisoformat(min(loads)), date.today())
        now = series[-1]
        print(f"\nFitness {now['fitness']}, fatigue {now['fatigue']}, form {now['form']} ({now['date']})")


def cmd_card(a):
    from .card.prepare import export_points, power_bins
    st = Store(a.store)
    r = st.ride(a.ride_id)
    cfg = json.load(open(a.config))
    os.makedirs("data/cards", exist_ok=True)
    pts = f"data/cards/{a.ride_id}_points.json"
    km = export_points(r, pts)
    cfg["pts"] = pts
    cfg.setdefault("dist_km", round((r.totals.get("distance_m") or km * 1000) / 1000, 1))
    if a.power:
        cfg["power"] = f"data/cards/{a.ride_id}_power.json"
        pb = power_bins(r, cfg["dist_km"], cfg["power"])
        if pb["simulated"]:
            print("No power in this ride: power strip uses SIMULATED values (tagged SIM).")
    cfg.setdefault("out", f"data/cards/{a.ride_id}.dc.html")
    tmp = f"data/cards/{a.ride_id}_config.json"
    json.dump(cfg, open(tmp, "w"))
    subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "card", "make_card.py"), tmp], check=True)
    print(f"Card written to {cfg['out']}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="rideengine")
    p.add_argument("--store", default="data/store")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("import")
    i.add_argument("files", nargs="*")
    i.add_argument("--apple", help="Apple Health export.zip")
    i.add_argument("--since", help="YYYY-MM-DD, skip older Apple workouts")
    i.add_argument("--source", help="override source key for FIT/GPX files (default garmin)")
    i.set_defaults(fn=cmd_import)
    sub.add_parser("rides").set_defaults(fn=cmd_rides)
    s = sub.add_parser("show")
    s.add_argument("ride_id")
    s.set_defaults(fn=cmd_show)
    sub.add_parser("trends").set_defaults(fn=cmd_trends)
    c = sub.add_parser("card")
    c.add_argument("ride_id")
    c.add_argument("--config", required=True)
    c.add_argument("--power", action="store_true", help="add the power strip (simulated if no power data)")
    c.set_defaults(fn=cmd_card)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
