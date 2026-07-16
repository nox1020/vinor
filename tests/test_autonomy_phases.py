from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from app.business_ai.engine import RuleAutonomousBusinessAI
from app.executive.engine import RuleExecutiveAI
from app.executive.interfaces import ExecutiveRequest
from app.goals.di import make_goal_manager
from app.goals.interfaces import GoalContext
from app.goals.service import run_goals
from app.long_planner.di import make_long_planner_manager
from app.self_improvement.manager import RuleImprovementManager
from app.self_learning.di import make_learning_manager
from app.self_reflection.engine import RuleReflectionEngine
from app.world_model.di import make_world_model_manager


class GoalEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["VINOR_GOALS_ENABLED"] = "1"
        import app.goals.service as gs

        gs._MANAGER = None

    def test_extract_search_goal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.goals.registry._dir", return_value=tmp):
                bundle = make_goal_manager().run(
                    GoalContext(message="ویلا در دماوند می‌خوام", user_key="u1")
                )
        self.assertTrue(bundle.goals)
        self.assertTrue(any(g.goal_type == "search" for g in bundle.goals))


class WorldModelTests(unittest.TestCase):
    def test_snapshot_from_shared(self) -> None:
        snap = make_world_model_manager().update(
            shared={
                "decision": {"selected_property": "P1", "decision_score": 0.7},
                "business_intelligence": {
                    "opportunity_score": 0.6,
                    "signals": {"market_attractiveness": 0.55, "lead_quality": 0.5},
                },
                "goals": {"goals": [{"goal_type": "search"}]},
                "customer_profile": {"relationship_score": 0.4},
            }
        )
        self.assertEqual(snap.property.selected, "P1")
        self.assertGreater(snap.market.opportunity_score, 0)


class LongPlannerTests(unittest.TestCase):
    def test_builds_graph_without_execution(self) -> None:
        graph = make_long_planner_manager().build(
            shared={
                "goals": {
                    "primary_goal_id": "g1",
                    "goals": [{"goal_type": "buy", "goal_id": "g1"}],
                },
                "world_model": {},
            },
            route="property_search",
        )
        self.assertTrue(graph.nodes)
        self.assertTrue(graph.waves)
        self.assertTrue(any(n.kind == "decision" for n in graph.nodes))


class LearningReflectionImprovementTests(unittest.TestCase):
    def test_learning_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.self_learning.manager._store_dir", return_value=tmp):
                report = make_learning_manager().learn(
                    [
                        {"ok": True, "selected_agent": "property_search", "quality": {"overall": 0.8}},
                        {"ok": False, "intent": "search", "quality": {"conflict_rate": 0.5}},
                    ]
                )
        self.assertGreater(report.pattern_count if hasattr(report, "pattern_count") else len(report.patterns), 0)

    def test_reflection(self) -> None:
        r = RuleReflectionEngine().reflect(
            analytics_row={
                "ok": True,
                "decision_selected_property": "X",
                "selected_agent": "property_search",
                "api_rounds": 1,
                "total_tokens": 900,
            },
            shared={"goals": {"goals": [{"goal_type": "search"}]}},
        )
        self.assertTrue(r.goal_completed)
        self.assertGreater(r.score, 0.4)

    def test_improvement_never_applies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.self_improvement.manager._dir", return_value=tmp):
                rep = RuleImprovementManager().improve(
                    reflection={"cost_high": True, "goal_completed": False},
                    learning={"patterns": [{"kind": "failure", "signal": "x", "weight": 0.6}]},
                )
        self.assertFalse(rep.applied)
        self.assertTrue(rep.suggestions)


class ExecutiveTests(unittest.TestCase):
    def test_greeting_light_plan(self) -> None:
        plan = RuleExecutiveAI().plan(ExecutiveRequest(message="سلام", intent="greeting"))
        self.assertTrue(plan.run_goals)
        self.assertFalse(plan.run_agents)
        self.assertEqual(plan.reason, "greeting_light")

    def test_full_cognitive(self) -> None:
        plan = RuleExecutiveAI().plan(
            ExecutiveRequest(message="ویلا تا ۱۵ میلیارد در دماوند", intent="property_search")
        )
        self.assertTrue(plan.run_long_plan)
        self.assertTrue(plan.run_decision)


class BusinessAITests(unittest.TestCase):
    def test_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.business_ai.engine._dir", return_value=tmp):
                report = RuleAutonomousBusinessAI().analyze(
                    evaluation=[
                        {
                            "intent": "search",
                            "property_selected": "A1",
                            "role": "partner",
                            "quality": {"overall": 0.7},
                            "estimated_cost": 0.001,
                        }
                    ],
                    bi_rows=[{"market_score": 0.6}],
                )
        self.assertTrue(report.best_regions)
        self.assertTrue(report.growth_suggestions)


class IntegrationAutonomyTests(unittest.TestCase):
    def setUp(self) -> None:
        for k in (
            "VINOR_GOALS_ENABLED",
            "VINOR_WORLD_MODEL_ENABLED",
            "VINOR_LONG_PLANNER_ENABLED",
            "VINOR_EXECUTIVE_ENABLED",
        ):
            os.environ[k] = "1"

    def test_goals_service_fail_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.goals.registry._dir", return_value=tmp):
                out = run_goals(message="زمین بخرم", user_key="09120001122", audience="partner")
        self.assertIsNotNone(out)


if __name__ == "__main__":
    unittest.main()
