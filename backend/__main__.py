"""Backend command line (dev).

  python -m backend create-user                       # prints a user id and a bearer token
  python -m backend new-token --user 1                # a fresh token for an existing user (new phone)
  python -m backend connect-garmin --user 1 --since 2026-10-01
                                                      # asks for your Garmin personal API key, pulls rides
  python -m backend sync --user 1 --provider garmin_personal
  python -m backend upload --user 1 data/apple_watch_2026-10-03.json
  python -m backend rides --user 1
  python -m backend rebuild --user 1                  # re-merge stored rides after an engine change
  python -m backend rebuild-insights --user 1         # work out routes, climbs and notes again
  python -m backend recheck-courses --user 1          # check every saved route again
  python -m backend you --user 1                      # tallies, streaks, personal bests
  python -m backend card --user 1 <ride_id> [--name "Durham Forest"] [--headline "..."] [--place "Uxbridge,44.10,-79.12"]
                                                      # towns are found automatically unless --place / --no-places
                                                      # collectible ride card (HTML) in data/cards/
  python -m backend compact                           # compress stored rides and recordings (backs up first)
  python -m backend serve                             # HTTP API on http://127.0.0.1:8000 (docs at /docs)
"""
from __future__ import annotations

import argparse
import getpass
import os
import socket
import sys
from datetime import datetime

from .config import Settings
from .connectors import ConnectorError
from .service import Backend


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="backend")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create-user")
    nt = sub.add_parser("new-token", help="a fresh login token for an existing user (the old one stops working)")
    nt.add_argument("--user", type=int, required=True)
    g = sub.add_parser("connect-garmin")
    g.add_argument("--user", type=int, required=True)
    g.add_argument("--since", help="YYYY-MM-DD; default: last 90 days")
    s = sub.add_parser("sync")
    s.add_argument("--user", type=int, required=True)
    s.add_argument("--provider", required=True)
    s.add_argument("--since")
    u = sub.add_parser("upload")
    u.add_argument("--user", type=int, required=True)
    u.add_argument("files", nargs="+")
    r = sub.add_parser("rides")
    r.add_argument("--user", type=int, required=True)
    r.add_argument("--all", action="store_true", help="include false starts and empty recordings")
    yo = sub.add_parser("you", help="tallies, streaks, personal bests")
    yo.add_argument("--user", type=int, required=True)
    ri = sub.add_parser("rebuild-insights", help="forget routes, climbs and notes and work them out again")
    ri.add_argument("--user", type=int, required=True)
    tzp = sub.add_parser("set-tz", help="the rider's time zone, e.g. America/Toronto")
    tzp.add_argument("--user", type=int, required=True)
    tzp.add_argument("tz")
    dl = sub.add_parser("delete-ride", help="delete a ride and its recordings (stays deleted)")
    dl.add_argument("--user", type=int, required=True)
    dl.add_argument("ride_id")
    rb = sub.add_parser("rebuild")
    rb.add_argument("--user", type=int, required=True)
    cd = sub.add_parser("card")
    cd.add_argument("--user", type=int, required=True)
    cd.add_argument("ride_id")
    cd.add_argument("--name")
    cd.add_argument("--headline")
    cd.add_argument("--place", action="append", default=[], help="label,lat,lon (repeatable)")
    cd.add_argument("--no-places", action="store_true", help="don't label towns")
    cd.add_argument("--out")
    bm = sub.add_parser("build-map", help="our own map for the route check, from an OpenStreetMap extract (.osm.pbf)")
    bm.add_argument("pbf", help="e.g. data/osm/ontario-latest.osm.pbf from download.geofabrik.de")
    rc = sub.add_parser("recheck-courses", help="check every saved route again (after a change to the route check)")
    rc.add_argument("--user", type=int, required=True)
    sub.add_parser("compact", help="compress stored rides and recordings (backs the database up first)")
    v = sub.add_parser("serve")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn
        from .app import create_app
        uvicorn.run(create_app(), host=a.host, port=a.port)
        return 0

    if a.cmd == "build-map":
        from .mapdata import build
        print(f"Building the map from {a.pbf} …")
        info = build(a.pbf)
        print(f"{int(info['ways']):,} roads and trails, {int(info['pois']):,} stops, map data of {info['osm_date']}, "
              f"in {info['seconds']} s")
        return 0

    be = Backend(Settings.from_env())
    try:
        if a.cmd == "new-token":
            token = be.new_token(a.user)
            host = socket.gethostname()
            host = host if host.endswith(".local") else host + ".local"
            print(f"user {a.user}\ntoken {token}\n(keep the token private; the old one no longer works)\n"
                  f"iPhone app settings: server http://{host}:8000 and this token.")
            return 0
        if a.cmd == "create-user":
            uid, token = be.create_user()
            host = socket.gethostname()
            host = host if host.endswith(".local") else host + ".local"
            print(f"user {uid}\ntoken {token}\n(keep the token private; it's the login for the API)\n"
                  f"iPhone app settings: server http://{host}:8000 and this token.\n"
                  f"Start the server so the phone can reach it: python -m backend serve --host 0.0.0.0")
        elif a.cmd == "connect-garmin":
            key = os.environ.get("GARMIN_PERSONAL_API_KEY") or getpass.getpass("Garmin personal API key: ")
            be.connect(a.user, "garmin_personal", {"api_key": key})
            print("Connected. Pulling rides...")
            print(be.sync(a.user, "garmin_personal", a.since))
        elif a.cmd == "sync":
            print(be.sync(a.user, a.provider, a.since))
        elif a.cmd == "upload":
            for f in a.files:
                rec = be.upload(a.user, "apple_health", open(f, "rb").read())
                print(f"{f}: {rec.source} {datetime.fromtimestamp(rec.start):%Y-%m-%d %H:%M} "
                      f"-> ride {be.ride_id_for(a.user, rec.start, rec.end)}")
        elif a.cmd == "card":
            from rideengine.sources import blocked_sources
            places = []
            for p in a.place:
                label, la, lo = p.rsplit(",", 2)
                places.append([label, float(la), float(lo)])
            html = be.card_html(a.user, a.ride_id, name=a.name, headline=a.headline,
                                places=[] if a.no_places else (places or None))
            if html is None:
                print(f"error: no ride {a.ride_id}", file=sys.stderr)
                return 1
            out = a.out or os.path.join("data", "cards", f"ride_{a.ride_id}.html")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(html)
            print(f"Ride card written to {out} (route cut around home)")
            blocked = blocked_sources(be.ride(a.user, a.ride_id).provenance, "share")
            if blocked:
                print(f"Note: sharing isn't cleared yet for data from {', '.join(sorted(blocked))} "
                      f"(provider terms not reviewed). Fine for you to look at; check before posting.")
        elif a.cmd == "you":
            from rideengine.analysis.records import report
            print(report(be.you(a.user)))
        elif a.cmd == "rebuild-insights":
            be.insights.rebuild(a.user)
            y = be.you(a.user)
            print(f"{len(y['routes'])} routes, {len(y['climbs'])} climbs")
        elif a.cmd == "recheck-courses":
            for c in be.courses(a.user):
                be.check_course(a.user, c["id"])
                after = be.course(a.user, c["id"])
                print(f"{c['id']:>4}  {after['status']:<7} {c['name']}")
        elif a.cmd == "set-tz":
            be.insights.set_tz(a.user, a.tz)
            print(f"time zone {a.tz}")
        elif a.cmd == "delete-ride":
            n = be.delete_ride(a.user, a.ride_id)
            print(f"no ride {a.ride_id}" if n is None else f"ride {a.ride_id} deleted ({n} recordings)")
        elif a.cmd == "compact":
            import sqlite3
            path = be.settings.database
            backup = path + ".before-compact"
            with sqlite3.connect(backup) as dest:
                be.db.backup(dest)
            before = os.path.getsize(path)
            n = be.compact()
            print(f"backed up to {backup}; compressed {n['recordings']} recordings and {n['rides']} rides; "
                  f"database {before / 1e6:.0f} MB -> {os.path.getsize(path) / 1e6:.0f} MB")
        elif a.cmd == "rebuild":
            print(f"{be.rebuild_all(a.user)} rides rebuilt")
        elif a.cmd == "rides":
            every = be.rides(a.user, include_hidden=True)
            for d in (every if a.all else [d for d in every if not d["hidden"]]):
                s = d["summary"]
                hr = f"{s['avg_hr']:.0f}/{s['max_hr']:.0f} bpm" if s["avg_hr"] else "no HR"
                cut = "".join(f"  (left out {e['km']} km in a vehicle)" for e in d["excluded"])
                print(f"{d['ride_id']}  {datetime.fromtimestamp(s['start']):%Y-%m-%d %H:%M}  {s['km']:6.1f} km  "
                      f"{s['ascent_m'] or 0:5.0f} m  {hr:>12}  {', '.join(d['sources'])}{cut}"
                      f"{'  [hidden: ' + d['hidden'].replace('_', ' ') + ']' if d['hidden'] else ''}")
            n_hidden = sum(1 for d in every if d["hidden"])
            if n_hidden and not a.all:
                print(f"({n_hidden} false starts and empty recordings hidden; --all shows them)")
    except ConnectorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
