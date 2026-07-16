from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class LearningPattern:
    pattern_id: str
    kind: str  # success | failure
    signal: str
    weight: float = 0.5
    count: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "kind": self.kind,
            "signal": self.signal,
            "weight": self.weight,
            "count": self.count,
            "metadata": dict(self.metadata),
        }


@dataclass
class LearningReport:
    patterns: list[LearningPattern] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "patterns": [p.to_dict() for p in self.patterns],
            "duration_ms": self.duration_ms,
            "pattern_count": len(self.patterns),
        }


class PatternExtractor(Protocol):
    def extract(self, records: list[dict[str, Any]]) -> list[LearningPattern]:
        ...


class SuccessDetector(Protocol):
    def detect(self, records: list[dict[str, Any]]) -> list[LearningPattern]:
        ...


class FailureDetector(Protocol):
    def detect(self, records: list[dict[str, Any]]) -> list[LearningPattern]:
        ...


class LearningManager(Protocol):
    def learn(self, records: list[dict[str, Any]] | None = None) -> LearningReport:
        ...
