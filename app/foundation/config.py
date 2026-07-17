# -*- coding: utf-8 -*-
"""Phase 0 Foundation feature flags — all default OFF (100% backward compatible)."""
from __future__ import annotations

import os


def _env_bool(name: str, default: str = "0") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def foundation_enabled() -> bool:
    """Master switch for Phase 0 Foundation layer."""
    return _env_bool("VINOR_FOUNDATION_ENABLED", "0")


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
    return _env_bool("VINOR_WORKFLOW_COMMIT_ENABLED", "0")


def workflow_commit_persist_enabled() -> bool:
    """
    When True, Commit Adapter may write to existing business JSON (visit/deal/apply).
    Phase 0 keeps this OFF by default — persist path is shadow-only until later phases.
    """
    if not workflow_commit_enabled():
        return False
    return _env_bool("VINOR_WORKFLOW_COMMIT_PERSIST", "0")
