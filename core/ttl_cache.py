"""Short memory for expensive library builds. A click should not scan the drive again."""

from __future__ import annotations


class TtlCache:
    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self.at = 0.0
        self.key = None
        self.payload = None

    def get(self, key, now: float):
        if self.payload is None or self.key != key:
            return None
        if now - self.at >= self.ttl:
            return None
        return self.payload

    def put(self, key, payload, now: float) -> None:
        self.key = key
        self.payload = payload
        self.at = now

    def clear(self) -> None:
        self.key = None
        self.payload = None
        self.at = 0.0
