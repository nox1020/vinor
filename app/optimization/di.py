from __future__ import annotations

from app.optimization.decision_optimizer import RuleDecisionOptimizer
from app.optimization.interfaces import OptimizationManager
from app.optimization.manager import DefaultOptimizationManager
from app.optimization.memory_optimizer import RuleMemoryOptimizer
from app.optimization.performance_optimizer import RulePerformanceOptimizer
from app.optimization.rag_optimizer import RuleRagOptimizer
from app.optimization.report_builder import DefaultOptimizationReportBuilder
from app.optimization.workflow_optimizer import RuleWorkflowOptimizer


def make_optimization_manager() -> OptimizationManager:
    return DefaultOptimizationManager(
        decision=RuleDecisionOptimizer(),
        rag=RuleRagOptimizer(),
        memory=RuleMemoryOptimizer(),
        workflow=RuleWorkflowOptimizer(),
        performance=RulePerformanceOptimizer(),
        builder=DefaultOptimizationReportBuilder(),
    )
