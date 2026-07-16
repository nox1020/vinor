from __future__ import annotations

import time
from typing import Any

from app.business_intelligence.config import load_bi_config
from app.business_intelligence.customer import RuleCustomerAnalyzer
from app.business_intelligence.interfaces import (
    BusinessInsights,
    BusinessIntelligenceManager,
    BusinessIntelligenceRequest,
    BusinessSignalBuilder,
    CustomerAnalyzer,
    MarketAnalyzer,
    PropertyAnalyzer,
    TrendAnalyzer,
)
from app.business_intelligence.market import RuleMarketAnalyzer
from app.business_intelligence.property_analyzer import RulePropertyAnalyzer
from app.business_intelligence.signals import RuleBusinessSignalBuilder
from app.business_intelligence.trend import RuleTrendAnalyzer


class DefaultBusinessIntelligenceManager(BusinessIntelligenceManager):
    """Business analysis only — no prompt / no agent re-run."""

    def __init__(
        self,
        *,
        market: MarketAnalyzer | None = None,
        property_analyzer: PropertyAnalyzer | None = None,
        customer: CustomerAnalyzer | None = None,
        trend: TrendAnalyzer | None = None,
        signals: BusinessSignalBuilder | None = None,
    ):
        self._market = market or RuleMarketAnalyzer()
        self._property = property_analyzer or RulePropertyAnalyzer()
        self._customer = customer or RuleCustomerAnalyzer()
        self._trend = trend or RuleTrendAnalyzer()
        self._signals = signals or RuleBusinessSignalBuilder()

    def analyze(self, req: BusinessIntelligenceRequest) -> BusinessInsights:
        t0 = time.perf_counter()
        shared = dict(req.shared or {})
        decision = dict(req.decision or {})
        evaluation = dict(req.evaluation or {})
        meta = dict(req.property_metadata or {})

        market = self._market.analyze(shared=shared, decision=decision)
        prop = self._property.analyze(
            shared=shared, decision=decision, property_metadata=meta
        )
        customer = self._customer.analyze(shared=shared, decision=decision)
        trends = self._trend.analyze(
            shared=shared, evaluation=evaluation, decision=decision
        )
        signals, opportunity, risks, metrics = self._signals.build(
            market=market,
            property_insights=prop,
            customer=customer,
            trends=trends,
        )
        return BusinessInsights(
            property_insights=prop,
            customer_insights=customer,
            market_insights=market,
            business_metrics=metrics,
            trend_signals=trends,
            opportunity_score=opportunity,
            risk_indicators=risks,
            signals=signals,
            analysis_time_ms=int((time.perf_counter() - t0) * 1000),
            metadata={
                "route": req.route or "",
                "config": (req.config or load_bi_config()).__dict__,
            },
        )
