from __future__ import annotations

import unittest

from app.agents.customer_memory.agent import CustomerMemoryAgent
from app.agents.customer_memory.builder import RuleCustomerProfileBuilder
from app.agents.customer_memory.di import make_customer_memory_manager
from app.agents.customer_memory.interfaces import CustomerMemoryRequest, CustomerPreferences
from app.agents.customer_memory.preferences import RulePreferenceExtractor
from app.agents.customer_memory.relationship import RuleRelationshipAnalyzer
from app.agents.customer_memory.service import (
    get_customer_profile,
    run_customer_memory,
    should_run_customer_memory,
)
from app.agents.di import make_agent_registry
from app.agents.interfaces import AGENT_CUSTOMER_MEMORY, AGENT_NEGOTIATION, AgentContext
from app.agents.selector import RuleAgentSelector


class PreferenceExtractorTests(unittest.TestCase):
    def test_extract_budget_location_type(self) -> None:
        ext = RulePreferenceExtractor()
        prefs = ext.extract(
            message="ویلا تا ۱۵ میلیارد در دماوند می‌خوام",
            memory_items=[{"key": "pref", "value": "باغ در گرمابسرد"}],
            shared={},
        )
        self.assertIsNotNone(prefs.budget_max)
        self.assertIn("دماوند", prefs.locations)
        self.assertTrue(any(t in prefs.property_types for t in ("ویلا", "باغ")))


class RelationshipAnalyzerTests(unittest.TestCase):
    def test_score_increases_with_signals(self) -> None:
        an = RuleRelationshipAnalyzer()
        prefs = CustomerPreferences(budget_max=10_000_000_000, locations=["دماوند"], property_types=["ویلا"])
        score, style, acts = an.analyze(
            preferences=prefs,
            memory_items=[{"key": "a", "value": "x"}, {"key": "b", "value": "y"}],
            shared={"recommended_code": "1", "reused_memory": True, "message": "کوتاه"},
            conversation_obs={"workflow": "visit", "workflow_state": "COMPLETED"},
        )
        self.assertGreater(score, 0.4)
        self.assertTrue(acts)


class ProfileBuilderTests(unittest.TestCase):
    def test_compact_hint_budget(self) -> None:
        b = RuleCustomerProfileBuilder()
        prefs = CustomerPreferences(budget_max=15_000_000_000, locations=["دماوند"], property_types=["ویلا"])
        profile = b.build(
            user_key="0912",
            preferences=prefs,
            relationship_score=0.7,
            interaction_style="decisive",
            last_activities=["search"],
            shared={"reused_memory": True},
            budget_chars=55,
        )
        self.assertIn("پروفایل مشتری", profile.compact_hint)
        self.assertLessEqual(len(profile.compact_hint), 65)
        self.assertEqual(profile.next_suggested_action, "recommend")
        self.assertGreater(profile.customer_memory_tokens, 0)


class CustomerMemoryManagerTests(unittest.TestCase):
    def test_build_reuses_shared_memory_no_write(self) -> None:
        mgr = make_customer_memory_manager()
        profile = mgr.build(
            CustomerMemoryRequest(
                user_key="09129998877",
                message="ترجیحات من برای خرید ویلا چیست؟",
                shared={
                    "memory_prefs": {"budget": "تا ۱۲ میلیارد", "city": "دماوند"},
                    "reused_memory": True,
                    "recommendation_items": [{"property_code": "x"}],
                },
            )
        )
        self.assertTrue(profile.reuse_memory)
        self.assertGreaterEqual(profile.preference_count, 1)
        self.assertEqual(profile.customer_memory_tokens, (len(profile.compact_hint) + 3) // 4)


class CustomerMemoryAgentTests(unittest.TestCase):
    def test_agent_active_and_runs(self) -> None:
        agent = CustomerMemoryAgent()
        self.assertTrue(agent.active)
        ctx = AgentContext(
            message="شناخت مشتری و ترجیحات من",
            route="",
            audience="partner",
            user_key="09129998877",
            shared={"memory_prefs": {"budget": "۱۰ میلیارد دماوند ویلا"}},
            context_budget_chars=70,
        )
        out = agent.run(ctx)
        self.assertTrue(out.ok)
        self.assertEqual(out.agent_id, AGENT_CUSTOMER_MEMORY)
        self.assertIn("customer_profile", ctx.shared)

    def test_selector_picks_customer_memory(self) -> None:
        reg = make_agent_registry()
        sel = RuleAgentSelector(reg)
        ctx = AgentContext(message="پروفایل و ترجیحات مشتری من", route="", audience="partner")
        pick = sel.select(route="", ctx=ctx)
        self.assertEqual(pick.selected_agent, AGENT_CUSTOMER_MEMORY)
        inactive = [a.agent_id for a in reg.all_agents() if not a.active]
        self.assertNotIn(AGENT_CUSTOMER_MEMORY, inactive)

    def test_negotiation_is_active(self) -> None:
        from app.agents.interfaces import AGENT_NEGOTIATION

        reg = make_agent_registry()
        neg = reg.get(AGENT_NEGOTIATION)
        self.assertIsNotNone(neg)
        self.assertTrue(neg.active)

    def test_should_run_and_service(self) -> None:
        self.assertTrue(should_run_customer_memory(message="سابقه و ترجیح من"))
        self.assertFalse(should_run_customer_memory(message="ویلا در دماوند"))
        p = run_customer_memory(
            message="بودجه من تا ۱۵ میلیارد ویلا دماوند",
            user_key="09129998877",
            shared={"memory_text": "علاقه به ویلا"},
        )
        self.assertIsNotNone(p)
        self.assertTrue(get_customer_profile() or p.to_dict())


if __name__ == "__main__":
    unittest.main()
