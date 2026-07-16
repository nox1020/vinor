from __future__ import annotations

import hashlib
import threading
import time

from app.agents.negotiation.config import negotiation_cache_enabled
from app.agents.negotiation.interfaces import NegotiationCache, NegotiationPlan


class MemoryNegotiationCache(NegotiationCache):
    """In-process plan cache — not a Memory Layer store."""

    def __init__(self, *, ttl_sec: float = 90.0, max_entries: int = 64):
        self._ttl = float(ttl_sec)
        self._max = int(max_entries)
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, NegotiationPlan]] = {}

    def get(self, key: str) -> NegotiationPlan | None:
        if not negotiation_cache_enabled():
            return None
        now = time.monotonic()
        with self._lock:
            row = self._store.get(key)
            if not row:
                return None
            ts, plan = row
            if now - ts > self._ttl:
                self._store.pop(key, None)
                return None
            return NegotiationPlan(
                property_code=plan.property_code,
                target_price=plan.target_price,
                minimum_price=plan.minimum_price,
                maximum_price=plan.maximum_price,
                suggested_offer=plan.suggested_offer,
                risk_score=plan.risk_score,
                risk_level=plan.risk_level,
                confidence=plan.confidence,
                recommended_strategy=plan.recommended_strategy,
                recommended_tone=plan.recommended_tone,
                suggested_actions=list(plan.suggested_actions),
                deal_probability=plan.deal_probability,
                next_action=plan.next_action,
                compact_hint=plan.compact_hint,
                negotiation_tokens=plan.negotiation_tokens,
                negotiation_time_ms=0,
                cache_hit=True,
                reuse_analysis=plan.reuse_analysis,
                reuse_recommendation=plan.reuse_recommendation,
                reuse_customer_profile=plan.reuse_customer_profile,
                reuse_workflow=plan.reuse_workflow,
                reuse_planning=plan.reuse_planning,
                metadata=dict(plan.metadata or {}),
            )

    def put(self, key: str, plan: NegotiationPlan) -> None:
        if not negotiation_cache_enabled():
            return
        with self._lock:
            if len(self._store) >= self._max:
                oldest = min(self._store.items(), key=lambda kv: kv[1][0])[0]
                self._store.pop(oldest, None)
            self._store[key] = (time.monotonic(), plan)


def cache_key_for(code: str, *, message: str = "", route: str = "") -> str:
    blob = f"{code}|{route}|{(message or '').strip()[:40]}"
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:24]
