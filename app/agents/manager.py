from __future__ import annotations

import time

from app.agents.interfaces import (
    AgentContext,
    AgentManager,
    AgentOutcome,
    AgentRegistry,
    AgentResult,
    AgentSelection,
    AgentSelector,
)


class DefaultAgentManager(AgentManager):
    """Select at most one agent; skeletons stay skipped."""

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
                result = agent.run(ctx)
            elif agent is not None:
                # Registered but inactive → treat as skipped skeleton path
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
