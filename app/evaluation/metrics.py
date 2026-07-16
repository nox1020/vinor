from __future__ import annotations

from typing import Any

from app.evaluation.interfaces import LayerMetrics, MetricsCollector


def _f(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key) if row.get(key) is not None else default)
    except Exception:
        return default


def _i(row: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(row.get(key) if row.get(key) is not None else default)
    except Exception:
        return default


class RowMetricsCollector(MetricsCollector):
    """Build layer metrics from existing analytics row / obs — no re-run."""

    def collect(self, analytics_row: dict[str, Any]) -> LayerMetrics:
        row = analytics_row or {}
        return LayerMetrics(
            conversation={
                "role": str(row.get("detected_role") or ""),
                "intent": str(row.get("detected_intent") or ""),
                "workflow": str(row.get("conversation_workflow") or row.get("workflow_name") or ""),
                "state": str(row.get("conversation_state") or ""),
                "step": str(row.get("conversation_step") or ""),
                "extra_tokens": _i(row, "conversation_extra_tokens"),
            },
            workflow={
                "name": str(row.get("workflow_name") or ""),
                "state": str(row.get("workflow_state") or ""),
                "extra_tokens": _i(row, "workflow_extra_tokens"),
                "validation_errors": list(row.get("validation_errors") or []),
            },
            supervisor={
                "routed_workflow": str(row.get("routed_workflow") or ""),
                "executed_components": list(row.get("executed_components") or []),
                "skipped_components": list(row.get("skipped_components") or []),
                "routing_time_ms": _i(row, "routing_time_ms"),
            },
            adaptive={
                "confidence_score": _f(row, "confidence_score"),
                "retry_count": _i(row, "retry_count"),
                "recovery_count": _i(row, "recovery_count"),
                "skipped_steps": list(row.get("skipped_steps") or []),
                "extra_tokens": _i(row, "adaptive_extra_tokens"),
            },
            planning={
                "plan_type": str(row.get("plan_type") or ""),
                "planning_time_ms": _i(row, "planning_time_ms"),
                "tasks_count": _i(row, "tasks_count"),
                "executed_tasks": _i(row, "executed_tasks"),
                "planning_tokens": _i(row, "planning_tokens"),
                "execution_tokens": _i(row, "execution_tokens"),
            },
            memory={
                "memory_retrieved": _i(row, "memory_retrieved"),
                "memory_used": _i(row, "memory_used"),
                "memory_tokens": _i(row, "memory_tokens"),
                "customer_memory_tokens": _i(row, "customer_memory_tokens"),
                "relationship_score": _f(row, "relationship_score"),
                "profile_confidence": _f(row, "profile_confidence"),
            },
            rag={
                "rag_tokens": _i(row, "rag_tokens"),
                "context_tokens": _i(row, "context_tokens"),
            },
            parallel={
                "parallel_tasks": _i(row, "parallel_tasks"),
                "parallel_execution_time_ms": _i(row, "parallel_execution_time_ms"),
                "parallel_merge_tokens": _i(row, "parallel_merge_tokens"),
                "merged_agents": list(row.get("merged_agents") or []),
                "execution_graph": list(row.get("execution_graph") or []),
            },
            decision={
                "decision_time_ms": _i(row, "decision_time_ms"),
                "decision_score": _f(row, "decision_score"),
                "decision_confidence": _f(row, "decision_confidence"),
                "conflict_count": _i(row, "conflict_count"),
                "alternative_count": _i(row, "alternative_count"),
                "selected_property": str(
                    row.get("decision_selected_property") or row.get("selected_property") or ""
                ),
                "decision_tokens": _i(row, "decision_tokens"),
            },
            llm={
                "provider": str(row.get("provider") or ""),
                "model": str(row.get("model") or ""),
                "prompt_tokens": _i(row, "prompt_tokens") or _i(row, "input_tokens"),
                "completion_tokens": _i(row, "output_tokens"),
                "total_tokens": _i(row, "total_tokens"),
                "latency_ms": _i(row, "latency_ms") or _i(row, "response_time_ms"),
                "api_rounds": _i(row, "api_rounds"),
                "cache_hit": bool(row.get("cache_hit")),
            },
            tools={
                "execution_tokens": _i(row, "execution_tokens"),
                "api_rounds": _i(row, "api_rounds"),
                "agent_tokens": _i(row, "agent_tokens"),
                "agent_execution_time_ms": _i(row, "agent_execution_time_ms"),
            },
        )
