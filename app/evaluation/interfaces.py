from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class EvaluationConfig:
    enabled: bool = True
    store_logs: bool = True
    max_top_queries: int = 20


@dataclass
class LayerMetrics:
    """Per-layer snapshot — reuse only, no re-execution."""

    conversation: dict[str, Any] = field(default_factory=dict)
    workflow: dict[str, Any] = field(default_factory=dict)
    supervisor: dict[str, Any] = field(default_factory=dict)
    adaptive: dict[str, Any] = field(default_factory=dict)
    planning: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    rag: dict[str, Any] = field(default_factory=dict)
    parallel: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    llm: dict[str, Any] = field(default_factory=dict)
    tools: dict[str, Any] = field(default_factory=dict)


@dataclass
class QualityScores:
    accuracy: float = 0.0
    conflict_rate: float = 0.0
    decision_quality: float = 0.0
    recommendation_quality: float = 0.0
    negotiation_quality: float = 0.0
    customer_success_quality: float = 0.0
    overall: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accuracy": self.accuracy,
            "conflict_rate": self.conflict_rate,
            "decision_quality": self.decision_quality,
            "recommendation_quality": self.recommendation_quality,
            "negotiation_quality": self.negotiation_quality,
            "customer_success_quality": self.customer_success_quality,
            "overall": self.overall,
            "notes": list(self.notes),
        }


@dataclass
class EvaluationRecord:
    request_id: str = ""
    user_id: str = ""
    role: str = ""
    intent: str = ""
    workflow: str = ""
    selected_agents: list[str] = field(default_factory=list)
    execution_graph: list[Any] = field(default_factory=list)
    decision_score: float = 0.0
    decision_confidence: float = 0.0
    property_selected: str = ""
    alternatives: list[str] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0
    latency_ms: int = 0
    rag_time_ms: int = 0
    memory_time_ms: int = 0
    planning_time_ms: int = 0
    decision_time_ms: int = 0
    llm_time_ms: int = 0
    tool_time_ms: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    retry_count: int = 0
    layer_metrics: LayerMetrics = field(default_factory=LayerMetrics)
    quality: QualityScores = field(default_factory=QualityScores)
    ok: bool = True
    ts: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "user_id": self.user_id,
            "role": self.role,
            "intent": self.intent,
            "workflow": self.workflow,
            "selected_agents": list(self.selected_agents),
            "execution_graph": list(self.execution_graph),
            "decision_score": self.decision_score,
            "decision_confidence": self.decision_confidence,
            "property_selected": self.property_selected,
            "alternatives": list(self.alternatives),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost": self.estimated_cost,
            "latency_ms": self.latency_ms,
            "rag_time_ms": self.rag_time_ms,
            "memory_time_ms": self.memory_time_ms,
            "planning_time_ms": self.planning_time_ms,
            "decision_time_ms": self.decision_time_ms,
            "llm_time_ms": self.llm_time_ms,
            "tool_time_ms": self.tool_time_ms,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "retry_count": self.retry_count,
            "layer_metrics": {
                "conversation": dict(self.layer_metrics.conversation),
                "workflow": dict(self.layer_metrics.workflow),
                "supervisor": dict(self.layer_metrics.supervisor),
                "adaptive": dict(self.layer_metrics.adaptive),
                "planning": dict(self.layer_metrics.planning),
                "memory": dict(self.layer_metrics.memory),
                "rag": dict(self.layer_metrics.rag),
                "parallel": dict(self.layer_metrics.parallel),
                "decision": dict(self.layer_metrics.decision),
                "llm": dict(self.layer_metrics.llm),
                "tools": dict(self.layer_metrics.tools),
            },
            "quality": self.quality.to_dict(),
            "ok": self.ok,
            "ts": self.ts,
            "metadata": dict(self.metadata),
        }


@dataclass
class AnalyticsSummary:
    period: str = ""  # daily | weekly | monthly
    period_key: str = ""
    request_count: int = 0
    failed_count: int = 0
    avg_cost: float = 0.0
    avg_token: float = 0.0
    avg_latency_ms: float = 0.0
    top_queries: list[dict[str, Any]] = field(default_factory=list)
    failed_queries: list[dict[str, Any]] = field(default_factory=list)
    most_used_agents: list[dict[str, Any]] = field(default_factory=list)
    avg_quality: float = 0.0
    avg_conflict_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "period_key": self.period_key,
            "request_count": self.request_count,
            "failed_count": self.failed_count,
            "avg_cost": self.avg_cost,
            "avg_token": self.avg_token,
            "avg_latency_ms": self.avg_latency_ms,
            "top_queries": list(self.top_queries),
            "failed_queries": list(self.failed_queries),
            "most_used_agents": list(self.most_used_agents),
            "avg_quality": self.avg_quality,
            "avg_conflict_rate": self.avg_conflict_rate,
        }


class MetricsCollector(Protocol):
    def collect(self, analytics_row: dict[str, Any]) -> LayerMetrics:
        ...


class PerformanceCollector(Protocol):
    def collect_timings(self, analytics_row: dict[str, Any], layers: LayerMetrics) -> dict[str, int]:
        ...


class CostCollector(Protocol):
    def collect_cost(self, analytics_row: dict[str, Any]) -> dict[str, Any]:
        ...


class QualityEvaluator(Protocol):
    def evaluate(self, *, row: dict[str, Any], layers: LayerMetrics) -> QualityScores:
        ...


class AnalyticsAggregator(Protocol):
    def summarize(
        self, *, records: list[dict[str, Any]], period: str, period_key: str
    ) -> AnalyticsSummary:
        ...


class EvaluationManager(Protocol):
    def evaluate_request(
        self, *, analytics_row: dict[str, Any], request_id: str = ""
    ) -> EvaluationRecord:
        ...
