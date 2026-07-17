from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from app.optimization.config import load_optimization_config, optimization_scheduler_enabled
from app.optimization.decision_optimizer import RuleDecisionOptimizer
from app.optimization.di import make_optimization_manager
from app.optimization.interfaces import OptimizationContext
from app.optimization.performance_optimizer import RulePerformanceOptimizer
from app.optimization.rag_optimizer import RuleRagOptimizer
from app.optimization.service import run_optimization
from app.optimization.storage import (
    list_optimization_reports,
    load_optimization_report,
    save_optimization_report,
)


def _eval_rows(n: int = 10, **overrides):
    rows = []
    for i in range(n):
        row = {
            "ok": True,
            "ts": 1_700_000_000 + i,
            "quality": {
                "conflict_rate": 0.4,
                "decision_quality": 0.35,
                "overall": 0.5,
                "recommendation_quality": 0.5,
            },
            "conflict_count": 3,
            "latency_ms": 3000,
            "total_tokens": 1800,
            "rag_tokens": 700,
            "context_tokens": 700,
            "memory_tokens": 150,
            "memory_used": 1,
            "memory_retrieved": 5,
            "estimated_cost": 0.001,
            "total_cost": 0.001,
            "retry_count": 1,
            "selected_agent": "property_search",
            "selected_agents": ["property_search"],
            "validation_errors": ["field_x"] if i % 3 == 0 else [],
            "bi_opportunity_score": 0.3,
        }
        row.update(overrides)
        rows.append(row)
    return rows


class OptimizerUnitTests(unittest.TestCase):
    def test_decision_optimizer_high_conflict(self) -> None:
        sug = RuleDecisionOptimizer().suggest(
            OptimizationContext(evaluation_records=_eval_rows())
        )
        self.assertTrue(any(s.area == "decision_weights" for s in sug))

    def test_rag_optimizer_high_share(self) -> None:
        sug = RuleRagOptimizer().suggest(
            OptimizationContext(token_analytics=_eval_rows())
        )
        self.assertTrue(any(s.area == "rag_top_k" for s in sug))

    def test_performance_optimizer_latency(self) -> None:
        sug = RulePerformanceOptimizer().suggest(
            OptimizationContext(token_analytics=_eval_rows())
        )
        self.assertTrue(any(s.area == "latency_trends" for s in sug))


class ManagerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["VINOR_OPTIMIZATION_ENABLED"] = "1"
        os.environ["VINOR_OPTIMIZATION_SCHEDULER"] = "0"
        import app.optimization.service as osvc

        osvc._MANAGER = None

    def test_manager_never_auto_applies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "app.optimization.storage.optimization_reports_dir", return_value=tmp
            ):
                with patch(
                    "app.optimization.manager.save_optimization_report",
                    side_effect=save_optimization_report,
                ):
                    mgr = make_optimization_manager()
                    report = mgr.run(
                        OptimizationContext(
                            evaluation_records=_eval_rows(),
                            token_analytics=_eval_rows(),
                            bi_snapshots=[{"opportunity_score": 0.3}],
                            lookback_hours=24,
                        )
                    )
            self.assertFalse(report.applied)
            self.assertFalse(report.to_dict().get("applied"))
            self.assertGreater(len(report.suggestions), 0)
            self.assertTrue(report.recommended_config_changes)

    def test_storage_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "app.optimization.storage.optimization_reports_dir", return_value=tmp
            ):
                path = save_optimization_report(
                    {
                        "report_id": "rep1",
                        "created_at": 123,
                        "optimization_count": 2,
                        "estimated_gain": 0.2,
                        "cost_saving": 0.0,
                        "applied": True,  # must be forced false on save
                        "suggestions": [],
                    }
                )
                self.assertTrue(os.path.isfile(path))
                loaded = load_optimization_report("rep1")
                self.assertIsNotNone(loaded)
                self.assertFalse(loaded.get("applied"))
                listed = list_optimization_reports(limit=5)
                self.assertTrue(listed)

    def test_run_optimization_with_mocked_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "app.optimization.storage.optimization_reports_dir", return_value=tmp
            ):
                with patch(
                    "app.optimization.service.build_optimization_context",
                    return_value=OptimizationContext(
                        evaluation_records=_eval_rows(8),
                        token_analytics=_eval_rows(8),
                    ),
                ):
                    with patch(
                        "app.optimization.manager.save_optimization_report",
                        side_effect=save_optimization_report,
                    ):
                        report = run_optimization()
            self.assertIsNotNone(report)
            self.assertFalse(report.applied)

    def test_disabled(self) -> None:
        os.environ["VINOR_OPTIMIZATION_ENABLED"] = "0"
        import app.optimization.service as osvc

        osvc._MANAGER = None
        self.assertIsNone(run_optimization())


class SchedulerConfigTests(unittest.TestCase):
    def test_scheduler_default_on(self) -> None:
        os.environ.pop("VINOR_OPTIMIZATION_SCHEDULER", None)
        self.assertTrue(optimization_scheduler_enabled())

    def test_config_auto_apply_always_false(self) -> None:
        cfg = load_optimization_config()
        self.assertFalse(cfg.auto_apply)

    def test_start_scheduler_noop_when_disabled(self) -> None:
        os.environ["VINOR_OPTIMIZATION_SCHEDULER"] = "0"
        from app.optimization.scheduler import start_optimization_scheduler

        class _App:
            logger = type("L", (), {"info": staticmethod(lambda *a, **k: None)})()

        # Should not raise / should not start thread work when disabled
        start_optimization_scheduler(_App())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
