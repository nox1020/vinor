from __future__ import annotations

import time

from app.goals.extractor import RuleGoalExtractor
from app.goals.interfaces import (
    GoalContext,
    GoalExtractor,
    GoalLifecycleManager,
    GoalManager,
    GoalPrioritizer,
    GoalRegistry,
    GoalsBundle,
)
from app.goals.lifecycle import DefaultGoalLifecycleManager
from app.goals.prioritizer import RuleGoalPrioritizer
from app.goals.registry import SessionGoalRegistry


class DefaultGoalManager(GoalManager):
    def __init__(
        self,
        *,
        extractor: GoalExtractor | None = None,
        registry: GoalRegistry | None = None,
        prioritizer: GoalPrioritizer | None = None,
        lifecycle: GoalLifecycleManager | None = None,
    ):
        self._extractor = extractor or RuleGoalExtractor()
        self._registry = registry or SessionGoalRegistry()
        self._prioritizer = prioritizer or RuleGoalPrioritizer()
        self._lifecycle = lifecycle or DefaultGoalLifecycleManager()

    def run(self, ctx: GoalContext) -> GoalsBundle:
        t0 = time.perf_counter()
        existing = self._registry.load(ctx.user_key) if ctx.user_key else list(ctx.session_goals or [])
        extracted = self._extractor.extract(ctx)
        merged = self._lifecycle.merge(existing, extracted)
        ranked = self._prioritizer.prioritize(merged)
        if ctx.user_key:
            try:
                self._registry.save(ctx.user_key, [g.to_dict() for g in ranked])
            except Exception:
                pass
        primary = ranked[0].goal_id if ranked else ""
        return GoalsBundle(
            goals=ranked,
            primary_goal_id=primary,
            extraction_time_ms=int((time.perf_counter() - t0) * 1000),
        )
