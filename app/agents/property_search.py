from __future__ import annotations

import time

from app.agents.interfaces import Agent, AgentContext, AgentResult


class PropertySearchAgent(Agent):
    """Active agent: orchestrates existing Planning→Memory→RAG→Tools→LLM.

    Does not re-implement those layers. Confirms shared supervisor flags and
    returns a ready signal so generate_reply continues the existing pipeline.
    Adds zero prompt tokens.
    """

    def __init__(self) -> None:
        self._id = "property_search"

    @property
    def agent_id(self) -> str:
        return self._id

    @property
    def active(self) -> bool:
        try:
            from app.agents.config import property_search_enabled

            return bool(property_search_enabled())
        except Exception:
            return True

    def run(self, ctx: AgentContext) -> AgentResult:
        t0 = time.perf_counter()
        used: list[str] = []
        try:
            from app.supervisor.service import allow_component, current_flags

            flags = current_flags()
            if allow_component("planning", default=True):
                used.append("planning")
            if allow_component("memory", default=True):
                used.append("memory")
            if allow_component("rag", default=True):
                used.append("rag")
            if allow_component("tools", default=True):
                used.append("tools")
            if allow_component("llm", default=True):
                used.append("llm")
            budget = (
                int(flags.context_budget_chars)
                if flags is not None
                else int(ctx.context_budget_chars or 3000)
            )
        except Exception:
            used = ["planning", "memory", "rag", "tools", "llm"]
            budget = int(ctx.context_budget_chars or 3000)

        # Shared context only — no prompt injection.
        ctx.shared["property_search_agent"] = True
        ctx.shared["context_budget_chars"] = budget
        ctx.shared["pipeline"] = "planning|memory|rag|tools|llm"
        ctx.shared["reused_rag"] = True
        ctx.shared["reused_memory"] = True
        ctx.shared["reused_planning"] = True
        # Handoff slot for Analysis Agent (codes filled later from planning/tools).
        ctx.shared.setdefault("property_codes", [])
        ctx.shared["search_handoff"] = True

        return AgentResult(
            agent_id=self.agent_id,
            status="ready",
            ok=True,
            skipped=False,
            used_components=used,
            agent_tokens=0,
            execution_time_ms=int((time.perf_counter() - t0) * 1000),
            metadata={
                "pipeline": "existing",
                "lazy": True,
                "shared_context": True,
                "context_budget_chars": budget,
            },
        )
