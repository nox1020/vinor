from __future__ import annotations

import time
import uuid
from typing import Any

from app.evaluation.analytics import RuleAnalyticsAggregator
from app.evaluation.config import load_evaluation_config
from app.evaluation.cost import RowCostCollector
from app.evaluation.interfaces import (
    AnalyticsAggregator,
    CostCollector,
    EvaluationConfig,
    EvaluationManager,
    EvaluationRecord,
    MetricsCollector,
    PerformanceCollector,
    QualityEvaluator,
)
from app.evaluation.metrics import RowMetricsCollector
from app.evaluation.performance import RowPerformanceCollector
from app.evaluation.quality import RuleQualityEvaluator
from app.evaluation.storage import append_evaluation_record


class DefaultEvaluationManager(EvaluationManager):
    """Observability-only — never mutates prompts or re-runs pipeline."""

    def __init__(
        self,
        *,
        metrics: MetricsCollector | None = None,
        performance: PerformanceCollector | None = None,
        cost: CostCollector | None = None,
        quality: QualityEvaluator | None = None,
        aggregator: AnalyticsAggregator | None = None,
        config: EvaluationConfig | None = None,
    ):
        self._metrics = metrics or RowMetricsCollector()
        self._performance = performance or RowPerformanceCollector()
        self._cost = cost or RowCostCollector()
        self._quality = quality or RuleQualityEvaluator()
        self._aggregator = aggregator or RuleAnalyticsAggregator()
        self._config = config or load_evaluation_config()

    def evaluate_request(
        self, *, analytics_row: dict[str, Any], request_id: str = ""
    ) -> EvaluationRecord:
        row = dict(analytics_row or {})
        layers = self._metrics.collect(row)
        timings = self._performance.collect_timings(row, layers)
        cost = self._cost.collect_cost(row)
        quality = self._quality.evaluate(row=row, layers=layers)

        selected_agents: list[str] = []
        sa = str(row.get("selected_agent") or "").strip()
        if sa:
            selected_agents.append(sa)
        for a in row.get("merged_agents") or []:
            s = str(a).strip()
            if s and s not in selected_agents:
                selected_agents.append(s)

        errors: list[str] = []
        if not row.get("ok", True):
            errors.append("request_failed")
        for e in row.get("validation_errors") or []:
            errors.append(str(e)[:120])

        warnings: list[str] = []
        if int(row.get("conflict_count") or 0) > 0:
            warnings.append("decision_conflicts")
        if int(row.get("retry_count") or 0) > 0:
            warnings.append("retries")
        for n in quality.notes:
            if n and n not in warnings:
                warnings.append(str(n)[:80])

        alts = list(row.get("alternatives") or [])
        if not alts:
            # soft from decision obs if present in row metadata
            pass

        rid = request_id or str(row.get("request_id") or "") or uuid.uuid4().hex[:16]
        record = EvaluationRecord(
            request_id=rid,
            user_id=str(row.get("user") or row.get("user_id") or ""),
            role=str(
                row.get("detected_role")
                or row.get("audience")
                or row.get("role")
                or ""
            ),
            intent=str(row.get("detected_intent") or row.get("intent") or ""),
            workflow=str(
                row.get("workflow_name")
                or row.get("conversation_workflow")
                or row.get("routed_workflow")
                or ""
            ),
            selected_agents=selected_agents,
            execution_graph=list(row.get("execution_graph") or []),
            decision_score=float(layers.decision.get("decision_score") or 0),
            decision_confidence=float(layers.decision.get("decision_confidence") or 0),
            property_selected=str(layers.decision.get("selected_property") or ""),
            alternatives=list(alts)[:8],
            prompt_tokens=int(cost.get("prompt_tokens") or 0),
            completion_tokens=int(cost.get("completion_tokens") or 0),
            total_tokens=int(cost.get("total_tokens") or 0),
            estimated_cost=float(cost.get("estimated_cost") or 0),
            latency_ms=int(timings.get("latency_ms") or 0),
            rag_time_ms=int(timings.get("rag_time_ms") or 0),
            memory_time_ms=int(timings.get("memory_time_ms") or 0),
            planning_time_ms=int(timings.get("planning_time_ms") or 0),
            decision_time_ms=int(timings.get("decision_time_ms") or 0),
            llm_time_ms=int(timings.get("llm_time_ms") or 0),
            tool_time_ms=int(timings.get("tool_time_ms") or 0),
            errors=errors[:12],
            warnings=warnings[:12],
            retry_count=int(row.get("retry_count") or 0),
            layer_metrics=layers,
            quality=quality,
            ok=bool(row.get("ok", True)),
            ts=int(time.time()),
            metadata={
                "provider": str(row.get("provider") or ""),
                "model": str(row.get("model") or ""),
                "cache_hit": bool(row.get("cache_hit")),
            },
        )

        if self._config.store_logs:
            try:
                # Enrich alternatives from decision dict if available on g
                data = record.to_dict()
                try:
                    from app.decision.service import get_decision

                    dec = get_decision()
                    if isinstance(dec, dict) and not data.get("alternatives"):
                        data["alternatives"] = list(dec.get("alternative_properties") or [])[:8]
                        record.alternatives = list(data["alternatives"])
                except Exception:
                    pass
                append_evaluation_record(data)
            except Exception:
                pass
        return record

    @property
    def aggregator(self) -> AnalyticsAggregator:
        return self._aggregator
