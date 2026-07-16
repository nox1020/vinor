from __future__ import annotations

from app.agents.interfaces import (
    AGENT_CUSTOMER_MEMORY,
    AGENT_FOLLOW_UP,
    AGENT_NEGOTIATION,
    AGENT_PROPERTY_ANALYSIS,
    AGENT_PROPERTY_SEARCH,
    AGENT_RECOMMENDATION,
)
from app.agents.parallel.interfaces import DependencyGraph, DependencyGraphBuilder, GraphNode

# Fixed collaboration DAG (Phase 16) — no new agents.
# Search → Analysis → Recommendation → Negotiation → Customer Success
# Customer Memory is independent (can run parallel with Search/Analysis).

_FULL_NODES: list[GraphNode] = [
    GraphNode(AGENT_PROPERTY_SEARCH, depends_on=()),
    GraphNode(AGENT_CUSTOMER_MEMORY, depends_on=()),
    GraphNode(AGENT_PROPERTY_ANALYSIS, depends_on=(AGENT_PROPERTY_SEARCH,)),
    GraphNode(AGENT_RECOMMENDATION, depends_on=(AGENT_PROPERTY_ANALYSIS,)),
    GraphNode(AGENT_NEGOTIATION, depends_on=(AGENT_RECOMMENDATION,)),
    GraphNode(AGENT_FOLLOW_UP, depends_on=(AGENT_NEGOTIATION,)),
]


class StaticDependencyGraphBuilder(DependencyGraphBuilder):
    def build(self) -> DependencyGraph:
        edges: list[tuple[str, str]] = []
        for node in _FULL_NODES:
            for dep in node.depends_on:
                edges.append((dep, node.agent_id))
        return DependencyGraph(nodes=list(_FULL_NODES), edges=edges)


def waves_for_subset(selected: set[str], full: DependencyGraph | None = None) -> list[list[str]]:
    """Kahn-style leveling restricted to selected agents."""
    full = full or StaticDependencyGraphBuilder().build()
    deps: dict[str, set[str]] = {n.agent_id: set() for n in full.nodes if n.agent_id in selected}
    for n in full.nodes:
        if n.agent_id not in selected:
            continue
        for d in n.depends_on:
            if d in selected:
                deps[n.agent_id].add(d)

    remaining = set(deps.keys())
    waves: list[list[str]] = []
    while remaining:
        ready = sorted(aid for aid in remaining if not deps[aid])
        if not ready:
            # cycle / missing dep — run remaining sequentially
            waves.append(sorted(remaining))
            break
        waves.append(ready)
        remaining -= set(ready)
        for aid in remaining:
            deps[aid] -= set(ready)
    return waves
