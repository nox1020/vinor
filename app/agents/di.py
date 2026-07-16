from __future__ import annotations

from app.agents.analysis.property_analysis import PropertyAnalysisAgent
from app.agents.customer_memory.agent import CustomerMemoryAgent
from app.agents.customer_success.agent import CustomerSuccessAgent
from app.agents.interfaces import AgentManager, AgentRegistry
from app.agents.manager import DefaultAgentManager
from app.agents.negotiation.agent import NegotiationAgent
from app.agents.property_search import PropertySearchAgent
from app.agents.recommendation.agent import RecommendationAgent
from app.agents.registry import InMemoryAgentRegistry
from app.agents.selector import RuleAgentSelector


def make_agent_registry() -> AgentRegistry:
    registry = InMemoryAgentRegistry()
    registry.register(PropertySearchAgent())
    registry.register(PropertyAnalysisAgent())
    registry.register(RecommendationAgent())
    registry.register(CustomerMemoryAgent())
    registry.register(NegotiationAgent())
    registry.register(CustomerSuccessAgent())  # Follow-up / Customer Success (Phase 15)
    return registry


def make_agent_manager(registry: AgentRegistry | None = None) -> AgentManager:
    reg = registry or make_agent_registry()
    selector = RuleAgentSelector(reg)
    return DefaultAgentManager(registry=reg, selector=selector)
