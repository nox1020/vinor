from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from app.evaluation.analytics import RuleAnalyticsAggregator
from app.evaluation.cost import RowCostCollector
from app.evaluation.di import make_evaluation_manager
from app.evaluation.metrics import RowMetricsCollector
from app.evaluation.performance import RowPerformanceCollector
from app.evaluation.quality import RuleQualityEvaluator
from app.evaluation.service import record_evaluation
from app.evaluation.storage import append_evaluation_record, read_evaluation_records


def _sample_row(**overrides):
    row = {
        "ok": True,
        "user": "09121112233",
        "audience": "partner",
        "detected_role": "partner",
        "detected_intent": "property_search",
        "workflow_name": "general",
        "routed_workflow": "property_search",
        "selected_agent": "property_search",
        "merged_agents": ["property_search", "customer_memory"],
        "execution_graph": [["property_search", "customer_memory"], ["property_analysis"]],
        "decision_score": 0.71,
        "decision_confidence": 0.77,
        "decision_selected_property": "CODE01",
        "conflict_count": 1,
        "alternative_count": 2,
        "prompt_tokens": 1000,
        "input_tokens": 1000,
        "output_tokens": 120,
        "total_tokens": 1120,
        "total_cost": 0.0004,
        "latency_ms": 800,
        "planning_time_ms": 5,
        "decision_time_ms": 1,
        "retry_count": 0,
        "recommendation_score": 0.8,
        "negotiation_confidence": 0.6,
        "deal_probability": 0.55,
        "negotiation_risk": 0.2,
        "customer_success_confidence": 0.5,
        "cs_conversion_probability": 0.45,
        "cs_next_action": "follow_up",
        "provider": "deepseek",
        "model": "flash",
    }
    row.update(overrides)
    return row


class MetricsTests(unittest.TestCase):
    def test_collects_all_layers(self) -> None:
        layers = RowMetricsCollector().collect(_sample_row())
        self.assertEqual(layers.conversation["intent"], "property_search")
        self.assertEqual(layers.decision["selected_property"], "CODE01")
        self.assertIn("property_search", layers.parallel["merged_agents"])
        self.assertEqual(layers.llm["prompt_tokens"], 1000)


class QualityTests(unittest.TestCase):
    def test_rule_scores_in_range(self) -> None:
        row = _sample_row()
        layers = RowMetricsCollector().collect(row)
        q = RuleQualityEvaluator().evaluate(row=row, layers=layers)
        self.assertGreater(q.accuracy, 0.5)
        self.assertGreater(q.decision_quality, 0.5)
        self.assertGreater(q.overall, 0.4)
        self.assertLessEqual(q.conflict_rate, 1.0)

    def test_greeting_no_decision_ok(self) -> None:
        row = _sample_row(
            detected_intent="greeting",
            routed_workflow="greeting",
            decision_selected_property="",
            decision_score=0,
            conflict_count=0,
        )
        layers = RowMetricsCollector().collect(row)
        q = RuleQualityEvaluator().evaluate(row=row, layers=layers)
        self.assertGreaterEqual(q.decision_quality, 0.6)


class ManagerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["VINOR_EVALUATION_ENABLED"] = "1"
        os.environ["VINOR_EVALUATION_STORE"] = "1"
        import app.evaluation.service as es

        es._MANAGER = None

    def test_evaluate_request_builds_record(self) -> None:
        mgr = make_evaluation_manager()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ai_evaluation.jsonl")
            with patch("app.evaluation.storage.evaluation_log_path", return_value=path):
                with patch("app.evaluation.manager.append_evaluation_record", side_effect=append_evaluation_record):
                    rec = mgr.evaluate_request(analytics_row=_sample_row(), request_id="req-1")
            self.assertEqual(rec.request_id, "req-1")
            self.assertEqual(rec.property_selected, "CODE01")
            self.assertGreater(rec.total_tokens, 0)
            self.assertGreater(rec.quality.overall, 0)
            self.assertIn("property_search", rec.selected_agents)

    def test_record_evaluation_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ai_evaluation.jsonl")
            with patch("app.evaluation.storage.evaluation_log_path", return_value=path):
                with patch(
                    "app.evaluation.manager.append_evaluation_record",
                    side_effect=append_evaluation_record,
                ):
                    rec = record_evaluation(analytics_row=_sample_row(), request_id="abc")
                    self.assertIsNotNone(rec)
                    rows = read_evaluation_records(limit=10)
                    self.assertTrue(rows)
                    self.assertEqual(rows[-1]["request_id"], "abc")

    def test_disabled_returns_none(self) -> None:
        os.environ["VINOR_EVALUATION_ENABLED"] = "0"
        import app.evaluation.service as es

        es._MANAGER = None
        self.assertIsNone(record_evaluation(analytics_row=_sample_row()))


class AnalyticsTests(unittest.TestCase):
    def test_summarize_daily(self) -> None:
        records = [
            {
                "ok": True,
                "intent": "search",
                "selected_agents": ["property_search"],
                "estimated_cost": 0.001,
                "total_tokens": 1000,
                "latency_ms": 500,
                "quality": {"overall": 0.8, "conflict_rate": 0.1},
            },
            {
                "ok": False,
                "intent": "search",
                "errors": ["request_failed"],
                "selected_agents": ["recommendation"],
                "estimated_cost": 0.002,
                "total_tokens": 1100,
                "latency_ms": 700,
                "quality": {"overall": 0.4, "conflict_rate": 0.2},
            },
        ]
        summary = RuleAnalyticsAggregator().summarize(
            records=records, period="daily", period_key="2026-07-16"
        )
        self.assertEqual(summary.request_count, 2)
        self.assertEqual(summary.failed_count, 1)
        self.assertTrue(summary.top_queries)
        self.assertTrue(summary.most_used_agents)

    def test_cost_and_performance_collectors(self) -> None:
        row = _sample_row()
        layers = RowMetricsCollector().collect(row)
        cost = RowCostCollector().collect_cost(row)
        timings = RowPerformanceCollector().collect_timings(row, layers)
        self.assertEqual(cost["prompt_tokens"], 1000)
        self.assertGreaterEqual(timings["latency_ms"], 800)
        self.assertGreaterEqual(timings["llm_time_ms"], 0)


if __name__ == "__main__":
    unittest.main()
