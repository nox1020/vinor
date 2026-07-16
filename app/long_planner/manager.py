from __future__ import annotations

from typing import Any

from app.long_planner.interfaces import HorizonPlanner, LongPlannerManager, PlanGraph
from app.long_planner.planner import RuleHorizonPlanner


class DefaultLongPlannerManager(LongPlannerManager):
    def __init__(self, *, planner: HorizonPlanner | None = None):
        self._planner = planner or RuleHorizonPlanner()

    def build(self, *, shared: dict[str, Any] | None = None, route: str = "") -> PlanGraph:
        shared = dict(shared or {})
        goals = shared.get("goals") if isinstance(shared.get("goals"), dict) else {}
        world = shared.get("world_model") if isinstance(shared.get("world_model"), dict) else {}
        return self._planner.plan(goals=goals, world=world, route=route)
