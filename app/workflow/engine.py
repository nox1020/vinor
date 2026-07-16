from __future__ import annotations

import time
from typing import Any

from app.conversation.config import conversation_early_return
from app.workflow.config import handoff_supervisor_on_complete
from app.workflow.interfaces import (
    ACTIVE_STATES,
    WF_GENERAL,
    WF_NONE,
    WF_STATE_CANCELLED,
    WF_STATE_COLLECTING,
    WF_STATE_COMPLETED,
    WF_STATE_FAILED,
    WF_STATE_INIT,
    WF_STATE_READY,
    WF_STATE_VALIDATING,
    WF_STATE_WAITING_USER,
    WorkflowContext,
    WorkflowEngine,
    WorkflowEngineResult,
)
from app.workflow.registry import WorkflowRegistry
from app.workflow.state_machine import transition
from app.workflow.validation import validate_step


def _missing(spec, collected: dict) -> list[str]:
    out = []
    for step in spec.steps:
        if not step.required:
            continue
        val = collected.get(step.field)
        if val is None or str(val).strip() == "":
            out.append(step.field)
    return out


def _next_step(spec, collected: dict) -> str:
    miss = _missing(spec, collected)
    return miss[0] if miss else ""


def _question(spec, step_id: str) -> str:
    for s in spec.steps:
        if s.id == step_id or s.field == step_id:
            return s.question
    return "لطفاً ادامه دهید."


def _step_validator(spec, step_id: str) -> str:
    for s in spec.steps:
        if s.id == step_id or s.field == step_id:
            return s.validator or "non_empty"
    return "non_empty"


class DefaultWorkflowEngine(WorkflowEngine):
    """Rule-based Workflow Engine — State/Steps/Validation outside Prompt."""

    def __init__(self, registry: WorkflowRegistry | None = None):
        self._registry = registry or WorkflowRegistry()

    def resolve_id(self, intent: str) -> str:
        return self._registry.resolve_id(intent)

    def get_spec(self, workflow_id: str):
        return self._registry.get_spec(workflow_id)

    def start(
        self,
        *,
        workflow_id: str,
        user_key: str,
        role: str,
        intent: str,
        message: str = "",
    ) -> WorkflowEngineResult:
        t0 = time.time()
        if not workflow_id or workflow_id == WF_NONE:
            return WorkflowEngineResult(
                handled=False,
                pass_to_supervisor=True,
                next_action="pass_supervisor",
                extra_tokens=0,
                observability=self._obs_empty(intent, role, t0),
            )

        wf = self._registry.get(workflow_id)
        if wf is None:
            return WorkflowEngineResult(handled=False, pass_to_supervisor=True, next_action="pass_supervisor")

        spec = wf.spec
        if spec.pass_through or workflow_id == WF_GENERAL:
            return WorkflowEngineResult(
                handled=False,
                pass_to_supervisor=True,
                next_action="pass_supervisor",
                extra_tokens=0,
                observability={
                    "workflow_name": spec.name,
                    "workflow_state": WF_STATE_INIT,
                    "current_step": "",
                    "completed_steps": [],
                    "missing_steps": [],
                    "validation_errors": [],
                    "conversation_extra_tokens": 0,
                    "workflow_extra_tokens": 0,
                },
            )

        now = time.time()
        ctx = WorkflowContext(
            workflow_id=spec.id,
            workflow_name=spec.name,
            state=WF_STATE_INIT,
            role=role,
            intent=intent or spec.intent,
            object_type=spec.object_type,
            user_key=user_key,
            started_at=now,
            updated_at=now,
        )
        transition(ctx, WF_STATE_COLLECTING)
        step = _next_step(spec, ctx.collected)
        ctx.current_step = step
        ctx.missing = _missing(spec, ctx.collected)
        transition(ctx, WF_STATE_WAITING_USER)
        obs = self._obs(ctx, t0)
        return WorkflowEngineResult(
            handled=True,
            ok=True,
            reply=_question(spec, step),
            context=ctx,
            pass_to_supervisor=not conversation_early_return(),
            next_action="ask_user",
            extra_tokens=0,
            observability=obs,
        )

    def continue_(self, *, ctx: WorkflowContext, message: str) -> WorkflowEngineResult:
        t0 = time.time()
        msg = (message or "").strip()
        wf = self._registry.get(ctx.workflow_id)
        if wf is None:
            return WorkflowEngineResult(handled=False, pass_to_supervisor=True, next_action="pass_supervisor")

        spec = wf.spec
        step_id = ctx.current_step or _next_step(spec, ctx.collected)
        if not step_id:
            return self._finish(wf, ctx, t0)

        transition(ctx, WF_STATE_VALIDATING)
        vkey = _step_validator(spec, step_id)
        result = validate_step(vkey, msg)
        if not result.ok:
            ctx.validation_ok = False
            ctx.validation_errors = [result.error]
            transition(ctx, WF_STATE_WAITING_USER)
            obs = self._obs(ctx, t0)
            return WorkflowEngineResult(
                handled=True,
                ok=False,
                reply=result.error + "\n" + _question(spec, step_id),
                context=ctx,
                pass_to_supervisor=False,
                next_action="ask_user",
                extra_tokens=0,
                observability=obs,
            )

        normalized = result.normalized if result.normalized is not None else msg
        if step_id == "confirm" and normalized == "no":
            transition(ctx, WF_STATE_CANCELLED)
            obs = self._obs(ctx, t0)
            return WorkflowEngineResult(
                handled=True,
                ok=True,
                reply="ثبت انجام نشد.",
                context=ctx,
                pass_to_supervisor=False,
                next_action="cancel",
                extra_tokens=0,
                observability=obs,
            )

        ctx.collected[step_id] = normalized
        if step_id not in ctx.completed_steps:
            ctx.completed_steps.append(step_id)
        ctx.validation_ok = True
        ctx.validation_errors = []
        ctx.missing = _missing(spec, ctx.collected)
        nxt = _next_step(spec, ctx.collected)
        if not nxt:
            return self._finish(wf, ctx, t0)

        ctx.current_step = nxt
        transition(ctx, WF_STATE_COLLECTING)
        transition(ctx, WF_STATE_WAITING_USER)
        obs = self._obs(ctx, t0)
        return WorkflowEngineResult(
            handled=True,
            ok=True,
            reply=_question(spec, nxt),
            context=ctx,
            pass_to_supervisor=not conversation_early_return(),
            next_action="ask_user",
            extra_tokens=0,
            observability=obs,
        )

    def cancel(self, *, ctx: WorkflowContext) -> WorkflowEngineResult:
        t0 = time.time()
        if ctx.state in ACTIVE_STATES or ctx.state == WF_STATE_INIT:
            transition(ctx, WF_STATE_CANCELLED)
        else:
            ctx.state = WF_STATE_CANCELLED
        obs = self._obs(ctx, t0)
        return WorkflowEngineResult(
            handled=True,
            ok=True,
            reply="فرآیند لغو شد. هر وقت آماده بودید از نو شروع کنید.",
            context=ctx,
            pass_to_supervisor=False,
            next_action="cancel",
            extra_tokens=0,
            observability=obs,
        )

    def _finish(self, wf, ctx: WorkflowContext, t0: float) -> WorkflowEngineResult:
        transition(ctx, WF_STATE_READY)
        transition(ctx, WF_STATE_COMPLETED)
        obj = wf.build_object(ctx)
        bits = [f"{k}: {v}" for k, v in (ctx.collected or {}).items() if k != "confirm"]
        summary = "\n".join(bits[:10])
        reply = f"«{ctx.object_type or ctx.workflow_name}» کامل شد."
        if summary:
            reply += "\n" + summary
        reply += "\nاگر مورد دیگری هست بگویید."
        handoff = handoff_supervisor_on_complete()
        obs = self._obs(ctx, t0)
        obs["completed"] = True
        obs["completion_time_ms"] = obs.get("session_duration_ms") or 0
        obs["next_action"] = "pass_supervisor" if handoff else "complete"
        return WorkflowEngineResult(
            handled=True,
            ok=True,
            reply=reply,
            context=ctx,
            structured_object=obj,
            pass_to_supervisor=handoff,
            next_action="pass_supervisor" if handoff else "complete",
            extra_tokens=0,
            observability=obs,
        )

    def _obs(self, ctx: WorkflowContext, t0: float) -> dict[str, Any]:
        started = float(ctx.started_at or t0)
        return {
            "workflow_name": ctx.workflow_name or ctx.workflow_id,
            "workflow": ctx.workflow_id,
            "workflow_state": ctx.state,
            "conversation_state": ctx.state,
            "current_step": ctx.current_step,
            "completed_steps": list(ctx.completed_steps),
            "completed_fields": list(ctx.collected.keys()),
            "missing_steps": list(ctx.missing),
            "missing_fields": list(ctx.missing),
            "validation_errors": list(ctx.validation_errors),
            "validation_ok": ctx.validation_ok,
            "detected_role": ctx.role,
            "detected_intent": ctx.intent,
            "session_duration_ms": int((time.time() - started) * 1000),
            "completion_time_ms": int((time.time() - started) * 1000),
            "conversation_extra_tokens": 0,
            "workflow_extra_tokens": 0,
            "object_type": ctx.object_type,
        }

    def _obs_empty(self, intent: str, role: str, t0: float) -> dict[str, Any]:
        return {
            "workflow_name": "",
            "workflow": WF_NONE,
            "workflow_state": "",
            "conversation_state": "",
            "current_step": "",
            "completed_steps": [],
            "completed_fields": [],
            "missing_steps": [],
            "missing_fields": [],
            "validation_errors": [],
            "detected_role": role,
            "detected_intent": intent,
            "session_duration_ms": int((time.time() - t0) * 1000),
            "conversation_extra_tokens": 0,
            "workflow_extra_tokens": 0,
        }
