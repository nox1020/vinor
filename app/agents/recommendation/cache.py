from __future__ import annotations

import hashlib
import threading
import time

from app.agents.recommendation.config import recommendation_cache_enabled
from app.agents.recommendation.interfaces import RecommendationCache, RecommendationResult


class MemoryRecommendationCache(RecommendationCache):
    def __init__(self, *, ttl_sec: float = 120.0, max_entries: int = 64):
        self._ttl = float(ttl_sec)
        self._max = int(max_entries)
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, RecommendationResult]] = {}

    def get(self, key: str) -> RecommendationResult | None:
        if not recommendation_cache_enabled():
            return None
        now = time.monotonic()
        with self._lock:
            row = self._store.get(key)
            if not row:
                return None
            ts, result = row
            if now - ts > self._ttl:
                self._store.pop(key, None)
                return None
            return RecommendationResult(
                ok=result.ok,
                items=list(result.items),
                selected_property=result.selected_property,
                alternate_property=result.alternate_property,
                rejected=list(result.rejected),
                compact_hint=result.compact_hint,
                recommendation_tokens=result.recommendation_tokens,
                recommendation_time_ms=0,
                top_score=result.top_score,
                cache_hit=True,
                reuse_search=result.reuse_search,
                reuse_analysis=result.reuse_analysis,
                reuse_memory=result.reuse_memory,
                reuse_planning=result.reuse_planning,
                metadata=dict(result.metadata or {}),
                error=result.error,
            )

    def put(self, key: str, result: RecommendationResult) -> None:
        if not recommendation_cache_enabled():
            return
        with self._lock:
            if len(self._store) >= self._max:
                oldest = min(self._store.items(), key=lambda kv: kv[1][0])[0]
                self._store.pop(oldest, None)
            self._store[key] = (time.monotonic(), result)


def cache_key_for(codes: list[str], *, route: str = "", message: str = "") -> str:
    raw = "|".join(sorted(c.strip() for c in codes if c.strip()))
    blob = f"{route}:{raw}:{(message or '').strip()[:40]}"
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:24]
