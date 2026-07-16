from __future__ import annotations

import time

from app.agents.interfaces import AgentRegistry
from app.agents.parallel.config import parallel_merge_hint_chars
from app.agents.parallel.executor import ThreadPoolParallelExecutor
from app.agents.parallel.interfaces import (
    AgentResultMerger,
    ExecutionContext,
    ExecutionPlanner,
    ExecutionResult,
    ParallelCollaborationManager,
    ParallelExecutor,
)
from app.agents.parallel.merger import CompactAgentResultMerger
from app.agents.parallel.planner import RuleExecutionPlanner


class DefaultParallelCollaborationManager(ParallelCollaborationManager):
    def __init__(
        self,
        *,
        registry: AgentRegistry,
        planner: ExecutionPlanner | None = None,
        executor: ParallelExecutor | None = None,
        merger: AgentResultMerger | None = None,
    ):
        self._registry = registry
        self._planner = planner or RuleExecutionPlanner()
        self._executor = executor or ThreadPoolParallelExecutor(registry)
        self._merger = merger or CompactAgentResultMerger()

    def run(self, ctx: ExecutionContext) -> ExecutionResult:
        t0 = time.perf_counter()
        plan = self._planner.plan(ctx)
        if not plan.waves:
            return ExecutionResult(
                ok=True,
                plan=plan,
                results={},
                merged={},
                compact_hint="",
                merge_tokens=0,
                execution_time_ms=int((time.perf_counter() - t0) * 1000),
                parallel_tasks=0,
                merged_agents=[],
                skipped_agents=list(plan.skipped),
                waves_executed=[],
                metadata={"reason": plan.reason},
            )

        results = self._executor.execute(plan, ctx)
        merged, hint, tokens = self._merger.merge(
            results=results,
            shared=ctx.shared,
            budget_chars=parallel_merge_hint_chars(),
        )
        ctx.shared["parallel_merge"] = merged
        ctx.shared["parallel_merge_hint"] = hint

        parallel_tasks = sum(1 for w in plan.waves if len(w) > 1)
        merged_agents = [
            aid for aid, r in results.items() if r and not r.skipped and r.status == "ready"
        ]
        return ExecutionResult(
            ok=True,
            plan=plan,
            results=results,
            merged=merged,
            compact_hint=hint,
            merge_tokens=tokens,
            execution_time_ms=int((time.perf_counter() - t0) * 1000),
            parallel_tasks=parallel_tasks,
            merged_agents=merged_agents,
            skipped_agents=list(plan.skipped),
            waves_executed=[list(w) for w in plan.waves],
            metadata={"reason": plan.reason, "waves": len(plan.waves), "shared": dict(ctx.shared)},
        )
