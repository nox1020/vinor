from __future__ import annotations

from typing import Any

from app.goals.interfaces import Goal, GoalLifecycleManager, GoalStatus


class DefaultGoalLifecycleManager(GoalLifecycleManager):
    def merge(self, existing: list[dict[str, Any]], new_goals: list[Goal]) -> list[Goal]:
        by_type: dict[str, Goal] = {}
        for raw in existing or []:
            if not isinstance(raw, dict):
                continue
            g = Goal(
                goal_id=str(raw.get("goal_id") or ""),
                goal_type=str(raw.get("goal_type") or "general"),
                title=str(raw.get("title") or ""),
                priority=str(raw.get("priority") or "medium"),
                status=str(raw.get("status") or GoalStatus.ACTIVE.value),
                confidence=float(raw.get("confidence") or 0.4),
                metadata=dict(raw.get("metadata") or {}),
            )
            if g.status == GoalStatus.ABANDONED.value:
                continue
            by_type[g.goal_type] = g
        for g in new_goals or []:
            prev = by_type.get(g.goal_type)
            if prev and prev.status == GoalStatus.COMPLETED.value:
                g.status = GoalStatus.ACTIVE.value
            by_type[g.goal_type] = g
        return list(by_type.values())[:12]
