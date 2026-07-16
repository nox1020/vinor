from __future__ import annotations

from typing import Any

from app.business_intelligence.interfaces import BusinessSignalBuilder, BusinessSignals


def _f(d: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(d.get(key) if d.get(key) is not None else default)
    except Exception:
        return default


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


class RuleBusinessSignalBuilder(BusinessSignalBuilder):
    def build(
        self,
        *,
        market: dict[str, Any],
        property_insights: dict[str, Any],
        customer: dict[str, Any],
        trends: dict[str, Any],
    ) -> tuple[BusinessSignals, float, list[str], dict[str, Any]]:
        signals = BusinessSignals(
            property_score=_f(property_insights, "property_score"),
            market_attractiveness=_f(market, "market_attractiveness"),
            region_popularity=_f(market, "region_popularity"),
            price_competitiveness=_f(market, "price_competitiveness"),
            customer_purchase_probability=_f(customer, "customer_purchase_probability"),
            seller_flexibility_score=_f(customer, "seller_flexibility_score"),
            lead_quality=_f(customer, "lead_quality"),
            demand_trend=_f(trends, "demand_trend"),
            supply_trend=_f(trends, "supply_trend"),
            listing_freshness=_f(property_insights, "listing_freshness"),
            recommendation_success_rate=_f(trends, "recommendation_success_rate"),
        )

        opportunity = _clamp(
            signals.property_score * 0.2
            + signals.market_attractiveness * 0.15
            + signals.lead_quality * 0.2
            + signals.customer_purchase_probability * 0.2
            + signals.recommendation_success_rate * 0.15
            + _f(trends, "trend_score") * 0.1
        )

        risks: list[str] = []
        if signals.lead_quality < 0.4:
            risks.append("low_lead_quality")
        if signals.price_competitiveness < 0.4:
            risks.append("price_pressure")
        if signals.demand_trend < 0.4:
            risks.append("weak_demand")
        if _f(trends, "conflict_pressure") >= 0.4:
            risks.append("decision_conflict")
        if signals.listing_freshness < 0.35:
            risks.append("stale_listing")
        if signals.seller_flexibility_score < 0.4:
            risks.append("seller_inflexible")

        metrics = {
            "market_score": signals.market_attractiveness,
            "property_score": signals.property_score,
            "lead_score": signals.lead_quality,
            "trend_score": _f(trends, "trend_score"),
            "opportunity_score": round(opportunity, 3),
            "purchase_probability": signals.customer_purchase_probability,
        }
        return signals, round(opportunity, 3), risks[:8], metrics
