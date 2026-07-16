from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class RecommendationItem:
    property_code: str
    score: float = 0.0
    match_reasons: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    priority: int = 0
    confidence: float = 0.0


@dataclass
class RecommendationRequest:
    property_codes: tuple[str, ...] = ()
    message: str = ""
    route: str = ""
    audience: str = ""
    user_key: str = ""
    shared: dict[str, Any] = field(default_factory=dict)
    analysis_categories: list[Any] = field(default_factory=list)
    context_budget_chars: int = 100


@dataclass
class RecommendationResult:
    ok: bool = True
    items: list[RecommendationItem] = field(default_factory=list)
    selected_property: str = ""
    alternate_property: str = ""
    rejected: list[str] = field(default_factory=list)
    compact_hint: str = ""
    recommendation_tokens: int = 0
    recommendation_time_ms: int = 0
    top_score: float = 0.0
    cache_hit: bool = False
    reuse_search: bool = False
    reuse_analysis: bool = False
    reuse_memory: bool = False
    reuse_planning: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class RecommendationEngine(Protocol):
    def rank(self, req: RecommendationRequest, lands: list[dict[str, Any]]) -> RecommendationResult:
        ...


class RecommendationCache(Protocol):
    def get(self, key: str) -> RecommendationResult | None:
        ...

    def put(self, key: str, result: RecommendationResult) -> None:
        ...


class RecommendationManager(Protocol):
    def run(self, req: RecommendationRequest) -> RecommendationResult:
        ...
