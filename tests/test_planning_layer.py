from __future__ import annotations

import unittest
from unittest.mock import patch

from app.planning.evaluator import GoalEvaluator
from app.planning.executor import ToolExecutor
from app.planning.interfaces import PlanningRequest, Task
from app.planning.manager import DefaultPlanningManager
from app.planning.planner import RulePlanner


class PlanningLayerTests(unittest.TestCase):
    def test_search_plan_shape(self) -> None:
        planner = RulePlanner()
        plan = planner.create_plan(
            PlanningRequest(goal="ویلا تا ۱۵ میلیارد در دماوند برای من پیدا کن")
        )
        self.assertEqual(plan.plan_type, "property_search")
        self.assertGreaterEqual(len(plan.tasks), 4)
        self.assertTrue(any(t.tool_name == "search_lands" for t in plan.tasks))

    def test_compare_plan(self) -> None:
        plan = RulePlanner().create_plan(
            PlanningRequest(goal="بین این دو فایل مقایسه کن")
        )
        self.assertEqual(plan.plan_type, "property_compare")

    def test_executor_uses_existing_tool_only(self) -> None:
        executor = ToolExecutor()
        with patch(
            "app.ai.agent_tools.run_tool",
            return_value={
                "ok": True,
                "land_codes": ["V-1"],
                "model_result": {"ok": True, "lands": [{"code": "V-1"}]},
            },
        ) as mocked:
            result = executor.execute_task(
                Task(id="t2", name="search", tool_name="search_lands", tool_args={"query": "ویلا", "limit": 3}),
                req=PlanningRequest(goal="ویلا", user_key="09120000000", audience="partner", voice="partner"),
            )
            self.assertTrue(result.ok)
            self.assertEqual(result.land_codes, ["V-1"])
            mocked.assert_called_once()

    def test_manager_run_once_observability(self) -> None:
        manager = DefaultPlanningManager(
            planner=RulePlanner(),
            executor=ToolExecutor(),
            evaluator=GoalEvaluator(),
        )
        with patch(
            "app.ai.agent_tools.run_tool",
            return_value={
                "ok": True,
                "land_codes": ["A-9"],
                "model_result": {"ok": True, "count": 1, "lands": [{"code": "A-9"}]},
            },
        ):
            out = manager.run_once(
                PlanningRequest(
                    goal="زمین مناسب سرمایه‌گذاری در گرمابسرد",
                    user_key="09120000000",
                    audience="public",
                    voice="public",
                )
            )
        self.assertIsNotNone(out.plan)
        self.assertGreater(out.tasks_count, 0)
        self.assertGreaterEqual(out.executed_tasks, 1)
        self.assertEqual(out.planning_tokens, 0)
        self.assertTrue(out.evaluation.goal_met)
        self.assertIn("A-9", out.land_codes)
        self.assertTrue(out.compact_hint.startswith("=== یافتهٔ برنامه‌ریز ==="))
        # Full plan tasks must not be dumped into hint
        self.assertNotIn("analyze_need", out.compact_hint)


if __name__ == "__main__":
    unittest.main()
