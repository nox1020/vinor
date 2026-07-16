from __future__ import annotations

from app.evaluation.analytics import RuleAnalyticsAggregator
from app.evaluation.config import load_evaluation_config
from app.evaluation.cost import RowCostCollector
from app.evaluation.interfaces import EvaluationManager
from app.evaluation.manager import DefaultEvaluationManager
from app.evaluation.metrics import RowMetricsCollector
from app.evaluation.performance import RowPerformanceCollector
from app.evaluation.quality import RuleQualityEvaluator


def make_evaluation_manager() -> EvaluationManager:
    return DefaultEvaluationManager(
        metrics=RowMetricsCollector(),
        performance=RowPerformanceCollector(),
        cost=RowCostCollector(),
        quality=RuleQualityEvaluator(),
        aggregator=RuleAnalyticsAggregator(),
        config=load_evaluation_config(),
    )
