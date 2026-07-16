from __future__ import annotations

from app.agents.interfaces import AgentManager, AgentRegistry
from app.agents.manager import DefaultAgentManager
from app.agents.property_search import PropertySearchAgent
from app.agents.registry import InMemoryAgentRegistry
from app.agents.selector import RuleAgentSelector
from app.agents.skeletons import make_skeleton_agents


def make_agent_registry() -> AgentRegistry:
    registry = InMemoryAgentRegistry()
    registry.register(PropertySearchAgent())
    for agent in make_skeleton_agents():
        registry.register(agent)
    return registry


def make_agent_manager(registry: AgentRegistry | None = None) -> AgentManager:
    reg = registry or make_agent_registry()
    selector = RuleAgentSelector(reg)
    return DefaultAgentManager(registry=reg, selector=selector)
