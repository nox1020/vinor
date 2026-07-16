from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class DecisionConfig:
    """Configurable agent weights — rule-based, no LLM."""

    search_weight: float = 0.10
    analysis_weight: float = 0.20
    recommendation_weight: float = 0.30
    negotiation_weight: float = 0.20
    customer_memory_weight: float = 0.10
    customer_success_weight: float = 0.10
    conflict_margin: float = 0.08  # if top2 within margin → conflict
    hint_budget_chars: int = 60

    def normalized(self) -> "DecisionConfig":
        total = (
            self.search_weight
            + self.analysis_weight
            + self.recommendation_weight
            + self.negotiation_weight
            + self.customer_memory_weight
            + self.customer_success_weight
        )
        if total <= 0:
            return self
        return DecisionConfig(
            search_weight=self.search_weight / total,
            analysis_weight=self.analysis_weight / total,
            recommendation_weight=self.recommendation_weight / total,
            negotiation_weight=self.negotiation_weight / total,
            customer_memory_weight=self.customer_memory_weight / total,
            customer_success_weight=self.customer_success_weight / total,
            conflict_margin=self.conflict_margin,
            hint_budget_chars=self.hint_budget_chars,
        )


@dataclass
class ScoredCandidate:
    property_code: str
    score: float = 0.0
    parts: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class DecisionResult:
    selected_property: str = ""
    alternative_properties: list[str] = field(default_factory=list)
    decision_score: float = 0.0
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    next_step: str = ""
    conflict_count: int = 0
    conflicts: list[str] = field(default_factory=list)
    compact_hint: str = ""
    decision_tokens: int = 0
    decision_time_ms: int = 0
    conflict_resolve_time_ms: int = 0
    cache_hit: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_property": self.selected_property,
            "alternative_properties": list(self.alternative_properties),
            "decision_score": self.decision_score,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "recommended_actions": list(self.recommended_actions),
            "next_step": self.next_step,
            "conflict_count": self.conflict_count,
            "conflicts": list(self.conflicts),
        }


@dataclass
class DecisionRequest:
    message: str = ""
    route: str = ""
    shared: dict[str, Any] = field(default_factory=dict)
    parallel_merge: dict[str, Any] = field(default_factory=dict)
    config: DecisionConfig | None = None


class DecisionScorer(Protocol):
    def score_candidates(
        self, *, shared: dict[str, Any], config: DecisionConfig
    ) -> list[ScoredCandidate]:
        ...


class ConflictResolver(Protocol):
    def resolve(
        self,
        *,
        ranked: list[ScoredCandidate],
        shared: dict[str, Any],
        config: DecisionConfig,
    ) -> tuple[ScoredCandidate | None, list[ScoredCandidate], list[str], int]:
        """Returns (winner, alternatives, conflict_notes, conflict_count)."""
        ...


class DecisionBuilder(Protocol):
    def build(
        self,
        *,
        winner: ScoredCandidate | None,
        alternatives: list[ScoredCandidate],
        conflicts: list[str],
        shared: dict[str, Any],
        config: DecisionConfig,
    ) -> DecisionResult:
        ...


class DecisionEngine(Protocol):
    def decide(self, req: DecisionRequest) -> DecisionResult:
        ...


class DecisionManager(Protocol):
    def run(self, req: DecisionRequest) -> DecisionResult:
        ...
