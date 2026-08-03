from __future__ import annotations

import time

from app.agents.customer_memory.config import customer_memory_hint_budget_chars
from app.agents.customer_memory.service import run_customer_memory, should_run_customer_memory
from app.agents.interfaces import AGENT_CUSTOMER_MEMORY, Agent, AgentContext, AgentResult


class CustomerMemoryAgent(Agent):
    """Active agent: analyzes existing Memory into Customer Profile — no new Memory store."""

    def __init__(self) -> None:
        self._id = AGENT_CUSTOMER_MEMORY

    @property
    def agent_id(self) -> str:
        return self._id

    @property
    def active(self) -> bool:
        try:
            from app.agents.customer_memory.config import customer_memory_enabled

            return bool(customer_memory_enabled())
        except Exception:
            return True

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.perf_counter()
        shared = ctx.shared if isinstance(ctx.shared, dict) else {}
        shared.setdefault("pipeline", "planning|memory|rag|tools|llm")
        shared["customer_memory_agent"] = True
        shared["last_user_message"] = ctx.message

        budget = min(int(ctx.context_budget_chars or 3000), customer_memory_hint_budget_chars())
        profile = run_customer_memory(
            message=ctx.message,
            route=ctx.route,
            audience=ctx.audience,
            user_key=ctx.user_key,
            shared=shared,
            context_budget_chars=budget,
        )
        if profile is None:
            return AgentResult(
                agent_id=self.agent_id,
                status="error",
                ok=False,
                skipped=True,
                agent_tokens=0,
                execution_time_ms=int((time.perf_counter() - t0) * 1000),
                error="customer_memory_unavailable",
            )

        shared["customer_profile"] = profile.to_dict()
        shared["customer_memory_hint"] = profile.compact_hint or ""
        shared["memory_prefs"] = {
            "budget_max": profile.preferences.budget_max,
            "locations": list(profile.location_preferences),
            "property_types": list(profile.property_interests),
            "style": profile.interaction_style,
            "next_action": profile.next_suggested_action,
        }
        shared["reused_memory"] = True
        ctx.shared.update(shared)

        return AgentResult(
            agent_id=self.agent_id,
            status="ready",
            ok=True,
            skipped=False,
            used_components=["customer_memory", "reuse:memory", "reuse:workflow"],
            agent_tokens=int(profile.customer_memory_tokens or 0),
            execution_time_ms=int((time.perf_counter() - t0) * 1000),
            metadata={
                "relationship_score": profile.relationship_score,
                "preference_count": profile.preference_count,
                "profile_confidence": profile.confidence,
                "cache_hit": profile.cache_hit,
                "reuse_memory": profile.reuse_memory,
                "reuse_workflow": profile.reuse_workflow,
                "reuse_recommendation": profile.reuse_recommendation,
                "next_suggested_action": profile.next_suggested_action,
                "hint_chars": len(profile.compact_hint or ""),
            },
        )

    @staticmethod
    def wants(ctx: AgentContext) -> bool:
        return should_run_customer_memory(
            route=ctx.route, message=ctx.message, chip_intent=ctx.chip_intent
        )
