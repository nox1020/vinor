from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class BusinessReport:
    best_regions: list[dict[str, Any]] = field(default_factory=list)
    high_sale_probability: list[dict[str, Any]] = field(default_factory=list)
    high_conversion_customers: list[dict[str, Any]] = field(default_factory=list)
    partner_performance: list[dict[str, Any]] = field(default_factory=list)
    market_opportunities: list[str] = field(default_factory=list)
    sales_trends: dict[str, Any] = field(default_factory=dict)
    revenue_insights: dict[str, Any] = field(default_factory=dict)
    growth_suggestions: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "best_regions": list(self.best_regions),
            "high_sale_probability": list(self.high_sale_probability),
            "high_conversion_customers": list(self.high_conversion_customers),
            "partner_performance": list(self.partner_performance),
            "market_opportunities": list(self.market_opportunities),
            "sales_trends": dict(self.sales_trends),
            "revenue_insights": dict(self.revenue_insights),
            "growth_suggestions": list(self.growth_suggestions),
            "duration_ms": self.duration_ms,
        }


class AutonomousBusinessAI(Protocol):
    def analyze(self, *, evaluation: list[dict[str, Any]], bi_rows: list[dict[str, Any]]) -> BusinessReport:
        ...
