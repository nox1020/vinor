from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ReflectionResult:
    goal_completed: bool = False
    agent_appropriate: bool = True
    extra_tools: bool = False
    cost_high: bool = False
    reply_sufficient: bool = True
    score: float = 0.5
    notes: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_completed": self.goal_completed,
            "agent_appropriate": self.agent_appropriate,
            "extra_tools": self.extra_tools,
            "cost_high": self.cost_high,
            "reply_sufficient": self.reply_sufficient,
            "score": self.score,
            "notes": list(self.notes),
            "duration_ms": self.duration_ms,
        }


class ReflectionEngine(Protocol):
    def reflect(self, *, analytics_row: dict[str, Any], shared: dict[str, Any] | None = None) -> ReflectionResult:
        ...
