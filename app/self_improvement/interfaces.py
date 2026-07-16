from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ImprovementSuggestion:
    area: str
    title: str
    recommendation: str
    priority: str = "medium"
    confidence: float = 0.5
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "area": self.area,
            "title": self.title,
            "recommendation": self.recommendation,
            "priority": self.priority,
            "confidence": self.confidence,
            "source": self.source,
        }


@dataclass
class ImprovementReport:
    suggestions: list[ImprovementSuggestion] = field(default_factory=list)
    applied: bool = False
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "suggestions": [s.to_dict() for s in self.suggestions],
            "applied": False,
            "duration_ms": self.duration_ms,
            "count": len(self.suggestions),
        }


class ImprovementManager(Protocol):
    def improve(
        self,
        *,
        reflection: dict[str, Any] | None = None,
        learning: dict[str, Any] | None = None,
    ) -> ImprovementReport:
        ...
