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
from rideengine.analysis import effort as effort_mod
from rideengine.clean import SESSION_GAP_S, _size, hidden_reasons
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


def train_mins(m: float) -> str:
    """Minutes of work in words, to the half minute: '7.5 min', '12 min'."""
    from rideengine.analysis.train import _mins
    return _mins(m * 60)


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
        self._stop = threading.Event()
        self.insights = Insights(self, background=background)
        from .coach import Coach
        self.coach = Coach(self.db, self.lock)   # the AI coach's words (backend/coach.py); tests swap its client
        from .coach_chat import CoachChat
        self.coach_chat = CoachChat(self, background)   # the coach you can ask anything (backend/coach_chat.py)
        self.map_source = None   # roads and stops for the route check; None: OpenStreetMap (tests swap it)
        self.graph_source = None  # roads to route on when tuning; None: our own map (tests swap it)
        self.heights = None       # ground heights for tuned routes; None: elevation tiles (tests swap it)
        self.area_source = None   # (bbox, prefs) -> (Graph, stops, places) for generating loops (tests swap it)
        self.gravel_grid = None   # where the gravel is (rideengine/routes/gravelmap.py); None: from our map

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

    # --- keeping pulled sources fresh -------------------------------------------------------------
    # Garmin (and later Wahoo, Whoop...) are pulled, not pushed: without this a ride only arrived when the
    # rider tapped Sync now. The server checks every POLL_S; the app asks when it opens (sync_due).
    POLL_S = 15 * 60

    def sync_due(self, user_id: int, max_age_s: float = 5 * 60) -> dict:
        """Sync each connected pull source (not Apple Health, which the phone pushes) last synced more
        than max_age_s ago. Errors are kept on the connection, as for Sync now. {provider: new rides}."""
        with self.lock:
            rows = self.db.execute("SELECT provider, last_sync_at FROM connections WHERE user_id = ?",
                                   (user_id,)).fetchall()
        out = {}
        for r in rows:
            c = self.registry.get(r["provider"])
            if c is None or c.info.auth == "device" or (r["last_sync_at"] or 0) > db.now() - max_age_s:
                continue
            try:
                out[r["provider"]] = self.sync(user_id, r["provider"])["new"]
            except ConnectorError:
                out[r["provider"]] = None
        return out

    def start_polling(self, interval_s: Optional[float] = None) -> None:
        """Server only: sync every rider's pull sources every interval_s, on a daemon thread."""
        interval = interval_s or self.POLL_S

        def loop():
            while not self._stop.wait(interval):
                with self.lock:
                    users = [r["user_id"] for r in self.db.execute("SELECT DISTINCT user_id FROM connections")]
                for uid in users:
                    try:
                        self.sync_due(uid, max_age_s=interval * 0.8)
                    except Exception:   # one rider's trouble never stops the others' syncs
                        pass

        threading.Thread(target=loop, name="poll-sources", daemon=True).start()

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
            gone = [r for r in rows if json.loads(db.unpack(r["data"])).get("origin") in origins]
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
                 db.pack(json.dumps(recording_to_dict(rec))), db.now()))
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
            rides = build_rides([recording_from_dict(json.loads(db.unpack(r["data"]))) for r in rows])
            removed = [r["ride_id"] for r in self.db.execute(
                "SELECT ride_id FROM rides WHERE user_id = ? AND end_t >= ? AND start_t <= ?", (user_id, lo, hi))]
            self.db.execute("DELETE FROM rides WHERE user_id = ? AND end_t >= ? AND start_t <= ?", (user_id, lo, hi))
            for r in rides:
                rid = str(int(r.start))
                self.db.execute("INSERT OR REPLACE INTO rides (user_id, ride_id, start_t, end_t, data, brief) "
                                "VALUES (?, ?, ?, ?, ?, ?)", (user_id, rid, r.start, r.end, db.pack(r.to_json()),
                                                              json.dumps(brief(rid, r))))
            # A ride's id is its start, which moves when another device's recording joins it (one started
            # earlier): what the rider said about the ride moves with it.
            new_ids = {str(int(r.start)): r for r in rides}
            for old in removed:
                if old in new_ids:
                    continue
                hit = next((rid for rid, r in new_ids.items() if r.start - 60 <= float(old) <= r.end), None)
                if hit:
                    self._move_ride_refs(user_id, old, hit)
            self.insights.rides_changed(user_id, removed, rides)
        return rides

    def _move_ride_refs(self, user_id: int, old: str, new: str) -> None:
        """The rider's own words about a ride (how it felt, which session it counts as) and the coach's saved
        story follow it to its new id. Where the new id already has its own, that one stays."""
        for table, col, a, b in (("ride_feel", "ride_id", old, new), ("plan_matches", "ride_id", old, new),
                                 ("coach_texts", "key", f"ride:{old}", f"ride:{new}")):
            self.db.execute(f"UPDATE OR IGNORE {table} SET {col} = ? WHERE user_id = ? AND {col} = ?", (b, user_id, a))
            self.db.execute(f"DELETE FROM {table} WHERE user_id = ? AND {col} = ?", (user_id, a))

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
        # From each ride's stored brief, never its samples: unpacking every ride's samples took 1.6 s of the
        # list's 1.7 s (20 Nov 2026). A ride stored before briefs existed gets one now.
        with self.lock:
            rows = self.db.execute("SELECT ride_id, brief FROM rides WHERE user_id = ? ORDER BY start_t DESC",
                                   (user_id,)).fetchall()
            briefs = []
            for r in rows:
                b = json.loads(r["brief"]) if r["brief"] else None
                if b is None or b.get("v") != BRIEF_VERSION:
                    ride = self.ride(user_id, r["ride_id"])
                    b = brief(r["ride_id"], ride)
                    self.db.execute("UPDATE rides SET brief = ? WHERE user_id = ? AND ride_id = ?",
                                    (json.dumps(b), user_id, r["ride_id"]))
                briefs.append(b)
        shapes = [_Shape(b["shape"]) for b in briefs]
        hide = hidden_reasons(shapes)
        efforts = effort_mod.group(shapes)
        effort_of = {k: rows[e["main"]]["ride_id"] for e in efforts for k in e["parts"] + e["folded"]}
        notes = self.insights.notes(user_id)
        out = []
        for i, (row, b) in enumerate(zip(rows, briefs)):
            if i in hide and not include_hidden:
                continue
            d = {k: v for k, v in b.items() if k not in ("v", "shape")}
            d["hidden"] = hide.get(i)
            d["notes"] = notes.get(row["ride_id"], [])
            d["effort"] = effort_of.get(i, row["ride_id"])   # the effort (outing) this ride is part of
            out.append(d)
        return out

    def effort(self, user_id: int, ride_id: str) -> Optional[dict]:
        """The effort a ride belongs to: its parts, the false starts folded into it, and for each part the
        phases (warm-up, structured workout, own riding, pushes, pauses, cool-down) with rule-based lines.
        See rideengine/analysis/effort.py."""
        with self.lock:
            rows = self.db.execute("SELECT ride_id, start_t, end_t FROM rides WHERE user_id = ? ORDER BY start_t",
                                   (user_id,)).fetchall()
            hit = next((r for r in rows if r["ride_id"] == ride_id), None)
            if hit is None:
                return None
            gap = SESSION_GAP_S
            near = [r["ride_id"] for r in rows if r["end_t"] >= hit["start_t"] - 3 * gap and r["start_t"] <= hit["end_t"] + 3 * gap]
            data = {r["ride_id"]: r["data"] for r in self.db.execute(
                f"SELECT ride_id, data FROM rides WHERE user_id = ? AND ride_id IN ({','.join('?' * len(near))})",
                (user_id, *near))}
        ids = [i for i in near if i in data]
        rides = [Ride.from_json(db.unpack(data[i])) for i in ids]
        e = next(x for x in effort_mod.group(rides) if ids.index(ride_id) in x["parts"] + x["folded"])
        parts = []
        for k in e["parts"]:
            d = describe(ids[k], rides[k])
            d["phases"] = effort_mod.phases(rides[k])
            parts.append(d)
        folded = [{"ride_id": ids[k], "reason": e["reasons"].get(k), "start": rides[k].start,
                   "minutes": round((rides[k].end - rides[k].start) / 60, 1)} for k in e["folded"]]
        lines = []
        starts = [f for f in folded if f["reason"] == "false_start"]
        if starts:
            mins = sorted(round(f["minutes"]) for f in starts)
            each = f"{mins[0]} min each" if len(set(mins)) == 1 else f"{', '.join(str(m) for m in mins)} min"
            lines.append(f"{len(starts)} false starts ({each}) left out of this effort." if len(starts) > 1
                         else f"A false start ({mins[0]} min) left out of this effort.")
        for n, part in enumerate(parts):
            if len(parts) > 1:
                at = datetime.fromtimestamp(part["summary"]["start"], self.insights.tz(user_id)).strftime("%H:%M")
                lines.append(f"Part {n + 1}, from {at}:")
            lines += part["phases"]["lines"]
        # The session this ride counts as, planned against ridden (the same words as the ride note in Train).
        plan = None
        from rideengine.analysis import train
        for k in e["parts"]:
            s_ = self._counted_session(user_id, ids[k])
            if s_:
                a = self._ridden_against(user_id, self._plan_context(user_id), s_, train.work(rides[k]), ids[k])
                plan = {"session_id": s_["id"], "title": s_["title"], "summary": a["summary"] if a else None,
                        "lines": a["lines"] if a else [], "sets": a["sets"] if a else []}
                break
        return {"effort_id": ids[e["main"]], "parts": parts, "folded": folded, "lines": lines, "plan": plan,
                "use": parts[0]["use"] if len(parts) == 1 else {
                    u: {"allowed": all(p["use"][u]["allowed"] for p in parts),
                        "blocked_by": sorted({b for p in parts for b in p["use"][u]["blocked_by"]})} for u in ("ai", "share")}}

    def compact(self) -> dict:
        """Compress rides and recordings stored as plain JSON (before 20 Nov 2026) and give every ride its brief,
        checking each compressed row reads back the same. In one transaction: all or nothing."""
        n = {"recordings": 0, "rides": 0}
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                for r in self.db.execute("SELECT rowid, data FROM recordings").fetchall():
                    if isinstance(r["data"], str):
                        packed = db.pack(r["data"])
                        assert db.unpack(packed) == r["data"]
                        self.db.execute("UPDATE recordings SET data = ? WHERE rowid = ?", (packed, r["rowid"]))
                        n["recordings"] += 1
                for r in self.db.execute("SELECT rowid, ride_id, data FROM rides").fetchall():
                    text = db.unpack(r["data"])
                    packed = db.pack(text)
                    assert db.unpack(packed) == text
                    b = brief(r["ride_id"], Ride.from_json(text))
                    self.db.execute("UPDATE rides SET data = ?, brief = ? WHERE rowid = ?",
                                    (packed, json.dumps(b), r["rowid"]))
                    n["rides"] += 1
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            self.db.execute("VACUUM")   # give the freed space back to the disk
        return n

    def visible_rides(self, user_id: int) -> list[Ride]:
        with self.lock:
            rows = self.db.execute("SELECT data FROM rides WHERE user_id = ? ORDER BY start_t",
                                   (user_id,)).fetchall()
        rides = [Ride.from_json(db.unpack(r["data"])) for r in rows]
        hide = hidden_reasons(rides)
        return [r for i, r in enumerate(rides) if i not in hide]

    def you(self, user_id: int) -> dict:
        """Tallies, streaks, personal bests, repeated routes and climbs, the latest rides' notes (from
        what backend/insights.py keeps stored), and the rider's power."""
        out = self.insights.you(user_id)
        out["power"] = self.power(user_id)
        out["headline"] = self.headline(user_id)
        return out

    def headline(self, user_id: int) -> dict:
        """The four headline numbers (rideengine/analysis/headline.py) with the active goal's targets, kept
        with the goal from the first time each number has a value, so progress has a fixed starting point."""
        from rideengine.analysis import headline as hl
        c = self._goal_context(user_id)
        row = self._active_goal_row(user_id)
        goal = json.loads(row["data"]) if row else None
        four = hl.four(c["feats"], c["today"], goal, self.me(user_id).get("ftp"))
        if row and four["targets_changed"]:
            with self.lock:
                self.db.execute("UPDATE goals SET data = ? WHERE goal_id = ?",
                                (json.dumps({**goal, "targets": four["targets"]}), row["goal_id"]))
        return {"metrics": four["metrics"], "next": four["next"],
                "goal": ({"id": row["goal_id"], "title": goal.get("title"), "aspiration": goal.get("aspiration"),
                          "words": goal.get("words"), "ready_by": goal.get("ready_by")} if row else None)}

    def _active_goal_row(self, user_id: int):
        with self.lock:
            return self.db.execute("SELECT goal_id, data, created_at FROM goals WHERE user_id = ? AND active = 1 "
                                   "ORDER BY goal_id DESC LIMIT 1", (user_id,)).fetchone()

    POWER_DAYS = 120  # bests and the FTP estimate come from this recent a window (as the plan's do)

    def power(self, user_id: int) -> Optional[dict]:
        """FTP (the rider's own, or estimated from the best 20 minutes), best 20 minutes and best minute
        over the last POWER_DAYS, and the latest ride with measured power. None before any power."""
        from rideengine.analysis import features as feat_mod
        from rideengine.analysis import goals as g
        from rideengine.analysis import plan as p
        tz = self.insights.tz(user_id)
        with self.lock:
            feats = self.insights._features(user_id)
        visible = feat_mod.visible_ids(feats)
        with_power = [f for f in feats if f["ride_id"] in visible and f.get("power_curve")]
        if not with_power:
            return None
        today = datetime.now(tz).astimezone(tz).date()
        best = g.best_power_curve(with_power, today - timedelta(days=self.POWER_DAYS))
        latest = max(with_power, key=lambda f: f["start"])
        return {"ftp": p.ftp_estimate(self.me(user_id).get("ftp"), best),
                "best_1200s": best.get("1200"), "best_60s": best.get("60"), "days": self.POWER_DAYS,
                "latest": {"ride_id": latest["ride_id"], "start": latest["start"], "avg_power": latest.get("power")}}

    def notes(self, user_id: int, ride_id: str) -> list[dict]:
        """What's notable about one ride, compared with the rides before it."""
        return self.insights.notes(user_id).get(ride_id, [])

    # --- the rider: name, avatar ------------------------------------------------------------------
    def me(self, user_id: int) -> dict:
        from rideengine.card.avatar import clean
        with self.lock:
            row = self.db.execute("SELECT id, tz, display_name, avatar, ftp, brief_at, zone2 FROM users WHERE id = ?",
                                  (user_id,)).fetchone()
        return {"id": row["id"], "tz": row["tz"], "name": row["display_name"] or "Rider",
                "avatar": clean(json.loads(row["avatar"])) if row["avatar"] else None, "ftp": row["ftp"],
                "brief_at": row["brief_at"] or "%02d:%02d" % self.BRIEF_AT, "zone2": row["zone2"],
                "ai": self.coach.allowed(user_id)}   # personal-use AI on: the coach you can ask is there

    def update_me(self, user_id: int, body: dict) -> dict:
        """{"tz": ..., "name": ..., "avatar": {...}, "brief_at": "06:00", "zone2": "126-138" or null}: any of them.
        The avatar is cleaned to known parts; the brief's time is from 04:00 to 12:00; null zone2 is worked out."""
        from rideengine.analysis import zone2
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
            if "brief_at" in body:
                m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(body["brief_at"] or ""))
                if not m or not (4 * 60 <= int(m[1]) * 60 + int(m[2]) <= 12 * 60) or int(m[2]) >= 60:
                    raise ValueError("The morning brief's time must be between 04:00 and 12:00")
                self.db.execute("UPDATE users SET brief_at = ? WHERE id = ?",
                                ("%02d:%02d" % (int(m[1]), int(m[2])), user_id))
            if "zone2" in body:
                own = zone2.parse_own(body["zone2"]) if body["zone2"] else None
                if body["zone2"] and own is None:
                    raise ValueError("Zone 2 is two heart rates, like 126-138")
                self.db.execute("UPDATE users SET zone2 = ? WHERE id = ?",
                                ("%d-%d" % tuple(own) if own else None, user_id))
        return self.me(user_id)

    # --- training plan (rideengine/analysis/plan.py) -----------------------------------------------
    def _plan_context(self, user_id: int) -> dict:
        from rideengine.analysis import features as feat_mod
        from rideengine.analysis import goals as g
        from rideengine.analysis import plan as p
        from rideengine.analysis import zone2
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
        ftp = p.ftp_estimate(me.get("ftp"), power)
        # Zone 2 (zone2.py): the rider's own range, else 60-70% of heart rate reserve. It's the zone 2 every
        # session's heart-rate target uses too.
        z2 = zone2.zone2_range(max_hr, rest, zone2.parse_own(me.get("zone2")))
        hrz = p.hr_zones(max_hr, rest)
        if hrz is not None and z2:
            hrz["Z2"] = z2["bpm"]
        return {"user_id": user_id, "tz": tz, "today": today, "feats": vfeats, "starts": starts,
                "ftp": ftp, "aim": self._aim(user_id, ftp, tz), "hr_zones": hrz, "zone2": z2,
                "max_hr": max_hr, "resting_hr": rest}

    AIM_STEP = 0.05          # a hard session that felt easy raises the targets this much ...
    AIM_MAX = 0.15           # ... up to this far above the estimate

    def _aim(self, user_id: int, ftp: dict, tz, skip: Optional[str] = None, before: Optional[str] = None) -> dict:
        """The watts the session targets start from: what the rider could hold for about an hour (`ftp`: their
        own number or the estimate), adjusted by how the last hard session felt. Felt easy: 5% above what that
        session's targets started from; good or hard: kept there; wrecked: 5% below. Never below the
        estimate, never more than 15% above it. Worked out from the stored taps, so changing a tap undoes it."""
        est = ftp.get("watts")
        with self.lock:
            rows = self.db.execute("SELECT ride_id, feel, ftp_w, under FROM ride_feel WHERE user_id = ? AND ftp_w IS NOT NULL",
                                   (user_id,)).fetchall()
        rows = sorted((r for r in rows if r["ride_id"] != skip and (before is None or int(r["ride_id"]) < int(before))),
                      key=lambda r: int(r["ride_id"]))
        if not est or not rows:
            return {**ftp, "base": est}
        r = rows[-1]
        # Felt easy but ridden under its targets: they stay until they're ridden (26 Nov 2026).
        step = {"easy": 1 + self.AIM_STEP, "wrecked": 1 - self.AIM_STEP}.get(r["feel"], 1.0)
        if r["feel"] == "easy" and r["under"]:
            step = 1.0
        floor = r["ftp_w"] * step
        aim = round(max(est, min(floor, est * (1 + self.AIM_MAX))))
        if aim == est:
            return {**ftp, "base": est}
        day = datetime.fromtimestamp(int(r["ride_id"]), tz).strftime("%A")
        why = (f"{day}'s hard session felt easy, though under its targets, so they stay" if r["feel"] == "easy" and r["under"]
               else f"{day}'s hard session felt easy" if r["feel"] == "easy" else
               f"{day}'s hard session felt about right at these watts")
        raised = f"raised from {est} W because {why}"
        return {"watts": aim, "base": est, "raised": raised,
                "source": ftp["source"] if ftp.get("source") == "yours" else f"{ftp['source']}, {raised}",
                "because": {"ride_id": r["ride_id"], "feel": r["feel"]}}

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
        # Sessions grow from the evidence from here on (sessions already shown keep their size).
        new["grow_from"] = (old.get("grow_from") if same_goal and old.get("grow_from") else c["today"].isoformat())
        if same_goal:   # what the Sunday reviews changed stays
            for k in ("alternatives", "swaps", "eased"):
                if old.get(k):
                    new[k] = old[k]
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
        with self.lock:
            done = {r["session_id"] for r in self.db.execute("SELECT session_id FROM plan_done WHERE user_id = ?", (user_id,))}
            moved = {r["ride_id"]: r["session_id"] for r in self.db.execute(
                "SELECT ride_id, session_id FROM plan_matches WHERE user_id = ?", (user_id,))}
            feels = {r["ride_id"]: (r["feel"], bool(r["hurts"])) for r in self.db.execute(
                "SELECT ride_id, feel, hurts FROM ride_feel WHERE user_id = ?", (user_id,))}
        today = c["today"]
        if not plan.get("grow_from"):
            # A plan from before growth by evidence (23 Nov 2026): sessions up to today were shown, and may have
            # been ridden, at their planned size; they keep it.
            plan["grow_from"] = (today + timedelta(days=1)).isoformat()
            with self.lock:
                self.db.execute("UPDATE plans SET data = ? WHERE plan_id = ?",
                                (json.dumps({k: v for k, v in plan.items() if k != "plan_id"}), plan["plan_id"]))
        weeks = []
        # Growth by evidence (docs/train-method.md): each job's sessions take their size from how that job went
        # in the weeks before, never from later ones, so a week already ridden keeps the sessions it was shown.
        score: dict[str, int] = {}
        last: dict[str, dict] = {}
        for w in plan["weeks"]:
            # Plans made before 21 Nov 2026 named winter sessions for the trainer; indoors or out is the rider's
            # choice.
            # Endurance became Zone 2 on 24 Nov 2026.
            names = {"Zwift group ride": "Group ride", "Long indoor ride": "Long ride", "Endurance": "Zone 2"}
            why = {"Easy aerobic miles that build the base.": p.workout("endurance", 0, 60, True)["purpose"],
                   "Time in the saddle at a pace you could chat at.": p.workout("long", 0, 120, True)["purpose"]}
            w = {**w, "sessions": [{**s, "title": names.get(s["title"], s["title"]),
                                    "purpose": why.get(s.get("purpose"), s.get("purpose")),
                                    "steps": p.renamed(s.get("steps") or [])} for s in w["sessions"]]}
            w = self._reviewed(plan, w)
            w = {**w, "sessions": [self._grow(s, w["phase"], score, last) if s["date"] >= plan["grow_from"] else s
                                   for s in w["sessions"]]}
            counted = self._count_week(c, w, moved)
            self._learn(w, counted, done, feels, today, score, last)
            replan = None
            ws = date.fromisoformat(w["week_start"])
            if ws <= today < ws + timedelta(days=7):
                w, replan = self._replan(user_id, c, w, counted, done)
            sessions = []
            for s in w["sessions"]:
                t = p.targets(s, c["aim"]["watts"], c["hr_zones"]) if s["steps"] else dict(s)
                if t["kind"] == "group" and "Zwift" not in t["purpose"]:
                    t["purpose"] = t["purpose"].rstrip(".") + ": a club ride outside, or a Zwift group ride."
                # The day it's on (24 Nov 2026): the day it was ridden, else the day this week's fresh layout puts
                # it on, else the plan's day. "date" is only the plan's first sketch.
                # Partly done and not laid out again (its little left joined a ride or was let go): the day of
                # its last ride, not the sketch's day (26 Nov 2026).
                x = counted["counted"].get(s["id"])
                part = counted["progress"].get(s["id"])
                ridden = {r["ride_id"]: r["date"] for r in counted["rides"]}
                part_day = max((ridden[r] for r in (part or {}).get("rides", []) if r in ridden), default=None)
                t["on"] = (x["date"] if x else (replan or {}).get("schedule", {}).get(s["id"]) or part_day or s["date"])
                t["status"] = self._session_status({**s, "date": t["on"]}, counted, done, w, today)
                t["job"] = p.JOB_OF.get(s["kind"])
                alt = (plan.get("alternatives") or {}).get(t["job"] or "")
                if alt and w["week_start"] >= alt["from"] and not s.get("off_bike"):
                    t["another_way"] = alt["text"]
                if s["id"] in counted["counted"]:
                    t["counted"] = counted["counted"][s["id"]]
                elif s["id"] in counted["progress"]:
                    t["progress"] = counted["progress"][s["id"]]
                if replan:
                    f = next((x for x in replan["folded"] if x["id"] == s["id"]), None)
                    if f:
                        t["folded_into"] = {"session_id": f["into"], "date": f["date"], "line": f["line"]}
                    added = [x["line"] for x in replan["folded"] if x["into"] == s["id"]]
                    if added:
                        t["added"] = added
                    gone = next((x for x in replan["dropped"] if x["id"] == s["id"]), None)
                    if gone:
                        t["dropped"] = gone["line"]
                t["summary"] = p.describe(t) if s["steps"] else s["purpose"]
                if not s.get("off_bike"):
                    main = next((x["steps"][0].get("target", {}).get("watts") for x in t.get("steps") or []
                                 if x.get("steps") and not (x.get("set") or "").startswith("Added")), None)
                    t["shape"] = p.shape(t, main)
                sessions.append(t)
            weeks.append({**w, "sessions": sessions, "rides": counted["rides"], "extra": counted["extra"],
                          "replan": replan,
                          "done": sum(1 for s in sessions if s["status"] == "done"), "total": len(sessions)})
        this_week = next((w for w in weeks if w["week_start"] <= today.isoformat() <
                          (date.fromisoformat(w["week_start"]) + timedelta(days=7)).isoformat()), None)
        return {"plan_id": plan["plan_id"], "goal_id": plan.get("goal_id"), "start": plan["start"],
                "ready_by": plan["ready_by"], "days": plan["days"], "times": plan["times"],
                "weekly_hours": plan["weekly_hours"], "ftp": c["aim"], "hr_zones": c["hr_zones"],
                "max_hr": c["max_hr"], "resting_hr": c["resting_hr"],
                "zones": {z: {"name": v["name"], "pct_ftp": [round(v["ftp"][0] * 100), round(v["ftp"][1] * 100)]}
                          for z, v in p.ZONES.items()},
                "this_week": this_week["index"] if this_week else None, "weeks": weeks}

    def _replan(self, user_id: int, c: dict, w: dict, counted: dict, done: set) -> tuple[dict, dict]:
        """This week laid out again from what's left (docs/train-method.md, after every ride): the open sessions
        on the days left within the limits, small leftovers added to a planned ride, and what doesn't fit let go.
        The leftovers become a set in their host session, so its page, the Watch and the spoken cues have them."""
        from rideengine.analysis import plan as p
        from rideengine.analysis import today as td
        light = [{**s, "status": self._session_status(s, counted, done, w, c["today"]),
                  "progress": counted["progress"].get(s["id"])} for s in w["sessions"]]
        readiness = (self.recovery(user_id).get("readiness") or {}).get("status", "unknown")
        t = td.plan_today(light, self._recent_kinds(c), c["today"], date.fromisoformat(w["week_start"]), readiness)
        if t["folded"]:
            by_id = {s["id"]: s for s in w["sessions"]}
            for f in t["folded"]:
                block = p.leftover(f["job"], f["left_min"])
                if block and f["into"] in by_id:
                    by_id[f["into"]] = p.with_leftover(by_id[f["into"]], block)
            w = {**w, "sessions": [by_id[s["id"]] for s in w["sessions"]]}
        return w, t

    @staticmethod
    def _reviewed(plan: dict, w: dict) -> dict:
        """The week as the Sunday reviews changed it (rideengine/analysis/review.py): a session swapped for the
        job a stalled goal number needs, or the whole week made easier."""
        from rideengine.analysis import plan as p
        swaps = plan.get("swaps") or {}
        sessions = []
        for s in w["sessions"]:
            if s["id"] in swaps and not s.get("off_bike"):
                new = p.workout(swaps[s["id"]], 0.0, max(30, round((s.get("seconds") or 0) / 60)), s.get("indoor", True))
                s = {**s, **new, "swapped_from": s["title"]}
            sessions.append(s)
        if w["week_start"] in (plan.get("eased") or []):
            easier = []
            for s in sessions:
                if not s.get("off_bike"):
                    kind = "long" if s["kind"] == "long" else "endurance" if (s.get("seconds") or 0) >= 45 * 60 else "easy"
                    mins = max(30, round((s.get("seconds") or 0) / 60 * 0.7 / 5) * 5)
                    s = {**s, **p.workout(kind, 0.0, mins, s.get("indoor", True)), "eased_from": s["title"]}
                easier.append(s)
            return {**w, "sessions": easier, "phase": "recovery", "eased": True}
        return {**w, "sessions": sessions}

    def train_review(self, user_id: int, week_start: Optional[str] = None) -> Optional[dict]:
        """The Sunday review (docs/train-method.md "Week to week"): the week in a few lines, and next week's
        proposed changes, each checked against the limits. Small ones apply on their own; big ones wait for the
        rider. The AI coach, when on, says it in its own words (it can't add or drop a change)."""
        from rideengine.analysis import headline as hl
        from rideengine.analysis import review as rv
        view = self.plan_view(user_id)
        if view is None:
            return None
        c = self._plan_context(user_id)
        tz = c["tz"]
        now = datetime.now(tz)
        weeks = view["weeks"]
        if week_start is None:
            this = self._this_week(view, c["today"])
            late_sunday = c["today"].weekday() == 6 and now.hour >= self.REVIEW_AT[0]
            end = c["today"] + timedelta(days=1) if late_sunday else c["today"] - timedelta(days=c["today"].weekday())
            past = [w for w in weeks if date.fromisoformat(w["week_start"]) + timedelta(days=7) <= end]
            week = past[-1] if past else None
            if late_sunday and this:
                week = this
        else:
            week = next((w for w in weeks if w["week_start"] == week_start), None)
        if week is None:
            return None
        i = weeks.index(week)
        history, next_week = weeks[:i], (weeks[i + 1] if i + 1 < len(weeks) else None)
        ws = date.fromisoformat(week["week_start"])
        end_ts = datetime.combine(ws + timedelta(days=7), datetime.min.time(), tz).timestamp()
        then_ts = end_ts - 28 * 86400
        markers = []
        row = self._active_goal_row(user_id)
        if row is not None:
            goal = json.loads(row["data"])
            own = self.me(user_id).get("ftp")
            now_m = hl.four([f for f in c["feats"] if f["start"] < end_ts], ws + timedelta(days=6), goal, own)
            then_m = hl.four([f for f in c["feats"] if f["start"] < then_ts], ws - timedelta(days=22), goal, own)
            before = {m["id"]: m["current"] for m in then_m["metrics"]}
            markers = [{"id": m["id"], "name": m["label"], "unit": m["unit"], "current": m["current"],
                        "then": before.get(m["id"]), "target": m.get("target")}
                       for m in now_m["metrics"] if m.get("focus")]
        feels = [f for f in (self.ride_feel(user_id, r["ride_id"]) for r in week.get("rides", [])) if f]
        r = rv.review(week, history, markers, feels, next_week, view["weekly_hours"])
        with self.lock:
            stored = {x["id"]: x for x in self.db.execute(
                "SELECT id, status, data FROM plan_proposals WHERE user_id = ? AND id LIKE ?",
                (user_id, week["week_start"] + ":%"))}
        proposals = []
        for prop in r["proposals"]:
            why_not = rv.check(prop, next_week, view["weekly_hours"])
            st = stored[prop["id"]]["status"] if prop["id"] in stored else None
            if why_not and st is None:
                continue                              # outside the limits: never offered
            if prop["size"] == "small" and st is None:
                self._apply_proposal(user_id, prop, next_week)
                st = self._set_proposal(user_id, prop, "applied")
            proposals.append({**prop, "status": st or "open"})
        # Changes already decided stay on the review, even once the rule that made them no longer fires (an easier
        # week accepted makes next week easy, so "tired" no longer proposes it).
        shown = {x["id"] for x in proposals}
        for pid, row in stored.items():
            if pid not in shown and row["data"]:
                proposals.append({**json.loads(row["data"]), "status": row["status"]})
        on_bike = [s for s in week["sessions"] if not s.get("off_bike")]
        out = {"week_start": week["week_start"], "index": week["index"], "lines": r["lines"],
               "proposals": proposals, "done": sum(1 for s in on_bike if s["status"] == "done"), "total": len(on_bike),
               "story": None}
        if self.coach.allowed(user_id):
            facts = {"week": r["lines"], "goal": [{k: m[k] for k in ("name", "unit", "current", "then", "target")}
                                                  for m in markers],
                     "sessions": [{"title": s["title"], "job": s.get("job"), "status": s["status"]}
                                  for s in week["sessions"]],
                     "how_rides_felt": [f["feel"] for f in feels],
                     "proposals": [{"id": x["id"], "change": x["change"], "reason": x["reason"], "size": x["size"]}
                                   for x in proposals]}
            out["story"] = self.coach.week_review(user_id, week["week_start"], facts)
        return out

    def _review_card(self, user_id: int, c: dict) -> Optional[dict]:
        """On Today from Sunday evening to Tuesday (or while a change waits for the rider): the week in review."""
        now = datetime.now(c["tz"])
        wd = c["today"].weekday()
        if not (wd in (0, 1) or (wd == 6 and now.hour >= self.REVIEW_AT[0])):
            return None
        r = self.train_review(user_id)
        if r is None:
            return None
        ask = sum(1 for p in r["proposals"] if p["status"] == "open")
        return {"week_start": r["week_start"], "index": r["index"], "line": r["lines"][0] if r["lines"] else None,
                "open": ask}

    def _set_proposal(self, user_id: int, prop: dict, status: str) -> str:
        data = json.dumps({k: v for k, v in prop.items() if k != "status"})
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO plan_proposals (user_id, id, status, at, data) VALUES (?, ?, ?, ?, ?)",
                            (user_id, prop["id"], status, db.now(), data))
        return status

    def _apply_proposal(self, user_id: int, prop: dict, next_week: Optional[dict]) -> None:
        """Make the change in the stored plan. Hours rebuild the plan from next week (keeping what's past)."""
        a = prop["apply"]
        if a["type"] == "hours":
            self.make_plan(user_id, weekly_hours=a["weekly_hours"])
            return
        plan = self._active_plan(user_id)
        if plan is None:
            return
        if a["type"] == "another_way":
            plan.setdefault("alternatives", {})[a["job"]] = {"text": a["text"],
                                                             "from": next_week["week_start"] if next_week else ""}
        elif a["type"] == "swap":
            plan.setdefault("swaps", {})[a["session_id"]] = a["to_kind"]
        elif a["type"] == "ease":
            plan.setdefault("eased", []).append(a["week_start"])
        with self.lock:
            self.db.execute("UPDATE plans SET data = ? WHERE plan_id = ?",
                            (json.dumps({k: v for k, v in plan.items() if k != "plan_id"}), plan["plan_id"]))

    def decide_proposal(self, user_id: int, pid: str, accept: bool) -> Optional[dict]:
        """The rider's OK (or not now) on a big change. Checked again against the limits before it applies."""
        from rideengine.analysis import review as rv
        r = self.train_review(user_id, pid.split(":")[0])
        prop = next((x for x in (r or {}).get("proposals", []) if x["id"] == pid), None)
        if prop is None or prop["status"] != "open":
            return None
        if accept:
            view = self.plan_view(user_id)
            i = next((k for k, w in enumerate(view["weeks"]) if w["week_start"] == r["week_start"]), None)
            nxt = view["weeks"][i + 1] if i is not None and i + 1 < len(view["weeks"]) else None
            if rv.check(prop, nxt, view["weekly_hours"]):
                return None
            self._apply_proposal(user_id, prop, nxt)
        self._set_proposal(user_id, prop, "accepted" if accept else "declined")
        return self.train_review(user_id, r["week_start"])

    @staticmethod
    def _grow(s: dict, phase: str, score: dict, last: dict) -> dict:
        """The session at the size the evidence so far says, with a line when it changed from the last one."""
        from rideengine.analysis import plan as p
        from rideengine.analysis import today as td
        job = p.JOB_OF.get(s["kind"])
        g = p.grown(s, score.get(job, 0), phase)
        if g is None:
            return s
        prev = last.get(s["kind"])
        now = p.job_minutes(g).get(job)
        before = last.get("shown:" + s["kind"])          # the session of this kind just before, done or not
        last["shown:" + s["kind"]] = now
        if before is not None and now == before:
            return g                                      # same as the one before it: nothing new to say
        if prev and now and prev["minutes"] and abs(now - prev["minutes"]) >= 0.5:
            what = "of hard efforts" if job in ("punch", "top_end") else "of steady work"
            was = date.fromisoformat(prev["date"])
            day = td.WEEKDAY[was.weekday()]
            # Said from the session's own week: "Monday's", "last Wednesday's", "the 4 Nov".
            monday = date.fromisoformat(s["date"]) - timedelta(days=date.fromisoformat(s["date"]).weekday())
            title = prev["title"].lower()
            that = (f"the {title} on {was.day} {was.strftime('%b')}" if was < monday - timedelta(days=7) else
                    f"last {day}'s {title}" if was < monday else f"{day}'s {title}")
            if now > prev["minutes"]:
                felt = {"easy": " and felt easy", "good": " and felt good"}.get(prev["feel"], "")
                g["grew"] = (f"A step up: {train_mins(now)} {what}, from {train_mins(prev['minutes'])}, because "
                             f"you did {that} in full{felt}.")
            elif prev["why"] in ("hurt", "felt wrecked"):
                g["grew"] = (f"A step back: {train_mins(now)} {what}, from {train_mins(prev['minutes'])}, because "
                             f"{that} {prev['why']}.")
        return g

    @staticmethod
    def _learn(w: dict, counted: dict, done: set, feels: dict, today: date, score: dict, last: dict) -> None:
        """What the week's hard sessions say about each job: done in full and felt fine steps it up, hard or
        partly done holds it, wrecked or something hurting steps it back (plan.grow_score)."""
        from rideengine.analysis import plan as p
        over = date.fromisoformat(w["week_start"]) + timedelta(days=7) <= today
        for s in w["sessions"]:
            if s["kind"] not in p.GROWS:
                continue
            job = p.JOB_OF[s["kind"]]
            x = counted["counted"].get(s["id"])
            if x:
                feel, hurts = feels.get(x["ride_id"], (None, False))
                outcome = "wrecked" if hurts or feel == "wrecked" else "hard" if feel == "hard" else "done"
                why = "hurt" if hurts else "felt wrecked" if feel == "wrecked" else "felt hard"
                last[s["kind"]] = {"minutes": p.job_minutes(s).get(job), "date": x["date"], "feel": feel,
                                   "title": s["title"], "why": why}
            elif over:
                outcome = "part" if s["id"] in counted["progress"] else "missed"
            else:
                continue
            score[job] = p.grow_score(score.get(job, 0), outcome)

    def _count_week(self, c: dict, week: dict, moved: dict) -> dict:
        """Which of the week's rides counts as which session, by what each ride contained, whatever the day
        (rideengine/analysis/train.py). Rides moved by hand (`moved`: ride_id -> session_id or None) stay put."""
        from rideengine.analysis import train
        start = date.fromisoformat(week["week_start"])
        end = start + timedelta(days=7)
        ftp = c["ftp"]["watts"]
        rides = []
        for f in c["feats"]:
            d = datetime.fromtimestamp(f["start"], c["tz"]).astimezone(c["tz"]).date()
            if not (start <= d < end) or d > c["today"]:
                continue
            if f.get("work"):
                cls = train.classify(f["work"], ftp, c["max_hr"], c["resting_hr"])
            else:   # features still being refreshed: judge on time alone
                minutes = round((f.get("moving_s") or 0) / 60)
                cls = {"kind": "mixed" if minutes >= train.MIN_MINUTES else None, "confidence": 0.3,
                       "reason": f"{minutes} minutes of riding.", "facts": {"minutes": minutes}}
            rides.append({"ride_id": f["ride_id"], "start": f["start"], "date": d.isoformat(),
                          "minutes": cls["facts"].get("minutes") or round((f.get("moving_s") or 0) / 60),
                          "indoor": f.get("indoor"), "class": cls, "jobs": Backend._jobs(c, f, week),
                          "kind_title": train.TITLES.get(cls["kind"]) if cls["kind"] else None})
        # By jobs (docs/train-method.md): each ride's jobs fill the week's sessions of the same job, whatever the
        # workout and the day; partly done leaves the rest open.
        rides.sort(key=lambda r: r["start"])
        m = train.count_jobs(week["sessions"], rides, {r: s for r, s in moved.items()})
        by_ride = {r["ride_id"]: r for r in rides}
        for r in rides:
            r["counts_for"] = m["ride_jobs"].get(r["ride_id"], [])
        counted = {sid: {**x, "fit": None, "reason": x["reason"] or by_ride[x["ride_id"]]["class"].get("reason"),
                         "date": by_ride[x["ride_id"]]["date"], "start": by_ride[x["ride_id"]]["start"],
                         "kind": by_ride[x["ride_id"]]["class"]["kind"],
                         "kind_title": by_ride[x["ride_id"]]["kind_title"]}
                   for sid, x in m["counted"].items()}
        return {"counted": counted, "progress": m["progress"], "rides": rides,
                "extra": [{"ride_id": r, "kind_title": by_ride[r]["kind_title"],
                           "reason": (by_ride[r]["jobs"] or {}).get("summary") or by_ride[r]["class"]["reason"]}
                          for r in m["extra"]]}

    @staticmethod
    def _job_wants(week: Optional[dict]) -> tuple[dict, Optional[float]]:
        """How much of each job the week's suggested workouts ask (docs/train-method.md), and its long-ride
        minutes: what a ride's jobs are judged against."""
        from rideengine.analysis import plan as p
        want: dict = {}
        long_min = None
        for s in (week or {}).get("sessions", []):
            for job, mins in p.job_minutes(s).items():
                if job == "long":
                    long_min = max(long_min or 0, mins)
                else:
                    want[job] = max(want.get(job, 0), mins)
        return want, long_min

    @staticmethod
    def _jobs(c: dict, f: dict, week: Optional[dict]) -> Optional[dict]:
        """Which jobs the ride did and how much of each (train.jobs_done), against the week's plan."""
        from rideengine.analysis import train
        if not f.get("work"):
            return None
        want, long_min = Backend._job_wants(week)
        minutes = round((f.get("moving_s") or 0) / 60) or None
        j = train.jobs_done(f["work"], c["ftp"]["watts"], c["max_hr"], c["resting_hr"], minutes=minutes,
                            long_min=long_min, want=want)
        return {"summary": j["summary"], "jobs": j["jobs"], "also": j["also"]}

    @staticmethod
    def _session_status(s: dict, counted: dict, done: set, week: dict, today: date) -> str:
        """done (a ride counted as it, or ticked by hand) | today | open (earlier this week, still to do: any
        day of the week counts) | missed (the week is over) | upcoming."""
        if s["id"] in done or s["id"] in counted["counted"]:
            return "done"
        d = date.fromisoformat(s["date"])
        if date.fromisoformat(week["week_start"]) + timedelta(days=7) <= today:
            return "missed"
        if d == today:
            return "today"
        return "open" if d < today else "upcoming"

    def count_ride_as(self, user_id: int, ride_id: str, session_id: Optional[str], automatic: bool = False) -> bool:
        """The rider moves a ride: it counts as `session_id`, or as nothing (None). `automatic` hands it back
        to the engine."""
        with self.lock:
            if self.db.execute("SELECT 1 FROM rides WHERE user_id = ? AND ride_id = ?", (user_id, ride_id)).fetchone() is None:
                return False
        if session_id is not None and self.plan_session(user_id, session_id) is None:
            return False
        with self.lock:
            if automatic:
                self.db.execute("DELETE FROM plan_matches WHERE user_id = ? AND ride_id = ?", (user_id, ride_id))
            else:
                self.db.execute("INSERT OR REPLACE INTO plan_matches (user_id, ride_id, session_id, at) VALUES (?, ?, ?, ?)",
                                (user_id, ride_id, session_id, db.now()))
        return True

    # --- Train (docs/train-tab.md, step 2): today, the week ahead, and a note for each ride --------------
    def _recent_kinds(self, c: dict, days: int = 8) -> list[dict]:
        """Rides of the last `days` days and today, with what kind of training each was."""
        from rideengine.analysis import train
        out = []
        cut = c["today"] - timedelta(days=days)
        for f in c["feats"]:
            d = datetime.fromtimestamp(f["start"], c["tz"]).astimezone(c["tz"]).date()
            if d < cut or d > c["today"]:
                continue
            cls = (train.classify(f["work"], c["ftp"]["watts"], c["max_hr"], c["resting_hr"]) if f.get("work") else
                   {"kind": "mixed" if (f.get("moving_s") or 0) >= train.MIN_MINUTES * 60 else None, "facts": {}})
            felt = self.ride_feel(c.get("user_id", 0), f["ride_id"]) if c.get("user_id") else None
            out.append({"ride_id": f["ride_id"], "date": d, "kind": cls["kind"],
                        "minutes": round((f.get("moving_s") or 0) / 60),
                        "feel": (felt or {}).get("feel"), "hurts": bool((felt or {}).get("hurts"))})
        return out

    def _this_week(self, view: dict, today: date) -> Optional[dict]:
        return next((w for w in view["weeks"] if date.fromisoformat(w["week_start"]) <= today <
                     date.fromisoformat(w["week_start"]) + timedelta(days=7)), None)

    def _goal_markers(self, user_id: int, c: dict) -> Optional[dict]:
        """The active goal, and the numbers it's judged by (the ones it focuses on), in plain words."""
        from rideengine.analysis import headline as hl
        row = self._active_goal_row(user_id)
        if row is None:
            return None
        goal = json.loads(row["data"])
        four = hl.four(c["feats"], c["today"], goal, self.me(user_id).get("ftp"))
        markers = [{"id": m["id"], "name": m["label"], "meaning": m["plain"], "unit": m["unit"],
                    "current": m["current"], "target": m.get("target"),
                    "baseline": (goal.get("targets", {}).get(m["id"]) or {}).get("baseline"),
                    "reached": bool(m["current"] and m.get("target") and m["current"] >= m["target"])}
                   for m in four["metrics"] if m.get("focus")]
        ready = date.fromisoformat(goal["ready_by"]) if goal.get("ready_by") else None
        return {"title": goal.get("title"), "words": goal.get("words"), "ready_by": goal.get("ready_by"),
                "weeks_left": max(0, (ready - c["today"]).days // 7) if ready else None, "markers": markers}

    def train_today(self, user_id: int) -> dict:
        """Today on the Train tab: the coach's opening line, today's session (or rest, or done), why, how it
        should feel, what's next, the goal, and the latest ride's note."""
        from rideengine.analysis import today as td
        view = self.plan_view(user_id)
        if view is None:
            return {"state": "no_plan"}
        c = self._plan_context(user_id)
        week = self._this_week(view, c["today"])
        recent = self._recent_kinds(c)
        readiness = (self.recovery(user_id).get("readiness") or {}).get("status", "unknown")
        if week is None:
            ahead = [w for w in view["weeks"] if date.fromisoformat(w["week_start"]) > c["today"]]
            if not ahead:
                return {"state": "no_plan", "goal": self._goal_markers(user_id, c)}
            first = date.fromisoformat(ahead[0]["week_start"])
            nxt = min(ahead[0]["sessions"], key=lambda s: s["date"]) if ahead[0]["sessions"] else None
            when = "tomorrow" if first == c["today"] + timedelta(days=1) else f"on {td.WEEKDAY[first.weekday()]}"
            return {"date": c["today"].isoformat(), "week": 0, "weeks": len(view["weeks"]), "phase": None,
                    "state": "rest", "greeting": td.greeting(recent, c["today"], readiness, "rest"),
                    "session": None, "why": f"Your plan starts {when}. Until then, ride as you like.",
                    "feel": None, "then": (f"{td.WEEKDAY[date.fromisoformat(nxt['date']).weekday()]}: {td.short(nxt)}."
                                           if nxt else ""),
                    "next": [self._next_item(nxt, c["today"])] if nxt else [],
                    "readiness": readiness, "goal": self._goal_markers(user_id, c), "latest": None}
        t = week.get("replan") or td.plan_today(week["sessions"], recent, c["today"],
                                                date.fromisoformat(week["week_start"]), readiness)
        changes = self._plan_changes(user_id, c, week, t)
        session = next((s for s in week["sessions"] if s["id"] == t["session_id"]), None)
        from rideengine.analysis import voice
        today_learn = voice.learn(session.get("job") if session else "rest", c["today"].toordinal())
        feel = _feel(session) if session else None
        latest = None
        rides_back = sorted((r for r in recent if r["date"] >= c["today"] - timedelta(days=2)),
                            key=lambda r: r["date"], reverse=True)
        if rides_back:
            latest = self.train_ride_note(user_id, rides_back[0]["ride_id"], _today=t)
        # The sessions What's Next names (tomorrow's and the one after it), so each can open its own page.
        by_id = {s["id"]: s for s in week["sessions"]}
        upcoming = [by_id[sid] for sid, d in sorted(t["schedule"].items(), key=lambda x: x[1])
                    if d > c["today"].isoformat() and sid in by_id and not by_id[sid].get("off_bike")]
        tomorrow = (c["today"] + timedelta(days=1)).isoformat()
        upcoming = upcoming[:2] if upcoming and t["schedule"].get(upcoming[0]["id"]) == tomorrow else upcoming[:1]
        if t["then"].startswith("A new week starts tomorrow"):      # name the new week's first session
            nxt = next((w for w in view["weeks"] if date.fromisoformat(w["week_start"]) > c["today"]), None)
            first = min((s for s in nxt["sessions"] if not s["off_bike"]), key=lambda s: s["date"], default=None) if nxt else None
            if first:
                t["then"] = f"A new week starts tomorrow, with {td.short(first)}."
                upcoming.append(first)
        # The week, day by day, for the strip on Today: ridden, a session expected, or rest.
        ws = date.fromisoformat(week["week_start"])
        titles = {s["id"]: s["title"] for s in week["sessions"]}
        rode = {}
        for r in week.get("rides", []):
            if (r.get("minutes") or 0) >= 15:
                rode.setdefault(r["date"], r.get("kind_title") or "Ride")
        expected = {}
        for sid, d in t["schedule"].items():
            expected.setdefault(d, titles.get(sid, ""))
        days = []
        for k in range(7):
            d = (ws + timedelta(days=k)).isoformat()
            state = "rode" if d in rode else "session" if d in expected else "rest"
            days.append({"date": d, "state": state, "title": rode.get(d) or expected.get(d),
                         "today": d == c["today"].isoformat()})
        return {"date": c["today"].isoformat(), "week": week["index"], "weeks": len(view["weeks"]),
                "days": days, "done": week["done"], "total": week["total"],
                "phase": week["phase"], "state": t["state"], "greeting": td.greeting(recent, c["today"], readiness, t["state"]),
                "session": session, "why": t["why"], "feel": feel, "where": td.WHERE.get(session["kind"]) if session else None,
                "then": t["then"], "next": [self._next_item(x, c["today"], t["schedule"].get(x["id"])) for x in upcoming],
                "next_note": next((f"{x['title']} is still open this week." for x in week["sessions"]
                                   if x.get("off_bike") and x.get("status") != "done"), None),
                "folded": t.get("folded", []), "dropped": t.get("dropped", []), "changes": changes,
                "learn": today_learn, "review": self._review_card(user_id, c),
                # This morning's brief in the coach's words, as the notification had it (no new call here); the
                # greeting stays when there's none, or once today's ride is in.
                "brief": (self.coach.saved(user_id, f"brief:{c['today'].isoformat()}")
                          if t["state"] in ("session", "rest") and "recovery" not in (t.get("why") or "").lower()
                          else None),
                "readiness": readiness, "goal": self._goal_markers(user_id, c), "latest": latest}

    @staticmethod
    def _left_this_week(c: dict, week: Optional[dict]) -> Optional[str]:
        """What's left of this week's jobs, on the days they're now expected: "Still to come this week: steady
        work on Wednesday, easy riding on Thursday and punch on Friday." Only for the week we're in."""
        from rideengine.analysis import today as td
        if not week or not week.get("replan"):
            return None
        when = week["replan"].get("schedule", {})
        words = {"punch": "punch", "top_end": "top-end work", "hold": "steady work", "long": "the long ride",
                 "easy": "easy riding"}
        left = sorted(((when[s["id"]], s) for s in week["sessions"] if s["id"] in when and not s.get("off_bike")
                       and s["status"] != "done" and not s.get("dropped")), key=lambda x: x[0])
        if not left:
            return "That's every job this week done." if all(
                s["status"] == "done" or s.get("off_bike") or s.get("dropped") for s in week["sessions"]) else None
        parts = []
        for d, s in left:
            day = td._day_name(date.fromisoformat(d), c["today"])
            day = day.lower() if day in ("Today", "Tomorrow") else f"on {day}"
            parts.append(f"{words.get(s.get('job'), s['title'].lower())} {day}")
        text = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        return f"Still to come this week: {text}."

    def _plan_changes(self, user_id: int, c: dict, week: dict, t: dict) -> list[dict]:
        """When this week's fresh layout differs from the last one the rider was shown, say so once, plainly
        (docs/train-method.md "When the plan changes"): "Your week now: sweet spot Wednesday, group ride Friday.",
        any leftover added to a ride or session let go, and the reason in a few words. Only the last layout is kept,
        to compare with; nothing about where sessions were. Returns this week's notes the rider hasn't seen."""
        from rideengine.analysis import today as td
        ws = week["week_start"]
        now = {"schedule": t.get("schedule", {}), "folded": {f["id"]: f["into"] for f in t.get("folded", [])},
               "dropped": [d["id"] for d in t.get("dropped", [])]}
        by_id = {s["id"]: s for s in week["sessions"]}
        with self.lock:
            row = self.db.execute("SELECT data, at FROM plan_snapshots WHERE user_id = ? AND week_start = ?",
                                  (user_id, ws)).fetchone()
        before = json.loads(row["data"]) if row else None
        stamp = db.now()
        if before != now:
            with self.lock:
                self.db.execute("INSERT OR REPLACE INTO plan_snapshots (user_id, week_start, data, at) VALUES (?, ?, ?, ?)",
                                (user_id, ws, json.dumps(now), stamp))
        if before is not None and before != now:
            parts = []
            was = before.get("schedule", {})
            # A ride that did a session just takes it off the layout: that's not news. A session on another day is.
            if any(sid in was and was[sid] != d for sid, d in now["schedule"].items()):
                days = sorted(now["schedule"].items(), key=lambda kv: kv[1])
                # Weekday names, not "tomorrow": the line is kept, and must stay true when read later.
                parts.append("Your week now: " + ", ".join(
                    f"{by_id[sid]['title'].lower()} {td.WEEKDAY[date.fromisoformat(d).weekday()]}"
                    for sid, d in days if sid in by_id) + ".")
            parts += [f["line"] for f in t.get("folded", []) if before.get("folded", {}).get(f["id"]) != f["into"]]
            gone = [d for d in t.get("dropped", []) if d["id"] not in before.get("dropped", [])]
            room = [d for d in gone if d["line"].startswith("No room for")]
            parts += [d["line"] for d in gone if d not in room]
            if len(room) > 1:
                names = [d["title"].lower() for d in room]
                parts.append(f"No room for {', '.join(names[:-1])} and {names[-1]} this week, so they're let go.")
            else:
                parts += [d["line"] for d in room]
            if gone:
                parts.append("Next week starts fresh.")
            longs = [sid for sid, x in by_id.items() if x.get("kind") == "long"]
            big = bool(gone) or any(was.get(sid) != now["schedule"].get(sid) for sid in longs
                                    if sid in now["schedule"] and sid in was)
            if parts:
                line = " ".join(parts)
                with self.lock:
                    self.db.execute("INSERT INTO plan_changes (user_id, week_start, data, at) VALUES (?, ?, ?, ?)",
                                    (user_id, ws, json.dumps({"line": line[0].upper() + line[1:], "big": big,
                                                              "reason": self._change_reason(c, week, t, row["at"])}),
                                     stamp))
        with self.lock:
            rows = self.db.execute("SELECT id, data, at FROM plan_changes WHERE user_id = ? AND week_start = ? "
                                   "AND seen = 0 ORDER BY id DESC LIMIT 1", (user_id, ws)).fetchall()
        out = []
        for r in rows:
            d = json.loads(r["data"])
            big = d.get("big", any(i["kind"] == "dropped" or i.get("long") for i in d.get("items", [])))
            out.append({"id": r["id"], "at": r["at"], "line": d["line"], "reason": d.get("reason"), "big": big})
        return out

    @staticmethod
    def _change_reason(c: dict, week: dict, t: dict, since: Optional[float]) -> str:
        """The evidence behind a change, in a few words: the ride since the week was last laid out and the job it
        did, how a ride felt or recovery (Today's own why), a day gone by without riding, or the days left."""
        from rideengine.analysis import today as td
        words = {"punch": "the punch", "top_end": "the top-end work", "hold": "the steady work",
                 "long": "the long ride", "easy": "the easy riding"}
        new = sorted((r for r in week.get("rides", []) if since is None or r["start"] > since),
                     key=lambda r: r["start"])
        if new:
            r = new[-1]
            day = td.WEEKDAY[date.fromisoformat(r["date"]).weekday()]
            day = "Today" if r["date"] == c["today"].isoformat() else day
            jobs = (r.get("jobs") or {}).get("jobs", [])
            done = [j for j in jobs if j["status"] in ("done", "more")]
            part = [j for j in jobs if j["status"] == "part"]
            if done:
                return f"{day}'s ride did {' and '.join(words.get(j['job'], j['job']) for j in done)}."
            if part:
                return f"{day}'s ride did part of {words.get(part[0]['job'], part[0]['job'])}."
            return f"{day}'s ride."
        why = t.get("why") or ""
        if "wrecked" in why or "recovery" in why or "hurt" in why:
            return why.split(". ")[0].rstrip(".") + "."
        yesterday = c["today"] - timedelta(days=1)
        if since is not None and datetime.fromtimestamp(since).date() <= yesterday and \
                not any(r["date"] == yesterday.isoformat() for r in week.get("rides", [])):
            return f"{td.WEEKDAY[yesterday.weekday()]} went by without a ride."
        return "To fit the days left."

    def seen_plan_changes(self, user_id: int, ids: list[int]) -> None:
        with self.lock:
            # Only the newest note is shown, so seeing it covers the ones before it.
            if ids:
                self.db.execute("UPDATE plan_changes SET seen = 1 WHERE user_id = ? AND id <= ?", (user_id, max(ids)))

    @staticmethod
    def _next_item(session: dict, today: date, on: Optional[str] = None) -> dict:
        """One session What's Next names, on the day this week's layout puts it."""
        from rideengine.analysis import today as td
        d = date.fromisoformat(on or session["date"])
        return {"date": d.isoformat(), "when": td._day_name(d, today) if d - today < timedelta(days=7)
                else d.strftime("%A %-d %B"), "session": session}

    def session_brief(self, user_id: int, session_id: str) -> Optional[dict]:
        """A session with how to ride it (td.guide) and how it should feel, with the watts when known: the
        session's own page in the app."""
        from rideengine.analysis import today as td
        s = self.plan_session(user_id, session_id)
        if s is None:
            return None
        return {**s, "guide": {**td.guide(s), "feel": _feel(s)}}

    BRIEF_AT = (6, 0)        # the morning brief's default time, the rider's local time: riders go out early

    def _brief_at(self, user_id: int) -> tuple[int, int]:
        """When this rider's morning brief arrives: their own time (You › Settings), else BRIEF_AT."""
        with self.lock:
            row = self.db.execute("SELECT brief_at FROM users WHERE id = ?", (user_id,)).fetchone()
        if row and row["brief_at"]:
            h, m = row["brief_at"].split(":")
            return int(h), int(m)
        return self.BRIEF_AT
    REVIEW_AT = (18, 0)      # the Sunday review, from this time on Sunday

    def train_inbox(self, user_id: int, now: Optional[datetime] = None) -> dict:
        """The coach speaking up (docs/train-tab.md, step 4): messages for the phone to show as notifications.
        Worked out fresh each time with stable ids, so the phone shows each once: after a ride (what it counted
        as, a best, one thing to try), a plan change today, and the week's review on Sunday evening. The morning
        brief comes as `scheduled` (its time and words), so the phone can schedule it itself. Lock-screen words
        only: never recovery numbers."""
        from rideengine.analysis import today as td
        brief_at = self._brief_at(user_id)
        t = self.train_today(user_id)
        if t.get("state") == "no_plan":
            return {"items": [], "scheduled": []}
        c = self._plan_context(user_id)
        tz = c["tz"]
        now = (now or datetime.now(tz)).astimezone(tz)
        today = c["today"]
        items = []

        def at(d: date, hm: tuple) -> str:
            return datetime.combine(d, datetime.min.time().replace(hour=hm[0], minute=hm[1])).replace(
                tzinfo=now.tzinfo).isoformat()

        # After each ride of today and yesterday (older news, like "your best yet", may no longer be true).
        for r in sorted(self._recent_kinds(c, days=1), key=lambda r: r["date"], reverse=True):
            if (r.get("minutes") or 0) < 15:
                continue
            n = self.train_ride_note(user_id, r["ride_id"], _today=t if r["date"] == today else {})
            if n is None:
                continue
            best = next((m for m in n["means"] if "your best yet" in m), None)
            if best:                    # "Best minute: 273 W, your best yet." -> "Your best minute yet: 273 W"
                name, _, rest = best.partition(": ")
                title = f"Your {name.lower()} yet: {rest.split(',')[0]}"
            else:
                title = f"Counted as {n['counted']['title']}" if n["counted"] else "Ride's in"
            body = []
            if best and n["counted"]:
                body.append(f"Counted as your {n['counted']['title'].lower()} session.")
            elif not n["counted"]:
                body.append("Extra riding this week.")
            if n["tips"]:
                body.append(f"One thing to try: {n['tips'][0]['title'].lower()}.")
            body.append("How did it feel?")
            items.append({"id": f"ride:{r['ride_id']}", "kind": "ride", "title": title, "body": " ".join(body),
                          "opens": {"screen": "ride", "ride_id": r["ride_id"]},
                          "at": datetime.fromtimestamp(float(r["ride_id"]), tz).isoformat()})

        # A change today: recovery says ease off.
        if now.time() >= datetime.min.time().replace(hour=brief_at[0], minute=brief_at[1]):
            if t.get("readiness") == "strained" and t["state"] in ("session", "rest"):
                title = "Easy today instead" if t["state"] == "session" else "Rest today instead"
                items.append({"id": f"change:{today}", "kind": "change", "title": title,
                              "body": "Your recovery is lower than usual this morning. " + (
                                  f"Today: {td.short(t['session'])}." if t.get("session") else "The harder work moves later."),
                              "opens": {"screen": "today"}, "at": at(today, brief_at)})
        # The week laid out differently: only a bigger change is worth a notification (a session let go, the long
        # ride on another day); the rest is said in the app, on Today (docs/train-method.md "When the plan changes").
        for ch in t.get("changes") or []:
            if ch.get("big"):
                items.append({"id": f"plan:{ch['id']}", "kind": "change", "title": "This week's plan changed",
                              "body": f"{ch['line']} {ch.get('reason') or ''}".strip(),
                              "opens": {"screen": "today"},
                              "at": datetime.fromtimestamp(ch["at"], tz).isoformat()})

        # The week's review, Sunday evening (or the Monday after, if the phone didn't wake).
        ws = date.fromisoformat(t["days"][0]["date"]) if t.get("days") else None
        last_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
        if today.weekday() == 6 and now.time() >= datetime.min.time().replace(hour=self.REVIEW_AT[0]):
            review_week = ws
        elif today.weekday() == 0:
            review_week = last_sunday - timedelta(days=6)
        else:
            review_week = None
        if review_week:
            r = self.train_review(user_id, review_week.isoformat())
            if r:
                body = [r["lines"][0]] if r["lines"] else []
                ask = [p for p in r["proposals"] if p["status"] == "open"]
                if ask:
                    body.append(f"{len(ask)} change{'s' if len(ask) > 1 else ''} for next week to look at.")
                else:
                    body.append("See how the week went, and what's next.")
                items.append({"id": f"review:{review_week}", "kind": "review",
                              "title": "Your week in review",
                              "body": " ".join(body), "opens": {"screen": "review", "week_start": review_week.isoformat()},
                              "at": at(review_week + timedelta(days=6), self.REVIEW_AT)})

        # The morning brief, for the phone to schedule: tomorrow (and today, if it's still early).
        scheduled = []
        days = [today] if now.time() < datetime.min.time().replace(hour=brief_at[0], minute=brief_at[1]) else []
        days.append(today + timedelta(days=1))
        week_days = {d["date"]: d for d in t.get("days") or []}
        for d in days:
            day = week_days.get(d.isoformat())
            if d == today and t["state"] == "session" and t.get("session"):
                title, body = f"{t['session']['title']} today", f"{td.short(t['session'])}. {td.WHY.get(t['session']['kind'], '')}"
            elif d == today and t["state"] == "rest":
                title, body = "Rest day", "No riding today: rest is when the fitness is built."
            elif day and day["state"] == "session" and day.get("title"):
                ses = next((s for s in (self._this_week(self.plan_view(user_id), c["today"]) or {}).get("sessions", [])
                            if s["title"] == day["title"] and s.get("status") != "done"), None)
                title = f"{day['title']} today"
                body = f"{td.short(ses)}. {td.WHY.get(ses['kind'], '')}" if ses else "Open Kova for today's session."
            elif day:
                title, body = "Rest day", "No riding today: rest is when the fitness is built."
            else:                       # a new week: its first session
                view = self.plan_view(user_id)
                nxt = next((w for w in view["weeks"] if w["week_start"] <= d.isoformat() <
                            (date.fromisoformat(w["week_start"]) + timedelta(days=7)).isoformat()), None) if view else None
                first = next((x for x in (nxt or {}).get("sessions", []) if x["date"] == d.isoformat() and not x["off_bike"]), None)
                if first:
                    title = f"{first['title']} today"
                    body = f"A new week starts. {td.short(first)}. {td.WHY.get(first['kind'], '')}"
                else:
                    title, body = "A new week", "Rest today; the week's first session comes tomorrow."
            ai = self._ai_brief(user_id, c, d, t, title, body.strip())
            if ai:
                title, body = ai["title"], ai["body"]
            scheduled.append({"id": f"brief:{d}", "kind": "brief", "title": title, "body": body.strip(),
                              "opens": {"screen": "today"}, "at": at(d, brief_at)})
        items.sort(key=lambda x: x["at"], reverse=True)
        return {"items": items, "scheduled": scheduled}

    def _brief_facts(self, c: dict, d: date, t: dict, title: str, body: str) -> Optional[dict]:
        """What the AI coach may know for a day's brief: the day's session or rest as the engine decided it, why,
        how it should feel, why the work works, the week so far and what's left, the goal, and the last ride's
        jobs and what it did well. Never recovery data: on a day the engine eased because recovery was low, there's
        no AI brief at all (the engine's words say it)."""
        from rideengine.analysis import plan as p
        from rideengine.analysis import today as td
        from rideengine.analysis import voice
        if d == c["today"] and "recovery" in (t.get("why") or "").lower():
            return None
        ses = None
        if d == c["today"] and t.get("state") == "session":
            ses = t.get("session")
        else:
            ses = next((n["session"] for n in t.get("next") or [] if n.get("date") == d.isoformat()), None)
        latest = t.get("latest") or {}
        facts = {"day": td.WEEKDAY[d.weekday()], "engine_words": {"title": title, "body": body},
                 "session": ({"title": ses["title"], "main": td.short(ses), "job": ses.get("job"),
                              "why": td.WHY.get(ses["kind"]), "how_it_should_feel": td.FEEL.get(ses["kind"]),
                              "why_it_works": (voice.learn(ses.get("job"), d.toordinal()) or {}).get("text"),
                              "minutes": round((ses.get("seconds") or 0) / 60)} if ses else None),
                 "rest_day": ses is None,
                 "week": {"done": t.get("done"), "total": t.get("total")},
                 "goal": ({"title": t["goal"].get("title"), "weeks_left": t["goal"].get("weeks_left")}
                          if t.get("goal") else None),
                 "last_ride": ({"date": latest.get("date"), "did": (latest.get("jobs") or {}).get("summary"),
                                "done_well": (latest.get("done_well") or {}).get("text")}
                               if latest and latest.get("date", "") >= (d - timedelta(days=2)).isoformat() else None)}
        if ses and ses.get("steps"):
            main = next((x["steps"][0].get("target", {}).get("watts") for x in ses["steps"] if x.get("steps")), None)
            if main:
                facts["session"]["watts"] = f"{main[0]}–{main[1]} W"
        return facts

    def _ai_brief(self, user_id: int, c: dict, d: date, t: dict, title: str, body: str) -> Optional[dict]:
        if not self.coach.allowed(user_id):
            return None
        facts = self._brief_facts(c, d, t, title, body)
        return self.coach.morning_brief(user_id, d.isoformat(), facts) if facts else None

    def train_week(self, user_id: int, start: Optional[str] = None) -> Optional[dict]:
        """A plan week with each session's status and the ride that counted, the week's rides with what kind of
        training each was, and (this week) the days the open sessions are now expected on."""
        from rideengine.analysis import today as td
        view = self.plan_view(user_id)
        if view is None:
            return None
        c = self._plan_context(user_id)
        week = (next((w for w in view["weeks"] if w["week_start"] == start), None) if start
                else self._this_week(view, c["today"]) or next(       # before the plan starts: its first week
                    (w for w in view["weeks"] if date.fromisoformat(w["week_start"]) > c["today"]), None))
        if week is None:
            return None
        out = {**week, "schedule": {}}
        ws = date.fromisoformat(week["week_start"])
        if ws <= c["today"] < ws + timedelta(days=7):
            readiness = (self.recovery(user_id).get("readiness") or {}).get("status", "unknown")
            t = week.get("replan") or td.plan_today(week["sessions"], self._recent_kinds(c), c["today"], ws, readiness)
            out.update(schedule=t["schedule"], folded=t.get("folded", []),
                       dropped=t.get("dropped", []))
        out["zone2"] = self._week_zone2(c, ws)
        return out

    @staticmethod
    def _week_zone2(c: dict, ws: date) -> Optional[dict]:
        """The week's time in zone 2, above and below, and its share at zone 2 or easier."""
        from rideengine.analysis import zone2
        if not c.get("zone2"):
            return None
        a = datetime.combine(ws, datetime.min.time(), c["tz"]).timestamp()
        hs = [f.get("hr_hist") for f in c["feats"] if a <= f["start"] < a + 7 * 86400]
        sp = zone2.split(hs, c["zone2"]["bpm"])
        return {**sp, "bpm": c["zone2"]["bpm"], "line": zone2.week_line(sp)} if sp else None

    def train_zone2(self, user_id: int) -> dict:
        """Zone 2 in one place (docs/train-method.md): the rider's range and where it came from, what the latest
        steady ride says about it, this week's share, and watts at zone 2 month by month (the proof it works)."""
        from rideengine.analysis import zone2
        c = self._plan_context(user_id)
        z = c["zone2"]
        if not z:
            return {"range": None, "own": self.me(user_id).get("zone2"),
                    "why": "Zone 2 is worked out from your resting and maximum heart rate: it needs ten rides with "
                           "heart rate and a resting heart rate from your Watch. Or set your own."}
        monday = c["today"] - timedelta(days=c["today"].weekday())
        return {"range": z["bpm"], "source": z["source"], "how": z["how"], "own": self.me(user_id).get("zone2"),
                "talk": "Easy enough to talk in full sentences.",
                "check": zone2.check(c["feats"], z["bpm"], c["tz"]),
                "week": self._week_zone2(c, monday),
                "trend": zone2.trend(c["feats"], z["bpm"], c["tz"])}

    def _ridden_against(self, user_id: int, c: dict, session: dict, work: Optional[dict], ride_id: str,
                        then: Optional[float] = None) -> Optional[dict]:
        """Planned against ridden, judged by the targets the ride was ridden to (not ones raised since): set by
        set, steady reps read minute by minute (rideengine/analysis/pacing.py), and one thing for next time when
        they fell short."""
        from rideengine.analysis import plan as p
        from rideengine.analysis import train
        if not work:
            return None
        feel = self.ride_feel(user_id, ride_id)
        then = then or (feel or {}).get("from_w") or self._aim(user_id, c["ftp"], c["tz"], before=ride_id)["watts"]
        if then and session.get("steps"):
            session = p.targets(session, then, c["hr_zones"])
        f = next((x for x in c["feats"] if x["ride_id"] == ride_id), None) or {}
        a = train.against(session, work, indoor=bool(f.get("indoor")), feel=(feel or {}).get("feel"))
        # Only when the ride was the suggested workout (docs/train-method.md): every planned set is in it. Another
        # workout that did the same job is read by its own sets and the job, not graded against this one.
        if a is None or any(r["verdict"] == "missing" for r in a["sets"]):
            return None
        return a

    def _counted_session(self, user_id: int, ride_id: str) -> Optional[dict]:
        """The planned session (targets filled in) this ride counts as, if any."""
        view = self.plan_view(user_id)
        return next((s for w in (view or {}).get("weeks", []) for s in w["sessions"]
                     if ride_id in (s.get("counted") or {}).get("rides", [(s.get("counted") or {}).get("ride_id")])), None)

    def train_ride_note(self, user_id: int, ride_id: str, _today: Optional[dict] = None) -> Optional[dict]:
        """After a ride (docs/train-words.md): what you did, what it counted as, what it means for the goal,
        what's next, and one thing to try. Every number comes from the engine."""
        from rideengine.analysis import feedback, train
        from rideengine.analysis import today as td
        c = self._plan_context(user_id)
        f = next((x for x in c["feats"] if x["ride_id"] == ride_id), None)
        if f is None:
            return None
        d = datetime.fromtimestamp(f["start"], c["tz"]).astimezone(c["tz"]).date()
        ftp = c["ftp"]["watts"]
        cls = (train.classify(f["work"], ftp, c["max_hr"], c["resting_hr"]) if f.get("work")
               else {"kind": None, "confidence": 0, "reason": "", "facts": {}})
        counted, intent, against, ride_week, toward = None, None, None, None, None
        view = self.plan_view(user_id)
        if view:
            ride_week = next((w for w in view["weeks"] if date.fromisoformat(w["week_start"]) <= d <
                              date.fromisoformat(w["week_start"]) + timedelta(days=7)), None)
            for w in view["weeks"]:
                for s in w["sessions"]:
                    if ride_id in (s.get("progress") or {}).get("rides", []):
                        toward = {"session_id": s["id"], "title": s["title"], "job": s.get("job"),
                                  "line": s["progress"]["line"]}
                        # Partly done: where it fell short matters most here (26 Nov 2026).
                        against = self._ridden_against(user_id, c, s, f.get("work"), ride_id)
                        intent = s["kind"]
                    if ride_id in (s.get("counted") or {}).get("rides", [(s.get("counted") or {}).get("ride_id")]):
                        against = self._ridden_against(user_id, c, s, f.get("work"), ride_id)
                        counted = {"session_id": s["id"], "title": s["title"], "kind": s["kind"],
                                   "reason": s["counted"]["reason"], "by_hand": s["counted"].get("by_hand", False)}
                        intent = s["kind"]
        earlier = [x for x in c["feats"] if x["start"] < f["start"]]
        contrib = feedback.contribution(f, earlier, ftp)
        tips = feedback.pointers(f.get("work") or {}, cls, ftp, intent) if f.get("work") else []
        if against and against.get("next_time"):
            # Where the session's reps fell short comes first: it's the one thing for next time.
            tips = [against["next_time"]] + [t for t in tips if t["id"] != "steady_too_hard"]
        goal = self._goal_markers(user_id, c)
        # A new best that's one of the goal's numbers is said once, with what it means for the goal.
        markers = {"60": "punch", "1200": "sustained"}
        by_id = {m["id"]: m for m in (goal or {}).get("markers", [])}
        means = []
        for b in contrib["bests"]:
            m = by_id.get(markers.get(b["id"], ""))
            if m and m.get("target") and m.get("current"):
                what = m["meaning"].split(":")[1].strip().rstrip(".") if ":" in m["meaning"] else ""
                lead = f"{b['text']} That's your {m['name'].lower()}" + (f" ({what})" if what else "")
                means.append(f"{lead}, and it's already past the {m['target']} {m['unit']} you were aiming for."
                             if m["reached"] else
                             f"{lead}: {m['current']} {m['unit']} now, on the way to {m['target']} {m['unit']}.")
            else:
                means.append(b["text"])
        if _today is None:
            _today = self.train_today(user_id) if d == c["today"] else None
        nxt = None
        if _today and d >= c["today"] - timedelta(days=2):
            nxt = _today.get("then") if _today.get("state") in ("done", "rest") else None
        did = {"km": round(f.get("km") or 0, 1), "minutes": round((f.get("moving_s") or 0) / 60),
               "ascent_m": f.get("ascent_m"), "avg_power": f.get("power"), "avg_hr": f.get("avg_hr"),
               "best_minute": (f.get("power_curve") or {}).get("60")}
        feel = self.ride_feel(user_id, ride_id)
        # The coach's voice (docs/train-method.md step 5): one specific thing done well, from the ride's own
        # numbers, and one line on why the work works (its research: docs/training-science.md).
        from rideengine.analysis import voice
        jobs = self._jobs(c, f, ride_week)
        done_well = (voice.done_well(f["work"], jobs, against, ftp, cls["kind"], round((f.get("moving_s") or 0) / 60),
                                     tips) if f.get("work") else None)
        jobs_done = [j["job"] for j in (jobs or {}).get("jobs", []) if j["status"] in ("done", "more")]
        kind_job = voice.KIND_JOB.get(cls["kind"])
        main_job = kind_job if kind_job in jobs_done else jobs_done[0] if jobs_done else kind_job
        note_learn = voice.learn(main_job, int(ride_id) if ride_id.isdigit() else 0)
        note_z2 = self._ride_zone2(c, f, intent, cls["kind"], jobs_done)
        note = {"ride_id": ride_id, "date": d.isoformat(), "indoor": f.get("indoor"), "did": did,
                "zone2": note_z2,
                "kind": cls["kind"], "kind_title": train.TITLES.get(cls["kind"]) if cls["kind"] else None,
                "reason": cls.get("reason"), "counted": counted, "against": against, "means": means,
                "jobs": jobs, "toward": toward, "left": self._left_this_week(c, ride_week),
                "done_well": done_well, "learn": note_learn,
                "load": contrib["load"],
                "next": nxt, "try": tips[0] if tips else None, "tips": tips,
                "feel": {"feel": feel["feel"], "hurts": feel["hurts"]} if feel else None,
                "feel_note": self._feel_note(c["aim"], ride_id, feel, *self._next_hard(view, c["today"], _today))}
        # The AI coach's words (backend/coach.py), from facts the engine made: only for riders with the
        # personal-use setting on; the engine's words above stay as the fallback.
        if self.coach.allowed(user_id):
            facts = self._story_facts(c, f, d, note, goal)
            note["story"] = self.coach.ride_story(user_id, ride_id, facts)
        return note

    @staticmethod
    def _ride_zone2(c: dict, f: dict, intent: Optional[str], kind: Optional[str], jobs_done: list) -> Optional[dict]:
        """A ride's time in zone 2, above and below (moving time), and one line where zone 2 was the point: the
        session it counted as, else what kind of riding it was, else the job it did (docs/train-method.md)."""
        from rideengine.analysis import zone2
        if not c.get("zone2") or not f.get("hr_hist"):
            return None
        rng = c["zone2"]["bpm"]
        sp = zone2.split([f["hr_hist"]], rng)
        if sp is None:
            return None
        point = intent or kind
        if intent is None and kind in (None, "mixed"):
            point = "long" if "long" in jobs_done else "endurance" if "easy" in jobs_done else None
        w = zone2.watts([f["hr_hist"]], rng, min_s=10 * 60)
        return {**sp, "bpm": rng, "line": zone2.ride_line(sp, rng, point, bool(f.get("indoor"))),
                "watts": (w or {}).get("watts")}

    def _story_facts(self, c: dict, f: dict, d: date, note: dict, goal: Optional[dict]) -> dict:
        BUILDS = {"surges": "punch: answering accelerations and closing gaps",
                  "vo2": "your top end", "sprint": "snap in a sprint",
                  "steady": "the power you could hold for about an hour",
                  "threshold": "the power you could hold for about an hour",
                  "endurance": "the aerobic base everything else sits on", "long": "endurance for long rides",
                  "easy": "recovery", "mixed": "a bit of everything, nothing in particular"}
        """What the AI coach may know about a ride: no GPS, no place names, no recovery data. Everything here
        is stable for the ride (nothing that changes day to day), so a saved story is only redone when it
        changes."""
        from rideengine.analysis import today as td
        recent = []
        for x in c["feats"]:
            xd = datetime.fromtimestamp(x["start"], c["tz"]).astimezone(c["tz"]).date()
            if d - timedelta(days=14) <= xd < d and (x.get("moving_s") or 0) >= 15 * 60:
                recent.append({"day": td.WEEKDAY[xd.weekday()], "days_before": (d - xd).days,
                               "minutes": round((x.get("moving_s") or 0) / 60), "indoor": bool(x.get("indoor"))})
        did = {k: (round(v) if isinstance(v, float) and k != "km" else v) for k, v in note["did"].items() if v}
        return {
            "ride": {"weekday": td.WEEKDAY[d.weekday()], "indoor": bool(note["indoor"]), **did,
                     "what_it_was": note["kind_title"], "how_we_know": note["reason"],
                     "what_this_kind_of_riding_builds": BUILDS.get(note["kind"])},
            "counted_as": ({"session": note["counted"]["title"], "set_by_rider": note["counted"]["by_hand"]}
                           if note["counted"] else None),
            "new_bests": [b for b in note["means"]],
            "goal": ({"title": goal["title"], "in_the_riders_words": goal.get("words"), "weeks_left": goal.get("weeks_left"),
                      "numbers": [{k: m[k] for k in ("name", "meaning", "current", "target", "unit", "reached")}
                                  for m in goal.get("markers", [])]} if goal else None),
            "rides_in_the_two_weeks_before": recent,
            "one_thing_to_try_shown_separately": note["tips"][0]["title"] if note["tips"] else None,
            "how_it_felt": (note["feel"] or {}).get("feel"),
            "what_changed_because_of_how_it_felt": note.get("feel_note"),
            "against_the_plan": ({"summary": note["against"]["summary"], "sets": note["against"]["lines"]}
                                 if note.get("against") else None),
            "jobs_it_did": (note.get("jobs") or {}).get("summary"),
            "done_well": (note.get("done_well") or {}).get("text"),
            # The split, not the range: the range is worked out from resting heart rate, which the AI never gets.
            "zone2": ({"percent_in": note["zone2"]["in"], "percent_above": note["zone2"]["above"],
                       "percent_below": note["zone2"]["below"]}
                      if note.get("zone2") else None),
        }

    def ride_feel(self, user_id: int, ride_id: str) -> Optional[dict]:
        with self.lock:
            row = self.db.execute("SELECT feel, hurts, ftp_w, under FROM ride_feel WHERE user_id = ? AND ride_id = ?",
                                  (user_id, ride_id)).fetchone()
        return ({"feel": row["feel"], "hurts": bool(row["hurts"]), "from_w": row["ftp_w"],
                 "under": json.loads(row["under"]) if row["under"] else None} if row else None)

    @staticmethod
    def _next_hard(view: Optional[dict], today: date, t: Optional[dict] = None) -> tuple[Optional[dict], Optional[str]]:
        """The next hard session still to ride (targets filled in), and the day it's on: as What's Next has it
        (sessions move to fit the week), else its planned day."""
        from rideengine.analysis import today as td
        for n in (t or {}).get("next") or []:
            if td.hard(n["session"]["kind"]) and n["session"].get("steps"):
                return n["session"], n["when"]
        # Else the next one on the days the week now has (re-planned this week, planned after), a session with
        # sets of its own before a group ride.
        ahead = []
        for w in (view or {}).get("weeks", []):
            when = (w.get("replan") or {}).get("schedule", {})
            for s in w["sessions"]:
                on = when.get(s["id"], s["date"])
                if on > today.isoformat() and s["status"] in ("upcoming", "open", "today") and td.hard(s["kind"]) \
                        and s.get("steps") and not s.get("dropped"):
                    ahead.append((on, s["kind"] == "group", s))
        if not ahead:
            return None, None
        on, _, s = min(ahead, key=lambda x: (x[0], x[1]))
        return s, td.WEEKDAY[date.fromisoformat(on).weekday()]

    @staticmethod
    def _feel_note(aim: dict, ride_id: str, feel: Optional[dict], nxt: Optional[dict] = None,
                   when: Optional[str] = None) -> Optional[str]:
        """What the rider's tap changed, when it changed the targets: said with the next hard session's watts,
        not as a new number for what they could hold for an hour (that stays the estimate)."""
        if feel and feel["feel"] == "easy" and feel.get("under"):
            u = feel["under"]
            return (f"You said it felt easy, at {u['w']} W against the {u['target'][0]}–{u['target'][1]} W asked, so "
                    f"the watts stay as they are: ride the full range next time, and if that feels easy too, they go up.")
        if not feel or (aim.get("because") or {}).get("ride_id") != ride_id or feel["feel"] != "easy":
            return None
        was = feel.get("from_w") or aim["base"]
        if aim["watts"] <= was:
            return None
        pct = round((aim["watts"] / was - 1) * 100)
        text = f"You said it felt easy, so I've raised the watts of your hard sessions by {pct}%."
        hard = [x for st in (nxt or {}).get("steps") or [] for x in (st.get("steps") or [st])
                if (x.get("target") or {}).get("watts") and x.get("zone") not in ("Z1", "Z2")]
        if hard and when:
            lo, hi = min(x["target"]["watts"][0] for x in hard), max(x["target"]["watts"][1] for x in hard)
            text += f" {when}'s {nxt['title'].lower()}: about {lo}–{hi} W."
        return text + " Tell me how that one feels."

    FEELS = ("easy", "good", "hard", "wrecked")

    def set_ride_feel(self, user_id: int, ride_id: str, feel: str, hurts: bool = False) -> bool:
        """The one tap after a ride: easy | good | hard | wrecked, and whether something hurts. It shapes the
        next days (rideengine/analysis/today.py) and what the coach says."""
        if feel not in self.FEELS:
            raise ValueError(f"feel must be one of {', '.join(self.FEELS)}")
        with self.lock:
            if self.db.execute("SELECT 1 FROM rides WHERE user_id = ? AND ride_id = ?", (user_id, ride_id)).fetchone() is None:
                return False
            old = self.db.execute("SELECT ftp_w FROM ride_feel WHERE user_id = ? AND ride_id = ?",
                                  (user_id, ride_id)).fetchone()
        # A hard ride keeps the watts its targets started from (the first tap's), so how it felt can move them.
        ftp_w = old["ftp_w"] if old and old["ftp_w"] else self._hard_ride_aim(user_id, ride_id)
        under = self._under_targets(user_id, ride_id, ftp_w) if ftp_w else None
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO ride_feel (user_id, ride_id, feel, hurts, at, ftp_w, under) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)", (user_id, ride_id, feel, 1 if hurts else 0, db.now(), ftp_w,
                                                            json.dumps(under) if under else None))
        return True

    def _under_targets(self, user_id: int, ride_id: str, then: float) -> Optional[dict]:
        """A hard ride whose main reps averaged under the targets it was ridden to: {"w", "target"}. Felt easy
        there means ride the targets first, not raise them (docs/train-method.md "Short of the target")."""
        view = self.plan_view(user_id)
        s = next((s for w in (view or {}).get("weeks", []) for s in w["sessions"]
                  if ride_id in (s.get("counted") or {}).get("rides", [(s.get("counted") or {}).get("ride_id")])
                  or ride_id in (s.get("progress") or {}).get("rides", [])), None)
        if s is None:
            return None
        c = self._plan_context(user_id)
        f = next((x for x in c["feats"] if x["ride_id"] == ride_id), None)
        a = self._ridden_against(user_id, c, s, (f or {}).get("work"), ride_id, then=then)
        low = [r for r in (a or {}).get("sets", []) if r["verdict"] == "below" and r.get("target")]
        return {"w": (low[0].get("watts") or [low[0]["power"]])[0], "target": low[0]["target"]} if low else None

    def _hard_ride_aim(self, user_id: int, ride_id: str) -> Optional[float]:
        """For a hard ride with power: the watts the targets started from before this ride's tap."""
        from rideengine.analysis import train
        from rideengine.analysis import today as td
        c = self._plan_context(user_id)
        f = next((x for x in c["feats"] if x["ride_id"] == ride_id), None)
        if not f or not f.get("work") or f["work"].get("basis") != "power" or not c["ftp"]["watts"]:
            return None
        kind = train.classify(f["work"], c["ftp"]["watts"], c["max_hr"], c["resting_hr"])["kind"]
        if not td.hard(kind) or kind == "mixed":
            return None
        return self._aim(user_id, c["ftp"], c["tz"], skip=ride_id)["watts"]

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
        local = col.local_times(vfeats, tz, self.home_point(user_id, vfeats))
        badges = col.badges(es, found, tz, local)
        names = {l["ride_id"]: r["name"] for r in found["routes"] for l in r["laps"]}
        shapes = {f["ride_id"]: f.get("shape") or [] for f in vfeats}
        # Indoor mini cards: the session's shape over time and the ride game's world (features.trace).
        inside = {f["ride_id"]: {"trace": f.get("trace") or [], "trace_kind": f.get("trace_kind"),
                                 "world": f.get("world")}
                  for f in vfeats if f["indoor"]}
        me = self.me(user_id)
        return {"rider": {**col.ratings(es, today), "name": me["name"], "avatar": me["avatar"],
                          "badges_earned": sum(b["earned"] for b in badges), "badges_total": len(badges)},
                "badges": badges, "binder": col.binder(es, notes, names, shapes, today, inside)}

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
        return {"es": es, "found": found, "today": today, "rest": rest, "feats": vfeats,
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
        from rideengine.analysis import headline as hl
        c = self._goal_context(user_id)
        four = hl.four(c["feats"], c["today"], goal, self.me(user_id).get("ftp"))
        return {"goal": {**goal, "targets": four["targets"]},
                "reveal": g.reveal(goal, c["es"], c["found"], c["today"], c["rest"]),
                "markers": g.markers(goal, c["es"], c["today"], four["metrics"]),
                "season": g.seasons(c["es"], c["today"])}

    def set_goal(self, user_id: int, goal: dict) -> dict:
        from rideengine.analysis import headline as hl
        goal = self.check_goal(user_id, goal)
        c = self._goal_context(user_id)
        # Targets start from where the rider is today; numbers without a value yet get theirs later.
        goal["targets"] = hl.four(c["feats"], c["today"], {**goal, "targets": {}}, self.me(user_id).get("ftp"))["targets"]
        with self.lock:
            self.db.execute("UPDATE goals SET active = 0, ended_at = ? WHERE user_id = ? AND active = 1", (db.now(), user_id))
            cur = self.db.execute("INSERT INTO goals (user_id, data, active, created_at) VALUES (?, ?, 1, ?)",
                                  (user_id, json.dumps(goal), db.now()))
        self.make_plan(user_id)
        return self.goal_view(user_id, {**goal, "id": cur.lastrowid})

    def current_goal(self, user_id: int) -> Optional[dict]:
        row = self._active_goal_row(user_id)
        if row is None:
            return None
        view = self.goal_view(user_id, {**json.loads(row["data"]), "id": row["goal_id"], "set_at": row["created_at"]})
        stored = json.loads(row["data"])
        if view["goal"]["targets"] != (stored.get("targets") or {}):
            with self.lock:
                self.db.execute("UPDATE goals SET data = ? WHERE goal_id = ?",
                                (json.dumps({**stored, "targets": view["goal"]["targets"]}), row["goal_id"]))
        return view

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
        # What the ride was (docs/train-method.md): the suggested session's name when it was that workout, else the
        # kind of work it did ("Punch"); indoors, where there's no place to name it after.
        a, jobs = None, None
        if (name is None and ride.indoor) or headline is None:
            from rideengine.analysis import train
            session = self._counted_session(user_id, ride_id)
            c = self._plan_context(user_id)
            if session:
                a = self._ridden_against(user_id, c, session, train.work(ride), ride_id)
            f = next((x for x in c["feats"] if x["ride_id"] == ride_id), None)
            jobs = self._jobs(c, f, None) if f else None
            if name is None and ride.indoor:
                name = (session["title"] if session and a else
                        jobs["jobs"][0]["title"] if jobs and jobs["jobs"] else None)
        if headline is None:
            headline = records.headline(self.notes(user_id, ride_id))
        if headline is None and a and a.get("short"):
            headline = a["short"]
        if headline is None and jobs and jobs.get("summary"):
            headline = jobs["summary"]
        home = self.home_point(user_id, [f for f in feats if f["ride_id"] in visible]) if privacy else None
        from rideengine.analysis.collection import is_holo
        return ride_card(ride, number=number, name=name, headline=headline, places=places, fonts=fonts,
                         hide_near=[home] if home else None, background=background,
                         avatar=self.me(user_id)["avatar"], holo=is_holo(self.notes(user_id, ride_id)))

    # --- planned routes ("courses": the route check and export, rideengine/routes/) ---------------
    def add_course(self, user_id: int, gpx: bytes, name: Optional[str] = None, source: Optional[str] = None,
                   plan: Optional[dict] = None) -> dict:
        """Keep the rider's GPX (Ride with GPS, Komoot...), then check it: on a worker thread in the
        server (the map lookup can take a minute), before returning otherwise."""
        from rideengine.routes.route import read_route
        route = read_route(gpx, name=name)       # ValueError for files without a route
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO courses (user_id, name, source, link, created_at, status, file, plan) "
                "VALUES (?, ?, ?, ?, ?, 'checking', '', ?)",
                (user_id, route.name[:80], source or route.source, route.link, db.now(),
                 json.dumps(plan) if plan else None))
            cid = cur.lastrowid
            folder = os.path.join(self.settings.raw_dir, str(user_id), "courses")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"{cid}.gpx")
            with open(path, "wb") as f:
                f.write(gpx)
            self.db.execute("UPDATE courses SET file = ? WHERE course_id = ?", (path, cid))
        if self.insights.background:
            threading.Thread(target=self.check_course, args=(user_id, cid), name=f"course-{cid}",
                             daemon=True).start()
        else:
            self.check_course(user_id, cid)
        return self.course(user_id, cid)

    def _course_row(self, user_id: int, course_id: int):
        # Checks run on their own threads and share the connection: reads take the lock too.
        with self.lock:
            return self.db.execute("SELECT * FROM courses WHERE user_id = ? AND course_id = ?",
                                   (user_id, course_id)).fetchone()

    def _course_route(self, row):
        from rideengine.routes.route import read_route
        with open(row["file"], "rb") as f:
            return read_route(f.read(), name=row["name"])

    def _map(self, route, pad_m: Optional[float] = None) -> dict:
        from rideengine.routes import osm
        if self.map_source:
            return self.map_source(route)
        return osm.corridor(route, pad_m=pad_m or osm.VIEW_M)

    def _chosen_stops(self, row) -> list:
        """Stops the rider picked for this course: the café asked for, and stops added in tuning."""
        out = []
        plan = json.loads(row["plan"]) if row["plan"] else {}
        if (plan.get("stop") or {}).get("lat") is not None:
            out.append((plan["stop"]["lat"], plan["stop"]["lon"]))
        for v in self._versions(row["course_id"]):
            op = json.loads(v["op"])
            if op.get("op") == "stop":
                out.append((op["lat"], op["lon"]))
        return out

    def _course_report(self, user_id: int, route, chosen=()) -> dict:
        from rideengine import places
        from rideengine.analysis import features as feat_mod
        from rideengine.analysis.repeats import bbox as box
        from rideengine.routes import check
        data = self._map(route)
        with self.lock:
            feats = self.insights._features(user_id)
        visible = feat_mod.visible_ids(feats)
        vfeats = [f for f in feats if f["ride_id"] in visible]
        known = {tuple(c) for f in vfeats if not f["indoor"] for c in f.get("cells") or []}
        pace = check.Pace.of(vfeats)
        names = places.load(box([(p[0], p[1]) for p in route.points[::20]]))
        return check.check(route, data, pace=pace, known_cells=known, places=names, chosen=list(chosen))

    def check_course(self, user_id: int, course_id: int) -> None:
        row = self._course_row(user_id, course_id)
        if row is None:
            return
        try:
            report = self._course_report(user_id, self._course_route(row), chosen=self._chosen_stops(row))
            with self.lock:
                self.db.execute("UPDATE courses SET status = 'ready', error = NULL, report = ? WHERE course_id = ?",
                                (json.dumps(report), course_id))
        except Exception as e:   # the map server being down shouldn't lose the rider's route
            with self.lock:
                self.db.execute("UPDATE courses SET status = 'failed', error = ? WHERE course_id = ?",
                                (str(e)[:300], course_id))

    @staticmethod
    def _course_summary(row) -> dict:
        r = json.loads(row["report"]) if row["report"] else {}
        return {"id": row["course_id"], "name": row["name"], "source": row["source"], "link": row["link"] or None,
                "created_at": row["created_at"], "status": row["status"], "error": row["error"],
                "km": r.get("km"), "ascent_m": r.get("ascent_m"), "gravel_share": r.get("gravel_share"),
                "time_s": r.get("time_s"), "loop": r.get("loop"),
                "singletrack_km": round(sum(x["km"] for x in r.get("singletrack", [])), 1) if r else None,
                "plan": json.loads(row["plan"]) if row["plan"] else None,
                "verdict": r.get("verdict", [])[:3],
                "shape": _shape([s for st in r.get("stretches", []) for s in st["points"]]) if r else []}

    def courses(self, user_id: int) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM courses WHERE user_id = ? ORDER BY created_at DESC",
                                   (user_id,)).fetchall()
        return [self._course_summary(r) for r in rows]

    def course(self, user_id: int, course_id: int) -> Optional[dict]:
        row = self._course_row(user_id, course_id)
        if row is None:
            return None
        out = self._course_summary(row)
        out["report"] = json.loads(row["report"]) if row["report"] else None
        out["changes"] = [{"n": v["n"], "change": v["change"]} for v in self._versions(course_id) if v["n"] > 0]
        return out

    # --- loops from a description (rideengine/routes/request.py, generate.py) --------------------------
    # --- home: the one the rider set, else where most of the past year's rides start ------------
    def home_set(self, user_id: int) -> Optional[tuple]:
        with self.lock:
            row = self.db.execute("SELECT home FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None or not row["home"]:
            return None
        h = json.loads(row["home"])
        return (h["lat"], h["lon"])

    def home_point(self, user_id: int, vfeats: Optional[list] = None) -> Optional[tuple]:
        """Used for "from home", the home loop, local times and the ride card's privacy zone."""
        from rideengine.analysis import features as feat_mod
        from rideengine.analysis import repeats
        h = self.home_set(user_id)
        if h:
            return h
        if vfeats is None:
            with self.lock:
                feats = self.insights._features(user_id)
            visible = feat_mod.visible_ids(feats)
            vfeats = [f for f in feats if f["ride_id"] in visible]
        return repeats.home_point(vfeats)

    def home(self, user_id: int) -> dict:
        """{"lat", "lon", "label", "source": "set" | "rides" | None, "rides": starts near it (from rides)}."""
        from rideengine.analysis import features as feat_mod
        from rideengine.analysis import repeats
        with self.lock:
            row = self.db.execute("SELECT home FROM users WHERE id = ?", (user_id,)).fetchone()
            feats = self.insights._features(user_id)
        visible = feat_mod.visible_ids(feats)
        vfeats = [f for f in feats if f["ride_id"] in visible]
        if row and row["home"]:
            h = json.loads(row["home"])
            return {"lat": h["lat"], "lon": h["lon"], "label": h.get("label"), "source": "set", "rides": None}
        p = repeats.home_point(vfeats)
        if not p:
            return {"lat": None, "lon": None, "label": None, "source": None, "rides": 0}
        n = sum(1 for f in vfeats if not f["indoor"] and f.get("first")
                and repeats.haversine(*p, *f["first"]) <= repeats.HOME_M)
        from rideengine import places
        near = places.load((p[0] - 0.05, p[1] - 0.07, p[0] + 0.05, p[1] + 0.07))
        label = None
        if near:
            best = min(near, key=lambda x: repeats.haversine(*p, x["lat"], x["lon"]))
            label = "near " + best["name"]
        return {"lat": p[0], "lon": p[1], "label": label, "source": "rides", "rides": n}

    def set_home(self, user_id: int, lat: Optional[float], lon: Optional[float], label: Optional[str] = None) -> dict:
        """Set home (lat/lon, e.g. an address from Apple Maps), or None to go back to working it out from
        rides. The home loop and the notes that mention it are worked out again."""
        if lat is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("That isn't a place on the map.")
        value = json.dumps({"lat": round(lat, 6), "lon": round(lon, 6), "label": (label or "")[:120]}) \
            if lat is not None else None
        with self.lock:
            self.db.execute("UPDATE users SET home = ? WHERE id = ?", (value, user_id))
            self.insights._mark_dirty(user_id, 0)
        self.insights.schedule(user_id)
        return self.home(user_id)

    def _home(self, user_id: int) -> Optional[dict]:
        h = self.home_point(user_id)
        return {"name": "home", "lat": h[0], "lon": h[1]} if h else None

    def plan_routes(self, user_id: int, body: dict) -> dict:
        """body: {"text": "60-70 km gravel loop near Uxbridge, café halfway"} and/or {"ask": {...}} (what we
        understood last time) with {"answers": {"start": "Goodwood", "end": "Port Perry", "km": [60, 70],
        "surface": "gravel", "stop": "midway", "shape": "loop" | "oneway" | "out_back"}}. Returns what was
        understood ("ask", with "tags" and "missing") and either the questions still to answer, or the routes
        made (loops, one way, or there and back): each saved as a course and checked like any route."""
        from rideengine import places
        from rideengine.routes import generate as gen
        from rideengine.routes import request as req
        from rideengine.routes.course import gpx_course
        from rideengine.routes.elevation import Heights
        home = self._home(user_id)
        if body.get("ask"):
            ask = req.Ask.from_dict(body["ask"])
        else:
            ask = req.read(str(body.get("text") or ""), home=home)
        def place(v, label):
            if isinstance(v, dict) and "lat" in v:
                return {"name": str(v.get("name") or label), "lat": float(v["lat"]), "lon": float(v["lon"])}
            if str(v).strip().lower() in ("home", "back home") and home:
                return dict(home)
            found = [p for p in places.find(str(v)) if p["name"].lower() not in req.NOT_PLACES]
            if not found:
                raise ValueError(f"Couldn't find {v} in Ontario.")
            return {"name": found[0]["name"], "lat": found[0]["lat"], "lon": found[0]["lon"]}

        for k, v in (body.get("answers") or {}).items():
            if k in ("start", "end", "via"):
                ask.guess.pop(k, None)          # answered: no longer a guess
            if k == "start":
                ask.start = place(v, "the start")
            elif k == "end":
                ask.end = place(v, "the end")
            elif k == "via":
                ask.via = place(v, "the way")
            elif k == "shape" and v in ("loop", "oneway", "out_back"):
                ask.shape = v
            elif k == "km":
                lo, hi = (float(v[0]), float(v[1])) if isinstance(v, (list, tuple)) else (float(v) * 0.92, float(v) * 1.08)
                ask.km = (round(lo), round(hi))
            elif k == "surface" and v in req.SURFACES:
                ask.surface, ask.gravel = v, req.SURFACES[v]
            elif k == "stop":
                ask.stop = v if v in ("midway", "any") else None
            elif k == "hills":
                ask.hills = v if v in ("flat", "hilly") else None
            elif k == "climb":              # metres of climbing: [lo, hi], or one number (±15%)
                lo, hi = (float(v[0]), float(v[1])) if isinstance(v, (list, tuple)) else (float(v) * 0.85, float(v) * 1.15)
                ask.climb = (round(lo), round(hi))
            elif k == "gravel_start":       # little gravel around the start: somewhere else, or stay
                if v == "stay":
                    ask.stay = True
                else:
                    ask.start = place(v, "the start")
        ask.refresh()
        out = {"ask": ask.to_dict()}
        if ask.missing:
            out["questions"] = [{"key": k, **req.QUESTIONS[k], **({"guess": ask.guess[k]} if ask.guess.get(k) else {})}
                                for k in ask.missing]
            out["home"] = bool(home)
            return out
        q = self._gravel_question(user_id, ask, home)
        if q:
            out["questions"] = [q]
            return out
        box = gen.bbox_for(ask)
        prefs = gen.prefs_for(ask)
        if self.area_source:
            g, stops, names = self.area_source(box, prefs)
        else:
            from rideengine.routes.router import Graph
            g, stops, names = Graph.around(box, prefs=prefs), gen.pois_in(box), places.load(box)
        if not g.edges:
            raise ValueError("Planning works where we have our own map (Ontario) for now.")
        heights = self.heights or Heights()
        opts = gen.routes(ask, g, stops, names, heights=heights)
        if not opts:
            raise ValueError("Couldn't make a route from there; try another start or distance.")
        made = []
        batch = f"{int(db.now())}"
        from rideengine.routes.route import Route
        # Saved worst first, so the best is the newest and sits at the top of the list.
        for o in reversed(opts):
            pts = [(la, lo, round(heights.height(la, lo), 1)) for la, lo, _ in o.route.points]
            route = Route(name=o.route.name, points=pts, source="generated")
            plan = {"text": ask.text, "tags": ask.tags, "why": o.why, "stop": o.stop, "via": o.via, "batch": batch}
            c = self.add_course(user_id, gpx_course(route, {}), name=o.route.name, source="generated", plan=plan)
            made.append(self.course(user_id, c["id"]))
        out["courses"] = made[::-1]
        return out

    def _gravel_question(self, user_id: int, ask, home) -> Optional[dict]:
        """A gravel (or mixed) loop from somewhere with hardly any gravel within reach (the city): say so
        before making mostly paved routes, and offer starts where the gravel is."""
        from rideengine import places
        from rideengine.routes import gravelmap as gm
        if ask.stay or not ask.gravel or ask.gravel[0] < 0.2 or not ask.start:
            return None
        if ask.shape == "oneway" or (ask.shape == "out_back" and ask.end) or ask.via:
            return None                 # the rider chose where it goes
        grid = self.gravel_grid if self.gravel_grid is not None else gm.load()
        if not grid:
            return None
        r = gm.radius_km(ask.km)
        here = gm.share(grid, ask.start["lat"], ask.start["lon"], r)
        if not gm.poor(here, ask.gravel[0]):
            return None
        s = ask.start
        ridden = [tuple(f["first"]) for f in self.insights._features(user_id) if f.get("first") and not f.get("indoor")]
        near = places.load((s["lat"] - 0.9, s["lon"] - 1.2, s["lat"] + 0.9, s["lon"] + 1.2))
        alts = gm.starts(grid, near, (s["lat"], s["lon"]), ask.km, ask.gravel[0], ridden=ridden)
        where = "home" if home and s["lat"] == home["lat"] and s["lon"] == home["lon"] else s["name"]
        words = "gravel" if ask.surface == "gravel" else "unpaved roads"
        hint = (f"Within {r:.0f} km of {where} only about {max(1, round(here * 100))}% of roads are unpaved, so a "
                f"{ask.surface} loop from there comes out mostly paved.")
        if alts:
            hint += " These starts have plenty of " + words + " within reach" + (
                "; you've ridden from " + " and ".join(a["name"] for a in alts if a["ridden"]) + " before."
                if any(a["ridden"] for a in alts) else ".")
        choices = [{"label": f"{a['name']} · {a['km_away']} km {a['direction']}",
                    "value": {"name": a["name"], "lat": a["lat"], "lon": a["lon"]}} for a in alts]
        choices.append({"label": f"From {where} anyway", "value": "stay"})
        return {"key": "gravel_start", "q": f"Not much {words} near {where}", "hint": hint, "choices": choices}

    # --- tuning (rideengine/routes/tune.py): each change is a version, and can be undone ------------
    def _versions(self, course_id: int) -> list:
        with self.lock:
            return self.db.execute("SELECT * FROM course_versions WHERE course_id = ? ORDER BY n",
                                   (course_id,)).fetchall()

    def tune_course(self, user_id: int, course_id: int, op: dict) -> Optional[dict]:
        """op: {"op": "start", "lat", "lon", "label"} | {"op": "stop", "lat", "lon", "name"} |
        {"op": "length", "km": -10}. Raises TuneError (a message for the rider) when it can't."""
        from rideengine.routes import tune
        from rideengine.routes.course import gpx_course
        from rideengine.routes.router import Prefs
        row = self._course_row(user_id, course_id)
        if row is None:
            return None
        if row["status"] != "ready":
            raise tune.TuneError("The route needs checking first.")
        route = self._course_route(row)
        report = json.loads(row["report"])
        prefs = Prefs.for_mix(report.get("gravel_share"))
        g = self.graph_source(route, prefs) if self.graph_source else tune.graph_for(route, prefs=prefs)
        if not g.edges:
            raise tune.TuneError("Tuning works where we have our own map (Ontario) for now.")
        versions = self._versions(course_id)
        # Stops the rider added stay on the route through later changes.
        keep = [(json.loads(v["op"])["lat"], json.loads(v["op"])["lon"]) for v in versions
                if json.loads(v["op"]).get("op") == "stop"]
        kind = op.get("op")
        try:
            if kind == "start":
                t = tune.move_start(route, g, float(op["lat"]), float(op["lon"]), label=op.get("label"),
                                    heights=self.heights)
            elif kind == "stop":
                t = tune.add_stop(route, g, float(op["lat"]), float(op["lon"]), name=op.get("name") or "the stop",
                                  heights=self.heights)
            elif kind == "length":
                t = tune.change_length(route, g, float(op["km"]), heights=self.heights, keep=keep)
            else:
                raise tune.TuneError("Unknown change: start, stop or length.")
        except (KeyError, TypeError, ValueError) as e:
            if isinstance(e, tune.TuneError):
                raise
            raise tune.TuneError(f"That change needs more detail ({e}).")
        chosen = keep + ([(float(op["lat"]), float(op["lon"]))] if kind == "stop" else [])
        plan = json.loads(row["plan"]) if row["plan"] else {}
        if (plan.get("stop") or {}).get("lat") is not None:
            chosen.append((plan["stop"]["lat"], plan["stop"]["lon"]))
        new_report = self._course_report(user_id, t.route, chosen=chosen)
        folder = os.path.dirname(row["file"])
        with self.lock:
            if not versions:   # keep the route as it came in as version 0
                self.db.execute("INSERT INTO course_versions VALUES (?, 0, ?, 'As it came in', '{}', ?, ?)",
                                (course_id, row["file"], row["report"], row["created_at"]))
                n = 1
            else:
                n = versions[-1]["n"] + 1
            path = os.path.join(folder, f"{course_id}.v{n}.gpx")
            with open(path, "wb") as f:
                f.write(gpx_course(t.route, {}))
            self.db.execute("INSERT INTO course_versions VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (course_id, n, path, t.change, json.dumps(op), json.dumps(new_report), db.now()))
            self.db.execute("UPDATE courses SET file = ?, report = ? WHERE course_id = ?",
                            (path, json.dumps(new_report), course_id))
        return self.course(user_id, course_id)

    def undo_course(self, user_id: int, course_id: int) -> Optional[dict]:
        """Back to the version before the last change."""
        row = self._course_row(user_id, course_id)
        if row is None:
            return None
        versions = self._versions(course_id)
        if len(versions) < 2:
            return self.course(user_id, course_id)
        last, prev = versions[-1], versions[-2]
        with self.lock:
            self.db.execute("DELETE FROM course_versions WHERE course_id = ? AND n = ?", (course_id, last["n"]))
            self.db.execute("UPDATE courses SET file = ?, report = ? WHERE course_id = ?",
                            (prev["file"], prev["report"], course_id))
            if prev["n"] == 0:
                self.db.execute("DELETE FROM course_versions WHERE course_id = ?", (course_id,))
        if last["file"] != prev["file"] and os.path.exists(last["file"]):
            os.remove(last["file"])
        return self.course(user_id, course_id)

    def course_options(self, user_id: int, course_id: int) -> Optional[dict]:
        """What the rider can tune towards: stops near the route but off it (for "add a stop"), and
        places to start from (cafés on the route, towns it passes)."""
        from rideengine.model import haversine
        row = self._course_row(user_id, course_id)
        if row is None or not row["report"]:
            return None
        route = self._course_route(row)
        report = json.loads(row["report"])
        data = self._map(route, pad_m=3000)
        pts = route.resample(100)
        grid: dict = {}
        for p in pts:
            grid.setdefault((int(p[0] // 0.01), int(p[1] // 0.014)), []).append(p)
        stops = []
        for poi in data["pois"]:
            if poi["kind"] not in ("food", "shop", "water"):
                continue
            ci, cj = int(poi["lat"] // 0.01), int(poi["lon"] // 0.014)
            near = [q for di in (-1, 0, 1) for dj in (-1, 0, 1) for q in grid.get((ci + di, cj + dj), ())]
            if not near:
                continue
            q = min(near, key=lambda q: haversine(poi["lat"], poi["lon"], q[0], q[1]))
            off = haversine(poi["lat"], poi["lon"], q[0], q[1])
            if 60 < off <= 3000 and poi["name"]:
                stops.append({"name": poi["name"], "kind": poi["kind"], "what": poi["what"], "hours": poi["hours"],
                              "lat": round(poi["lat"], 6), "lon": round(poi["lon"], 6),
                              "km": round(q[3] / 1000, 1), "off_m": round(off)})
        coffee = {"cafe": 0, "bakery": 0, "coffee": 0, "ice_cream": 1}
        stops.sort(key=lambda x: (coffee.get(x["what"], 2), x["off_m"]))
        seen, picked = set(), []
        gap0 = report.get("longest_gap") or {}
        stops.sort(key=lambda x: (not (gap0.get("from_km", 1e9) + 5 <= x["km"] <= gap0.get("to_km", -1) - 5),
                                  coffee.get(x["what"], 2), x["off_m"]))
        for st in stops:
            if (st["name"], round(st["km"])) not in seen:
                seen.add((st["name"], round(st["km"])))
                picked.append(st)
        starts = [{"name": st["items"][0]["name"] + (f", {st['place']}" if st.get("place") else ""),
                   "lat": st["items"][0].get("lat", st["lat"]), "lon": st["items"][0].get("lon", st["lon"]),
                   "km": st["km"], "kind": "cafe"}
                  for st in report.get("stops", []) if st.get("food")]
        starts += [{"name": t["name"], "lat": None, "lon": None, "km": t["km"], "kind": "town"}
                   for t in report.get("towns", [])]
        for t in starts:   # towns: the route's point nearest the town's km
            if t["lat"] is None:
                q = min(pts, key=lambda q: abs(q[3] / 1000 - t["km"]))
                t["lat"], t["lon"] = round(q[0], 6), round(q[1], 6)
        # Stops that would fill the longest stretch with no food or water come first in the app.
        gap = report.get("longest_gap")
        if gap and gap["km"] < 25:
            gap = None
        for st in picked:
            st["fills_gap"] = bool(gap) and gap["from_km"] + 5 <= st["km"] <= gap["to_km"] - 5
        return {"stops": sorted(picked[:40], key=lambda x: x["km"]), "starts": sorted(starts, key=lambda x: x["km"]),
                "gap": gap and {"from_km": gap["from_km"], "to_km": gap["to_km"], "km": gap["km"]}}

    def rename_course(self, user_id: int, course_id: int, name: str) -> Optional[dict]:
        with self.lock:
            self.db.execute("UPDATE courses SET name = ? WHERE user_id = ? AND course_id = ?",
                            (name.strip()[:80], user_id, course_id))
        return self.course(user_id, course_id)

    def delete_course(self, user_id: int, course_id: int) -> bool:
        row = self._course_row(user_id, course_id)
        if row is None:
            return False
        files = {row["file"]} | {v["file"] for v in self._versions(course_id)}
        with self.lock:
            self.db.execute("DELETE FROM course_versions WHERE course_id = ?", (course_id,))
            self.db.execute("DELETE FROM courses WHERE course_id = ?", (course_id,))
        for f in files:
            if f and os.path.exists(f):
                os.remove(f)
        return True

    def course_file(self, user_id: int, course_id: int, kind: str = "fit") -> Optional[tuple[bytes, str]]:
        """(bytes, file name) of the course for a bike computer: FIT (Garmin, Wahoo, Hammerhead) or GPX."""
        from rideengine.routes.course import fit_course, gpx_course
        row = self._course_row(user_id, course_id)
        if row is None or not row["report"]:
            return None
        route = self._course_route(row)
        report = json.loads(row["report"])
        safe = _SAFE_ID.sub("_", row["name"]).strip("_")[:40] or "route"
        if kind == "gpx":
            return gpx_course(route, report), f"{safe}.gpx"
        return fit_course(route, report), f"{safe}.fit"

    def ride(self, user_id: int, ride_id: str) -> Optional[Ride]:
        with self.lock:
            row = self.db.execute("SELECT data FROM rides WHERE user_id = ? AND ride_id = ?",
                                  (user_id, ride_id)).fetchone()
        return Ride.from_json(db.unpack(row["data"])) if row else None

    def ride_id_for(self, user_id: int, start: float, end: float) -> Optional[str]:
        """The merged ride a recording ended up in (the one it overlaps most)."""
        with self.lock:
            row = self.db.execute(
                "SELECT ride_id, MIN(end_t, ?) - MAX(start_t, ?) AS o FROM rides WHERE user_id = ? "
                "AND end_t >= ? AND start_t <= ? ORDER BY o DESC LIMIT 1",
                (end, start, user_id, start, end)).fetchone()
        return row["ride_id"] if row else None


def _shape(points: list, n: int = 64) -> list[list[float]]:
    """A route's outline for thumbnails, in a unit square (x east, y south), like features.shape."""
    import math
    if len(points) < 2:
        return []
    picks = [points[int(i * (len(points) - 1) / n)] for i in range(n + 1)]
    k = math.cos(math.radians(sum(p[0] for p in picks) / len(picks)))
    xy = [(p[1] * k, -p[0]) for p in picks]
    xs, ys = [p[0] for p in xy], [p[1] for p in xy]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1e-9
    ox, oy = (span - (max(xs) - min(xs))) / 2, (span - (max(ys) - min(ys))) / 2
    return [[round((x - min(xs) + ox) / span, 3), round((y - min(ys) + oy) / span, 3)] for x, y in xy]


BRIEF_VERSION = 2   # bump when describe() or summary() change what they return: briefs are then redone


class _Shape:
    """Just enough of a ride for hidden_reasons() and effort grouping, from its brief."""

    def __init__(self, s: dict):
        self.start, self.end, self.indoor = s["start"], s["end"], s["indoor"]
        self.totals = {"distance_m": s["km"] * 1000, "moving_s": s["moving_s"]}
        self.samples: list = []


def brief(ride_id: str, ride: Ride) -> dict:
    """What the ride list needs, stored with each ride: describe(), and the ride's shape for hiding false
    starts and grouping efforts (the same km and moving time hidden_reasons() works out from the samples)."""
    km, moving = _size(ride)
    return {**describe(ride_id, ride), "v": BRIEF_VERSION,
            "shape": {"start": ride.start, "end": ride.end, "indoor": ride.indoor, "km": km, "moving_s": moving}}


def describe(ride_id: str, ride: Ride) -> dict:
    """A ride without its samples: summary, where each value came from, what it may be used for."""
    return {"ride_id": ride_id, "summary": summary(ride), "sources": sorted(sources_used(ride.provenance)),
            "provenance": ride.provenance, "recordings": ride.recordings, "excluded": ride.excluded, "added": ride.added,
            "use": {u: {"allowed": allowed(ride.provenance, u),
                        "blocked_by": sorted(blocked_sources(ride.provenance, u))} for u in ("ai", "share")}}


def records_entries(feats: list[dict], tz):
    from rideengine.analysis import records
    return records.entries_from_features(feats, tz)


def _feel(session: dict) -> Optional[str]:
    """How a session should feel (today.FEEL), with the hard parts' watts when they're known."""
    from rideengine.analysis import today as td
    feel = td.FEEL.get(session.get("kind"))
    hard = [x for st in session.get("steps") or [] for x in (st.get("steps") or [st])
            if (x.get("target") or {}).get("watts") and x.get("zone") not in ("Z1", "Z2")]
    if hard and feel:
        lo = min(x["target"]["watts"][0] for x in hard)
        hi = max(x["target"]["watts"][1] for x in hard)
        watts = f"about {lo}–{hi} W" if lo != hi else f"about {lo} W"
        head, sep, rest = feel.partition(";") if ";" in feel else feel.rstrip(".").partition("\0")
        feel = f"{head} ({watts}){sep}{rest}" + ("" if sep else ".")
    return feel
