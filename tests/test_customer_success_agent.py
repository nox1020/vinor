from __future__ import annotations

import unittest

from app.agents.customer_success.actions import RuleNextActionBuilder
from app.agents.customer_success.agent import CustomerSuccessAgent
from app.agents.customer_success.conversion import RuleConversionAnalyzer
from app.agents.customer_success.di import make_customer_success_manager
from app.agents.customer_success.interfaces import CustomerSuccessRequest
from app.agents.customer_success.service import (
    get_customer_success_plan,
    run_customer_success,
    should_run_customer_success,
)
from app.agents.di import make_agent_registry
from app.agents.interfaces import AGENT_FOLLOW_UP, AgentContext
from app.agents.selector import RuleAgentSelector
from app.agents.skeletons import make_skeleton_agents


class ConversionAndActionTests(unittest.TestCase):
    def test_ready_stage_high_conversion(self) -> None:
        p, stage = RuleConversionAnalyzer().analyze(
            profile={"relationship_score": 0.7},
            negotiation={"deal_probability": 0.8, "recommended_strategy": "close_fast"},
            recommendation={"score": 0.85},
            workflow={"workflow": "deal"},
            shared={"analysis_categories": [{"score": 0.7}]},
        )
        self.assertGreaterEqual(p, 0.6)
        self.assertEqual(stage, "ready")

    def test_actions_no_dialogue(self) -> None:
        nxt, ftype, ftime, pri, urg = RuleNextActionBuilder().build(
            stage="ready",
            conversion_probability=0.8,
            negotiation={},
            profile={},
            workflow={},
        )
        self.assertEqual(nxt, "propose_close")
        self.assertEqual(ftype, "deal_push")
        blob = " ".join([nxt, ftype, ftime, pri, urg])
        self.assertLess(len(blob), 80)


class CustomerSuccessManagerTests(unittest.TestCase):
    def test_plan_from_reused_outputs(self) -> None:
        mgr = make_customer_success_manager()
        plan = mgr.run(
            CustomerSuccessRequest(
                message="پیگیری و اقدام بعدی مشتری",
                user_key="09121112233",
                shared={
                    "customer_profile": {
                        "relationship_score": 0.55,
                        "interaction_style": "decisive",
                        "next_suggested_action": "recommend",
                    },
                    "negotiation_plan": {
                        "deal_probability": 0.62,
                        "risk_score": 0.3,
                        "recommended_strategy": "value_focus",
                        "next_action": "send_offer",
                    },
                    "recommendation_items": [
                        {"property_code": "20250101120001", "score": 0.8}
                    ],
                    "analysis_categories": [{"name": "price", "score": 0.7}],
                    "workflow": "visit",
                    "reused_planning": True,
                },
                context_budget_chars=55,
            )
        )
        self.assertTrue(plan.customer_stage)
        self.assertTrue(plan.next_action)
        self.assertTrue(plan.reuse_customer_profile)
        self.assertTrue(plan.reuse_negotiation)
        self.assertTrue(plan.reuse_recommendation)
        self.assertIn("پیگیری", plan.compact_hint)
        self.assertLessEqual(len(plan.compact_hint), 60)
        self.assertNotIn("سلام", plan.compact_hint)


class CustomerSuccessAgentTests(unittest.TestCase):
    def test_agent_active_as_follow_up(self) -> None:
        agent = CustomerSuccessAgent()
        self.assertTrue(agent.active)
        self.assertEqual(agent.agent_id, AGENT_FOLLOW_UP)
        ctx = AgentContext(
            message="یادآوری پیگیری مشتری",
            audience="partner",
            user_key="09121112233",
            shared={
                "customer_profile": {"relationship_score": 0.4},
                "negotiation_plan": {"deal_probability": 0.5},
            },
            context_budget_chars=55,
        )
        out = agent.run(ctx)
        self.assertTrue(out.ok)
        self.assertIn("customer_success", ctx.shared)

    def test_selector_and_no_skeletons(self) -> None:
        self.assertEqual(make_skeleton_agents(), [])
        reg = make_agent_registry()
        sel = RuleAgentSelector(reg)
        ctx = AgentContext(message="فالوآپ و پیگیری اقدام بعدی", route="")
        pick = sel.select(route="", ctx=ctx)
        self.assertEqual(pick.selected_agent, AGENT_FOLLOW_UP)
        fu = reg.get(AGENT_FOLLOW_UP)
        self.assertIsNotNone(fu)
        self.assertTrue(fu.active)

    def test_service(self) -> None:
        self.assertTrue(should_run_customer_success(message="پیگیری کن"))
        self.assertFalse(should_run_customer_success(message="ویلا در دماوند"))
        plan = run_customer_success(
            message="اقدام بعدی چیست؟",
            user_key="09121112233",
            shared={"customer_profile": {"relationship_score": 0.3}},
        )
        self.assertIsNotNone(plan)
        self.assertTrue(get_customer_success_plan() or plan.to_dict())


if __name__ == "__main__":
    unittest.main()
