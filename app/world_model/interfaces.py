from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class PropertyState:
    codes: list[str] = field(default_factory=list)
    selected: str = ""
    alternatives: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "codes": list(self.codes),
            "selected": self.selected,
            "alternatives": list(self.alternatives),
            "scores": dict(self.scores),
        }


@dataclass
class CustomerState:
    user_key: str = ""
    relationship_score: float = 0.0
    purchase_probability: float = 0.0
    lead_quality: float = 0.0
    preferences: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_key": self.user_key,
            "relationship_score": self.relationship_score,
            "purchase_probability": self.purchase_probability,
            "lead_quality": self.lead_quality,
            "preferences": dict(self.preferences),
        }


@dataclass
class PartnerState:
    audience: str = ""
    partner_mode: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"audience": self.audience, "partner_mode": self.partner_mode}


@dataclass
class MarketState:
    attractiveness: float = 0.0
    demand_trend: float = 0.0
    supply_trend: float = 0.0
    opportunity_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "attractiveness": self.attractiveness,
            "demand_trend": self.demand_trend,
            "supply_trend": self.supply_trend,
            "opportunity_score": self.opportunity_score,
        }


@dataclass
class ConversationState:
    intent: str = ""
    role: str = ""
    workflow: str = ""
    route: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "role": self.role,
            "workflow": self.workflow,
            "route": self.route,
        }


@dataclass
class WorldSnapshot:
    property: PropertyState = field(default_factory=PropertyState)
    customer: CustomerState = field(default_factory=CustomerState)
    partner: PartnerState = field(default_factory=PartnerState)
    market: MarketState = field(default_factory=MarketState)
    conversation: ConversationState = field(default_factory=ConversationState)
    goals: list[dict[str, Any]] = field(default_factory=list)
    update_time_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "property": self.property.to_dict(),
            "customer": self.customer.to_dict(),
            "partner": self.partner.to_dict(),
            "market": self.market.to_dict(),
            "conversation": self.conversation.to_dict(),
            "goals": list(self.goals),
            "update_time_ms": self.update_time_ms,
        }


class WorldReasoner(Protocol):
    def snapshot(self, *, shared: dict[str, Any]) -> WorldSnapshot:
        ...


class WorldModelManager(Protocol):
    def update(self, *, shared: dict[str, Any] | None = None) -> WorldSnapshot:
        ...
