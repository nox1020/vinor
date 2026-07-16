from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class OptimizationConfig:
    enabled: bool = True
    scheduler_enabled: bool = False
    interval_seconds: int = 3600
    lookback_hours: int = 24
    min_samples: int = 5
    auto_apply: bool = False  # ALWAYS false — recommendations only


@dataclass
class OptimizationSuggestion:
    area: str
    title: str
    recommendation: str
    recommended_config: dict[str, Any] = field(default_factory=dict)
    priority: str = "medium"  # low | medium | high
    expected_impact: str = ""
    confidence: float = 0.5
    estimated_gain: float = 0.0
    cost_saving: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "area": self.area,
            "title": self.title,
            "recommendation": self.recommendation,
            "recommended_config": dict(self.recommended_config),
            "priority": self.priority,
            "expected_impact": self.expected_impact,
            "confidence": self.confidence,
            "estimated_gain": self.estimated_gain,
            "cost_saving": self.cost_saving,
        }


@dataclass
class OptimizationReport:
    report_id: str = ""
    created_at: int = 0
    sample_count: int = 0
    suggestions: list[OptimizationSuggestion] = field(default_factory=list)
    performance_findings: list[str] = field(default_factory=list)
    cost_findings: list[str] = field(default_factory=list)
    recommended_config_changes: dict[str, Any] = field(default_factory=dict)
    optimization_duration_ms: int = 0
    estimated_gain: float = 0.0
    cost_saving: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    applied: bool = False  # always False — never auto-apply

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "created_at": self.created_at,
            "sample_count": self.sample_count,
            "suggestions": [s.to_dict() for s in self.suggestions],
            "performance_findings": list(self.performance_findings),
            "cost_findings": list(self.cost_findings),
            "recommended_config_changes": dict(self.recommended_config_changes),
            "optimization_duration_ms": self.optimization_duration_ms,
            "estimated_gain": self.estimated_gain,
            "cost_saving": self.cost_saving,
            "metadata": dict(self.metadata),
            "applied": False,
            "optimization_count": len(self.suggestions),
        }


@dataclass
class OptimizationContext:
    evaluation_records: list[dict[str, Any]] = field(default_factory=list)
    token_analytics: list[dict[str, Any]] = field(default_factory=list)
    bi_snapshots: list[dict[str, Any]] = field(default_factory=list)
    decision_samples: list[dict[str, Any]] = field(default_factory=list)
    lookback_hours: int = 24


class DecisionOptimizer(Protocol):
    def suggest(self, ctx: OptimizationContext) -> list[OptimizationSuggestion]:
        ...


class RagOptimizer(Protocol):
    def suggest(self, ctx: OptimizationContext) -> list[OptimizationSuggestion]:
        ...


class MemoryOptimizer(Protocol):
    def suggest(self, ctx: OptimizationContext) -> list[OptimizationSuggestion]:
        ...


class WorkflowOptimizer(Protocol):
    def suggest(self, ctx: OptimizationContext) -> list[OptimizationSuggestion]:
        ...


class PerformanceOptimizer(Protocol):
    def suggest(self, ctx: OptimizationContext) -> list[OptimizationSuggestion]:
        ...


class OptimizationReportBuilder(Protocol):
    def build(
        self,
        *,
        suggestions: list[OptimizationSuggestion],
        ctx: OptimizationContext,
        duration_ms: int,
        report_id: str,
    ) -> OptimizationReport:
        ...


class OptimizationManager(Protocol):
    def run(self, ctx: OptimizationContext | None = None) -> OptimizationReport:
        ...
