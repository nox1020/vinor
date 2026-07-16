from __future__ import annotations

import os

from app.executive.interfaces import ExecutiveAI, ExecutivePlan, ExecutiveRequest


def executive_enabled() -> bool:
    return (os.environ.get("VINOR_EXECUTIVE_ENABLED") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


class RuleExecutiveAI(ExecutiveAI):
    """Orchestrator only — decides layer flags, never generates text/prompts."""

    def plan(self, req: ExecutiveRequest) -> ExecutivePlan:
        text = (req.message or "").strip()
        intent = (req.intent or "").lower()
        greeting = len(text) < 12 and any(k in text for k in ("سلام", "درود", "hi", "hello"))
        if req.conversation_handled:
            return ExecutivePlan(
                run_goals=True,
                run_world_model=False,
                run_long_plan=False,
                run_supervisor=False,
                run_agents=False,
                run_decision=False,
                run_bi=False,
                run_reflection=True,
                reason="conversation_early_return",
            )
        if greeting or intent in ("greeting",):
            return ExecutivePlan(
                run_goals=True,
                run_world_model=True,
                run_long_plan=False,
                run_supervisor=True,
                run_agents=False,
                run_decision=False,
                run_bi=False,
                run_reflection=True,
                reason="greeting_light",
            )
        return ExecutivePlan(
            run_goals=True,
            run_world_model=True,
            run_long_plan=True,
            run_supervisor=True,
            run_agents=True,
            run_decision=True,
            run_bi=True,
            run_reflection=True,
            reason="full_cognitive",
        )
