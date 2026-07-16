from __future__ import annotations

import unittest

from app.agents.analysis.cache import MemoryAnalysisCache, cache_key_for
from app.agents.analysis.di import make_analysis_manager
from app.agents.analysis.interfaces import AnalysisRequest
from app.agents.analysis.property_analysis import PropertyAnalysisAgent
from app.agents.analysis.service import should_run_analysis
from app.agents.analysis.strategy import RuleAnalysisStrategy
from app.agents.di import make_agent_manager, make_agent_registry
from app.agents.interfaces import AGENT_PROPERTY_ANALYSIS, AGENT_PROPERTY_SEARCH, AgentContext
from app.agents.skeletons import make_skeleton_agents
from app.supervisor.interfaces import SupervisorRequest
from app.supervisor.manager import DefaultSupervisor, DefaultSupervisorManager
from app.supervisor.policy import RuleExecutionPolicy
from app.supervisor.router import RuleRouter
from app.supervisor.service import set_supervisor_context


class PropertyAnalysisAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = make_agent_registry()
        self.manager = make_agent_manager(self.registry)
        self.sup = DefaultSupervisorManager(
            DefaultSupervisor(router=RuleRouter(), policy=RuleExecutionPolicy())
        )
        self.analysis_mgr = make_analysis_manager()

    def test_analysis_agent_is_active(self) -> None:
        agent = self.registry.get(AGENT_PROPERTY_ANALYSIS)
        self.assertIsNotNone(agent)
        self.assertTrue(agent.active)
        for sk in make_skeleton_agents():
            self.assertNotEqual(sk.agent_id, AGENT_PROPERTY_ANALYSIS)
            self.assertFalse(sk.active)

    def test_compare_route_selects_analysis(self) -> None:
        out = self.sup.orchestrate(
            SupervisorRequest(message="این دو فایل را مقایسه کن کدام بهتر است")
        )
        set_supervisor_context(out)
        self.assertEqual(out.workflow.route, "property_compare")
        agent_out = self.manager.prepare(
            AgentContext(message="مقایسه کن", route=out.workflow.route)
        )
        self.assertEqual(agent_out.selection.selected_agent, AGENT_PROPERTY_ANALYSIS)
        self.assertEqual(agent_out.result.status, "ready")
        self.assertTrue(agent_out.result.ok)
        self.assertTrue(any(u.startswith("reuse:") or u == "analysis" for u in agent_out.result.used_components))
        set_supervisor_context(None)

    def test_search_without_analysis_keeps_search_agent(self) -> None:
        out = self.sup.orchestrate(
            SupervisorRequest(message="ویلا تا ۱۵ میلیارد در دماوند پیدا کن")
        )
        agent_out = self.manager.prepare(
            AgentContext(message="ویلا تا ۱۵ میلیارد در دماوند", route=out.workflow.route)
        )
        self.assertEqual(agent_out.selection.selected_agent, AGENT_PROPERTY_SEARCH)

    def test_rule_strategy_price_location_investment(self) -> None:
        strategy = RuleAnalysisStrategy()
        lands = [
            {
                "code": "20250101120001",
                "title": "ویلا دماوند",
                "city": "دماوند",
                "location": "جاده اصلی",
                "category": "ویلا",
                "price_total": 12_000_000_000,
                "villa_built_area": 220,
                "description": "استخر و پارکینگ دارد",
            },
            {
                "code": "20250101120002",
                "title": "ویلا گرمابسرد",
                "city": "گرمابسرد",
                "category": "ویلا",
                "price_total": 18_000_000_000,
                "villa_built_area": 180,
            },
        ]
        result = strategy.analyze(
            AnalysisRequest(property_codes=("20250101120001", "20250101120002")),
            lands,
        )
        self.assertTrue(result.ok)
        names = {c.name for c in result.categories}
        self.assertTrue({"price", "location", "amenities", "investment"} <= names)
        self.assertIn("مقایسه", result.comparison)
        self.assertTrue(result.compact_hint.startswith("=== تحلیل فایل ==="))
        self.assertLessEqual(len(result.compact_hint), 180)

    def test_analysis_cache_hit(self) -> None:
        cache = MemoryAnalysisCache(ttl_sec=60)
        mgr = make_analysis_manager()
        # force same cache instance via direct strategy run + cache
        from app.agents.analysis.manager import DefaultAnalysisManager
        from app.agents.analysis.strategy import RuleAnalysisStrategy

        mgr = DefaultAnalysisManager(strategy=RuleAnalysisStrategy(), cache=cache)
        req = AnalysisRequest(
            property_codes=("99990000111111",),
            message="تحلیل فایل",
            shared={"pipeline": "planning|memory|rag|tools|llm", "property_search_agent": True},
        )
        r1 = mgr.run(req)
        r2 = mgr.run(req)
        self.assertFalse(r1.cache_hit)
        self.assertTrue(r2.cache_hit)
        self.assertEqual(r1.compact_hint, r2.compact_hint)

    def test_should_run_analysis_gate(self) -> None:
        self.assertTrue(should_run_analysis(route="property_compare"))
        self.assertTrue(should_run_analysis(message="تحلیل ارزش خرید این ویلا"))
        self.assertFalse(should_run_analysis(route="greeting", message="سلام"))

    def test_agent_tokens_bounded(self) -> None:
        agent = PropertyAnalysisAgent()
        ctx = AgentContext(
            message="تحلیل این فایل 20250101120001",
            route="property_compare",
            shared={
                "pipeline": "planning|memory|rag|tools|llm",
                "property_codes": ["20250101120001"],
            },
            context_budget_chars=100,
        )
        result = agent.run(ctx)
        self.assertEqual(result.status, "ready")
        self.assertLessEqual(result.agent_tokens, 50)


if __name__ == "__main__":
    unittest.main()
