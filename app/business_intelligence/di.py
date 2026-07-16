from __future__ import annotations

from app.business_intelligence.customer import RuleCustomerAnalyzer
from app.business_intelligence.interfaces import BusinessIntelligenceManager
from app.business_intelligence.manager import DefaultBusinessIntelligenceManager
from app.business_intelligence.market import RuleMarketAnalyzer
from app.business_intelligence.property_analyzer import RulePropertyAnalyzer
from app.business_intelligence.signals import RuleBusinessSignalBuilder
from app.business_intelligence.trend import RuleTrendAnalyzer


def make_business_intelligence_manager() -> BusinessIntelligenceManager:
    return DefaultBusinessIntelligenceManager(
        market=RuleMarketAnalyzer(),
        property_analyzer=RulePropertyAnalyzer(),
        customer=RuleCustomerAnalyzer(),
        trend=RuleTrendAnalyzer(),
        signals=RuleBusinessSignalBuilder(),
    )
