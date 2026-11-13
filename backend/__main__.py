"""Backend command line (dev).

  python -m backend create-user                       # prints a user id and a bearer token
  python -m backend connect-garmin --user 1 --since 2026-10-01
                                                      # asks for your Garmin personal API key, pulls rides
  python -m backend sync --user 1 --provider garmin_personal
  python -m backend upload --user 1 data/apple_watch_2026-10-03.json
  python -m backend rides --user 1
  python -m backend rebuild --user 1                  # re-merge stored rides after an engine change
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
    rb = sub.add_parser("rebuild")
    rb.add_argument("--user", type=int, required=True)
    v = sub.add_parser("serve")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn
        from .app import create_app
        uvicorn.run(create_app(), host=a.host, port=a.port)
        return 0

    be = Backend(Settings.from_env())
    try:
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
        elif a.cmd == "rebuild":
            print(f"{be.rebuild_all(a.user)} rides rebuilt")
        elif a.cmd == "rides":
            for d in be.rides(a.user):
                s = d["summary"]
                hr = f"{s['avg_hr']:.0f}/{s['max_hr']:.0f} bpm" if s["avg_hr"] else "no HR"
                cut = "".join(f"  (left out {e['km']} km in a vehicle)" for e in d["excluded"])
                print(f"{d['ride_id']}  {datetime.fromtimestamp(s['start']):%Y-%m-%d %H:%M}  {s['km']:6.1f} km  "
                      f"{s['ascent_m'] or 0:5.0f} m  {hr:>12}  {', '.join(d['sources'])}{cut}")
    except ConnectorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
