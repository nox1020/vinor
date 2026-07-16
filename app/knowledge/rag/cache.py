from __future__ import annotations

import time


class TTLCache:
    def __init__(self, ttl_sec: int = 120, max_items: int = 512):
        self.ttl_sec = max(1, int(ttl_sec))
        self.max_items = max(32, int(max_items))
        self._store: dict[str, tuple[float, list[str]]] = {}

    def get(self, key: str) -> list[str] | None:
        item = self._store.get(key)
        if not item:
            return None
        exp, value = item
        if exp < time.time():
            self._store.pop(key, None)
            return None
        return list(value)

    def set(self, key: str, value: list[str]) -> None:
        if len(self._store) >= self.max_items:
            oldest_key = min(self._store.items(), key=lambda x: x[1][0])[0]
            self._store.pop(oldest_key, None)
        self._store[key] = (time.time() + self.ttl_sec, list(value))

