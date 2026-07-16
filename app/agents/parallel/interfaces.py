from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.agents.interfaces import AgentContext, AgentResult


@dataclass
class ExecutionContext:
    """Shared execution envelope — reuses AgentContext.shared (no new prompt context)."""

    message: str = ""
    route: str = ""
    audience: str = ""
    voice: str = ""
    chip_intent: str = ""
    user_key: str = ""
    thread_id: str | None = None
    context_budget_chars: int = 3000
    shared: dict[str, Any] = field(default_factory=dict)
    parallel: bool = True


@dataclass
class GraphNode:
    agent_id: str
    depends_on: tuple[str, ...] = ()


@dataclass
class DependencyGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)  # (from, to)

    def agent_ids(self) -> list[str]:
        return [n.agent_id for n in self.nodes]


@dataclass
class ExecutionPlan:
    graph: DependencyGraph
    waves: list[list[str]] = field(default_factory=list)  # parallelizable levels
    skipped: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class ExecutionResult:
    ok: bool = True
    plan: ExecutionPlan | None = None
    results: dict[str, AgentResult] = field(default_factory=dict)
    merged: dict[str, Any] = field(default_factory=dict)
    compact_hint: str = ""
    merge_tokens: int = 0
    execution_time_ms: int = 0
    parallel_tasks: int = 0
    merged_agents: list[str] = field(default_factory=list)
    skipped_agents: list[str] = field(default_factory=list)
    waves_executed: list[list[str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class DependencyGraphBuilder(Protocol):
    def build(self) -> DependencyGraph:
        ...


class ExecutionPlanner(Protocol):
    def plan(self, ctx: ExecutionContext) -> ExecutionPlan:
        ...


class ParallelExecutor(Protocol):
    def execute(self, plan: ExecutionPlan, ctx: ExecutionContext) -> dict[str, AgentResult]:
        ...


class AgentResultMerger(Protocol):
    def merge(
        self,
        *,
        results: dict[str, AgentResult],
        shared: dict[str, Any],
        budget_chars: int = 80,
    ) -> tuple[dict[str, Any], str, int]:
        """Returns (merged_object, compact_hint, tokens)."""
        ...


class ParallelCollaborationManager(Protocol):
    def run(self, ctx: ExecutionContext) -> ExecutionResult:
        ...
