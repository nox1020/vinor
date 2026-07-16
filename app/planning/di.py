from __future__ import annotations

from app.planning.evaluator import GoalEvaluator
from app.planning.executor import ToolExecutor
from app.planning.interfaces import PlanningManager
from app.planning.manager import DefaultPlanningManager
from app.planning.planner import RulePlanner


def make_planning_manager() -> PlanningManager:
    return DefaultPlanningManager(
        planner=RulePlanner(),
        executor=ToolExecutor(),
        evaluator=GoalEvaluator(),
    )
