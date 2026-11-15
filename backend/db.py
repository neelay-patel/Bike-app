"""Database: SQLite for development. The SQL is kept plain so it moves to Postgres with little change
(JSON text columns become jsonb, BLOB becomes bytea)."""
from __future__ import annotations

import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    created_at    REAL NOT NULL,
    token_hash    TEXT UNIQUE,          -- dev bearer token (sha256); Sign in with Apple comes with the app
    apple_sub     TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS connections (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    provider      TEXT NOT NULL,
    secret        BLOB NOT NULL,        -- encrypted credentials (crypto.Vault)
    status        TEXT NOT NULL,        -- connected | error
    detail        TEXT,                 -- last error or sync note, shown in the app
    created_at    REAL NOT NULL,
    last_sync_at  REAL,
    PRIMARY KEY (user_id, provider)
);
CREATE TABLE IF NOT EXISTS recordings (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    provider      TEXT NOT NULL,        -- connector that delivered it
    external_id   TEXT NOT NULL,        -- the provider's id for the activity
    source        TEXT NOT NULL,        -- rideengine source key (garmin, apple_watch, ...)
    start_t       REAL NOT NULL,
    end_t         REAL NOT NULL,
    raw_path      TEXT,                 -- original file as received, kept for re-processing
    data          TEXT NOT NULL,        -- Recording as JSON
    received_at   REAL NOT NULL,
    PRIMARY KEY (user_id, provider, external_id)
);
CREATE INDEX IF NOT EXISTS recordings_time ON recordings (user_id, start_t, end_t);
CREATE TABLE IF NOT EXISTS rides (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    ride_id       TEXT NOT NULL,        -- int(start) of the merged ride, as in the CLI store
    start_t       REAL NOT NULL,
    end_t         REAL NOT NULL,
    data          TEXT NOT NULL,        -- Ride as JSON
    PRIMARY KEY (user_id, ride_id)
);
CREATE INDEX IF NOT EXISTS rides_time ON rides (user_id, start_t, end_t);

-- Recordings the rider deleted (with their ride): kept so a later sync or upload doesn't bring them back.
CREATE TABLE IF NOT EXISTS deleted_recordings (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    provider      TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    start_t       REAL NOT NULL,
    end_t         REAL NOT NULL,
    deleted_at    REAL NOT NULL,
    PRIMARY KEY (user_id, provider, external_id)
);

-- The rider's goals (rideengine/analysis/goals.py). One active at a time; older ones kept as history.
CREATE TABLE IF NOT EXISTS goals (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    goal_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    data          TEXT NOT NULL,        -- objective, aspiration, the rider's words, tags, params, ready_by
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    REAL NOT NULL,
    ended_at      REAL
);
CREATE INDEX IF NOT EXISTS goals_user ON goals (user_id, active);

-- Recovery and fitness readings (VO2 max, HRV, resting heart rate, Cardio Recovery). Never shared.
CREATE TABLE IF NOT EXISTS metrics (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    provider      TEXT NOT NULL,
    external_id   TEXT NOT NULL,        -- the provider's id for the reading (HealthKit sample uuid)
    kind          TEXT NOT NULL,        -- rideengine.analysis.wellness.KINDS
    t             REAL NOT NULL,
    value         REAL NOT NULL,
    source        TEXT NOT NULL,
    received_at   REAL NOT NULL,
    PRIMARY KEY (user_id, provider, external_id)
);
CREATE INDEX IF NOT EXISTS metrics_kind ON metrics (user_id, kind, t);

-- Insights (backend/insights.py). Everything below is derived from the rides and can be rebuilt.
CREATE TABLE IF NOT EXISTS ride_features (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    ride_id       TEXT NOT NULL,
    start_t       REAL NOT NULL,
    data          TEXT NOT NULL,        -- rideengine.analysis.features.extract(ride)
    PRIMARY KEY (user_id, ride_id)
);
CREATE TABLE IF NOT EXISTS routes (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    route_id      TEXT NOT NULL,        -- stable once made
    auto_name     TEXT,
    custom_name   TEXT,                 -- the rider's own name, if they gave one
    data          TEXT NOT NULL,        -- grid cells, length, loop, home flags
    created_at    REAL NOT NULL,
    PRIMARY KEY (user_id, route_id)
);
CREATE TABLE IF NOT EXISTS route_laps (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    route_id      TEXT NOT NULL,
    ride_id       TEXT NOT NULL,
    start_t       REAL NOT NULL,
    data          TEXT NOT NULL,
    PRIMARY KEY (user_id, route_id, ride_id)
);
CREATE INDEX IF NOT EXISTS route_laps_ride ON route_laps (user_id, ride_id);
CREATE TABLE IF NOT EXISTS climbs (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    climb_id      TEXT NOT NULL,        -- stable once made
    auto_name     TEXT,
    custom_name   TEXT,
    data          TEXT NOT NULL,        -- start/finish gates, length, gain, path
    created_at    REAL NOT NULL,
    PRIMARY KEY (user_id, climb_id)
);
CREATE TABLE IF NOT EXISTS climb_attempts (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    climb_id      TEXT NOT NULL,
    ride_id       TEXT NOT NULL,
    at_t          REAL NOT NULL,        -- when the attempt started (a ride can go up twice)
    data          TEXT NOT NULL,
    PRIMARY KEY (user_id, climb_id, at_t)
);
CREATE INDEX IF NOT EXISTS climb_attempts_ride ON climb_attempts (user_id, ride_id);
CREATE TABLE IF NOT EXISTS ride_notes (
    user_id       INTEGER NOT NULL REFERENCES users(id),
    ride_id       TEXT NOT NULL,
    start_t       REAL NOT NULL,
    data          TEXT NOT NULL,        -- what's notable, as of the ride
    PRIMARY KEY (user_id, ride_id)
);
CREATE TABLE IF NOT EXISTS insight_state (
    user_id       INTEGER PRIMARY KEY REFERENCES users(id),
    dirty_from    REAL,                 -- notes from this time on need redoing (NULL: all up to date)
    gen           INTEGER NOT NULL DEFAULT 0,   -- bumped on every ride change
    updated_at    REAL
);
"""

# Columns added after the first release of a table: (table, column, definition).
MIGRATIONS = [
    ("users", "tz", "TEXT"),        # the rider's IANA time zone, e.g. America/Toronto
    ("users", "display_name", "TEXT"),  # shown on the rider card
    ("users", "avatar", "TEXT"),        # avatar spec as JSON (rideengine/card/avatar.py)
]


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    for table, column, definition in MIGRATIONS:
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    return conn


def now() -> float:
    return time.time()
