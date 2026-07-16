from __future__ import annotations

import time

from app.agents.interfaces import AGENT_NEGOTIATION, Agent, AgentContext, AgentResult
from app.agents.negotiation.config import negotiation_hint_budget_chars
from app.agents.negotiation.service import run_negotiation, should_run_negotiation


class NegotiationAgent(Agent):
    """Active agent: builds NegotiationPlan from reused prior agents — no dialogue text."""

    def __init__(self) -> None:
        self._id = AGENT_NEGOTIATION

    @property
    def agent_id(self) -> str:
        return self._id

    @property
    def active(self) -> bool:
        return True

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.perf_counter()
        shared = ctx.shared if isinstance(ctx.shared, dict) else {}
        shared.setdefault("pipeline", "planning|memory|rag|tools|llm")
        shared["negotiation_agent"] = True

        # Soft-reuse customer profile into shared if already on g (no re-build required).
        if not shared.get("customer_profile"):
            try:
                from app.agents.customer_memory.service import get_customer_profile

                prof = get_customer_profile()
                if prof:
                    shared["customer_profile"] = prof
            except Exception:
                pass

        budget = min(int(ctx.context_budget_chars or 3000), negotiation_hint_budget_chars())
        plan = run_negotiation(
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
                error="negotiation_unavailable",
            )

        shared["negotiation_plan"] = plan.to_dict()
        shared["negotiation_hint"] = plan.compact_hint or ""
        ctx.shared.update(shared)

        return AgentResult(
            agent_id=self.agent_id,
            status="ready",
            ok=True,
            skipped=False,
            used_components=[
                "negotiation",
                "reuse:analysis",
                "reuse:recommendation",
                "reuse:customer_profile",
            ],
            agent_tokens=int(plan.negotiation_tokens or 0),
            execution_time_ms=int((time.perf_counter() - t0) * 1000),
            metadata={
                "confidence": plan.confidence,
                "risk": plan.risk_score,
                "deal_probability": plan.deal_probability,
                "strategy": plan.recommended_strategy,
                "cache_hit": plan.cache_hit,
                "reuse_analysis": plan.reuse_analysis,
                "reuse_recommendation": plan.reuse_recommendation,
                "reuse_customer_profile": plan.reuse_customer_profile,
                "hint_chars": len(plan.compact_hint or ""),
            },
        )

    @staticmethod
    def wants(ctx: AgentContext) -> bool:
        return should_run_negotiation(
            route=ctx.route, message=ctx.message, chip_intent=ctx.chip_intent
        )
