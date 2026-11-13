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
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


def now() -> float:
    return time.time()
