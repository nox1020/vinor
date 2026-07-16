from __future__ import annotations

import time

from app.agents.negotiation.cache import MemoryNegotiationCache, cache_key_for
from app.agents.negotiation.config import negotiation_hint_budget_chars
from app.agents.negotiation.interfaces import (
    NegotiationCache,
    NegotiationManager,
    NegotiationPlan,
    NegotiationPlanner,
    NegotiationRequest,
)
from app.agents.negotiation.planner import RuleNegotiationPlanner


class DefaultNegotiationManager(NegotiationManager):
    def __init__(
        self,
        *,
        planner: NegotiationPlanner | None = None,
        cache: NegotiationCache | None = None,
    ):
        self._planner = planner or RuleNegotiationPlanner()
        self._cache = cache or MemoryNegotiationCache()

    def run(self, req: NegotiationRequest) -> NegotiationPlan:
        t0 = time.perf_counter()
        shared = dict(req.shared or {})
        code = str(shared.get("recommended_code") or "")
        if not code:
            items = shared.get("recommendation_items") or []
            if items and isinstance(items[0], dict):
                code = str(items[0].get("property_code") or "")
        key = cache_key_for(code or "none", message=req.message, route=req.route)
        cached = self._cache.get(key)
        if cached is not None:
            cached.negotiation_time_ms = int((time.perf_counter() - t0) * 1000)
            return cached

        budget = int(req.context_budget_chars or negotiation_hint_budget_chars())
        plan = self._planner.plan(
            NegotiationRequest(
                message=req.message,
                route=req.route,
                audience=req.audience,
                user_key=req.user_key,
                shared=shared,
                context_budget_chars=budget,
            )
        )
        plan.negotiation_time_ms = int((time.perf_counter() - t0) * 1000)
        self._cache.put(key, plan)
        return plan
