# -*- coding: utf-8 -*-
"""
Vinor Foundation Layer (Phase 0)

Additive infrastructure for Activity / Timeline / Workflow Commit Adapter.
All feature flags default ON — disable via env if needed. Existing Partner/Visit/Deal/AI paths unchanged when flags are off.
"""

from app.foundation.config import (
    activity_store_enabled,
    foundation_enabled,
    timeline_store_enabled,
    workflow_commit_enabled,
    workflow_commit_persist_enabled,
)
from app.foundation.service import foundation_status, maybe_record_workflow_commit

__all__ = [
    "foundation_enabled",
    "activity_store_enabled",
    "timeline_store_enabled",
    "workflow_commit_enabled",
    "workflow_commit_persist_enabled",
    "maybe_record_workflow_commit",
    "foundation_status",
]
