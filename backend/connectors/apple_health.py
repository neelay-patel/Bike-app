"""Apple Health: no web API, so the iPhone app reads HealthKit (with the rider's permission) and
uploads each cycling workout as recording JSON (rideengine/importers/recording_json.py).

Read (the agreed scope, CLAUDE.md): cycling workouts with their route, heart rate, calories and
distance; heart rate in the 3 minutes after each ride; and VO2 max, HRV, resting heart rate and
Cardio Recovery, uploaded as metrics batches (parse_metrics). Nothing else.
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
METRICS_FORMAT = "rideengine.metrics/1"


class AppleHealth(Connector):
    info = ProviderInfo(
        key="apple_health", name="Apple Health", auth="device", status="available",
        gives="Route, heart rate every ~5 s, active calories, climbing (Apple Watch); "
              "VO2 max, HRV, resting heart rate, heart-rate recovery",
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

    def parse_metrics(self, payload: bytes) -> list[dict]:
        """A batch of recovery and fitness readings from the phone:
        {"format": "rideengine.metrics/1", "metrics": [{"id": <HealthKit uuid>, "kind": "hrv_sdnn",
        "t": <unix seconds>, "value": 52.3, "source": "apple_watch"}, ...]}.
        Only the agreed kinds are accepted (rideengine/analysis/wellness.KINDS); readings outside
        believable ranges are dropped."""
        from rideengine.analysis.wellness import valid
        if len(payload) > MAX_UPLOAD_BYTES:
            raise ConnectorError("Upload too large")
        try:
            d = json.loads(payload)
        except ValueError as exc:
            raise ConnectorError(f"Not valid JSON: {exc}") from exc
        if not isinstance(d, dict) or d.get("format") != METRICS_FORMAT or not isinstance(d.get("metrics"), list):
            raise ConnectorError(f"Expected {{'format': '{METRICS_FORMAT}', 'metrics': [...]}}")
        out = []
        for m in d["metrics"]:
            if not isinstance(m, dict) or not isinstance(m.get("id"), str) or not m["id"]:
                continue
            if m.get("source", "apple_watch") not in ALLOWED_SOURCES or not valid(m):
                continue
            out.append({"id": m["id"][:64], "kind": m["kind"], "t": float(m["t"]), "value": float(m["value"]),
                        "source": m.get("source", "apple_watch")})
        return out

