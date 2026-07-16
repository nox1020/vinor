from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

from app.agents.analysis.config import analysis_cache_enabled
from app.agents.analysis.interfaces import AnalysisCache, AnalysisResult


class MemoryAnalysisCache(AnalysisCache):
    """In-process TTL cache — avoids re-analysis of same codes in a short window."""

    def __init__(self, *, ttl_sec: float = 120.0, max_entries: int = 64):
        self._ttl = float(ttl_sec)
        self._max = int(max_entries)
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, AnalysisResult]] = {}

    def get(self, key: str) -> AnalysisResult | None:
        if not analysis_cache_enabled():
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
            # Return a shallow copy flagging cache hit
            hit = AnalysisResult(
                ok=result.ok,
                property_codes=list(result.property_codes),
                categories=list(result.categories),
                comparison=result.comparison,
                compact_hint=result.compact_hint,
                analysis_tokens=result.analysis_tokens,
                analysis_time_ms=0,
                cache_hit=True,
                reused_context=result.reused_context,
                reused_rag=result.reused_rag,
                reused_memory=result.reused_memory,
                reused_planning=result.reused_planning,
                metadata=dict(result.metadata or {}),
                error=result.error,
            )
            return hit

    def put(self, key: str, result: AnalysisResult) -> None:
        if not analysis_cache_enabled():
            return
        with self._lock:
            if len(self._store) >= self._max:
                # Drop oldest
                oldest = min(self._store.items(), key=lambda kv: kv[1][0])[0]
                self._store.pop(oldest, None)
            self._store[key] = (time.monotonic(), result)


def cache_key_for(codes: list[str], *, route: str = "", message: str = "") -> str:
    raw = "|".join(sorted(c.strip() for c in codes if c.strip()))
    msg_bit = (message or "").strip()[:40]
    blob = f"{route}:{raw}:{msg_bit}"
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:24]
