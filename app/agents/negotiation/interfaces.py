from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class NegotiationPlan:
    """Structured negotiation strategy — no dialogue text."""

    property_code: str = ""
    target_price: int | None = None
    minimum_price: int | None = None
    maximum_price: int | None = None
    suggested_offer: int | None = None
    risk_score: float = 0.0
    risk_level: str = "medium"  # low | medium | high
    confidence: float = 0.0
    recommended_strategy: str = "value_focus"
    recommended_tone: str = "calm"
    suggested_actions: list[str] = field(default_factory=list)
    deal_probability: float = 0.0
    next_action: str = "clarify_budget"
    compact_hint: str = ""
    negotiation_tokens: int = 0
    negotiation_time_ms: int = 0
    cache_hit: bool = False
    reuse_analysis: bool = False
    reuse_recommendation: bool = False
    reuse_customer_profile: bool = False
    reuse_workflow: bool = False
    reuse_planning: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "property_code": self.property_code,
            "target_price": self.target_price,
            "minimum_price": self.minimum_price,
            "maximum_price": self.maximum_price,
            "suggested_offer": self.suggested_offer,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "confidence": self.confidence,
            "recommended_strategy": self.recommended_strategy,
            "recommended_tone": self.recommended_tone,
            "suggested_actions": list(self.suggested_actions),
            "deal_probability": self.deal_probability,
            "next_action": self.next_action,
        }


@dataclass
class NegotiationRequest:
    message: str = ""
    route: str = ""
    audience: str = ""
    user_key: str = ""
    shared: dict[str, Any] = field(default_factory=dict)
    context_budget_chars: int = 55


@dataclass
class PriceBand:
    asking: int | None = None
    target: int | None = None
    minimum: int | None = None
    maximum: int | None = None
    suggested_offer: int | None = None


class NegotiationRiskAnalyzer(Protocol):
    def analyze(
        self,
        *,
        asking: int | None,
        budget_max: int | None,
        analysis_score: float,
        recommendation_score: float,
        shared: dict[str, Any],
    ) -> tuple[float, str]:
        """Returns (risk_score 0..1, risk_level)."""
        ...


class NegotiationStrategyBuilder(Protocol):
    def build(
        self,
        *,
        risk_level: str,
        risk_score: float,
        deal_probability: float,
        profile: dict[str, Any],
    ) -> tuple[str, str, list[str], str]:
        """Returns (strategy, tone, actions, next_action)."""
        ...


class NegotiationPlanner(Protocol):
    def plan(self, req: NegotiationRequest) -> NegotiationPlan:
        ...


class NegotiationCache(Protocol):
    def get(self, key: str) -> NegotiationPlan | None:
        ...

    def put(self, key: str, plan: NegotiationPlan) -> None:
        ...


class NegotiationManager(Protocol):
    def run(self, req: NegotiationRequest) -> NegotiationPlan:
        ...
