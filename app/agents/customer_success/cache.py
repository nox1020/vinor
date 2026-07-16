from __future__ import annotations

import hashlib
import threading
import time

from app.agents.customer_success.config import customer_success_cache_enabled
from app.agents.customer_success.interfaces import CustomerSuccessCache, CustomerSuccessPlan


class MemoryCustomerSuccessCache(CustomerSuccessCache):
    """In-process plan cache — not a Memory Layer store."""

    def __init__(self, *, ttl_sec: float = 90.0, max_entries: int = 64):
        self._ttl = float(ttl_sec)
        self._max = int(max_entries)
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, CustomerSuccessPlan]] = {}

    def get(self, key: str) -> CustomerSuccessPlan | None:
        if not customer_success_cache_enabled():
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
            return CustomerSuccessPlan(
                customer_stage=plan.customer_stage,
                next_action=plan.next_action,
                followup_type=plan.followup_type,
                followup_time=plan.followup_time,
                priority=plan.priority,
                conversion_probability=plan.conversion_probability,
                urgency=plan.urgency,
                reason=plan.reason,
                confidence=plan.confidence,
                compact_hint=plan.compact_hint,
                customer_success_tokens=plan.customer_success_tokens,
                build_time_ms=0,
                cache_hit=True,
                reuse_analysis=plan.reuse_analysis,
                reuse_recommendation=plan.reuse_recommendation,
                reuse_negotiation=plan.reuse_negotiation,
                reuse_customer_profile=plan.reuse_customer_profile,
                reuse_workflow=plan.reuse_workflow,
                reuse_planning=plan.reuse_planning,
                metadata=dict(plan.metadata or {}),
            )

    def put(self, key: str, plan: CustomerSuccessPlan) -> None:
        if not customer_success_cache_enabled():
            return
        with self._lock:
            if len(self._store) >= self._max:
                oldest = min(self._store.items(), key=lambda kv: kv[1][0])[0]
                self._store.pop(oldest, None)
            self._store[key] = (time.monotonic(), plan)


def cache_key_for(user_key: str, *, message: str = "", route: str = "") -> str:
    blob = f"{user_key}|{route}|{(message or '').strip()[:40]}"
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:24]
