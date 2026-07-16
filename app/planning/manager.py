from __future__ import annotations

import time

from app.ai.token_analytics import estimate_tokens
from app.planning.config import (
    planning_hint_budget_chars,
    planning_inject_hint,
    planning_seed_tool_messages,
)
from app.planning.executor import ToolExecutor, build_seed_messages
from app.planning.interfaces import (
    Evaluator,
    Executor,
    Plan,
    Planner,
    PlanningManager,
    PlanningOutcome,
    PlanningRequest,
    TaskResult,
)


class DefaultPlanningManager(PlanningManager):
    def __init__(self, *, planner: Planner, executor: Executor, evaluator: Evaluator):
        self._planner = planner
        self._executor = executor
        self._evaluator = evaluator

    def run_once(self, req: PlanningRequest) -> PlanningOutcome:
        started = time.perf_counter()
        plan = self._planner.create_plan(req)
        results: list[TaskResult] = []
        for task in plan.tasks:
            task.status = "running"
            result = self._executor.execute_task(task, req=req)
            task.status = "done" if result.ok else "failed"
            task.result = dict(result.model_result or {})
            results.append(result)

        evaluation = self._evaluator.evaluate(plan, results, req=req)
        land_codes: list[str] = []
        actions: list[dict] = []
        exec_chars = 0
        for r in results:
            for c in r.land_codes:
                if c not in land_codes:
                    land_codes.append(c)
            if r.ui_action:
                actions.append(r.ui_action)
            try:
                exec_chars += len(str(r.model_result))
            except Exception:
                pass

        hint = ""
        if planning_inject_hint():
            hint = _compact_hint(plan, land_codes, evaluation.reason)
            budget = planning_hint_budget_chars()
            if len(hint) > budget:
                hint = hint[: budget - 1].rstrip() + "…"

        seed = build_seed_messages(results) if planning_seed_tool_messages() else []
        elapsed = int((time.perf_counter() - started) * 1000)
        return PlanningOutcome(
            plan=plan,
            executed=results,
            evaluation=evaluation,
            land_codes=land_codes[:5],
            agent_actions=actions,
            seed_messages=seed,
            compact_hint=hint,
            planning_time_ms=elapsed,
            tasks_count=len(plan.tasks),
            executed_tasks=sum(1 for r in results if r.tool_name and not r.model_result.get("local")),
            planning_tokens=0,
            execution_tokens=estimate_tokens("x" * min(exec_chars, 4000)),
        )


def _compact_hint(plan: Plan, land_codes: list[str], reason: str) -> str:
    # Never dump full plan/tasks into prompt — only minimal findings.
    bits = [f"نوع_برنامه={plan.plan_type}"]
    if land_codes:
        bits.append("کدها=" + ",".join(land_codes[:5]))
    if reason:
        bits.append(f"وضعیت={reason}")
    return "=== یافتهٔ برنامه‌ریز ===\n" + " | ".join(bits)
