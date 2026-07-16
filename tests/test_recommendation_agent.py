from __future__ import annotations

import unittest

from app.agents.analysis.interfaces import AnalysisCategoryResult
from app.agents.di import make_agent_manager, make_agent_registry
from app.agents.interfaces import (
    AGENT_PROPERTY_ANALYSIS,
    AGENT_PROPERTY_SEARCH,
    AGENT_RECOMMENDATION,
    AgentContext,
)
from app.agents.recommendation.agent import RecommendationAgent
from app.agents.recommendation.di import make_recommendation_manager
from app.agents.recommendation.engine import RuleRecommendationEngine
from app.agents.recommendation.interfaces import RecommendationRequest
from app.agents.recommendation.manager import DefaultRecommendationManager
from app.agents.recommendation.cache import MemoryRecommendationCache
from app.agents.recommendation.service import should_run_recommendation
from app.agents.skeletons import make_skeleton_agents
from app.supervisor.interfaces import SupervisorRequest
from app.supervisor.manager import DefaultSupervisor, DefaultSupervisorManager
from app.supervisor.policy import RuleExecutionPolicy
from app.supervisor.router import RuleRouter
from app.supervisor.service import set_supervisor_context


class RecommendationAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = make_agent_registry()
        self.manager = make_agent_manager(self.registry)
        self.sup = DefaultSupervisorManager(
            DefaultSupervisor(router=RuleRouter(), policy=RuleExecutionPolicy())
        )

    def test_recommendation_active_others_skeleton(self) -> None:
        self.assertTrue(self.registry.get(AGENT_RECOMMENDATION).active)
        self.assertTrue(self.registry.get(AGENT_PROPERTY_SEARCH).active)
        self.assertTrue(self.registry.get(AGENT_PROPERTY_ANALYSIS).active)
        for sk in make_skeleton_agents():
            self.assertNotEqual(sk.agent_id, AGENT_RECOMMENDATION)
            self.assertFalse(sk.active)

    def test_selector_picks_recommendation(self) -> None:
        out = self.sup.orchestrate(
            SupervisorRequest(message="بهترین ویلا را پیشنهاد بده تا ۱۵ میلیارد")
        )
        set_supervisor_context(out)
        agent_out = self.manager.prepare(
            AgentContext(
                message="بهترین ویلا را پیشنهاد بده تا ۱۵ میلیارد",
                route=out.workflow.route,
                shared={"property_codes": ["20250101120001", "20250101120002"]},
            )
        )
        self.assertEqual(agent_out.selection.selected_agent, AGENT_RECOMMENDATION)
        self.assertEqual(agent_out.result.status, "ready")
        set_supervisor_context(None)

    def test_engine_ranks_with_analysis_object(self) -> None:
        engine = RuleRecommendationEngine()
        cats = [
            AnalysisCategoryResult(
                name="price",
                summary="20250101120001:قیمت",
                pros=["در بودجه"],
                cons=[],
                score=0.8,
            ),
            AnalysisCategoryResult(
                name="location",
                summary="20250101120001:موقعیت",
                pros=["دماوند"],
                cons=[],
                score=0.7,
            ),
            AnalysisCategoryResult(
                name="price",
                summary="20250101120002:قیمت",
                pros=[],
                cons=["گران"],
                score=0.3,
            ),
        ]
        lands = [
            {
                "code": "20250101120001",
                "city": "دماوند",
                "category": "ویلا",
                "price_total": 10_000_000_000,
            },
            {
                "code": "20250101120002",
                "city": "لواسان",
                "category": "ویلا",
                "price_total": 30_000_000_000,
            },
        ]
        result = engine.rank(
            RecommendationRequest(
                property_codes=("20250101120001", "20250101120002"),
                message="پیشنهاد بهترین ویلا تا ۱۵ میلیارد در دماوند",
                analysis_categories=cats,
                context_budget_chars=90,
            ),
            lands,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.selected_property, "20250101120001")
        self.assertTrue(result.items[0].score >= result.items[-1].score)
        self.assertTrue(result.compact_hint.startswith("=== پیشنهاد فایل ==="))
        self.assertLessEqual(len(result.compact_hint), 160)
        # Accuracy: budget+city winner
        self.assertIn("20250101120001", result.selected_property)

    def test_cache_hit_no_recompute(self) -> None:
        cache = MemoryRecommendationCache()
        mgr = DefaultRecommendationManager(
            engine=RuleRecommendationEngine(), cache=cache
        )
        req = RecommendationRequest(
            property_codes=("11112222333344",),
            message="پیشنهاد بده",
            shared={"search_handoff": True, "property_search_agent": True},
        )
        r1 = mgr.run(req)
        r2 = mgr.run(req)
        self.assertFalse(r1.cache_hit)
        self.assertTrue(r2.cache_hit)
        self.assertTrue(r2.reuse_search)

    def test_should_run_gate(self) -> None:
        self.assertTrue(should_run_recommendation(message="بهترین گزینه را پیشنهاد بده"))
        self.assertFalse(should_run_recommendation(message="سلام"))

    def test_agent_token_budget(self) -> None:
        agent = RecommendationAgent()
        result = agent.run(
            AgentContext(
                message="پیشنهاد بهترین فایل 20250101120001",
                route="property_search",
                shared={
                    "property_codes": ["20250101120001"],
                    "search_handoff": True,
                    "analysis_categories": [
                        AnalysisCategoryResult(
                            name="investment",
                            summary="20250101120001:سرمایه",
                            pros=["مناسب"],
                            score=0.7,
                        )
                    ],
                },
                context_budget_chars=90,
            )
        )
        self.assertEqual(result.status, "ready")
        self.assertLessEqual(result.agent_tokens, 45)


if __name__ == "__main__":
    unittest.main()
