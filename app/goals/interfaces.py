from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class GoalType(str, Enum):
    SEARCH = "search"
    BUY = "buy"
    SELL = "sell"
    VISIT = "visit"
    DEAL = "deal"
    NEGOTIATE = "negotiate"
    SUPPORT = "support"
    PARTNER = "partner"
    GENERAL = "general"


class GoalPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class GoalStatus(str, Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


@dataclass
class Goal:
    goal_id: str = ""
    goal_type: str = GoalType.GENERAL.value
    title: str = ""
    priority: str = GoalPriority.MEDIUM.value
    status: str = GoalStatus.ACTIVE.value
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "goal_type": self.goal_type,
            "title": self.title,
            "priority": self.priority,
            "status": self.status,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


@dataclass
class GoalContext:
    message: str = ""
    user_key: str = ""
    audience: str = ""
    route: str = ""
    intent: str = ""
    role: str = ""
    shared: dict[str, Any] = field(default_factory=dict)
    session_goals: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GoalsBundle:
    goals: list[Goal] = field(default_factory=list)
    primary_goal_id: str = ""
    extraction_time_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "goals": [g.to_dict() for g in self.goals],
            "primary_goal_id": self.primary_goal_id,
            "extraction_time_ms": self.extraction_time_ms,
        }


class GoalExtractor(Protocol):
    def extract(self, ctx: GoalContext) -> list[Goal]:
        ...


class GoalRegistry(Protocol):
    def load(self, user_key: str) -> list[dict[str, Any]]:
        ...

    def save(self, user_key: str, goals: list[dict[str, Any]]) -> None:
        ...


class GoalPrioritizer(Protocol):
    def prioritize(self, goals: list[Goal]) -> list[Goal]:
        ...


class GoalLifecycleManager(Protocol):
    def merge(self, existing: list[dict[str, Any]], new_goals: list[Goal]) -> list[Goal]:
        ...


class GoalManager(Protocol):
    def run(self, ctx: GoalContext) -> GoalsBundle:
        ...
