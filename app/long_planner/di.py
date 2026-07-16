from __future__ import annotations

from app.long_planner.interfaces import LongPlannerManager
from app.long_planner.manager import DefaultLongPlannerManager
from app.long_planner.planner import RuleHorizonPlanner


def make_long_planner_manager() -> LongPlannerManager:
    return DefaultLongPlannerManager(planner=RuleHorizonPlanner())
