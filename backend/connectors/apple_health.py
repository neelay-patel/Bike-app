"""Apple Health: no web API, so the iPhone app reads HealthKit (with the rider's permission) and
uploads each cycling workout as recording JSON (rideengine/importers/recording_json.py).

Only cycling workouts and the heart rate recorded during them are read (the agreed scope).
Workouts other apps wrote into Health (Whoop, Oura, Garmin Connect...) keep their own source key,
set by the phone from the workout's HealthKit source, so source rules still apply.
"""
from __future__ import annotations

import json

from rideengine.importers.recording_json import recording_from_dict
from rideengine.model import Recording

from .base import Connector, ConnectorError, ProviderInfo

# Source keys the phone may report. Anything else is refused rather than trusted.
ALLOWED_SOURCES = {"apple_watch", "iphone", "whoop", "oura", "fitbit", "garmin", "wahoo", "hammerhead"}
MAX_UPLOAD_BYTES = 32 * 1024 * 1024


class AppleHealth(Connector):
    info = ProviderInfo(
        key="apple_health", name="Apple Health", auth="device", status="available",
        gives="Route, heart rate every ~5 s, active calories, climbing (Apple Watch)",
        notes="Connected in the iPhone app; new rides arrive in the background.")

    def parse_upload(self, payload: bytes) -> Recording:
        if len(payload) > MAX_UPLOAD_BYTES:
            raise ConnectorError("Upload too large")
        try:
            rec = recording_from_dict(json.loads(payload))
        except (ValueError, TypeError) as exc:
            raise ConnectorError(f"Not a valid recording: {exc}") from exc
        if rec.source not in ALLOWED_SOURCES:
            raise ConnectorError(f"Unknown source {rec.source!r}")
        if rec.sport != "cycling":
            raise ConnectorError("Only cycling workouts are accepted")
        if not rec.origin.startswith("healthkit:"):
            raise ConnectorError("origin must be 'healthkit:<workout uuid>'")
        return rec

    def normalize(self, path: str, external_id: str) -> Recording:
        with open(path, "rb") as f:
            return self.parse_upload(f.read())
