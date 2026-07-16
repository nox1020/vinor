from __future__ import annotations

import os
import unittest

from app.business_intelligence.customer import RuleCustomerAnalyzer
from app.business_intelligence.di import make_business_intelligence_manager
from app.business_intelligence.interfaces import BusinessIntelligenceRequest
from app.business_intelligence.market import RuleMarketAnalyzer
from app.business_intelligence.property_analyzer import RulePropertyAnalyzer
from app.business_intelligence.service import get_business_intelligence, run_business_intelligence
from app.business_intelligence.signals import RuleBusinessSignalBuilder
from app.business_intelligence.trend import RuleTrendAnalyzer


def _shared(**extra):
    base = {
        "recommended_code": "CODE01",
        "property_codes": ["CODE01", "CODE02", "CODE03"],
        "recommendation_items": [
            {"property_code": "CODE01", "score": 0.85},
            {"property_code": "CODE02", "score": 0.7},
        ],
        "analysis_categories": [{"score": 0.72}],
        "customer_profile": {
            "relationship_score": 0.6,
            "confidence": 0.55,
            "preference_count": 3,
            "location_preferences": ["دماوند"],
            "interaction_style": "direct",
            "next_suggested_action": "visit",
        },
        "negotiation_plan": {
            "deal_probability": 0.65,
            "risk_score": 0.3,
            "recommended_strategy": "value_anchor",
            "next_action": "counter",
        },
        "customer_success": {
            "conversion_probability": 0.55,
            "confidence": 0.5,
            "next_action": "schedule_visit",
        },
    }
    base.update(extra)
    return base


def _decision(**extra):
    base = {
        "selected_property": "CODE01",
        "alternative_properties": ["CODE02", "CODE03"],
        "decision_score": 0.74,
        "confidence": 0.78,
        "conflict_count": 1,
    }
    base.update(extra)
    return base


class AnalyzerUnitTests(unittest.TestCase):
    def test_market_analyzer(self) -> None:
        out = RuleMarketAnalyzer().analyze(shared=_shared(), decision=_decision())
        self.assertGreater(out["market_attractiveness"], 0.3)
        self.assertEqual(out["primary_region"], "دماوند")

    def test_property_analyzer(self) -> None:
        out = RulePropertyAnalyzer().analyze(
            shared=_shared(),
            decision=_decision(),
            property_metadata={"code": "CODE01", "age_days": 10, "status": "active"},
        )
        self.assertEqual(out["property_code"], "CODE01")
        self.assertGreater(out["property_score"], 0.4)
        self.assertGreater(out["listing_freshness"], 0.5)

    def test_customer_analyzer(self) -> None:
        out = RuleCustomerAnalyzer().analyze(shared=_shared(), decision=_decision())
        self.assertGreater(out["lead_quality"], 0.4)
        self.assertGreater(out["customer_purchase_probability"], 0.4)

    def test_trend_and_signals(self) -> None:
        shared = _shared()
        decision = _decision()
        market = RuleMarketAnalyzer().analyze(shared=shared, decision=decision)
        prop = RulePropertyAnalyzer().analyze(
            shared=shared, decision=decision, property_metadata={}
        )
        customer = RuleCustomerAnalyzer().analyze(shared=shared, decision=decision)
        trends = RuleTrendAnalyzer().analyze(
            shared=shared, evaluation={}, decision=decision
        )
        signals, opp, risks, metrics = RuleBusinessSignalBuilder().build(
            market=market,
            property_insights=prop,
            customer=customer,
            trends=trends,
        )
        self.assertGreater(signals.property_score, 0)
        self.assertGreater(opp, 0)
        self.assertIn("opportunity_score", metrics)
        self.assertIsInstance(risks, list)


class ManagerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["VINOR_BI_ENABLED"] = "1"
        os.environ["VINOR_BI_INJECT_HINT"] = "0"
        import app.business_intelligence.service as bis

        bis._MANAGER = None

    def test_manager_produces_insights_object(self) -> None:
        mgr = make_business_intelligence_manager()
        insights = mgr.analyze(
            BusinessIntelligenceRequest(
                message="ویلا",
                route="property_search",
                shared=_shared(),
                decision=_decision(),
                evaluation={"quality": {"overall": 0.8, "recommendation_quality": 0.75}},
                property_metadata={"age_days": 5},
            )
        )
        data = insights.to_dict()
        self.assertIn("property_insights", data)
        self.assertIn("customer_insights", data)
        self.assertIn("market_insights", data)
        self.assertIn("signals", data)
        self.assertGreater(insights.opportunity_score, 0)
        self.assertGreaterEqual(insights.analysis_time_ms, 0)
        self.assertIn("property_score", data["signals"])

    def test_run_bi_stores_object(self) -> None:
        result = run_business_intelligence(
            message="پیشنهاد",
            route="property_search",
            shared=_shared(),
        )
        self.assertIsNotNone(result)
        stored = get_business_intelligence()
        self.assertTrue(stored.get("signals"))
        self.assertIn("opportunity_score", stored)

    def test_disabled_returns_none(self) -> None:
        os.environ["VINOR_BI_ENABLED"] = "0"
        import app.business_intelligence.service as bis

        bis._MANAGER = None
        self.assertIsNone(run_business_intelligence(shared=_shared()))

    def test_no_default_hint_flag(self) -> None:
        from app.business_intelligence.config import bi_inject_hint

        os.environ["VINOR_BI_INJECT_HINT"] = "0"
        self.assertFalse(bi_inject_hint())


if __name__ == "__main__":
    unittest.main()
