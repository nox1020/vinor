from __future__ import annotations

import os
import unittest

from app.agents.di import make_agent_registry
from app.agents.interfaces import (
    AGENT_CUSTOMER_MEMORY,
    AGENT_PROPERTY_ANALYSIS,
    AGENT_PROPERTY_SEARCH,
    AGENT_RECOMMENDATION,
)
from app.agents.parallel.di import make_parallel_manager
from app.agents.parallel.graph import StaticDependencyGraphBuilder, waves_for_subset
from app.agents.parallel.interfaces import ExecutionContext
from app.agents.parallel.merger import CompactAgentResultMerger
from app.agents.parallel.planner import RuleExecutionPlanner
from app.agents.parallel.service import execution_result_to_outcome, run_parallel_collaboration
from app.agents.service import prepare_agent


class GraphTests(unittest.TestCase):
    def test_waves_search_memory_parallel_then_analysis(self) -> None:
        selected = {
            AGENT_PROPERTY_SEARCH,
            AGENT_CUSTOMER_MEMORY,
            AGENT_PROPERTY_ANALYSIS,
        }
        waves = waves_for_subset(selected)
        self.assertEqual(len(waves), 2)
        self.assertEqual(set(waves[0]), {AGENT_PROPERTY_SEARCH, AGENT_CUSTOMER_MEMORY})
        self.assertEqual(waves[1], [AGENT_PROPERTY_ANALYSIS])

    def test_full_dag_levels(self) -> None:
        full = StaticDependencyGraphBuilder().build()
        ids = {n.agent_id for n in full.nodes}
        waves = waves_for_subset(ids, full)
        self.assertGreaterEqual(len(waves), 4)
        self.assertIn(AGENT_PROPERTY_SEARCH, waves[0])
        self.assertIn(AGENT_CUSTOMER_MEMORY, waves[0])


class PlannerTests(unittest.TestCase):
    def test_greeting_empty(self) -> None:
        plan = RuleExecutionPlanner().plan(
            ExecutionContext(message="سلام", route="greeting")
        )
        self.assertEqual(plan.waves, [])

    def test_recommend_includes_chain(self) -> None:
        plan = RuleExecutionPlanner().plan(
            ExecutionContext(
                message="بهترین ویلا را پیشنهاد بده تا ۱۵ میلیارد",
                route="property_search",
            )
        )
        flat = [a for w in plan.waves for a in w]
        self.assertIn(AGENT_PROPERTY_SEARCH, flat)
        self.assertIn(AGENT_PROPERTY_ANALYSIS, flat)
        self.assertIn(AGENT_RECOMMENDATION, flat)
        self.assertIn(AGENT_CUSTOMER_MEMORY, flat)


class MergerTests(unittest.TestCase):
    def test_compact_hint_budget(self) -> None:
        obj, hint, tok = CompactAgentResultMerger().merge(
            results={},
            shared={
                "recommended_code": "20250101120001",
                "customer_success": {"next_action": "propose_close"},
                "property_search_agent": True,
            },
            budget_chars=80,
        )
        self.assertIn("همکاری", hint)
        self.assertLessEqual(len(hint), 80)
        self.assertGreater(tok, 0)


class ParallelIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["VINOR_PARALLEL_AGENTS"] = "1"
        os.environ["VINOR_AGENTS_ENABLED"] = "1"
        import app.agents.parallel.service as ps
        import app.agents.service as ags

        ps._MANAGER = None
        ags._MANAGER = None

    def test_parallel_run_search_path(self) -> None:
        mgr = make_parallel_manager(make_agent_registry())
        result = mgr.run(
            ExecutionContext(
                message="ویلا تا ۱۵ میلیارد در دماوند",
                route="property_search",
                audience="partner",
                user_key="09121112233",
                parallel=True,
            )
        )
        self.assertTrue(result.ok)
        self.assertTrue(result.merged_agents)
        self.assertIn(AGENT_PROPERTY_SEARCH, result.merged_agents)
        self.assertIn(AGENT_CUSTOMER_MEMORY, result.merged_agents)
        self.assertGreaterEqual(result.parallel_tasks, 1)
        self.assertTrue(result.compact_hint)
        out = execution_result_to_outcome(result)
        self.assertEqual(out.selection.selected_agent, AGENT_PROPERTY_SEARCH)

    def test_prepare_agent_uses_parallel(self) -> None:
        out = prepare_agent(
            message="ویلا در دماوند",
            route="property_search",
            audience="partner",
            user_key="09121112233",
        )
        self.assertIsNotNone(out)
        self.assertIn("parallel", out.result.used_components)

    def test_sequential_flag_still_runs_waves(self) -> None:
        result = run_parallel_collaboration(
            message="ویلا در دماوند",
            route="property_search",
            user_key="09121112233",
            parallel=False,
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.merged_agents)


if __name__ == "__main__":
    unittest.main()
