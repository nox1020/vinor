from __future__ import annotations

import time
from typing import Any

from app.long_planner.graph_builder import DefaultExecutionGraphBuilder
from app.long_planner.interfaces import (
    ExecutionGraphBuilder,
    HorizonPlanner,
    PlanEdge,
    PlanGraph,
    PlanNode,
)


class RuleHorizonPlanner(HorizonPlanner):
    """Build multi-step plan graph — does not execute tasks/tools."""

    def __init__(self, *, builder: ExecutionGraphBuilder | None = None):
        self._builder = builder or DefaultExecutionGraphBuilder()

    def plan(self, *, goals: dict[str, Any], world: dict[str, Any], route: str = "") -> PlanGraph:
        t0 = time.perf_counter()
        goals_list = list((goals or {}).get("goals") or [])
        primary = str((goals or {}).get("primary_goal_id") or "")
        gtypes = [str(g.get("goal_type") or "") for g in goals_list if isinstance(g, dict)]
        nodes: list[PlanNode] = []
        edges: list[PlanEdge] = []

        def add(nid: str, kind: str, label: str) -> None:
            nodes.append(PlanNode(node_id=nid, kind=kind, label=label))

        add("goal_primary", "goal", primary or "primary_goal")
        add("mem", "memory", "customer_memory")
        if any(t in ("search", "buy", "visit", "general") for t in gtypes) or "search" in (route or ""):
            add("search", "search", "property_search")
            edges.append(PlanEdge("goal_primary", "search"))
            edges.append(PlanEdge("mem", "search", "parallel"))
        if any(t in ("search", "buy", "negotiate") for t in gtypes) or route:
            add("analysis", "analysis", "property_analysis")
            edges.append(PlanEdge("search", "analysis") if any(n.node_id == "search" for n in nodes) else PlanEdge("goal_primary", "analysis"))
            add("rec", "recommendation", "recommendation")
            edges.append(PlanEdge("analysis", "rec"))
        if "negotiate" in gtypes or "buy" in gtypes:
            add("neg", "negotiation", "negotiation")
            edges.append(PlanEdge("rec", "neg") if any(n.node_id == "rec" for n in nodes) else PlanEdge("goal_primary", "neg"))
        if "buy" in gtypes or "visit" in gtypes:
            add("cs", "success", "customer_success")
            prev = "neg" if any(n.node_id == "neg" for n in nodes) else ("rec" if any(n.node_id == "rec" for n in nodes) else "goal_primary")
            edges.append(PlanEdge(prev, "cs"))
        add("decide", "decision", "decision_engine")
        last = nodes[-2].node_id if len(nodes) > 1 else "goal_primary"
        if last != "decide":
            edges.append(PlanEdge(last, "decide"))
        edges.append(PlanEdge("goal_primary", "mem", "parallel"))

        graph = PlanGraph(nodes=nodes, edges=edges, primary_goal=primary)
        graph.waves = self._builder.build_waves(graph)
        graph.build_time_ms = int((time.perf_counter() - t0) * 1000)
        # silence unused world for now but keep signature for future reasoners
        _ = world
        return graph
