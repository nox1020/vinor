from __future__ import annotations

import time

from app.agents.customer_success.actions import RuleNextActionBuilder
from app.agents.customer_success.cache import MemoryCustomerSuccessCache, cache_key_for
from app.agents.customer_success.config import customer_success_hint_budget_chars
from app.agents.customer_success.conversion import RuleConversionAnalyzer
from app.agents.customer_success.interfaces import (
    CustomerSuccessCache,
    CustomerSuccessManager,
    CustomerSuccessPlan,
    CustomerSuccessRequest,
    FollowUpPlanner,
)
from app.agents.customer_success.planner import RuleFollowUpPlanner


class DefaultCustomerSuccessManager(CustomerSuccessManager):
    def __init__(
        self,
        *,
        planner: FollowUpPlanner | None = None,
        cache: CustomerSuccessCache | None = None,
    ):
        self._planner = planner or RuleFollowUpPlanner(
            conversion=RuleConversionAnalyzer(),
            actions=RuleNextActionBuilder(),
        )
        self._cache = cache or MemoryCustomerSuccessCache()

    def run(self, req: CustomerSuccessRequest) -> CustomerSuccessPlan:
        t0 = time.perf_counter()
        key = cache_key_for(req.user_key or "anon", message=req.message, route=req.route)
        cached = self._cache.get(key)
        if cached is not None:
            cached.build_time_ms = int((time.perf_counter() - t0) * 1000)
            return cached

        budget = int(req.context_budget_chars or customer_success_hint_budget_chars())
        plan = self._planner.plan(
            CustomerSuccessRequest(
                message=req.message,
                route=req.route,
                audience=req.audience,
                user_key=req.user_key,
                shared=dict(req.shared or {}),
                context_budget_chars=budget,
            )
        )
        plan.build_time_ms = int((time.perf_counter() - t0) * 1000)
        self._cache.put(key, plan)
        return plan
