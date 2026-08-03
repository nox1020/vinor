from __future__ import annotations

import time

from app.agents.customer_success.config import customer_success_hint_budget_chars
from app.agents.customer_success.service import (
    run_customer_success,
    should_run_customer_success,
)
from app.agents.interfaces import AGENT_FOLLOW_UP, Agent, AgentContext, AgentResult


class CustomerSuccessAgent(Agent):
    """Active Follow-up / Customer Success agent — lifecycle plan only, no message text."""

    def __init__(self) -> None:
        self._id = AGENT_FOLLOW_UP

    @property
    def agent_id(self) -> str:
        return self._id

    @property
    def active(self) -> bool:
        try:
            from app.agents.customer_success.config import customer_success_enabled

            return bool(customer_success_enabled())
        except Exception:
            return True

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.perf_counter()
        shared = ctx.shared if isinstance(ctx.shared, dict) else {}
        shared.setdefault("pipeline", "planning|memory|rag|tools|llm")
        shared["customer_success_agent"] = True
        shared["follow_up_agent"] = True

        if not shared.get("customer_profile"):
            try:
                from app.agents.customer_memory.service import get_customer_profile

                prof = get_customer_profile()
                if prof:
                    shared["customer_profile"] = prof
            except Exception:
                pass
        if not shared.get("negotiation_plan"):
            try:
                from app.agents.negotiation.service import get_negotiation_plan

                neg = get_negotiation_plan()
                if neg:
                    shared["negotiation_plan"] = neg
            except Exception:
                pass

        budget = min(int(ctx.context_budget_chars or 3000), customer_success_hint_budget_chars())
        plan = run_customer_success(
            message=ctx.message,
            route=ctx.route,
            audience=ctx.audience,
            user_key=ctx.user_key,
            shared=shared,
            context_budget_chars=budget,
        )
        if plan is None:
            return AgentResult(
                agent_id=self.agent_id,
                status="error",
                ok=False,
                skipped=True,
                agent_tokens=0,
                execution_time_ms=int((time.perf_counter() - t0) * 1000),
                error="customer_success_unavailable",
            )

        shared["customer_success"] = plan.to_dict()
        shared["customer_success_hint"] = plan.compact_hint or ""
        ctx.shared.update(shared)

        return AgentResult(
            agent_id=self.agent_id,
            status="ready",
            ok=True,
            skipped=False,
            used_components=[
                "customer_success",
                "follow_up",
                "reuse:profile",
                "reuse:negotiation",
                "reuse:recommendation",
            ],
            agent_tokens=int(plan.customer_success_tokens or 0),
            execution_time_ms=int((time.perf_counter() - t0) * 1000),
            metadata={
                "customer_stage": plan.customer_stage,
                "conversion_probability": plan.conversion_probability,
                "next_action": plan.next_action,
                "priority": plan.priority,
                "confidence": plan.confidence,
                "cache_hit": plan.cache_hit,
                "reuse_analysis": plan.reuse_analysis,
                "reuse_recommendation": plan.reuse_recommendation,
                "reuse_negotiation": plan.reuse_negotiation,
                "reuse_customer_profile": plan.reuse_customer_profile,
                "hint_chars": len(plan.compact_hint or ""),
            },
        )

    @staticmethod
    def wants(ctx: AgentContext) -> bool:
        return should_run_customer_success(
            route=ctx.route, message=ctx.message, chip_intent=ctx.chip_intent
        )
