"""Garmin Connect Personal API: one rider's own activities, pulled with a personal API key.

Garmin's terms: the Personal tier is for "your own use" and "not intended for commercial
applications serving multiple end users". So this connector is for Neelay's account while we
build; other riders connect through the Starter tier (OAuth + push), which comes next.

API details from Garmin's official client (github.com/garmin/connect-personal-api-python):
- POST /personalapitoken-service/personal-api/personal-api-key/token, header "Authorization: ApiKey
  <key>" returns a JWT access token (plain text) valid 24 h; no refresh tokens.
- GET /activitylist-service/activities/search/activities?start&limit&startDate&endDate&activityType
- GET /download-service/files/activity/<id> returns the original file inside a ZIP.
"""
from __future__ import annotations

import base64
import io
import json
import time
import zipfile
from datetime import date
from typing import Callable, Iterator, Optional

import httpx

from rideengine.importers.fit import read_fit
from rideengine.importers.gpx import read_gpx
from rideengine.model import Recording

from .base import Connector, ConnectorError, Fetched, ProviderInfo

BASE_URL = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
SEARCH_PATH = "/activitylist-service/activities/search/activities"
DOWNLOAD_PATH = "/download-service/files/activity/{id}"
PAGE = 100
REFRESH_WITHIN_S = 3600
MAX_FILE_BYTES = 64 * 1024 * 1024  # a 10-hour 1 Hz FIT is a few MB; refuse anything absurd


def _jwt_exp(token: str) -> float:
    try:
        part = token.split(".")[1]
        return float(json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))["exp"])
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise ConnectorError("Garmin returned an unexpected token") from exc


class GarminPersonal(Connector):
    info = ProviderInfo(
        key="garmin_personal", name="Garmin (personal key)", auth="api_key", status="available",
        gives="Original .FIT files: route, barometric climbing, speed, power, temperature",
        notes="Your own account only (Garmin's Personal tier). Other riders use Garmin sign-in.")

    def __init__(self, client: Optional[httpx.Client] = None, clock: Callable[[], float] = time.time):
        self.http = client or httpx.Client(base_url=BASE_URL, timeout=30.0)
        self.clock = clock

    def _send(self, method: str, path: str, **kw) -> httpx.Response:
        """One HTTP call; network and TLS failures become a message the rider can act on."""
        try:
            return self.http.request(method, path, **kw)
        except httpx.HTTPError as exc:
            hint = " (this Python's TLS library is too old: use Python 3.11+)" \
                if "PROTOCOL_VERSION" in str(exc) else ""
            raise ConnectorError(f"Couldn't reach Garmin{hint}: {type(exc).__name__}") from exc

    # --- auth -------------------------------------------------------------------------------
    def _token(self, api_key: str) -> dict:
        r = self._send("POST", TOKEN_PATH, headers={"Accept": "*/*", "Authorization": f"ApiKey {api_key}"})
        if r.status_code in (401, 403):
            # Describe the key's shape (never the key) so a bad copy-paste is easy to spot.
            parts = len(api_key.split("."))
            raise ConnectorError(
                f"Garmin didn't accept that personal API key ({r.status_code}). Check it hasn't expired "
                f"or been deleted. Received {len(api_key)} characters starting '{api_key[:5]}', "
                f"in {parts} dot-separated parts.")
        if r.status_code >= 400:
            raise ConnectorError(f"Garmin token request failed ({r.status_code})")
        token = r.text.strip()
        return {"access_token": token, "expires_at": _jwt_exp(token)}

    def connect(self, credentials: dict) -> dict:
        key = (credentials.get("api_key") or "").strip()
        if not key:
            raise ConnectorError("Paste the personal API key from Garmin Connect settings.")
        if key.count("GCDC_") > 1:  # hidden prompts make it easy to paste twice
            raise ConnectorError(f"That looks like the key pasted {key.count('GCDC_')} times. Paste it once.")
        return {"api_key": key, **self._token(key)}

    def _bearer(self, secret: dict) -> dict:
        if secret.get("expires_at", 0) - self.clock() < REFRESH_WITHIN_S:
            secret.update(self._token(secret["api_key"]))
        return {"Authorization": f"Bearer {secret['access_token']}"}

    def _get(self, secret: dict, path: str, **kw) -> httpx.Response:
        extra = kw.pop("headers", {})
        r = self._send("GET", path, headers={**self._bearer(secret), **extra}, **kw)
        if r.status_code == 401:  # token revoked early: one fresh try
            secret["expires_at"] = 0
            r = self._send("GET", path, headers={**self._bearer(secret), **extra}, **kw)
        if r.status_code == 429:
            raise ConnectorError("Garmin is rate-limiting us; the next sync will carry on.")
        if r.status_code >= 400:
            raise ConnectorError(f"Garmin request failed ({r.status_code}) for {path.split('?')[0]}")
        return r

    # --- fetch ------------------------------------------------------------------------------
    def list_rides(self, secret: dict, since: Optional[str]) -> Iterator[dict]:
        params = {"limit": PAGE, "activityType": "cycling", "endDate": date.today().isoformat()}
        if since:
            params["startDate"] = since
        start = 0
        while True:
            page = self._get(secret, SEARCH_PATH, params={**params, "start": start}).json() or []
            yield from page
            if len(page) < PAGE:
                return
            start += PAGE

    def fetch(self, secret: dict, since: Optional[str], known: Callable[[str], bool]) -> Iterator[Fetched]:
        for act in self.list_rides(secret, since):
            aid = str(act.get("activityId", ""))
            if not aid.isdecimal() or known(aid):
                continue
            r = self._get(secret, DOWNLOAD_PATH.format(id=aid),
                          headers={"Accept": "application/zip, application/x-zip-compressed, application/octet-stream"})
            got = _unzip_activity(r.content)
            if got:
                yield Fetched(external_id=aid, kind=got[0], content=got[1])

    # --- normalize --------------------------------------------------------------------------
    def normalize(self, path: str, external_id: str) -> Recording:
        rec = read_gpx(path, source="garmin", device="Garmin (GPX)") if path.endswith(".gpx") \
            else read_fit(path, source="garmin", device="Garmin (FIT)")
        rec.origin = f"garmin:{external_id}"
        return rec


def _unzip_activity(blob: bytes) -> Optional[tuple[str, bytes]]:
    """The original file from Garmin's download ZIP: (kind, bytes), FIT preferred."""
    if blob[:4] != b"PK\x03\x04":  # not a zip: some endpoints may hand back the file itself
        return ("fit", blob) if blob[8:12] == b".FIT" else None
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        for ext in ("fit", "gpx"):
            for m in members:
                if m.filename.lower().endswith("." + ext):
                    if m.file_size > MAX_FILE_BYTES:
                        raise ConnectorError(f"Garmin file too large ({m.file_size} bytes)")
                    return ext, zf.read(m)
    return None
