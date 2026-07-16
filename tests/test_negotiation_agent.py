from __future__ import annotations

import unittest

from app.agents.di import make_agent_registry
from app.agents.interfaces import AGENT_FOLLOW_UP, AGENT_NEGOTIATION, AgentContext
from app.agents.negotiation.agent import NegotiationAgent
from app.agents.negotiation.di import make_negotiation_manager
from app.agents.negotiation.interfaces import NegotiationRequest
from app.agents.negotiation.risk import RuleNegotiationRiskAnalyzer
from app.agents.negotiation.service import (
    get_negotiation_plan,
    run_negotiation,
    should_run_negotiation,
)
from app.agents.negotiation.strategy import RuleNegotiationStrategyBuilder
from app.agents.selector import RuleAgentSelector


class RiskAndStrategyTests(unittest.TestCase):
    def test_high_risk_when_budget_far_below(self) -> None:
        risk, level = RuleNegotiationRiskAnalyzer().analyze(
            asking=20_000_000_000,
            budget_max=10_000_000_000,
            analysis_score=0.3,
            recommendation_score=0.3,
            shared={},
        )
        self.assertEqual(level, "high")
        self.assertGreater(risk, 0.6)

    def test_strategy_no_dialogue(self) -> None:
        strategy, tone, actions, nxt = RuleNegotiationStrategyBuilder().build(
            risk_level="low",
            risk_score=0.2,
            deal_probability=0.8,
            profile={"interaction_style": "decisive"},
        )
        self.assertTrue(strategy)
        self.assertTrue(tone)
        self.assertTrue(actions)
        # Ensure no long Persian negotiation script
        blob = " ".join([strategy, tone, nxt] + actions)
        self.assertLess(len(blob), 120)


class NegotiationManagerTests(unittest.TestCase):
    def test_plan_from_reused_shared(self) -> None:
        mgr = make_negotiation_manager()
        plan = mgr.run(
            NegotiationRequest(
                message="برای این فایل مذاکره و تخفیف می‌خوام",
                user_key="09121112233",
                shared={
                    "recommended_code": "20250101120001",
                    "asking_price": 15_000_000_000,
                    "recommendation_items": [
                        {"property_code": "20250101120001", "score": 0.82}
                    ],
                    "analysis_categories": [{"name": "price", "score": 0.7}],
                    "customer_profile": {
                        "interaction_style": "decisive",
                        "relationship_score": 0.6,
                        "preferences": {"budget_max": 14_000_000_000},
                        "budget_profile": {"max": 14_000_000_000},
                    },
                    "reused_planning": True,
                },
                context_budget_chars=55,
            )
        )
        self.assertIsNotNone(plan.target_price)
        self.assertIsNotNone(plan.suggested_offer)
        self.assertTrue(plan.reuse_recommendation)
        self.assertTrue(plan.reuse_analysis)
        self.assertTrue(plan.reuse_customer_profile)
        self.assertIn("مذاکره", plan.compact_hint)
        self.assertLessEqual(len(plan.compact_hint), 60)
        self.assertGreater(plan.negotiation_tokens, 0)
        # No dialogue paragraphs
        self.assertNotIn("سلام", plan.compact_hint)
        self.assertNotIn("\n\n", plan.compact_hint)


class NegotiationAgentTests(unittest.TestCase):
    def test_agent_active(self) -> None:
        agent = NegotiationAgent()
        self.assertTrue(agent.active)
        ctx = AgentContext(
            message="مذاکره روی قیمت و تخفیف",
            audience="partner",
            user_key="09121112233",
            shared={
                "asking_price": 12_000_000_000,
                "recommended_code": "111122223333",
                "customer_profile": {
                    "preferences": {"budget_max": 11_000_000_000},
                    "budget_profile": {"max": 11_000_000_000},
                },
            },
            context_budget_chars=55,
        )
        out = agent.run(ctx)
        self.assertTrue(out.ok)
        self.assertEqual(out.agent_id, AGENT_NEGOTIATION)
        self.assertIn("negotiation_plan", ctx.shared)
        self.assertIsInstance(ctx.shared["negotiation_plan"], dict)

    def test_selector_picks_negotiation(self) -> None:
        reg = make_agent_registry()
        sel = RuleAgentSelector(reg)
        ctx = AgentContext(message="چانه‌زنی و مذاکره قیمت نهایی", route="")
        pick = sel.select(route="", ctx=ctx)
        self.assertEqual(pick.selected_agent, AGENT_NEGOTIATION)
        follow = reg.get(AGENT_FOLLOW_UP)
        self.assertIsNotNone(follow)
        self.assertTrue(follow.active)

    def test_service_and_should_run(self) -> None:
        self.assertTrue(should_run_negotiation(message="تخفیف بگیرید"))
        self.assertFalse(should_run_negotiation(message="ویلا در دماوند"))
        plan = run_negotiation(
            message="مذاکره برای تخفیف",
            user_key="09121112233",
            shared={
                "asking_price": 10_000_000_000,
                "memory_prefs": {"budget_max": 9_000_000_000},
            },
        )
        self.assertIsNotNone(plan)
        self.assertTrue(get_negotiation_plan() or plan.to_dict())


if __name__ == "__main__":
    unittest.main()
