# -*- coding: utf-8 -*-
"""Phase 0 Foundation feature flags — all default ON (disable via env if needed)."""
from __future__ import annotations

import os


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def foundation_enabled() -> bool:
    """Master switch for Phase 0 Foundation layer."""
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_FOUNDATION_ENABLED", default=True)


def activity_store_enabled() -> bool:
    """Append-only Activity store. Requires foundation_enabled."""
    if not foundation_enabled():
        return False
    return _env_bool("VINOR_ACTIVITY_STORE_ENABLED", "1")


def timeline_store_enabled() -> bool:
    """Timeline index store. Requires foundation_enabled."""
    if not foundation_enabled():
        return False
    return _env_bool("VINOR_TIMELINE_STORE_ENABLED", "1")


def workflow_commit_enabled() -> bool:
    """
    When True, completed Workflow Engine objects are recorded via Commit Adapter
    (Activity/Timeline). Does not change reply/Supervisor path.
    """
    if not foundation_enabled():
        return False
    return _env_bool("VINOR_WORKFLOW_COMMIT_ENABLED", "1")


def workflow_commit_persist_enabled() -> bool:
    """
    When True, Commit Adapter may write to existing business JSON (visit/deal/apply).
    Default ON; set VINOR_WORKFLOW_COMMIT_PERSIST=0 to keep shadow-only.
    """
    if not workflow_commit_enabled():
        return False
    return _env_bool("VINOR_WORKFLOW_COMMIT_PERSIST", "1")
