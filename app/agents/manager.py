from __future__ import annotations

import time

from app.agents.interfaces import (
    AGENT_PROPERTY_ANALYSIS,
    AGENT_PROPERTY_SEARCH,
    AGENT_RECOMMENDATION,
    AgentContext,
    AgentManager,
    AgentOutcome,
    AgentRegistry,
    AgentResult,
    AgentSelection,
    AgentSelector,
)


class DefaultAgentManager(AgentManager):
    """Primary agent + Search/Analysis handoff for Recommendation (no re-query)."""

    def __init__(self, *, registry: AgentRegistry, selector: AgentSelector):
        self._registry = registry
        self._selector = selector

    def prepare(self, ctx: AgentContext) -> AgentOutcome:
        t0 = time.perf_counter()
        selection = self._selector.select(route=ctx.route, ctx=ctx)
        result: AgentResult | None = None

        if selection.selected_agent:
            agent = self._registry.get(selection.selected_agent)
            if agent is not None and agent.active:
                if selection.selected_agent in (
                    AGENT_PROPERTY_ANALYSIS,
                    AGENT_RECOMMENDATION,
                ):
                    search = self._registry.get(AGENT_PROPERTY_SEARCH)
                    if search is not None and search.active:
                        search.run(ctx)
                        ctx.shared["search_handoff"] = True
                        ctx.shared["reused_rag"] = True
                        ctx.shared["reused_memory"] = True
                        ctx.shared["reused_planning"] = True
                if selection.selected_agent == AGENT_RECOMMENDATION:
                    # Structured Analysis handoff via service cache — Analysis Agent file untouched.
                    try:
                        from app.agents.analysis.manager import extract_property_codes
                        from app.agents.analysis.service import run_property_analysis

                        codes = extract_property_codes(ctx.message, ctx.shared)
                        ar = run_property_analysis(
                            property_codes=codes,
                            message=ctx.message,
                            route=ctx.route,
                            audience=ctx.audience,
                            user_key=ctx.user_key,
                            shared=ctx.shared,
                        )
                        if ar is not None:
                            ctx.shared["analysis_categories"] = list(ar.categories or [])
                            ctx.shared["analysis_codes"] = list(ar.property_codes or [])
                            ctx.shared["property_analysis_agent"] = True
                            ctx.shared["reused_analysis"] = True
                    except Exception:
                        pass
                result = agent.run(ctx)
            elif agent is not None:
                result = agent.run(ctx)
                selection = AgentSelection(
                    selected_agent="",
                    skipped_agents=list(
                        dict.fromkeys(
                            [selection.selected_agent] + list(selection.skipped_agents)
                        )
                    ),
                    reason="selected_inactive",
                )
            else:
                result = AgentResult(
                    agent_id=selection.selected_agent,
                    status="error",
                    ok=False,
                    skipped=True,
                    error="agent_not_registered",
                )
        else:
            result = AgentResult(
                agent_id="",
                status="skipped",
                ok=True,
                skipped=True,
                metadata={"reason": selection.reason},
            )

        return AgentOutcome(
            selection=selection,
            result=result,
            execution_time_ms=int((time.perf_counter() - t0) * 1000),
        )
