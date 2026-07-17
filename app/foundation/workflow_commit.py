# -*- coding: utf-8 -*-
"""
Workflow Commit Adapter — records completed Workflow Engine objects into
Activity + Timeline without changing Engine reply / Supervisor handoff.

Gated by VINOR_FOUNDATION_ENABLED + VINOR_WORKFLOW_COMMIT_ENABLED (default OFF).
"""
from __future__ import annotations

from typing import Any, Optional

from app.foundation.activity_store import append_activity
from app.foundation.config import workflow_commit_enabled
from app.foundation.interfaces import CommitResult
from app.foundation.storage_adapter import (
    execute_storage_commit,
    land_code_from_fields,
    plan_from_structured_object,
)
from app.foundation.timeline_store import link_activity_to_timeline
from app.workflow.interfaces import WF_STATE_COMPLETED, WorkflowEngineResult


def commit_structured_object(
    obj: dict[str, Any] | None,
    *,
    actor_key: str = "",
    actor_role: str = "",
    source: str = "workflow_commit",
) -> CommitResult:
    """Commit a structured Workflow object (Activity/Timeline + shadow storage plan)."""
    if not workflow_commit_enabled():
        return CommitResult(ok=True, shadowed=True, reason="commit_disabled")
    if not isinstance(obj, dict) or not obj:
        return CommitResult(ok=True, shadowed=True, reason="empty_object")

    plan = plan_from_structured_object(obj)
    storage_result = execute_storage_commit(plan)

    fields = dict(plan.fields or {})
    land_code = land_code_from_fields(fields)
    summary = (
        f"workflow_complete:{plan.object_type or plan.workflow_id or 'unknown'}"
    )
    activity = append_activity(
        action="workflow_completed",
        actor_key=actor_key or str(obj.get("role") or ""),
        actor_role=actor_role or str(obj.get("role") or ""),
        entity_type=plan.object_type or "workflow_object",
        entity_id=str(fields.get("id") or land_code or plan.workflow_id or ""),
        land_code=land_code,
        workflow_id=plan.workflow_id,
        object_type=plan.object_type,
        summary=summary,
        payload={
            "fields": fields,
            "plan": plan.to_dict(),
            "storage": {
                "shadowed": storage_result.shadowed,
                "persisted": storage_result.persisted,
                "reason": storage_result.reason,
            },
        },
        source=source,
        metadata={"status": str(obj.get("status") or "")},
    )

    timeline_ids: list[str] = []
    if activity is not None:
        entries = link_activity_to_timeline(activity)
        timeline_ids = [e.id for e in entries if e and e.id]

    return CommitResult(
        ok=True,
        committed=bool(activity),
        shadowed=True,
        persisted=False,
        activity_id=(activity.id if activity else ""),
        timeline_ids=timeline_ids,
        plan=plan,
        reason=storage_result.reason or ("recorded" if activity else "activity_skipped"),
    )


def commit_workflow_engine_result(
    result: WorkflowEngineResult | None,
) -> Optional[CommitResult]:
    """
    Hook for Conversation/Workflow completion.
    Returns None when disabled or nothing to commit; never raises.
    """
    if not workflow_commit_enabled():
        return None
    if result is None:
        return None
    try:
        ctx = result.context
        state = (ctx.state if ctx is not None else "") or ""
        obj = result.structured_object
        # Only record terminal successful completions with an object
        if state and state != WF_STATE_COMPLETED and not obj:
            return None
        if not obj:
            if state == WF_STATE_COMPLETED:
                obj = {
                    "type": (ctx.object_type if ctx else "") or "",
                    "workflow_id": (ctx.workflow_id if ctx else "") or "",
                    "role": (ctx.role if ctx else "") or "",
                    "fields": dict(ctx.collected or {}) if ctx else {},
                    "status": state,
                }
            else:
                return None
        actor_key = ""
        actor_role = ""
        if ctx is not None:
            actor_key = str(ctx.user_key or "")
            actor_role = str(ctx.role or "")
        return commit_structured_object(
            obj,
            actor_key=actor_key,
            actor_role=actor_role,
            source="workflow_engine",
        )
    except Exception:
        return CommitResult(ok=False, shadowed=True, reason="commit_error", error="exception")
