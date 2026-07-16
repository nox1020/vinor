from __future__ import annotations

from app.goals.interfaces import Goal, GoalPrioritizer, GoalPriority


_RANK = {
    GoalPriority.CRITICAL.value: 0,
    GoalPriority.HIGH.value: 1,
    GoalPriority.MEDIUM.value: 2,
    GoalPriority.LOW.value: 3,
}


class RuleGoalPrioritizer(GoalPrioritizer):
    def prioritize(self, goals: list[Goal]) -> list[Goal]:
        return sorted(
            goals,
            key=lambda g: (_RANK.get(g.priority, 9), -float(g.confidence or 0)),
        )
