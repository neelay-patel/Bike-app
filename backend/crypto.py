"""Encryption at rest for provider credentials (API keys, OAuth tokens).

Dev: a key file created on first use (mode 0600). Hosted: set RIDE_SECRET_KEY (a Fernet key)
from the host's secret store instead.
"""
from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet


def load_key(path: str) -> bytes:
    env = os.environ.get("RIDE_SECRET_KEY")
    if env:
        return env.encode()
    if os.path.exists(path):
        return open(path, "rb").read().strip()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    key = Fernet.generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


class Vault:
    def __init__(self, key: bytes):
        self._f = Fernet(key)

    def seal(self, secret: dict) -> bytes:
        return self._f.encrypt(json.dumps(secret).encode())

    def open(self, blob: bytes) -> dict:
        return json.loads(self._f.decrypt(blob))
