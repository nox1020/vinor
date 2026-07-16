from __future__ import annotations

from typing import Any

from app.long_planner.interfaces import ExecutionGraphBuilder, PlanEdge, PlanGraph, PlanNode


class DefaultExecutionGraphBuilder(ExecutionGraphBuilder):
    def build_waves(self, graph: PlanGraph) -> list[list[str]]:
        # Simple topological waves by kind order
        order = ["goal", "memory", "search", "analysis", "recommendation", "negotiation", "success", "decision"]
        by_kind: dict[str, list[str]] = {}
        for n in graph.nodes:
            by_kind.setdefault(n.kind, []).append(n.node_id)
        waves: list[list[str]] = []
        for kind in order:
            ids = by_kind.get(kind) or []
            if ids:
                waves.append(ids)
        # leftovers
        used = {i for w in waves for i in w}
        rest = [n.node_id for n in graph.nodes if n.node_id not in used]
        if rest:
            waves.append(rest)
        return waves
