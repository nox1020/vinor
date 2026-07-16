from __future__ import annotations

import unittest

from app.supervisor.interfaces import SupervisorRequest
from app.supervisor.manager import DefaultSupervisor, DefaultSupervisorManager
from app.supervisor.policy import RuleExecutionPolicy
from app.supervisor.router import RuleRouter
from app.supervisor.service import allow_component, set_supervisor_context


class SupervisorLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mgr = DefaultSupervisorManager(
            DefaultSupervisor(router=RuleRouter(), policy=RuleExecutionPolicy())
        )

    def test_greeting_skips_heavy_components(self) -> None:
        out = self.mgr.orchestrate(SupervisorRequest(message="سلام"))
        self.assertEqual(out.workflow.route, "greeting")
        self.assertFalse(out.workflow.flags.use_rag)
        self.assertFalse(out.workflow.flags.use_planning)
        self.assertFalse(out.workflow.flags.use_memory)
        self.assertIn("rag", out.workflow.skipped)
        self.assertIn("llm", out.workflow.executed)

    def test_property_search_enables_planning_memory_rag(self) -> None:
        out = self.mgr.orchestrate(
            SupervisorRequest(message="ویلا تا ۱۵ میلیارد در دماوند پیدا کن")
        )
        self.assertEqual(out.workflow.route, "property_search")
        self.assertTrue(out.workflow.flags.use_planning)
        self.assertTrue(out.workflow.flags.use_memory)
        self.assertTrue(out.workflow.flags.use_rag)

    def test_follow_up_memory_and_planning(self) -> None:
        out = self.mgr.orchestrate(SupervisorRequest(message="کار بعدی چیه؟"))
        self.assertEqual(out.workflow.route, "follow_up")
        self.assertTrue(out.workflow.flags.use_memory)
        self.assertTrue(out.workflow.flags.use_planning)
        self.assertFalse(out.workflow.flags.use_rag)

    def test_faq_route(self) -> None:
        out = self.mgr.orchestrate(SupervisorRequest(message="شرایط همکاری و پورسانت چیست؟"))
        self.assertEqual(out.workflow.route, "faq")

    def test_allow_component_gate(self) -> None:
        out = self.mgr.orchestrate(SupervisorRequest(message="سلام"))
        set_supervisor_context(out)
        self.assertFalse(allow_component("rag", default=True))
        self.assertTrue(allow_component("llm", default=True))
        set_supervisor_context(None)


if __name__ == "__main__":
    unittest.main()
