from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.agents.interfaces import Agent, AgentContext, AgentRegistry, AgentResult
from app.agents.parallel.config import parallel_max_workers
from app.agents.parallel.interfaces import ExecutionContext, ExecutionPlan, ParallelExecutor


class ThreadPoolParallelExecutor(ParallelExecutor):
    """Runs independent wave agents concurrently; merges shared after each wave."""

    def __init__(self, registry: AgentRegistry, *, max_workers: int | None = None):
        self._registry = registry
        self._max_workers = int(max_workers or parallel_max_workers())

    def execute(self, plan: ExecutionPlan, ctx: ExecutionContext) -> dict[str, AgentResult]:
        results: dict[str, AgentResult] = {}
        shared = ctx.shared if isinstance(ctx.shared, dict) else {}
        lock = threading.Lock()

        for wave in plan.waves or []:
            if not wave:
                continue
            if len(wave) == 1 or not ctx.parallel:
                for aid in wave:
                    res = self._run_one(aid, ctx, shared, lock)
                    if res is not None:
                        results[aid] = res
                continue

            # Parallel wave — each agent gets a snapshot; merge writes after.
            snapshots: dict[str, dict[str, Any]] = {}
            with lock:
                base = dict(shared)

            def _job(agent_id: str) -> tuple[str, AgentResult | None, dict[str, Any]]:
                local_shared = dict(base)
                local_ctx = AgentContext(
                    message=ctx.message,
                    route=ctx.route,
                    audience=ctx.audience,
                    voice=ctx.voice,
                    chip_intent=ctx.chip_intent,
                    user_key=ctx.user_key,
                    thread_id=ctx.thread_id,
                    context_budget_chars=ctx.context_budget_chars,
                    shared=local_shared,
                )
                agent = self._registry.get(agent_id)
                if agent is None or not agent.active:
                    return agent_id, AgentResult(
                        agent_id=agent_id,
                        status="skipped",
                        ok=True,
                        skipped=True,
                        error="inactive_or_missing",
                    ), local_shared
                try:
                    out = agent.run(local_ctx)
                    return agent_id, out, dict(local_ctx.shared or {})
                except Exception as exc:
                    return agent_id, AgentResult(
                        agent_id=agent_id,
                        status="error",
                        ok=False,
                        skipped=True,
                        error=str(exc)[:120],
                    ), local_shared

            with ThreadPoolExecutor(max_workers=min(self._max_workers, len(wave))) as pool:
                futs = [pool.submit(_job, aid) for aid in wave]
                for fut in as_completed(futs):
                    aid, res, local = fut.result()
                    if res is not None:
                        results[aid] = res
                    snapshots[aid] = local

            with lock:
                for aid in wave:
                    shared.update(snapshots.get(aid) or {})
                ctx.shared.update(shared)

        return results

    def _run_one(
        self,
        agent_id: str,
        ctx: ExecutionContext,
        shared: dict[str, Any],
        lock: threading.Lock,
    ) -> AgentResult | None:
        agent = self._registry.get(agent_id)
        if agent is None:
            return AgentResult(
                agent_id=agent_id,
                status="error",
                ok=False,
                skipped=True,
                error="agent_not_registered",
            )
        with lock:
            local_ctx = AgentContext(
                message=ctx.message,
                route=ctx.route,
                audience=ctx.audience,
                voice=ctx.voice,
                chip_intent=ctx.chip_intent,
                user_key=ctx.user_key,
                thread_id=ctx.thread_id,
                context_budget_chars=ctx.context_budget_chars,
                shared=shared,
            )
        if not agent.active:
            return agent.run(local_ctx)
        try:
            out = agent.run(local_ctx)
            with lock:
                shared.update(local_ctx.shared or {})
                ctx.shared.update(shared)
            return out
        except Exception as exc:
            return AgentResult(
                agent_id=agent_id,
                status="error",
                ok=False,
                skipped=True,
                error=str(exc)[:120],
            )
