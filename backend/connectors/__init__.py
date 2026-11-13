"""Every provider the app offers, in the order the Connections screen shows them.

"available" connectors work now; "planned" ones are listed so the app can show them as coming soon;
"blocked" means no route in yet (see notes). Details and order of work: docs/connectors.md.
"""
from __future__ import annotations

from .apple_health import AppleHealth
from .base import Connector, ConnectorError, Fetched, ProviderInfo
from .garmin_personal import GarminPersonal


class Planned(Connector):
    def __init__(self, info: ProviderInfo):
        self.info = info


PLANNED = [
    ProviderInfo("garmin", "Garmin", "oauth2", "planned",
                 "Original .FIT files and summaries, pushed by Garmin as rides sync",
                 "Starter tier: free up to ~1,000 riders, no history before connecting."),
    ProviderInfo("wahoo", "Wahoo", "oauth2", "planned",
                 "Original .FIT files from ELEMNT and KICKR (power)",
                 "Needs Wahoo's app review before going live."),
    ProviderInfo("hammerhead", "Hammerhead Karoo", "oauth2", "blocked",
                 "Original ride files",
                 "No public API. Asking SRAM for partner access; aggregator as fallback."),
    ProviderInfo("whoop", "WHOOP", "oauth2", "planned",
                 "Workout totals: average and max heart rate, energy, zones",
                 "No heart-rate stream in WHOOP's API."),
    ProviderInfo("oura", "Oura", "oauth2", "planned",
                 "Workouts and heart rate over time",
                 "Membership needed on newer rings. Terms appear to bar AI use."),
    ProviderInfo("google_health", "Fitbit (Google)", "oauth2", "planned",
                 "Exercise sessions, heart rate, GPS route",
                 "Google Health API; Restricted scopes need Google's review before launch."),
]

_LIVE: list[Connector] = [AppleHealth(), GarminPersonal()]
REGISTRY: dict[str, Connector] = {c.info.key: c for c in _LIVE}
REGISTRY.update({i.key: Planned(i) for i in PLANNED})


def get(key: str) -> Connector:
    try:
        return REGISTRY[key]
    except KeyError:
        raise ConnectorError(f"Unknown provider {key!r}") from None


__all__ = ["REGISTRY", "get", "Connector", "ConnectorError", "Fetched", "ProviderInfo"]
