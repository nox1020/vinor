from __future__ import annotations

from app.agents.interfaces import (
    AGENT_PROPERTY_SEARCH,
    ALL_AGENT_IDS,
    AgentContext,
    AgentRegistry,
    AgentSelection,
    AgentSelector,
)
from app.supervisor.interfaces import (
    ROUTE_PROPERTY_COMPARE,
    ROUTE_PROPERTY_SEARCH,
)


class RuleAgentSelector(AgentSelector):
    """Supervisor-driven selection: map route → agent. Only property_search is active."""

    def __init__(self, registry: AgentRegistry):
        self._registry = registry

    def select(self, *, route: str, ctx: AgentContext) -> AgentSelection:
        route = (route or "").strip()
        selected = ""
        reason = "none"

        if route in (ROUTE_PROPERTY_SEARCH, ROUTE_PROPERTY_COMPARE):
            agent = self._registry.get(AGENT_PROPERTY_SEARCH)
            if agent is not None and agent.active:
                selected = AGENT_PROPERTY_SEARCH
                reason = f"route:{route}"
            else:
                reason = "property_search_inactive"
        else:
            # Agents only when needed — no agent for greeting/faq/etc.
            reason = f"no_agent_for_route:{route or 'empty'}"

        skipped = [aid for aid in ALL_AGENT_IDS if aid != selected]

        return AgentSelection(
            selected_agent=selected,
            skipped_agents=skipped,
            reason=reason,
        )
