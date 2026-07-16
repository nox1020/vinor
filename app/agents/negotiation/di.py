from __future__ import annotations

from app.agents.negotiation.cache import MemoryNegotiationCache
from app.agents.negotiation.interfaces import NegotiationManager
from app.agents.negotiation.manager import DefaultNegotiationManager
from app.agents.negotiation.planner import RuleNegotiationPlanner
from app.agents.negotiation.risk import RuleNegotiationRiskAnalyzer
from app.agents.negotiation.strategy import RuleNegotiationStrategyBuilder


def make_negotiation_manager() -> NegotiationManager:
    planner = RuleNegotiationPlanner(
        risk=RuleNegotiationRiskAnalyzer(),
        strategy=RuleNegotiationStrategyBuilder(),
    )
    return DefaultNegotiationManager(
        planner=planner,
        cache=MemoryNegotiationCache(),
    )
