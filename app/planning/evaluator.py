from __future__ import annotations

from app.planning.interfaces import (
    PLAN_FOLLOW_UP,
    PLAN_INFORMATION,
    PLAN_PROPERTY_COMPARE,
    PLAN_PROPERTY_RECOMMENDATION,
    PLAN_PROPERTY_SEARCH,
    EvaluationResult,
    Evaluator,
    Plan,
    PlanningRequest,
    TaskResult,
)


class GoalEvaluator(Evaluator):
    def evaluate(
        self,
        plan: Plan,
        results: list[TaskResult],
        *,
        req: PlanningRequest,
    ) -> EvaluationResult:
        executed_tools = [r for r in results if r.tool_name and not r.model_result.get("local")]
        failed = [r for r in executed_tools if not r.ok]
        codes: list[str] = []
        for r in results:
            codes.extend(r.land_codes)
        codes = list(dict.fromkeys(codes))

        if plan.plan_type in (
            PLAN_PROPERTY_SEARCH,
            PLAN_PROPERTY_COMPARE,
            PLAN_PROPERTY_RECOMMENDATION,
        ):
            if codes:
                return EvaluationResult(True, True, False, "property_codes_ready")
            if failed:
                return EvaluationResult(False, False, True, "search_failed")
            return EvaluationResult(False, False, True, "no_codes")

        if plan.plan_type == PLAN_INFORMATION:
            ok_info = any(r.ok and r.tool_name for r in executed_tools)
            return EvaluationResult(ok_info, ok_info, not ok_info, "info" if ok_info else "info_missing")

        if plan.plan_type == PLAN_FOLLOW_UP:
            ok_next = any(r.ok and r.tool_name for r in executed_tools)
            return EvaluationResult(ok_next, ok_next, not ok_next, "follow_up" if ok_next else "follow_up_missing")

        return EvaluationResult(bool(executed_tools), bool(executed_tools), False, "generic")
