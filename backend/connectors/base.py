"""What every provider connector implements.

A connector does three things:
1. `connect(credentials)`: check what the rider gave us (API key, OAuth code...) and return the
   secret to store (encrypted) for later syncs.
2. `fetch(secret, since, known)`: yield new activities as original files (`Fetched`), skipping
   provider ids we already have. It may refresh tokens in `secret` in place; the caller saves it.
3. `normalize(path, external_id)`: turn a stored original file into a rideengine `Recording`.
   Kept separate from fetching so stored files can be re-processed when the engine improves.

Device connectors (Apple Health) have no fetch: the phone uploads, and only normalize runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, Optional

from rideengine.model import Recording


@dataclass(frozen=True)
class ProviderInfo:
    key: str            # stable id used in URLs and the database
    name: str           # shown in the app
    auth: str           # "device" | "api_key" | "oauth2" | "none"
    status: str         # "available" | "planned" | "blocked"
    gives: str          # what data we get, in plain words
    notes: str = ""     # catches, shown to us (and maybe the rider)


@dataclass
class Fetched:
    external_id: str
    kind: str           # file extension of the original: "fit", "gpx", "json"
    content: bytes


class ConnectorError(Exception):
    """Something the rider or we can act on (bad key, provider down...). Message is user-safe."""


class Connector:
    info: ProviderInfo

    def connect(self, credentials: dict) -> dict:
        raise ConnectorError(f"{self.info.name} can't be connected yet")

    def fetch(self, secret: dict, since: Optional[str], known: Callable[[str], bool]) -> Iterator[Fetched]:
        """Yield new activities. May update `secret` in place (e.g. refreshed token)."""
        return iter(())

    def normalize(self, path: str, external_id: str) -> Recording:
        raise NotImplementedError
