from __future__ import annotations

from typing import Any

from app.evaluation.interfaces import LayerMetrics, PerformanceCollector


def _i(d: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(d.get(key) if d.get(key) is not None else default)
    except Exception:
        return default


class RowPerformanceCollector(PerformanceCollector):
    """Timing metrics from existing row/layers only."""

    def collect_timings(
        self, analytics_row: dict[str, Any], layers: LayerMetrics
    ) -> dict[str, int]:
        row = analytics_row or {}
        latency = _i(row, "latency_ms") or _i(row, "response_time_ms")
        planning = _i(layers.planning, "planning_time_ms") or _i(row, "planning_time_ms")
        decision = _i(layers.decision, "decision_time_ms") or _i(row, "decision_time_ms")
        parallel = _i(layers.parallel, "parallel_execution_time_ms")
        agent = _i(layers.tools, "agent_execution_time_ms")
        routing = _i(layers.supervisor, "routing_time_ms")
        # Approximate residual LLM time when not separately measured
        accounted = planning + decision + parallel + agent + routing
        llm_time = max(0, latency - accounted) if latency else 0
        return {
            "latency_ms": latency,
            "rag_time_ms": _i(row, "rag_time_ms"),  # may be 0 if not instrumented
            "memory_time_ms": _i(row, "memory_time_ms")
            or _i(row, "profile_build_time_ms"),
            "planning_time_ms": planning,
            "decision_time_ms": decision,
            "llm_time_ms": llm_time,
            "tool_time_ms": agent,
            "parallel_time_ms": parallel,
            "routing_time_ms": routing,
        }
