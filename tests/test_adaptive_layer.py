from __future__ import annotations

import unittest

from app.adaptive.confidence import RuleConfidenceEstimator
from app.adaptive.di import make_adaptive_controller
from app.adaptive.evaluator import RuleQualityEvaluator
from app.adaptive.interfaces import (
    STATE_DONE,
    STATE_FAILED,
    STATE_READY,
    STATE_SEARCHING,
    AdaptiveRequest,
    ConfidenceScore,
)
from app.adaptive.retry import RuleRetryPolicy
from app.adaptive.service import (
    after_agent_prepare_adaptive,
    after_response_adaptive,
    begin_adaptive,
    clear_adaptive,
    get_adaptive_obs,
    use_lean_strategy,
)
from app.adaptive.state import RuleWorkflowMachine


class AdaptiveLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_adaptive()
        self.ctrl = make_adaptive_controller()

    def tearDown(self) -> None:
        clear_adaptive()

    def test_search_workflow_reaches_ready_then_done(self) -> None:
        out = self.ctrl.begin(AdaptiveRequest(message="ویلا", route="property_search"))
        self.assertEqual(out.workflow.state, STATE_SEARCHING)
        out = self.ctrl.after_agent_prepare(
            out.workflow,
            agent_status="ready",
            used_components=["planning", "memory", "rag", "tools", "llm"],
            selected_agent="property_search",
        )
        self.assertEqual(out.workflow.state, STATE_READY)
        self.assertGreaterEqual(out.workflow.confidence.value, 0.7)
        out = self.ctrl.after_response(
            out.workflow,
            reply="چند فایل مناسب پیدا شد.",
            land_codes=["A1", "B2"],
            ok=True,
        )
        self.assertEqual(out.workflow.state, STATE_DONE)
        self.assertEqual(out.extra_tokens, 0)

    def test_greeting_passthrough(self) -> None:
        out = self.ctrl.begin(AdaptiveRequest(message="سلام", route="greeting"))
        out = self.ctrl.after_agent_prepare(
            out.workflow,
            agent_status="skipped",
            used_components=[],
            selected_agent="",
        )
        self.assertEqual(out.workflow.state, STATE_READY)
        out = self.ctrl.after_response(
            out.workflow, reply="سلام، چطور کمک کنم؟", land_codes=[], ok=True
        )
        self.assertEqual(out.workflow.state, STATE_DONE)

    def test_low_prepare_confidence_triggers_retry_lean(self) -> None:
        out = self.ctrl.begin(AdaptiveRequest(message="ویلا", route="property_search"))
        out = self.ctrl.after_agent_prepare(
            out.workflow,
            agent_status="ready",
            used_components=["llm"],  # missing rag/planning → low conf
            selected_agent="property_search",
        )
        self.assertEqual(out.workflow.retry_count, 1)
        self.assertEqual(out.workflow.strategy, "lean")
        self.assertLess(out.workflow.confidence.value, 0.55)

    def test_quality_partial_search_recovers_without_loop(self) -> None:
        out = self.ctrl.begin(AdaptiveRequest(message="ویلا", route="property_search"))
        out = self.ctrl.after_agent_prepare(
            out.workflow,
            agent_status="ready",
            used_components=["planning", "memory", "rag", "tools", "llm"],
            selected_agent="property_search",
        )
        out = self.ctrl.after_response(
            out.workflow,
            reply="فعلاً فایل دقیقی پیدا نشد، جزئیات بیشتری بدهید.",
            land_codes=[],
            ok=True,
        )
        self.assertIn(out.workflow.state, (STATE_DONE, STATE_FAILED))
        self.assertGreaterEqual(out.workflow.recovery_count, 1)
        # No infinite history growth
        self.assertLessEqual(len(out.workflow.history), 12)

    def test_failure_recovery(self) -> None:
        out = self.ctrl.begin(AdaptiveRequest(message="ویلا", route="property_search"))
        out = self.ctrl.on_failure(out.workflow, error="llm_failed")
        self.assertEqual(out.workflow.state, STATE_FAILED)
        self.assertGreaterEqual(out.workflow.recovery_count, 1)

    def test_illegal_transition_does_not_crash(self) -> None:
        machine = RuleWorkflowMachine()
        wf = machine.start(route="property_search")
        machine.advance(wf, STATE_SEARCHING)
        machine.advance(wf, STATE_DONE, reason="force")  # illegal from SEARCHING? SEARCHING allows DONE
        # Force illegal: DONE -> SEARCHING
        machine.advance(wf, STATE_SEARCHING, reason="bad")
        self.assertEqual(wf.state, STATE_FAILED)

    def test_service_hooks_and_obs(self) -> None:
        begin_adaptive(message="ویلا دماوند", route="property_search")
        after_agent_prepare_adaptive(
            agent_status="ready",
            used_components=["planning", "memory", "rag", "tools", "llm"],
            selected_agent="property_search",
        )
        after_response_adaptive(
            reply="فایل‌ها آماده است.",
            land_codes=["X1"],
            ok=True,
        )
        obs = get_adaptive_obs()
        self.assertEqual(obs["workflow_state"], STATE_DONE)
        self.assertEqual(obs["adaptive_extra_tokens"], 0)
        self.assertGreater(obs["confidence_score"], 0.5)

    def test_evaluator_and_confidence_units(self) -> None:
        conf = RuleConfidenceEstimator().estimate_response(
            route="property_search",
            reply="ok",
            land_codes=["A"],
            ok=True,
        )
        q = RuleQualityEvaluator().evaluate(
            route="property_search",
            reply="ok enough text here",
            land_codes=["A"],
            ok=True,
            confidence=conf,
        )
        self.assertTrue(q.complete)
        self.assertTrue(q.found_suitable)

    def test_retry_policy_max_one(self) -> None:
        policy = RuleRetryPolicy()
        from app.adaptive.interfaces import WorkflowState

        wf = WorkflowState(state=STATE_SEARCHING, route="property_search", retry_count=1)
        self.assertFalse(policy.should_retry(wf, ConfidenceScore(value=0.1)))


if __name__ == "__main__":
    unittest.main()
