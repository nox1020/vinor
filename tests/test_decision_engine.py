from __future__ import annotations

import os
import unittest

from app.decision.builder import RuleDecisionBuilder
from app.decision.config import load_decision_config
from app.decision.conflict import RuleConflictResolver
from app.decision.di import make_decision_manager
from app.decision.interfaces import DecisionConfig, DecisionRequest, ScoredCandidate
from app.decision.scorer import RuleDecisionScorer
from app.decision.service import get_decision, run_decision


class ScorerTests(unittest.TestCase):
    def test_weighted_ranking_prefers_recommendation(self) -> None:
        cfg = DecisionConfig(
            search_weight=0.1,
            analysis_weight=0.2,
            recommendation_weight=0.5,
            negotiation_weight=0.1,
            customer_memory_weight=0.05,
            customer_success_weight=0.05,
        ).normalized()
        shared = {
            "property_search_agent": True,
            "recommended_code": "AAA111",
            "recommendation_items": [
                {"property_code": "AAA111", "score": 0.9},
                {"property_code": "BBB222", "score": 0.4},
            ],
            "analysis_categories": [{"score": 0.7}],
            "customer_profile": {"relationship_score": 0.5},
            "negotiation_plan": {"deal_probability": 0.4, "risk_score": 0.3},
            "customer_success": {"conversion_probability": 0.5, "next_action": "follow_up"},
        }
        ranked = RuleDecisionScorer().score_candidates(shared=shared, config=cfg)
        self.assertGreaterEqual(len(ranked), 2)
        self.assertEqual(ranked[0].property_code, "AAA111")
        self.assertGreater(ranked[0].score, ranked[1].score)


class ConflictTests(unittest.TestCase):
    def test_close_scores_recorded(self) -> None:
        cfg = DecisionConfig(conflict_margin=0.08)
        ranked = [
            ScoredCandidate(property_code="A", score=0.60, parts={}),
            ScoredCandidate(property_code="B", score=0.58, parts={}),
        ]
        winner, alts, notes, count = RuleConflictResolver().resolve(
            ranked=ranked, shared={}, config=cfg
        )
        self.assertEqual(winner.property_code, "A")
        self.assertTrue(alts)
        self.assertGreaterEqual(count, 1)
        self.assertTrue(any("close_scores" in n for n in notes))

    def test_rec_vs_neg_prefers_high_deal(self) -> None:
        cfg = DecisionConfig(conflict_margin=0.05)
        ranked = [
            ScoredCandidate(property_code="REC", score=0.70, parts={}),
            ScoredCandidate(property_code="NEG", score=0.65, parts={}),
        ]
        shared = {
            "recommended_code": "REC",
            "negotiation_plan": {
                "property_code": "NEG",
                "deal_probability": 0.85,
            },
        }
        winner, alts, notes, count = RuleConflictResolver().resolve(
            ranked=ranked, shared=shared, config=cfg
        )
        self.assertEqual(winner.property_code, "NEG")
        self.assertTrue(any("prefer_negotiation" in n for n in notes))
        self.assertGreaterEqual(count, 1)
        self.assertIn("REC", [a.property_code for a in alts] + [winner.property_code])


class BuilderTests(unittest.TestCase):
    def test_hint_under_70_chars(self) -> None:
        cfg = load_decision_config()
        winner = ScoredCandidate(
            property_code="20250101120001",
            score=0.81,
            parts={},
            reasons=["recommended"],
        )
        result = RuleDecisionBuilder().build(
            winner=winner,
            alternatives=[ScoredCandidate(property_code="ALT1", score=0.7)],
            conflicts=[],
            shared={"customer_success": {"next_action": "propose_close"}},
            config=cfg,
        )
        self.assertEqual(result.selected_property, "20250101120001")
        self.assertLessEqual(len(result.compact_hint), 70)
        self.assertIn("تصمیم", result.compact_hint)
        self.assertTrue(result.alternative_properties)


class EngineIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["VINOR_DECISION_ENABLED"] = "1"
        os.environ["VINOR_DECISION_INJECT_HINT"] = "1"
        import app.decision.service as ds

        ds._MANAGER = None

    def test_manager_produces_decision_object(self) -> None:
        mgr = make_decision_manager()
        result = mgr.run(
            DecisionRequest(
                message="پیشنهاد ویلا",
                route="property_search",
                shared={
                    "recommended_code": "CODE99",
                    "recommendation_items": [{"property_code": "CODE99", "score": 0.88}],
                    "property_codes": ["CODE99", "CODE88"],
                    "customer_profile": {"relationship_score": 0.6},
                    "negotiation_plan": {
                        "property_code": "CODE99",
                        "deal_probability": 0.55,
                        "risk_score": 0.2,
                        "recommended_strategy": "value_anchor",
                    },
                    "customer_success": {
                        "conversion_probability": 0.6,
                        "next_action": "schedule_visit",
                        "followup_type": "visit",
                    },
                    "parallel_merge": {"recommendation": "CODE99"},
                },
                parallel_merge={"recommendation": "CODE99"},
            )
        )
        self.assertEqual(result.selected_property, "CODE99")
        self.assertGreater(result.decision_score, 0)
        self.assertGreater(result.confidence, 0)
        self.assertTrue(result.next_step)
        self.assertTrue(result.recommended_actions)
        self.assertLessEqual(len(result.compact_hint), 70)

    def test_run_decision_stores_on_service(self) -> None:
        result = run_decision(
            message="ویلا",
            route="property_search",
            shared={
                "recommended_code": "X1",
                "property_codes": ["X1", "X2"],
                "recommendation_items": [
                    {"property_code": "X1", "score": 0.8},
                    {"property_code": "X2", "score": 0.75},
                ],
            },
            parallel_merge={"recommendation": "X1"},
        )
        self.assertIsNotNone(result)
        stored = get_decision()
        self.assertEqual(stored.get("selected_property"), "X1")
        self.assertIn("alternative_properties", stored)

    def test_disabled_returns_none(self) -> None:
        os.environ["VINOR_DECISION_ENABLED"] = "0"
        import app.decision.service as ds

        ds._MANAGER = None
        self.assertIsNone(
            run_decision(shared={"recommended_code": "Z"}, parallel_merge={})
        )


if __name__ == "__main__":
    unittest.main()
