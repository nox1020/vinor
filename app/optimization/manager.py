from __future__ import annotations

import time
import uuid

from app.optimization.config import load_optimization_config
from app.optimization.decision_optimizer import RuleDecisionOptimizer
from app.optimization.interfaces import (
    DecisionOptimizer,
    MemoryOptimizer,
    OptimizationContext,
    OptimizationManager,
    OptimizationReport,
    OptimizationReportBuilder,
    PerformanceOptimizer,
    RagOptimizer,
    WorkflowOptimizer,
)
from app.optimization.memory_optimizer import RuleMemoryOptimizer
from app.optimization.performance_optimizer import RulePerformanceOptimizer
from app.optimization.rag_optimizer import RuleRagOptimizer
from app.optimization.report_builder import DefaultOptimizationReportBuilder
from app.optimization.storage import save_optimization_report
from app.optimization.workflow_optimizer import RuleWorkflowOptimizer


class DefaultOptimizationManager(OptimizationManager):
    """Background recommendations only — never mutates runtime config."""

    def __init__(
        self,
        *,
        decision: DecisionOptimizer | None = None,
        rag: RagOptimizer | None = None,
        memory: MemoryOptimizer | None = None,
        workflow: WorkflowOptimizer | None = None,
        performance: PerformanceOptimizer | None = None,
        builder: OptimizationReportBuilder | None = None,
    ):
        self._decision = decision or RuleDecisionOptimizer()
        self._rag = rag or RuleRagOptimizer()
        self._memory = memory or RuleMemoryOptimizer()
        self._workflow = workflow or RuleWorkflowOptimizer()
        self._performance = performance or RulePerformanceOptimizer()
        self._builder = builder or DefaultOptimizationReportBuilder()

    def run(self, ctx: OptimizationContext | None = None) -> OptimizationReport:
        t0 = time.perf_counter()
        cfg = load_optimization_config()
        # Force never auto-apply
        assert cfg.auto_apply is False
        ctx = ctx or OptimizationContext(lookback_hours=cfg.lookback_hours)
        suggestions = []
        for opt in (
            self._decision,
            self._rag,
            self._memory,
            self._workflow,
            self._performance,
        ):
            try:
                suggestions.extend(opt.suggest(ctx) or [])
            except Exception:
                continue
        duration_ms = int((time.perf_counter() - t0) * 1000)
        report = self._builder.build(
            suggestions=suggestions,
            ctx=ctx,
            duration_ms=duration_ms,
            report_id=uuid.uuid4().hex[:16],
        )
        report.applied = False
        try:
            save_optimization_report(report.to_dict())
        except Exception:
            pass
        return report
