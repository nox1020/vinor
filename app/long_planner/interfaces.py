from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class PlanNode:
    node_id: str
    kind: str  # goal | agent | decision | workflow | tool_gate
    label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "label": self.label,
            "metadata": dict(self.metadata),
        }


@dataclass
class PlanEdge:
    source: str
    target: str
    relation: str = "next"

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "target": self.target, "relation": self.relation}


@dataclass
class PlanGraph:
    nodes: list[PlanNode] = field(default_factory=list)
    edges: list[PlanEdge] = field(default_factory=list)
    waves: list[list[str]] = field(default_factory=list)
    primary_goal: str = ""
    build_time_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "waves": [list(w) for w in self.waves],
            "primary_goal": self.primary_goal,
            "build_time_ms": self.build_time_ms,
        }


class HorizonPlanner(Protocol):
    def plan(self, *, goals: dict[str, Any], world: dict[str, Any], route: str = "") -> PlanGraph:
        ...


class ExecutionGraphBuilder(Protocol):
    def build_waves(self, graph: PlanGraph) -> list[list[str]]:
        ...


class LongPlannerManager(Protocol):
    def build(self, *, shared: dict[str, Any] | None = None, route: str = "") -> PlanGraph:
        ...
