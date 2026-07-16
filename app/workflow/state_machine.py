from __future__ import annotations

from app.workflow.interfaces import (
    WF_STATE_CANCELLED,
    WF_STATE_COLLECTING,
    WF_STATE_COMPLETED,
    WF_STATE_FAILED,
    WF_STATE_INIT,
    WF_STATE_READY,
    WF_STATE_VALIDATING,
    WF_STATE_WAITING_USER,
    WorkflowContext,
)

_ALLOWED: dict[str, set[str]] = {
    WF_STATE_INIT: {
        WF_STATE_COLLECTING,
        WF_STATE_WAITING_USER,
        WF_STATE_READY,
        WF_STATE_COMPLETED,
        WF_STATE_FAILED,
        WF_STATE_CANCELLED,
    },
    WF_STATE_COLLECTING: {
        WF_STATE_VALIDATING,
        WF_STATE_WAITING_USER,
        WF_STATE_COLLECTING,
        WF_STATE_READY,
        WF_STATE_COMPLETED,
        WF_STATE_FAILED,
        WF_STATE_CANCELLED,
    },
    WF_STATE_VALIDATING: {
        WF_STATE_COLLECTING,
        WF_STATE_WAITING_USER,
        WF_STATE_READY,
        WF_STATE_FAILED,
        WF_STATE_CANCELLED,
    },
    WF_STATE_WAITING_USER: {
        WF_STATE_COLLECTING,
        WF_STATE_VALIDATING,
        WF_STATE_READY,
        WF_STATE_FAILED,
        WF_STATE_CANCELLED,
    },
    WF_STATE_READY: {
        WF_STATE_COMPLETED,
        WF_STATE_FAILED,
        WF_STATE_CANCELLED,
    },
    WF_STATE_COMPLETED: {WF_STATE_COMPLETED},
    WF_STATE_FAILED: {WF_STATE_FAILED, WF_STATE_INIT},
    WF_STATE_CANCELLED: {WF_STATE_CANCELLED, WF_STATE_INIT},
}


def transition(ctx: WorkflowContext, new_state: str) -> WorkflowContext:
    new_state = (new_state or "").strip().upper() or WF_STATE_FAILED
    allowed = _ALLOWED.get(ctx.state, set())
    if new_state not in allowed:
        old = ctx.state
        ctx.metadata["illegal_transition"] = True
        ctx.metadata["from_state"] = old
        ctx.metadata["to_state"] = new_state
        ctx.state = WF_STATE_FAILED
        return ctx
    ctx.state = new_state
    return ctx
