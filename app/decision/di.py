from __future__ import annotations

from app.decision.builder import RuleDecisionBuilder
from app.decision.conflict import RuleConflictResolver
from app.decision.engine import RuleDecisionEngine
from app.decision.interfaces import DecisionManager
from app.decision.manager import DefaultDecisionManager
from app.decision.scorer import RuleDecisionScorer


def make_decision_manager() -> DecisionManager:
    engine = RuleDecisionEngine(
        scorer=RuleDecisionScorer(),
        resolver=RuleConflictResolver(),
        builder=RuleDecisionBuilder(),
    )
    return DefaultDecisionManager(engine=engine)
