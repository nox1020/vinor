from __future__ import annotations

from typing import Any

from app.agents.interfaces import Agent, AgentRegistry


class InMemoryAgentRegistry(AgentRegistry):
    """Lazy registry — agents are stored by id; lookup is O(1)."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        self._agents[str(agent.agent_id)] = agent

    def get(self, agent_id: str) -> Agent | None:
        return self._agents.get(str(agent_id or ""))

    def list_ids(self) -> list[str]:
        return list(self._agents.keys())

    def all_agents(self) -> list[Agent]:
        return list(self._agents.values())

    def snapshot(self) -> dict[str, Any]:
        return {
            aid: {"active": bool(a.active)} for aid, a in self._agents.items()
        }
