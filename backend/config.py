"""Settings from environment variables, with dev defaults that keep everything under data/ (git-ignored)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    data_dir: str
    database: str
    raw_dir: str
    secret_key_file: str
    public_base_url: str

    @staticmethod
    def from_env() -> "Settings":
        data = os.environ.get("RIDE_DATA_DIR", "data/backend")
        return Settings(
            data_dir=data,
            database=os.environ.get("RIDE_DATABASE", os.path.join(data, "rides.sqlite3")),
            raw_dir=os.environ.get("RIDE_RAW_DIR", os.path.join(data, "raw")),
            secret_key_file=os.environ.get("RIDE_SECRET_KEY_FILE", os.path.join(data, "secret.key")),
            public_base_url=os.environ.get("RIDE_PUBLIC_BASE_URL", "http://localhost:8000"),
        )
