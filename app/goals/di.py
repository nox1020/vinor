from __future__ import annotations

from app.goals.extractor import RuleGoalExtractor
from app.goals.interfaces import GoalManager
from app.goals.lifecycle import DefaultGoalLifecycleManager
from app.goals.manager import DefaultGoalManager
from app.goals.prioritizer import RuleGoalPrioritizer
from app.goals.registry import SessionGoalRegistry


def make_goal_manager() -> GoalManager:
    return DefaultGoalManager(
        extractor=RuleGoalExtractor(),
        registry=SessionGoalRegistry(),
        prioritizer=RuleGoalPrioritizer(),
        lifecycle=DefaultGoalLifecycleManager(),
    )
