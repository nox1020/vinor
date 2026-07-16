from __future__ import annotations

import hashlib
import threading
import time

from app.agents.customer_memory.config import customer_memory_cache_enabled
from app.agents.customer_memory.interfaces import CustomerMemoryCache, CustomerProfile


class MemoryCustomerProfileCache(CustomerMemoryCache):
    """In-process profile cache — NOT a Memory Layer store."""

    def __init__(self, *, ttl_sec: float = 90.0, max_entries: int = 64):
        self._ttl = float(ttl_sec)
        self._max = int(max_entries)
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, CustomerProfile]] = {}

    def get(self, key: str) -> CustomerProfile | None:
        if not customer_memory_cache_enabled():
            return None
        now = time.monotonic()
        with self._lock:
            row = self._store.get(key)
            if not row:
                return None
            ts, profile = row
            if now - ts > self._ttl:
                self._store.pop(key, None)
                return None
            # shallow copy flags
            return CustomerProfile(
                user_key=profile.user_key,
                preferences=profile.preferences,
                budget_profile=dict(profile.budget_profile),
                location_preferences=list(profile.location_preferences),
                property_interests=list(profile.property_interests),
                interaction_style=profile.interaction_style,
                last_activities=list(profile.last_activities),
                relationship_score=profile.relationship_score,
                confidence=profile.confidence,
                next_suggested_action=profile.next_suggested_action,
                preference_count=profile.preference_count,
                summary=profile.summary,
                compact_hint=profile.compact_hint,
                customer_memory_tokens=profile.customer_memory_tokens,
                profile_build_time_ms=0,
                cache_hit=True,
                reuse_memory=profile.reuse_memory,
                reuse_workflow=profile.reuse_workflow,
                reuse_recommendation=profile.reuse_recommendation,
                reuse_analysis=profile.reuse_analysis,
                reuse_planning=profile.reuse_planning,
                metadata=dict(profile.metadata or {}),
            )

    def put(self, key: str, profile: CustomerProfile) -> None:
        if not customer_memory_cache_enabled():
            return
        with self._lock:
            if len(self._store) >= self._max:
                oldest = min(self._store.items(), key=lambda kv: kv[1][0])[0]
                self._store.pop(oldest, None)
            self._store[key] = (time.monotonic(), profile)


def cache_key_for(user_key: str, *, message: str = "", route: str = "") -> str:
    blob = f"{user_key}|{route}|{(message or '').strip()[:48]}"
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:24]
