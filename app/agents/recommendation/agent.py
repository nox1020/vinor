from __future__ import annotations

import time

from app.agents.analysis.manager import extract_property_codes
from app.agents.interfaces import AGENT_RECOMMENDATION, Agent, AgentContext, AgentResult
from app.agents.recommendation.config import recommendation_hint_budget_chars
from app.agents.recommendation.service import run_recommendation, should_run_recommendation


class RecommendationAgent(Agent):
    """Active agent: ranks reused Search/Analysis results — no new search/RAG/memory."""

    def __init__(self) -> None:
        self._id = AGENT_RECOMMENDATION

    @property
    def agent_id(self) -> str:
        return self._id

    @property
    def active(self) -> bool:
        try:
            from app.agents.recommendation.config import recommendation_enabled

            return bool(recommendation_enabled())
        except Exception:
            return True

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.perf_counter()
        shared = ctx.shared if isinstance(ctx.shared, dict) else {}
        shared.setdefault("pipeline", "planning|memory|rag|tools|llm")
        shared["recommendation_agent"] = True

        codes = extract_property_codes(ctx.message, shared)
        budget = min(int(ctx.context_budget_chars or 3000), recommendation_hint_budget_chars())
        cats = list(shared.get("analysis_categories") or [])

        result = run_recommendation(
            property_codes=codes,
            message=ctx.message,
            route=ctx.route,
            audience=ctx.audience,
            user_key=ctx.user_key,
            shared=shared,
            analysis_categories=cats,
            context_budget_chars=budget,
        )
        if result is None:
            return AgentResult(
                agent_id=self.agent_id,
                status="error",
                ok=False,
                skipped=True,
                agent_tokens=0,
                execution_time_ms=int((time.perf_counter() - t0) * 1000),
                error="recommendation_unavailable",
            )

        shared["recommendation_hint"] = result.compact_hint or ""
        shared["recommended_code"] = result.selected_property or ""
        shared["recommendation_items"] = [
            {
                "property_code": it.property_code,
                "score": it.score,
                "match_reasons": list(it.match_reasons),
                "weaknesses": list(it.weaknesses),
                "priority": it.priority,
                "confidence": it.confidence,
            }
            for it in (result.items or [])
        ]
        ctx.shared.update(shared)

        return AgentResult(
            agent_id=self.agent_id,
            status="ready",
            ok=bool(result.ok),
            skipped=False,
            used_components=["recommendation", "reuse:search", "reuse:analysis"],
            agent_tokens=int(result.recommendation_tokens or 0),
            execution_time_ms=int((time.perf_counter() - t0) * 1000),
            metadata={
                "selected_property": result.selected_property,
                "top_score": result.top_score,
                "cache_hit": result.cache_hit,
                "reuse_search": result.reuse_search,
                "reuse_analysis": result.reuse_analysis,
                "reuse_memory": result.reuse_memory,
                "hint_chars": len(result.compact_hint or ""),
            },
        )

    @staticmethod
    def wants(ctx: AgentContext) -> bool:
        return should_run_recommendation(
            route=ctx.route, message=ctx.message, chip_intent=ctx.chip_intent
        )
