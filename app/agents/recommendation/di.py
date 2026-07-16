from __future__ import annotations

from app.agents.recommendation.cache import MemoryRecommendationCache
from app.agents.recommendation.engine import RuleRecommendationEngine
from app.agents.recommendation.interfaces import RecommendationManager
from app.agents.recommendation.manager import DefaultRecommendationManager


def make_recommendation_manager() -> RecommendationManager:
    return DefaultRecommendationManager(
        engine=RuleRecommendationEngine(),
        cache=MemoryRecommendationCache(),
    )
