from __future__ import annotations

import time
from typing import Any

from app.agents.analysis.config import analysis_hint_budget_chars
from app.agents.analysis.manager import extract_property_codes
from app.agents.analysis.service import run_property_analysis, should_run_analysis
from app.agents.interfaces import (
    AGENT_PROPERTY_ANALYSIS,
    Agent,
    AgentContext,
    AgentResult,
)


class PropertyAnalysisAgent(Agent):
    """Active agent: rule-first analysis over existing Search/Planning/RAG context.

    Does not collect data itself — reuses shared codes and land accessors.
    Injects only a compact hint (budget-capped); LLM reasoning stays in generate_reply.
    """

    def __init__(self) -> None:
        self._id = AGENT_PROPERTY_ANALYSIS

    @property
    def agent_id(self) -> str:
        return self._id

    @property
    def active(self) -> bool:
        try:
            from app.agents.analysis.config import analysis_enabled

            return bool(analysis_enabled())
        except Exception:
            return True

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.perf_counter()
        shared = ctx.shared if isinstance(ctx.shared, dict) else {}

        # Inherit pipeline flags from Search handoff (no re-search / re-RAG).
        if not shared.get("pipeline"):
            shared["pipeline"] = "planning|memory|rag|tools|llm"
        shared["property_analysis_agent"] = True

        codes = extract_property_codes(ctx.message, shared)
        budget = min(int(ctx.context_budget_chars or 3000), analysis_hint_budget_chars())

        analysis = run_property_analysis(
            property_codes=codes,
            message=ctx.message,
            route=ctx.route,
            audience=ctx.audience,
            user_key=ctx.user_key,
            shared=shared,
            context_budget_chars=budget,
        )

        if analysis is None:
            return AgentResult(
                agent_id=self.agent_id,
                status="error",
                ok=False,
                skipped=True,
                agent_tokens=0,
                execution_time_ms=int((time.perf_counter() - t0) * 1000),
                error="analysis_unavailable",
            )

        # Stash for generate_reply injection (no big prompt).
        shared["analysis_hint"] = analysis.compact_hint or ""
        shared["analysis_codes"] = list(analysis.property_codes or [])
        shared["analysis_cache_hit"] = bool(analysis.cache_hit)
        ctx.shared.update(shared)

        used = ["analysis"]
        for name in ("planning", "memory", "rag", "tools", "llm"):
            if name in str(shared.get("pipeline") or ""):
                used.append(f"reuse:{name}")

        return AgentResult(
            agent_id=self.agent_id,
            status="ready",
            ok=bool(analysis.ok),
            skipped=False,
            used_components=used,
            agent_tokens=int(analysis.analysis_tokens or 0),
            execution_time_ms=int((time.perf_counter() - t0) * 1000),
            metadata={
                "cache_hit": bool(analysis.cache_hit),
                "reused_context": bool(analysis.reused_context),
                "reused_rag": bool(analysis.reused_rag),
                "reused_memory": bool(analysis.reused_memory),
                "reused_planning": bool(analysis.reused_planning),
                "codes": list(analysis.property_codes or []),
                "hint_chars": len(analysis.compact_hint or ""),
                "rule_first": True,
            },
        )

    @staticmethod
    def wants_analysis(ctx: AgentContext) -> bool:
        return should_run_analysis(
            route=ctx.route, message=ctx.message, chip_intent=ctx.chip_intent
        )
