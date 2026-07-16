from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class BusinessIntelligenceConfig:
    enabled: bool = True
    inject_hint: bool = False  # default OFF — 0% token


@dataclass
class BusinessSignals:
    property_score: float = 0.0
    market_attractiveness: float = 0.0
    region_popularity: float = 0.0
    price_competitiveness: float = 0.0
    customer_purchase_probability: float = 0.0
    seller_flexibility_score: float = 0.0
    lead_quality: float = 0.0
    demand_trend: float = 0.0
    supply_trend: float = 0.0
    listing_freshness: float = 0.0
    recommendation_success_rate: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "property_score": self.property_score,
            "market_attractiveness": self.market_attractiveness,
            "region_popularity": self.region_popularity,
            "price_competitiveness": self.price_competitiveness,
            "customer_purchase_probability": self.customer_purchase_probability,
            "seller_flexibility_score": self.seller_flexibility_score,
            "lead_quality": self.lead_quality,
            "demand_trend": self.demand_trend,
            "supply_trend": self.supply_trend,
            "listing_freshness": self.listing_freshness,
            "recommendation_success_rate": self.recommendation_success_rate,
        }


@dataclass
class BusinessInsights:
    property_insights: dict[str, Any] = field(default_factory=dict)
    customer_insights: dict[str, Any] = field(default_factory=dict)
    market_insights: dict[str, Any] = field(default_factory=dict)
    business_metrics: dict[str, Any] = field(default_factory=dict)
    trend_signals: dict[str, Any] = field(default_factory=dict)
    opportunity_score: float = 0.0
    risk_indicators: list[str] = field(default_factory=list)
    signals: BusinessSignals = field(default_factory=BusinessSignals)
    analysis_time_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "property_insights": dict(self.property_insights),
            "customer_insights": dict(self.customer_insights),
            "market_insights": dict(self.market_insights),
            "business_metrics": dict(self.business_metrics),
            "trend_signals": dict(self.trend_signals),
            "opportunity_score": self.opportunity_score,
            "risk_indicators": list(self.risk_indicators),
            "signals": self.signals.to_dict(),
            "analysis_time_ms": self.analysis_time_ms,
            "metadata": dict(self.metadata),
        }


@dataclass
class BusinessIntelligenceRequest:
    message: str = ""
    route: str = ""
    shared: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    evaluation: dict[str, Any] = field(default_factory=dict)
    property_metadata: dict[str, Any] = field(default_factory=dict)
    config: BusinessIntelligenceConfig | None = None


class MarketAnalyzer(Protocol):
    def analyze(self, *, shared: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        ...


class PropertyAnalyzer(Protocol):
    def analyze(
        self,
        *,
        shared: dict[str, Any],
        decision: dict[str, Any],
        property_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        ...


class CustomerAnalyzer(Protocol):
    def analyze(self, *, shared: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        ...


class TrendAnalyzer(Protocol):
    def analyze(
        self,
        *,
        shared: dict[str, Any],
        evaluation: dict[str, Any],
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        ...


class BusinessSignalBuilder(Protocol):
    def build(
        self,
        *,
        market: dict[str, Any],
        property_insights: dict[str, Any],
        customer: dict[str, Any],
        trends: dict[str, Any],
    ) -> tuple[BusinessSignals, float, list[str], dict[str, Any]]:
        """Returns signals, opportunity_score, risks, business_metrics."""
        ...


class BusinessIntelligenceManager(Protocol):
    def analyze(self, req: BusinessIntelligenceRequest) -> BusinessInsights:
        ...
