"""The backend's core, independent of HTTP: users, connections, sync, upload, merge into rides.

Flow for every activity, whichever way it arrives:
  original file kept on disk → connector.normalize() → recording row → re-merge that time window
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from rideengine.analysis.basics import summary
from rideengine.clean import hidden_reasons
from rideengine.importers.recording_json import recording_from_dict, recording_to_dict
from rideengine.merge import build_rides
from rideengine.model import Recording, Ride
from rideengine.sources import allowed, blocked_sources, sources_used

from . import db
from .config import Settings
from .connectors import REGISTRY, ConnectorError
from .crypto import Vault, load_key
from .insights import Insights

FIRST_SYNC_DAYS = 90      # history pulled on first connect unless a start date is given
RESYNC_OVERLAP_DAYS = 2   # later syncs look back a little, in case a ride synced late
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Backend:
    def __init__(self, settings: Settings, registry: Optional[dict] = None, background: bool = False):
        """background: refresh insights on a worker thread (the server). Off, they're refreshed
        before each call returns (tests, the command line)."""
        self.settings = settings
        os.makedirs(settings.data_dir, exist_ok=True)
        os.makedirs(settings.raw_dir, exist_ok=True)
        self.db = db.connect(settings.database)
        self.vault = Vault(load_key(settings.secret_key_file))
        self.registry = registry if registry is not None else REGISTRY
        self.lock = threading.RLock()
        self.insights = Insights(self, background=background)

    def connector(self, provider: str):
        if provider not in self.registry:
            raise ConnectorError(f"Unknown provider {provider!r}")
        return self.registry[provider]

    # --- users (dev tokens until Sign in with Apple) ------------------------------------------
    def create_user(self) -> tuple[int, str]:
        token = secrets.token_urlsafe(32)
        with self.lock:
            cur = self.db.execute("INSERT INTO users (created_at, token_hash) VALUES (?, ?)",
                                  (db.now(), _hash(token)))
        return cur.lastrowid, token

    def new_token(self, user_id: int) -> str:
        """A fresh login token for an existing user (e.g. a new phone); the old one stops working."""
        token = secrets.token_urlsafe(32)
        with self.lock:
            cur = self.db.execute("UPDATE users SET token_hash = ? WHERE id = ?", (_hash(token), user_id))
        if not cur.rowcount:
            raise ValueError(f"no user {user_id}")
        return token

    def user_for_token(self, token: str) -> Optional[int]:
        with self.lock:
            row = self.db.execute("SELECT id FROM users WHERE token_hash = ?", (_hash(token),)).fetchone()
        return row["id"] if row else None

    # --- connections ------------------------------------------------------------------------
    def connections(self, user_id: int) -> list[dict]:
        with self.lock:
            rows = {r["provider"]: r for r in self.db.execute(
                "SELECT provider, status, detail, last_sync_at FROM connections WHERE user_id = ?", (user_id,))}
            counts = {r["provider"]: r["n"] for r in self.db.execute(
                "SELECT provider, COUNT(*) AS n FROM recordings WHERE user_id = ? GROUP BY provider", (user_id,))}
        out = []
        for key, c in self.registry.items():
            i, row = c.info, rows.get(key)
            if i.auth == "device":
                state = "connected" if counts.get(key) else "not_connected"
            else:
                state = row["status"] if row else "not_connected"
            out.append({"provider": key, "name": i.name, "auth": i.auth, "availability": i.status,
                        "gives": i.gives, "notes": i.notes, "state": state,
                        "detail": row["detail"] if row else None,
                        "last_sync_at": row["last_sync_at"] if row else None,
                        "recordings": counts.get(key, 0)})
        return out

    def connect(self, user_id: int, provider: str, credentials: dict) -> None:
        c = self.connector(provider)
        if c.info.status != "available" or c.info.auth == "device":
            raise ConnectorError(f"{c.info.name} can't be connected here")
        secret = c.connect(credentials)
        with self.lock:
            self.db.execute(
                "INSERT INTO connections (user_id, provider, secret, status, detail, created_at) "
                "VALUES (?, ?, ?, 'connected', NULL, ?) ON CONFLICT (user_id, provider) DO UPDATE SET "
                "secret = excluded.secret, status = 'connected', detail = NULL",
                (user_id, provider, self.vault.seal(secret), db.now()))

    def disconnect(self, user_id: int, provider: str) -> int:
        """Forget the credentials and everything that provider delivered. Returns recordings removed."""
        with self.lock:
            rows = self.db.execute("SELECT external_id, start_t, end_t, raw_path FROM recordings "
                                   "WHERE user_id = ? AND provider = ?", (user_id, provider)).fetchall()
            self.db.execute("DELETE FROM connections WHERE user_id = ? AND provider = ?", (user_id, provider))
            self.db.execute("DELETE FROM recordings WHERE user_id = ? AND provider = ?", (user_id, provider))
            for r in rows:
                if r["raw_path"] and os.path.exists(r["raw_path"]):
                    os.remove(r["raw_path"])
            for r in rows:
                self.remerge(user_id, r["start_t"], r["end_t"])
            self.db.execute("DELETE FROM metrics WHERE user_id = ? AND provider = ?", (user_id, provider))
            metrics_dir = os.path.join(self.settings.raw_dir, str(user_id), provider, "metrics")
            if os.path.isdir(metrics_dir):
                shutil.rmtree(metrics_dir)
        self.insights.schedule(user_id)
        return len(rows)

    # --- recovery and fitness readings ------------------------------------------------------------
    def upload_metrics(self, user_id: int, provider: str, payload: bytes) -> dict:
        """Keep the batch as received, then store each reading once (by the provider's id)."""
        c = self.connector(provider)
        if not hasattr(c, "parse_metrics"):
            raise ConnectorError(f"{c.info.name} doesn't send recovery data")
        metrics = c.parse_metrics(payload)
        folder = os.path.join(self.settings.raw_dir, str(user_id), provider, "metrics")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, hashlib.sha256(payload).hexdigest()[:24] + ".json"), "wb") as fh:
            fh.write(payload)
        with self.lock:
            before = self.db.execute("SELECT COUNT(*) FROM metrics WHERE user_id = ?", (user_id,)).fetchone()[0]
            for m in metrics:
                self.db.execute(
                    "INSERT OR REPLACE INTO metrics (user_id, provider, external_id, kind, t, value, source, received_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (user_id, provider, m["id"], m["kind"], m["t"], m["value"], m["source"], db.now()))
            after = self.db.execute("SELECT COUNT(*) FROM metrics WHERE user_id = ?", (user_id,)).fetchone()[0]
        return {"received": len(metrics), "new": after - before}

    def recovery(self, user_id: int) -> dict:
        """HRV, resting heart rate, VO2 max and heart-rate recovery after rides, against the rider's
        own usual range (rideengine.analysis.wellness). For the rider only: never shared."""
        from rideengine.analysis import wellness
        with self.lock:
            metrics = [dict(r) for r in self.db.execute(
                "SELECT kind, t, value, source FROM metrics WHERE user_id = ? ORDER BY t", (user_id,))]
            rides = [json.loads(r["data"]) for r in self.db.execute(
                "SELECT data FROM ride_features WHERE user_id = ? ORDER BY start_t", (user_id,))]
        tz = self.insights.tz(user_id)
        return wellness.summary(metrics, [{"ride_id": f["ride_id"], "start": f["start"],
                                           "hr_drop_60s": f.get("hr_drop_60s")} for f in rides], tz=tz)

    # --- sync (pull connectors) ----------------------------------------------------------------
    def sync(self, user_id: int, provider: str, since: Optional[str] = None) -> dict:
        c = self.connector(provider)
        with self.lock:
            row = self.db.execute("SELECT secret, last_sync_at FROM connections WHERE user_id = ? AND provider = ?",
                                  (user_id, provider)).fetchone()
        if row is None:
            raise ConnectorError(f"{c.info.name} isn't connected")
        secret = self.vault.open(row["secret"])
        if since is None:
            back = (datetime.fromtimestamp(row["last_sync_at"], timezone.utc).date()
                    - timedelta(days=RESYNC_OVERLAP_DAYS)) if row["last_sync_at"] \
                else date.today() - timedelta(days=FIRST_SYNC_DAYS)
            since = back.isoformat()

        def known(external_id: str) -> bool:
            # Already stored, or deleted by the rider (then it stays deleted).
            return self.has_recording(user_id, provider, external_id) or self.is_deleted(user_id, provider, external_id)

        new, skipped, status, detail = 0, 0, "connected", None
        try:
            for f in c.fetch(secret, since, known):
                try:
                    self.ingest(user_id, provider, f.external_id, f.kind, f.content)
                    new += 1
                except ValueError:
                    skipped += 1  # unreadable or empty file: keep going
        except ConnectorError as exc:
            status, detail = "error", str(exc)
        with self.lock:
            self.db.execute("UPDATE connections SET secret = ?, status = ?, detail = ?, last_sync_at = ? "
                            "WHERE user_id = ? AND provider = ?",
                            (self.vault.seal(secret), status, detail,
                             db.now() if status == "connected" else row["last_sync_at"], user_id, provider))
        if status == "error":
            raise ConnectorError(detail)
        return {"provider": provider, "since": since, "new": new, "skipped": skipped}

    # --- upload (device connectors) ------------------------------------------------------------
    def upload(self, user_id: int, provider: str, payload: bytes) -> Recording:
        c = self.connector(provider)
        if not hasattr(c, "parse_upload"):
            raise ConnectorError(f"{c.info.name} doesn't take uploads")
        rec = c.parse_upload(payload)
        external_id = rec.origin.split(":", 1)[1]
        if self.is_deleted(user_id, provider, external_id):
            return rec  # the rider deleted this ride: accept the upload (so the phone stops sending it), keep nothing
        return self.ingest(user_id, provider, external_id, "json", payload)

    # --- deleting a ride ----------------------------------------------------------------------
    def has_recording(self, user_id: int, provider: str, external_id: str) -> bool:
        with self.lock:
            return self.db.execute("SELECT 1 FROM recordings WHERE user_id = ? AND provider = ? AND external_id = ?",
                                   (user_id, provider, external_id)).fetchone() is not None

    def is_deleted(self, user_id: int, provider: str, external_id: str) -> bool:
        with self.lock:
            return self.db.execute("SELECT 1 FROM deleted_recordings WHERE user_id = ? AND provider = ? "
                                   "AND external_id = ?", (user_id, provider, external_id)).fetchone() is not None

    def delete_ride(self, user_id: int, ride_id: str) -> Optional[int]:
        """Delete a ride: every recording merged into it (and its original file) goes, and is remembered
        as deleted so a later sync or upload doesn't bring it back. Returns recordings removed, or None
        if there's no such ride."""
        ride = self.ride(user_id, ride_id)
        if ride is None:
            return None
        origins = set(ride.recordings)
        with self.lock:
            rows = self.db.execute(
                "SELECT provider, external_id, start_t, end_t, raw_path, data FROM recordings WHERE user_id = ? "
                "AND end_t >= ? AND start_t <= ?", (user_id, ride.start - 60, ride.end + 60)).fetchall()
            gone = [r for r in rows if json.loads(r["data"]).get("origin") in origins]
            for r in gone:
                self.db.execute("DELETE FROM recordings WHERE user_id = ? AND provider = ? AND external_id = ?",
                                (user_id, r["provider"], r["external_id"]))
                self.db.execute("INSERT OR REPLACE INTO deleted_recordings (user_id, provider, external_id, start_t, "
                                "end_t, deleted_at) VALUES (?, ?, ?, ?, ?, ?)",
                                (user_id, r["provider"], r["external_id"], r["start_t"], r["end_t"], db.now()))
                if r["raw_path"] and os.path.exists(r["raw_path"]):
                    os.remove(r["raw_path"])
            lo = min([ride.start] + [r["start_t"] for r in gone])
            hi = max([ride.end] + [r["end_t"] for r in gone])
            self.remerge(user_id, lo, hi)
        self.insights.schedule(user_id)
        return len(gone)

    # --- ingest and merge ----------------------------------------------------------------------
    def ingest(self, user_id: int, provider: str, external_id: str, kind: str, content: bytes) -> Recording:
        """Keep the original, normalize it, store the recording, rebuild rides around it."""
        c = self.connector(provider)
        folder = os.path.join(self.settings.raw_dir, str(user_id), provider)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{_SAFE_ID.sub('_', external_id)}.{_SAFE_ID.sub('', kind)}")
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(content)
        os.replace(tmp, path)
        try:
            rec = c.normalize(path, external_id)
        except Exception:
            os.remove(path)
            raise
        with self.lock:
            old = self.db.execute("SELECT start_t, end_t FROM recordings WHERE user_id = ? AND provider = ? "
                                  "AND external_id = ?", (user_id, provider, external_id)).fetchone()
            self.db.execute(
                "INSERT INTO recordings (user_id, provider, external_id, source, start_t, end_t, raw_path, data, "
                "received_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (user_id, provider, external_id) "
                "DO UPDATE SET source = excluded.source, start_t = excluded.start_t, end_t = excluded.end_t, "
                "raw_path = excluded.raw_path, data = excluded.data, received_at = excluded.received_at",
                (user_id, provider, external_id, rec.source, rec.start, rec.end, path,
                 json.dumps(recording_to_dict(rec)), db.now()))
            if old:  # a re-upload may have moved in time
                self.remerge(user_id, old["start_t"], old["end_t"])
            self.remerge(user_id, rec.start, rec.end)
        self.insights.schedule(user_id)
        return rec

    def remerge(self, user_id: int, start: float, end: float) -> list[Ride]:
        """Rebuild the rides around [start, end]. The window grows until it holds every recording
        that touches it, so a ride is always rebuilt from all of its recordings."""
        lo, hi = start - 60, end + 60
        with self.lock:
            while True:
                rows = self.db.execute("SELECT data, start_t, end_t FROM recordings WHERE user_id = ? "
                                       "AND end_t >= ? AND start_t <= ?", (user_id, lo, hi)).fetchall()
                nlo = min([lo] + [r["start_t"] for r in rows])
                nhi = max([hi] + [r["end_t"] for r in rows])
                if (nlo, nhi) == (lo, hi):
                    break
                lo, hi = nlo, nhi
            rides = build_rides([recording_from_dict(json.loads(r["data"])) for r in rows])
            removed = [r["ride_id"] for r in self.db.execute(
                "SELECT ride_id FROM rides WHERE user_id = ? AND end_t >= ? AND start_t <= ?", (user_id, lo, hi))]
            self.db.execute("DELETE FROM rides WHERE user_id = ? AND end_t >= ? AND start_t <= ?", (user_id, lo, hi))
            for r in rides:
                self.db.execute("INSERT OR REPLACE INTO rides (user_id, ride_id, start_t, end_t, data) "
                                "VALUES (?, ?, ?, ?, ?)", (user_id, str(int(r.start)), r.start, r.end, r.to_json()))
            self.insights.rides_changed(user_id, removed, rides)
        return rides

    def rebuild_all(self, user_id: int) -> int:
        """Re-merge every ride from the stored recordings (after the engine changes). Returns rides."""
        with self.lock:
            row = self.db.execute("SELECT MIN(start_t) AS a, MAX(end_t) AS b FROM recordings WHERE user_id = ?",
                                  (user_id,)).fetchone()
            if row["a"] is None:
                return 0
            n = len(self.remerge(user_id, row["a"], row["b"]))
        self.insights.schedule(user_id)
        return n

    # --- reading rides ------------------------------------------------------------------------
    def rides(self, user_id: int, include_hidden: bool = False) -> list[dict]:
        """Rides newest first. False starts and empty recordings are left out unless asked for;
        with include_hidden each ride says why it would be hidden ("hidden": reason or None)."""
        with self.lock:
            rows = self.db.execute("SELECT ride_id, data FROM rides WHERE user_id = ? ORDER BY start_t DESC",
                                   (user_id,)).fetchall()
        rides = [Ride.from_json(r["data"]) for r in rows]
        hide = hidden_reasons(rides)
        notes = self.insights.notes(user_id)
        out = []
        for i, (row, ride) in enumerate(zip(rows, rides)):
            if i in hide and not include_hidden:
                continue
            d = describe(row["ride_id"], ride)
            d["hidden"] = hide.get(i)
            d["notes"] = notes.get(row["ride_id"], [])
            out.append(d)
        return out

    def visible_rides(self, user_id: int) -> list[Ride]:
        with self.lock:
            rows = self.db.execute("SELECT data FROM rides WHERE user_id = ? ORDER BY start_t",
                                   (user_id,)).fetchall()
        rides = [Ride.from_json(r["data"]) for r in rows]
        hide = hidden_reasons(rides)
        return [r for i, r in enumerate(rides) if i not in hide]

    def you(self, user_id: int) -> dict:
        """Tallies, streaks, personal bests, repeated routes and climbs, and the latest rides' notes,
        from what backend/insights.py keeps stored."""
        return self.insights.you(user_id)

    def notes(self, user_id: int, ride_id: str) -> list[dict]:
        """What's notable about one ride, compared with the rides before it."""
        return self.insights.notes(user_id).get(ride_id, [])

    # --- the rider: name, avatar ------------------------------------------------------------------
    def me(self, user_id: int) -> dict:
        from rideengine.card.avatar import clean
        with self.lock:
            row = self.db.execute("SELECT id, tz, display_name, avatar, ftp FROM users WHERE id = ?", (user_id,)).fetchone()
        return {"id": row["id"], "tz": row["tz"], "name": row["display_name"] or "Rider",
                "avatar": clean(json.loads(row["avatar"])) if row["avatar"] else None, "ftp": row["ftp"]}

    def update_me(self, user_id: int, body: dict) -> dict:
        """{"tz": ..., "name": ..., "avatar": {...}}: any of them. The avatar is cleaned to known parts."""
        from rideengine.card.avatar import clean
        if "tz" in body:
            self.insights.set_tz(user_id, str(body["tz"]))
        with self.lock:
            if "name" in body:
                name = str(body["name"] or "").strip()[:40] or None
                self.db.execute("UPDATE users SET display_name = ? WHERE id = ?", (name, user_id))
            if "avatar" in body:
                spec = json.dumps(clean(body["avatar"])) if isinstance(body["avatar"], dict) else None
                self.db.execute("UPDATE users SET avatar = ? WHERE id = ?", (spec, user_id))
            if "ftp" in body:
                ftp = body["ftp"]
                if ftp is not None and not (50 <= float(ftp) <= 600):
                    raise ValueError("FTP must be between 50 and 600 watts")
                self.db.execute("UPDATE users SET ftp = ? WHERE id = ?", (None if ftp is None else float(ftp), user_id))
        return self.me(user_id)

    # --- training plan (rideengine/analysis/plan.py) -----------------------------------------------
    def _plan_context(self, user_id: int) -> dict:
        from rideengine.analysis import features as feat_mod
        from rideengine.analysis import goals as g
        from rideengine.analysis import plan as p
        tz = self.insights.tz(user_id)
        with self.lock:
            feats = self.insights._features(user_id)
        visible = feat_mod.visible_ids(feats)
        vfeats = [f for f in feats if f["ride_id"] in visible]
        today = datetime.now(tz).astimezone(tz).date()
        recent = [f for f in vfeats if f["start"] >= (datetime.now() - timedelta(days=365)).timestamp()]
        starts = [datetime.fromtimestamp(f["start"], tz).astimezone(tz) for f in recent]
        power = g.best_power_curve(vfeats, today - timedelta(days=120))
        me = self.me(user_id)
        rest = self.recovery(user_id)["resting_hr"].get("usual")
        max_hr = p.max_hr_estimate([f.get("max_hr") for f in recent])
        return {"tz": tz, "today": today, "feats": vfeats, "starts": starts,
                "ftp": p.ftp_estimate(me.get("ftp"), power), "hr_zones": p.hr_zones(max_hr, rest),
                "max_hr": max_hr, "resting_hr": rest}

    def _active_plan(self, user_id: int) -> Optional[dict]:
        with self.lock:
            row = self.db.execute("SELECT plan_id, data FROM plans WHERE user_id = ? AND active = 1 "
                                  "ORDER BY plan_id DESC LIMIT 1", (user_id,)).fetchone()
        return {**json.loads(row["data"]), "plan_id": row["plan_id"]} if row else None

    def make_plan(self, user_id: int, days: Optional[list] = None, times: Optional[dict] = None,
                  weekly_hours: Optional[float] = None) -> Optional[dict]:
        """(Re)build the plan from the active goal. Days and times default to the rider's usual ones; weeks
        already past are kept as they were, so "did you do it" history survives a change."""
        from rideengine.analysis import goals as g
        from rideengine.analysis import plan as p
        with self.lock:
            row = self.db.execute("SELECT goal_id, data FROM goals WHERE user_id = ? AND active = 1 "
                                  "ORDER BY goal_id DESC LIMIT 1", (user_id,)).fetchone()
        if row is None:
            return None
        goal = {**json.loads(row["data"]), "id": row["goal_id"]}
        c = self._plan_context(user_id)
        old = self._active_plan(user_id)
        same_goal = old and old.get("goal_id") == goal["id"]
        hours = float(weekly_hours or (old["weekly_hours"] if same_goal else None)
                      or goal.get("params", {}).get("weekly_hours") or 4.5)
        n = p.sessions_for(hours)
        days = days or (old["days"] if same_goal else None) or p.usual_days(c["starts"], n)
        bad = [d for d in days if d not in p.WEEKDAYS]
        if bad or not days:
            raise ValueError("days must be some of Mon Tue Wed Thu Fri Sat Sun")
        times = {**p.usual_times(c["starts"]), **((old or {}).get("times", {}) if same_goal else {}), **(times or {})}
        for d, t in times.items():
            datetime.strptime(t, "%H:%M")  # raises ValueError for a bad time
        season = g.seasons(records_entries(c["feats"], c["tz"]), c["today"])
        new = p.build_plan(goal, c["today"], season, days, times, hours)
        if same_goal:  # keep the sessions before today
            kept = [s for w in old["weeks"] for s in w["sessions"] if s["date"] < c["today"].isoformat()]
            if kept and new["weeks"]:
                first = new["weeks"][0]
                prior = [w for w in old["weeks"] if w["week_start"] < first["week_start"]]
                first["sessions"] = sorted([s for s in kept if s["date"] >= first["week_start"]] + first["sessions"],
                                           key=lambda s: s["date"])
                new["weeks"] = prior + new["weeks"]
                new["start"] = old["start"]
        with self.lock:
            self.db.execute("UPDATE plans SET active = 0 WHERE user_id = ?", (user_id,))
            self.db.execute("INSERT INTO plans (user_id, goal_id, data, active, created_at) VALUES (?, ?, ?, 1, ?)",
                            (user_id, goal["id"], json.dumps(new), db.now()))
        return new

    def plan_view(self, user_id: int) -> Optional[dict]:
        """The active plan with targets filled in (current FTP and heart-rate zones) and each session's status."""
        from rideengine.analysis import plan as p
        plan = self._active_plan(user_id)
        if plan is None:
            return None
        c = self._plan_context(user_id)
        by_day: dict[str, list] = {}
        for f in c["feats"]:
            by_day.setdefault(datetime.fromtimestamp(f["start"], c["tz"]).astimezone(c["tz"]).date().isoformat(), []).append(f)
        with self.lock:
            done = {r["session_id"] for r in self.db.execute("SELECT session_id FROM plan_done WHERE user_id = ?", (user_id,))}
        today = c["today"]
        weeks = []
        for w in plan["weeks"]:
            sessions = []
            for s in w["sessions"]:
                t = p.targets(s, c["ftp"]["watts"], c["hr_zones"]) if s["steps"] else dict(s)
                t["status"] = p.status(s, by_day.get(s["date"], []), today, done)
                t["summary"] = p.describe(t) if s["steps"] else s["purpose"]
                sessions.append(t)
            weeks.append({**w, "sessions": sessions,
                          "done": sum(1 for s in sessions if s["status"] == "done"), "total": len(sessions)})
        this_week = next((w for w in weeks if w["week_start"] <= today.isoformat() <
                          (date.fromisoformat(w["week_start"]) + timedelta(days=7)).isoformat()), None)
        return {"plan_id": plan["plan_id"], "goal_id": plan.get("goal_id"), "start": plan["start"],
                "ready_by": plan["ready_by"], "days": plan["days"], "times": plan["times"],
                "weekly_hours": plan["weekly_hours"], "ftp": c["ftp"], "hr_zones": c["hr_zones"],
                "max_hr": c["max_hr"], "resting_hr": c["resting_hr"],
                "zones": {z: {"name": v["name"], "pct_ftp": [round(v["ftp"][0] * 100), round(v["ftp"][1] * 100)]}
                          for z, v in p.ZONES.items()},
                "this_week": this_week["index"] if this_week else None, "weeks": weeks}

    def plan_session(self, user_id: int, session_id: str) -> Optional[dict]:
        view = self.plan_view(user_id)
        if view is None:
            return None
        return next((s for w in view["weeks"] for s in w["sessions"] if s["id"] == session_id), None)

    def mark_done(self, user_id: int, session_id: str, done: bool = True) -> bool:
        if self.plan_session(user_id, session_id) is None:
            return False
        with self.lock:
            if done:
                self.db.execute("INSERT OR REPLACE INTO plan_done (user_id, session_id, at) VALUES (?, ?, ?)",
                                (user_id, session_id, db.now()))
            else:
                self.db.execute("DELETE FROM plan_done WHERE user_id = ? AND session_id = ?", (user_id, session_id))
        return True

    def session_zwo(self, user_id: int, session_id: str) -> Optional[str]:
        from rideengine.analysis import plan as p
        s = self.plan_session(user_id, session_id)
        return p.to_zwo(s) if s and s["steps"] else None

    def calendar_token(self, user_id: int, reset: bool = False) -> str:
        """The secret in the calendar feed's address (calendar apps can't send a login). Reset makes a new
        one, so old subscriptions stop updating."""
        with self.lock:
            row = self.db.execute("SELECT calendar_token FROM users WHERE id = ?", (user_id,)).fetchone()
            if row["calendar_token"] and not reset:
                return row["calendar_token"]
            token = secrets.token_urlsafe(24)
            self.db.execute("UPDATE users SET calendar_token = ? WHERE id = ?", (token, user_id))
            return token

    def calendar_ics(self, token: str) -> Optional[str]:
        from rideengine.analysis import plan as p
        with self.lock:
            row = self.db.execute("SELECT id FROM users WHERE calendar_token = ?", (token,)).fetchone()
        if row is None:
            return None
        view = self.plan_view(row["id"])
        sessions = [s for w in (view or {}).get("weeks", []) for s in w["sessions"]]
        return p.to_ics(sessions, self.insights.tz(row["id"]))

    # --- the fun bucket: badges, rider card, binder ------------------------------------------------
    def collection(self, user_id: int) -> dict:
        """Badges, the rider card's ratings and the season binder, from what insights keeps stored."""
        from rideengine.analysis import collection as col
        from rideengine.analysis import features as feat_mod
        from rideengine.analysis import records, repeats
        with self.lock:
            feats = self.insights._features(user_id)
            visible = feat_mod.visible_ids(feats)
            found = self.insights._found(user_id, visible)
        notes = self.insights.notes(user_id)
        tz = self.insights.tz(user_id)
        vfeats = [f for f in feats if f["ride_id"] in visible]
        es = records.entries_from_features(vfeats, tz)
        today = datetime.now(tz).astimezone(tz).date()
        local = col.local_times(vfeats, tz, repeats.home_point(vfeats))
        badges = col.badges(es, found, tz, local)
        names = {l["ride_id"]: r["name"] for r in found["routes"] for l in r["laps"]}
        shapes = {f["ride_id"]: f.get("shape") or [] for f in vfeats}
        me = self.me(user_id)
        return {"rider": {**col.ratings(es, today), "name": me["name"], "avatar": me["avatar"],
                          "badges_earned": sum(b["earned"] for b in badges), "badges_total": len(badges)},
                "badges": badges, "binder": col.binder(es, notes, names, shapes, today)}

    def rider_card_html(self, user_id: int, fonts: str = "google", background: str = "#FFFFFF") -> str:
        from rideengine.card.rider_card import rider_card
        c = self.collection(user_id)
        r = c["rider"]
        return rider_card(r, r["avatar"], name=r["name"], badges_earned=r["badges_earned"],
                          badges_total=r["badges_total"], fonts=fonts, background=background)

    # --- goals (rideengine/analysis/goals.py, docs/coaching.md) --------------------------------------
    def _goal_context(self, user_id: int) -> dict:
        from rideengine.analysis import features as feat_mod
        from rideengine.analysis import goals as g
        from rideengine.analysis import records
        with self.lock:
            feats = self.insights._features(user_id)
            visible = feat_mod.visible_ids(feats)
            found = self.insights._found(user_id, visible)
        tz = self.insights.tz(user_id)
        vfeats = [f for f in feats if f["ride_id"] in visible]
        es = records.entries_from_features(vfeats, tz)
        today = datetime.now(tz).astimezone(tz).date()
        rest = self.recovery(user_id)["resting_hr"].get("usual")
        return {"es": es, "found": found, "today": today, "rest": rest,
                "power": g.best_power_curve(vfeats, today - timedelta(days=120))}

    def goal_options(self, user_id: int) -> dict:
        from rideengine.analysis import goals as g
        c = self._goal_context(user_id)
        return {"objectives": g.options(c["es"], c["found"], c["today"]), "season": g.seasons(c["es"], c["today"])}

    def check_goal(self, user_id: int, goal: dict) -> dict:
        """A goal as the app sends it, checked and tidied. Raises ValueError with a message to show."""
        from rideengine.analysis import goals as g
        if not isinstance(goal, dict):
            raise ValueError("A goal is an object")
        objective, aspiration = goal.get("objective"), goal.get("aspiration")
        opts = {o["id"]: {a["id"]: a for a in o["aspirations"]} for o in self.goal_options(user_id)["objectives"]}
        if objective not in opts or aspiration not in opts[objective]:
            raise ValueError(f"Unknown goal {objective!r} / {aspiration!r}")
        p = goal.get("params") or {}
        if not isinstance(p, dict):
            raise ValueError("params must be an object")
        params: dict = {}
        for key, lo, hi in (("group_kmh", 15, 50), ("ride_hours", 0.5, 12), ("target_km", 10, 1000),
                            ("event_km", 5, 1000), ("event_climbing_m", 0, 10000), ("weekly_hours", 1, 30)):
            if p.get(key) is not None:
                v = float(p[key])
                if not lo <= v <= hi:
                    raise ValueError(f"{key} must be between {lo} and {hi}")
                params[key] = v
        if p.get("terrain") is not None:
            if p["terrain"] not in ("flat", "rolling", "hilly"):
                raise ValueError("terrain must be flat, rolling or hilly")
            params["terrain"] = p["terrain"]
        if objective == "further" and "target_km" not in params and opts[objective][aspiration].get("target_km"):
            params["target_km"] = opts[objective][aspiration]["target_km"]
        ready_by = goal.get("ready_by")
        if ready_by in (None, "", "season"):
            ready_by = self.goal_options(user_id)["season"]["outdoor_from"]
        else:
            date.fromisoformat(str(ready_by))  # raises ValueError for a bad date
        words = str(goal.get("words") or "").strip()[:500] or None
        tags = [str(t)[:40] for t in (goal.get("tags") or [])][:10]
        return {"objective": objective, "aspiration": aspiration, "title": opts[objective][aspiration]["title"],
                "params": params, "ready_by": ready_by, "words": words, "tags": tags}

    def goal_view(self, user_id: int, goal: dict) -> dict:
        """A goal with what it means (the reveal) and how we'll see it working (markers), from the rider's data."""
        from rideengine.analysis import goals as g
        c = self._goal_context(user_id)
        return {"goal": goal, "reveal": g.reveal(goal, c["es"], c["found"], c["today"], c["rest"]),
                "markers": g.markers(goal, c["es"], c["found"], c["today"], c["rest"], c["power"]),
                "season": g.seasons(c["es"], c["today"])}

    def set_goal(self, user_id: int, goal: dict) -> dict:
        goal = self.check_goal(user_id, goal)
        with self.lock:
            self.db.execute("UPDATE goals SET active = 0, ended_at = ? WHERE user_id = ? AND active = 1", (db.now(), user_id))
            cur = self.db.execute("INSERT INTO goals (user_id, data, active, created_at) VALUES (?, ?, 1, ?)",
                                  (user_id, json.dumps(goal), db.now()))
        self.make_plan(user_id)
        return self.goal_view(user_id, {**goal, "id": cur.lastrowid})

    def current_goal(self, user_id: int) -> Optional[dict]:
        with self.lock:
            row = self.db.execute("SELECT goal_id, data, created_at FROM goals WHERE user_id = ? AND active = 1 "
                                  "ORDER BY goal_id DESC LIMIT 1", (user_id,)).fetchone()
        if row is None:
            return None
        return self.goal_view(user_id, {**json.loads(row["data"]), "id": row["goal_id"], "set_at": row["created_at"]})

    def end_goal(self, user_id: int) -> bool:
        with self.lock:
            cur = self.db.execute("UPDATE goals SET active = 0, ended_at = ? WHERE user_id = ? AND active = 1",
                                  (db.now(), user_id))
            self.db.execute("UPDATE plans SET active = 0 WHERE user_id = ?", (user_id,))
        return cur.rowcount > 0

    def card_html(self, user_id: int, ride_id: str, name: Optional[str] = None, headline: Optional[str] = None,
                  places: Optional[list] = None, fonts: str = "google", background: str = "#FFFFFF",
                  privacy: bool = True) -> Optional[str]:
        """The ride's collectible card (rideengine/card/ride_card.py), filled in from what's stored:
        the route's name if the ride is a lap of one, its number in the year, its top note as the
        headline, and (privacy) the route cut around home so a shared card doesn't show it."""
        from rideengine.analysis import features as feat_mod
        from rideengine.analysis import records, repeats
        from rideengine.card.ride_card import ride_card
        ride = self.ride(user_id, ride_id)
        if ride is None:
            return None
        with self.lock:
            feats = self.insights._features(user_id)
            visible = feat_mod.visible_ids(feats)
            found = self.insights._found(user_id, visible)
        tz = self.insights.tz(user_id)
        year = datetime.fromtimestamp(ride.start, tz).year
        same_year = [f["ride_id"] for f in feats if f["ride_id"] in visible
                     and datetime.fromtimestamp(f["start"], tz).year == year]
        number = same_year.index(ride_id) + 1 if ride_id in same_year else None
        if name is None:
            name = next((r["name"] for r in found["routes"] if any(l["ride_id"] == ride_id for l in r["laps"])), None)
        if name is None and not ride.indoor:
            # Not a repeated route: name it after the main town on it ("Cannington loop").
            from rideengine.places import places_on_route
            on = places_on_route(ride, limit=1)
            f = next((x for x in feats if x["ride_id"] == ride_id), None)
            if on and f and f.get("first"):
                loop = repeats.haversine(*f["first"], *f["last"]) <= repeats.LOOP_M
                name = f"{on[0]['name']} {'loop' if loop else 'ride'}"
        if headline is None:
            headline = records.headline(self.notes(user_id, ride_id))
        home = repeats.home_point([f for f in feats if f["ride_id"] in visible]) if privacy else None
        from rideengine.analysis.collection import is_holo
        return ride_card(ride, number=number, name=name, headline=headline, places=places, fonts=fonts,
                         hide_near=[home] if home else None, background=background,
                         avatar=self.me(user_id)["avatar"], holo=is_holo(self.notes(user_id, ride_id)))

    def ride(self, user_id: int, ride_id: str) -> Optional[Ride]:
        with self.lock:
            row = self.db.execute("SELECT data FROM rides WHERE user_id = ? AND ride_id = ?",
                                  (user_id, ride_id)).fetchone()
        return Ride.from_json(row["data"]) if row else None

    def ride_id_for(self, user_id: int, start: float, end: float) -> Optional[str]:
        """The merged ride a recording ended up in (the one it overlaps most)."""
        with self.lock:
            row = self.db.execute(
                "SELECT ride_id, MIN(end_t, ?) - MAX(start_t, ?) AS o FROM rides WHERE user_id = ? "
                "AND end_t >= ? AND start_t <= ? ORDER BY o DESC LIMIT 1",
                (end, start, user_id, start, end)).fetchone()
        return row["ride_id"] if row else None


def describe(ride_id: str, ride: Ride) -> dict:
    """A ride without its samples: summary, where each value came from, what it may be used for."""
    return {"ride_id": ride_id, "summary": summary(ride), "sources": sorted(sources_used(ride.provenance)),
            "provenance": ride.provenance, "recordings": ride.recordings, "excluded": ride.excluded,
            "use": {u: {"allowed": allowed(ride.provenance, u),
                        "blocked_by": sorted(blocked_sources(ride.provenance, u))} for u in ("ai", "share")}}


def records_entries(feats: list[dict], tz):
    from rideengine.analysis import records
    return records.entries_from_features(feats, tz)
