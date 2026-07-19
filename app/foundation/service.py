# -*- coding: utf-8 -*-
"""Public Foundation service — fail-open hooks for existing Vinor paths."""
from __future__ import annotations

from typing import Any, Optional

from app.foundation.config import foundation_enabled, workflow_commit_enabled
from app.foundation.interfaces import CommitResult
from app.foundation.workflow_commit import commit_workflow_engine_result
from app.workflow.interfaces import WorkflowEngineResult


def maybe_record_workflow_commit(
    result: WorkflowEngineResult | None,
) -> Optional[CommitResult]:
    """
    Safe hook after Workflow Engine persist.
    Flags default ON; writes Activity/Timeline only (storage persist remains shadow).
    Failures never propagate.
    """
    if not foundation_enabled() or not workflow_commit_enabled():
        return None
    try:
        return commit_workflow_engine_result(result)
    except Exception:
        return None


def foundation_status() -> dict[str, Any]:
    """Observability helper for admin/debug — no side effects."""
    from app.foundation import config as cfg

    return {
        "foundation_enabled": cfg.foundation_enabled(),
        "activity_store_enabled": cfg.activity_store_enabled(),
        "timeline_store_enabled": cfg.timeline_store_enabled(),
        "workflow_commit_enabled": cfg.workflow_commit_enabled(),
        "workflow_commit_persist_enabled": cfg.workflow_commit_persist_enabled(),
        "phase": 0,
    }
