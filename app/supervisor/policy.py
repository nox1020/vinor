from __future__ import annotations

from app.supervisor.config import supervisor_default_context_budget
from app.supervisor.interfaces import (
    ROUTE_FAQ,
    ROUTE_FOLLOW_UP,
    ROUTE_GENERAL_CHAT,
    ROUTE_GREETING,
    ROUTE_PARTNER_OPS,
    ROUTE_PROPERTY_COMPARE,
    ROUTE_PROPERTY_SEARCH,
    ComponentFlags,
    ExecutionPolicy,
    SupervisorRequest,
)


class RuleExecutionPolicy(ExecutionPolicy):
    """Maps route -> which components to run (lazy)."""

    def resolve(self, route: str, *, req: SupervisorRequest) -> ComponentFlags:
        budget = supervisor_default_context_budget()
        if route == ROUTE_GREETING:
            return ComponentFlags(
                use_planning=False,
                use_memory=False,
                use_rag=False,
                use_tools=False,
                use_llm=True,
                inject_planning_hint=False,
                seed_planning_tools=False,
                context_budget_chars=min(budget, 1800),
            )
        if route == ROUTE_GENERAL_CHAT:
            return ComponentFlags(
                use_planning=False,
                use_memory=True,
                use_rag=False,
                use_tools=True,
                use_llm=True,
                inject_planning_hint=False,
                seed_planning_tools=False,
                context_budget_chars=min(budget, 2400),
            )
        if route == ROUTE_FAQ:
            return ComponentFlags(
                use_planning=True,
                use_memory=False,
                use_rag=False,
                use_tools=True,
                use_llm=True,
                inject_planning_hint=True,
                seed_planning_tools=True,
                context_budget_chars=min(budget, 2600),
            )
        if route == ROUTE_FOLLOW_UP:
            return ComponentFlags(
                use_planning=True,
                use_memory=True,
                use_rag=False,
                use_tools=True,
                use_llm=True,
                inject_planning_hint=True,
                seed_planning_tools=True,
                context_budget_chars=budget,
            )
        if route in (ROUTE_PROPERTY_SEARCH, ROUTE_PROPERTY_COMPARE):
            return ComponentFlags(
                use_planning=True,
                use_memory=True,
                use_rag=True,
                use_tools=True,
                use_llm=True,
                inject_planning_hint=True,
                seed_planning_tools=True,
                context_budget_chars=budget,
            )
        if route == ROUTE_PARTNER_OPS:
            # Multi-step forms: keep tools/LLM; skip planning+rag to avoid noise.
            return ComponentFlags(
                use_planning=False,
                use_memory=True,
                use_rag=False,
                use_tools=True,
                use_llm=True,
                inject_planning_hint=False,
                seed_planning_tools=False,
                context_budget_chars=budget,
            )
        return ComponentFlags(context_budget_chars=budget)
