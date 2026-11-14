"""Insights kept up to date as rides arrive, for every rider: stored, incremental, in the background.

When rides change (Backend.remerge calls rides_changed):
  - each new or rebuilt ride's features are extracted once (rideengine.analysis.features) and stored;
  - it's matched to the routes the rider already has, and timed on their known climbs;
  - the rider is marked dirty from that ride's start, and a refresh is scheduled.
A refresh (worker thread on the server, inline in tests and the CLI):
  - finds new routes and climbs among the rider's rides (repeats.discover_*), names them once
    (GeoNames), and stores them with ids that never change;
  - works out which route is the home loop;
  - redoes the notes of rides from the dirty point on (a ride's notes only depend on earlier rides).
Reads (/v1/you, notes on rides) only read what's stored, so they stay fast.

The algorithm is the engine's (rideengine/analysis/repeats.py, records.py); this module only stores.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import tzinfo
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rideengine.analysis import features as feat_mod
from rideengine.analysis import records, repeats
from rideengine.analysis.repeats import Track
from rideengine.model import Ride

from . import db

log = logging.getLogger("uvicorn.error")
DEBOUNCE_S = 1.5        # a sync delivers many rides at once: wait for the burst, then refresh once
NOTES_MARGIN_S = 86400  # redo notes from a day before the change (false starts depend on neighbours)


class Insights:
    def __init__(self, backend, background: bool = False):
        self.be = backend
        self.db = backend.db
        self.lock = backend.lock
        self.background = background
        self._pending: set[int] = set()
        self._cv = threading.Condition()
        if background:
            threading.Thread(target=self._worker, name="insights", daemon=True).start()
            for row in self.db.execute("SELECT id FROM users"):
                self.schedule(row["id"])  # catch up on anything left over (or never built)

    # --- writes, as rides change ---------------------------------------------------------------
    def rides_changed(self, user_id: int, removed_ids: list[str], rides: list[Ride]) -> None:
        """Called inside Backend.lock after a re-merge replaced `removed_ids` with `rides`."""
        for rid in removed_ids:
            self._forget(user_id, rid)
        if not removed_ids and not rides:
            return
        routes = self._routes(user_id)
        climbs = self._climbs(user_id)
        for ride in rides:
            self._add(user_id, ride, feat_mod.extract(ride), routes, climbs)
        starts = [float(r) for r in removed_ids] + [r.start for r in rides]
        self._mark_dirty(user_id, min(starts))

    def _add(self, user_id: int, ride: Ride, f: dict, routes: list[dict], climbs: list[dict]) -> None:
        rid = f["ride_id"]
        self.db.execute("INSERT OR REPLACE INTO ride_features (user_id, ride_id, start_t, data) VALUES (?, ?, ?, ?)",
                        (user_id, rid, f["start"], json.dumps(f)))
        route_id = repeats.match_route(f, routes)
        if route_id:
            self._insert_lap(user_id, repeats.lap(f, route_id))
        track = None
        for c in climbs:
            if repeats.may_pass(f, c):
                track = track or Track.of(ride)
                for a in repeats.time_climb(track, c):
                    self._insert_attempt(user_id, a)

    def _forget(self, user_id: int, ride_id: str) -> None:
        for table in ("ride_features", "route_laps", "climb_attempts", "ride_notes"):
            self.db.execute(f"DELETE FROM {table} WHERE user_id = ? AND ride_id = ?", (user_id, ride_id))

    def _insert_lap(self, user_id: int, lap: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO route_laps (user_id, route_id, ride_id, start_t, data) "
                        "VALUES (?, ?, ?, ?, ?)", (user_id, lap["route_id"], lap["ride_id"], lap["start"], json.dumps(lap)))

    def _insert_attempt(self, user_id: int, a: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO climb_attempts (user_id, climb_id, ride_id, at_t, data) "
                        "VALUES (?, ?, ?, ?, ?)", (user_id, a["climb_id"], a["ride_id"], a["at"], json.dumps(a)))

    def _mark_dirty(self, user_id: int, since: float) -> None:
        self.db.execute(
            "INSERT INTO insight_state (user_id, dirty_from, gen) VALUES (?, ?, 1) ON CONFLICT (user_id) DO UPDATE "
            "SET dirty_from = MIN(COALESCE(dirty_from, excluded.dirty_from), excluded.dirty_from), gen = gen + 1",
            (user_id, since))

    # --- reading stored rows ----------------------------------------------------------------------
    def _features(self, user_id: int) -> list[dict]:
        return [json.loads(r["data"]) for r in self.db.execute(
            "SELECT data FROM ride_features WHERE user_id = ? ORDER BY start_t", (user_id,))]

    def _routes(self, user_id: int) -> list[dict]:
        return [{**json.loads(r["data"]), "auto_name": r["auto_name"], "custom_name": r["custom_name"]}
                for r in self.db.execute("SELECT * FROM routes WHERE user_id = ?", (user_id,))]

    def _climbs(self, user_id: int) -> list[dict]:
        return [{**json.loads(r["data"]), "auto_name": r["auto_name"], "custom_name": r["custom_name"]}
                for r in self.db.execute("SELECT * FROM climbs WHERE user_id = ?", (user_id,))]

    def _laps(self, user_id: int) -> list[dict]:
        return [json.loads(r["data"]) for r in self.db.execute(
            "SELECT data FROM route_laps WHERE user_id = ?", (user_id,))]

    def _attempts(self, user_id: int) -> list[dict]:
        return [json.loads(r["data"]) for r in self.db.execute(
            "SELECT data FROM climb_attempts WHERE user_id = ?", (user_id,))]

    def _state(self, user_id: int):
        return self.db.execute("SELECT dirty_from, gen FROM insight_state WHERE user_id = ?", (user_id,)).fetchone()

    def tz(self, user_id: int) -> Optional[tzinfo]:
        row = self.db.execute("SELECT tz FROM users WHERE id = ?", (user_id,)).fetchone()
        try:
            return ZoneInfo(row["tz"]) if row and row["tz"] else None
        except ZoneInfoNotFoundError:
            return None

    # --- background refresh ---------------------------------------------------------------------
    def schedule(self, user_id: int) -> None:
        if not self.background:
            self.refresh(user_id)
            return
        with self._cv:
            self._pending.add(user_id)
            self._cv.notify()

    def _worker(self) -> None:
        while True:
            with self._cv:
                while not self._pending:
                    self._cv.wait()
            time.sleep(DEBOUNCE_S)
            with self._cv:
                users, self._pending = self._pending, set()
            for uid in users:
                try:
                    if not self.refresh(uid):
                        self.schedule(uid)  # rides changed while it ran: go again
                except Exception:
                    log.exception("insights refresh failed for user %s", uid)

    def _catch_up(self, user_id: int) -> None:
        """Rides with no stored features (stored before insights existed, or extracted by an older
        engine): extract them now, as if they had just arrived."""
        with self.lock:
            have = {r["ride_id"]: json.loads(r["data"]).get("v") for r in self.db.execute(
                "SELECT ride_id, data FROM ride_features WHERE user_id = ?", (user_id,))}
            todo = [r["ride_id"] for r in self.db.execute("SELECT ride_id FROM rides WHERE user_id = ?", (user_id,))
                    if have.get(r["ride_id"]) != feat_mod.VERSION]
        for rid in todo:
            ride = self.be.ride(user_id, rid)
            if ride is None:
                continue
            f = feat_mod.extract(ride)
            with self.lock:
                self._add(user_id, ride, f, self._routes(user_id), self._climbs(user_id))
                self._mark_dirty(user_id, ride.start)

    def refresh(self, user_id: int) -> bool:
        """Bring one rider's routes, climbs and notes up to date. Returns False if rides changed while
        it ran (nothing was written; run it again)."""
        self._catch_up(user_id)
        with self.lock:
            st = self._state(user_id)
            if st is None or st["dirty_from"] is None:
                return True
            dirty, gen = st["dirty_from"], st["gen"]
            feats = self._features(user_id)
            routes, laps = self._routes(user_id), self._laps(user_id)
            climbs, attempts = self._climbs(user_id), self._attempts(user_id)
            tz = self.tz(user_id)

        # The slow part, without holding the lock: discovery loads only the rides it needs.
        visible = feat_mod.visible_ids(feats)
        vfeats = [f for f in feats if f["ride_id"] in visible]
        by_id = {f["ride_id"]: f for f in feats}

        def load_track(rid: str) -> Optional[Track]:
            ride = self.be.ride(user_id, rid)
            return Track.of(ride) if ride else None

        new_routes = repeats.discover_routes(vfeats, {l["ride_id"] for l in laps})
        new_climbs = repeats.discover_climbs(vfeats, climbs, load_track)
        before = {r["id"]: (r.get("home"), r.get("from_home")) for r in routes}
        for r, ls in new_routes:
            routes.append(r)
            laps += ls
            dirty = min([dirty] + [l["start"] for l in ls])
        for c, at in new_climbs:
            climbs.append(c)
            attempts += at
            dirty = min([dirty] + [a["start"] for a in at])
        # Home first: a new route that starts at home is named "Home loop via ...".
        repeats.update_home(vfeats, routes, laps)
        for r in routes:
            if r["id"] in before and before[r["id"]] != (r["home"], r["from_home"]):  # "home loop" in notes
                dirty = min([dirty] + [l["start"] for l in laps if l["route_id"] == r["id"]])
        if new_routes or new_climbs:
            places = repeats.load_places(repeats.place_boxes([r for r, _ in new_routes], [c for c, _ in new_climbs], by_id))
            for r, _ in new_routes:
                ref = self.be.ride(user_id, r["ref_ride_id"])
                r["auto_name"] = repeats.name_route(r, ref, places) if ref else None
            for c, _ in new_climbs:
                c["auto_name"] = repeats.name_climb(c, places)
        # A route or climb whose rides are all gone (e.g. a provider disconnected) goes too.
        routes = [r for r in routes if any(l["route_id"] == r["id"] for l in laps)]
        climbs = [c for c in climbs if any(a["climb_id"] == c["id"] for a in attempts)]

        found = repeats.assemble(routes, laps, climbs, attempts, visible=visible)
        es = records.entries_from_features(vfeats, tz)
        since = dirty - NOTES_MARGIN_S
        notes = records.notes_for(es, found, tz, since=since)

        with self.lock:
            st = self._state(user_id)
            if st is None or st["gen"] != gen:
                return False
            new_route_ids = {r["id"] for r, _ in new_routes}
            new_climb_ids = {c["id"] for c, _ in new_climbs}
            self.db.execute("DELETE FROM routes WHERE user_id = ?", (user_id,))
            for r in routes:
                data = {k: v for k, v in r.items() if k not in ("auto_name", "custom_name")}
                self.db.execute("INSERT INTO routes (user_id, route_id, auto_name, custom_name, data, created_at) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                (user_id, r["id"], r.get("auto_name"), r.get("custom_name"), json.dumps(data), db.now()))
            self.db.execute("DELETE FROM climbs WHERE user_id = ?", (user_id,))
            for c in climbs:
                data = {k: v for k, v in c.items() if k not in ("auto_name", "custom_name")}
                self.db.execute("INSERT INTO climbs (user_id, climb_id, auto_name, custom_name, data, created_at) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                (user_id, c["id"], c.get("auto_name"), c.get("custom_name"), json.dumps(data), db.now()))
            for r, ls in new_routes:
                for l in ls:
                    self._insert_lap(user_id, l)
            for c, at in new_climbs:
                for a in at:
                    self._insert_attempt(user_id, a)
            self.db.execute("DELETE FROM ride_notes WHERE user_id = ? AND start_t >= ?", (user_id, since))
            for e in es:
                if e.ride_id in notes:
                    self.db.execute("INSERT OR REPLACE INTO ride_notes (user_id, ride_id, start_t, data) "
                                    "VALUES (?, ?, ?, ?)", (user_id, e.ride_id, e.start, json.dumps(notes[e.ride_id])))
            self.db.execute("UPDATE insight_state SET dirty_from = NULL, updated_at = ? WHERE user_id = ?",
                            (db.now(), user_id))
        if new_route_ids or new_climb_ids:
            log.info("insights: user %s: %d new routes, %d new climbs", user_id, len(new_route_ids), len(new_climb_ids))
        return True

    def rebuild(self, user_id: int) -> None:
        """Forget every derived row for this rider (custom names kept) and build again from the rides."""
        with self.lock:
            names = {("r", r["route_id"]): r["custom_name"] for r in self.db.execute(
                "SELECT route_id, custom_name FROM routes WHERE user_id = ? AND custom_name IS NOT NULL", (user_id,))}
            names |= {("c", r["climb_id"]): r["custom_name"] for r in self.db.execute(
                "SELECT climb_id, custom_name FROM climbs WHERE user_id = ? AND custom_name IS NOT NULL", (user_id,))}
            for table in ("ride_features", "routes", "route_laps", "climbs", "climb_attempts", "ride_notes",
                          "insight_state"):
                self.db.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        self._catch_up(user_id)
        self.refresh(user_id)
        with self.lock:
            for (kind, key), name in names.items():
                table, col = ("routes", "route_id") if kind == "r" else ("climbs", "climb_id")
                self.db.execute(f"UPDATE {table} SET custom_name = ? WHERE user_id = ? AND {col} = ?", (name, user_id, key))
            if names:
                self._mark_dirty(user_id, 0)
        if names:
            self.refresh(user_id)

    # --- reads -----------------------------------------------------------------------------------
    def _found(self, user_id: int, visible: set[str]) -> dict:
        return repeats.assemble(self._routes(user_id), self._laps(user_id), self._climbs(user_id),
                                self._attempts(user_id), visible=visible)

    def you(self, user_id: int) -> dict:
        with self.lock:
            feats = self._features(user_id)
            visible = feat_mod.visible_ids(feats)
            found = self._found(user_id, visible)
            tz = self.tz(user_id)
            es = records.entries_from_features([f for f in feats if f["ride_id"] in visible], tz)
            recent = {e.ride_id for e in es[-5:]}
            notes = {r["ride_id"]: json.loads(r["data"]) for r in self.db.execute(
                "SELECT ride_id, data FROM ride_notes WHERE user_id = ?", (user_id,)) if r["ride_id"] in recent}
            st = self._state(user_id)
        out = records.you_from(es, found, notes, tz=tz)
        out["updating"] = bool(st and st["dirty_from"] is not None)
        return out

    def notes(self, user_id: int) -> dict[str, list[dict]]:
        with self.lock:
            return {r["ride_id"]: json.loads(r["data"]) for r in self.db.execute(
                "SELECT ride_id, data FROM ride_notes WHERE user_id = ?", (user_id,))}

    def rename(self, user_id: int, kind: str, item_id: str, name: Optional[str]) -> bool:
        """The rider's own name for a route or climb (None or "" goes back to the automatic one)."""
        table, col, child, when = ("routes", "route_id", "route_laps", "start_t") if kind == "route" else \
            ("climbs", "climb_id", "climb_attempts", "at_t")
        name = (name or "").strip()[:60] or None
        with self.lock:
            cur = self.db.execute(f"UPDATE {table} SET custom_name = ? WHERE user_id = ? AND {col} = ?",
                                  (name, user_id, item_id))
            if not cur.rowcount:
                return False
            first = self.db.execute(f"SELECT MIN({when}) AS t FROM {child} WHERE user_id = ? AND {col} = ?",
                                    (user_id, item_id)).fetchone()["t"]
            self._mark_dirty(user_id, first or 0)  # notes mention the name
        self.schedule(user_id)
        return True

    def set_tz(self, user_id: int, tz: str) -> None:
        ZoneInfo(tz)  # raises for an unknown zone
        with self.lock:
            old = self.db.execute("SELECT tz FROM users WHERE id = ?", (user_id,)).fetchone()["tz"]
            if old == tz:
                return
            self.db.execute("UPDATE users SET tz = ? WHERE id = ?", (tz, user_id))
            self._mark_dirty(user_id, 0)  # dates, years and "since June" all depend on it
        self.schedule(user_id)
