from __future__ import annotations

import os


def workflow_engine_enabled() -> bool:
    from app.ai_console.flag_settings import resolve_feature_flag

    return resolve_feature_flag("VINOR_WORKFLOW_ENGINE_ENABLED", default=True)


def handoff_supervisor_on_complete() -> bool:
    """When True, COMPLETED workflows continue to Supervisor (Agent handoff)."""
    return (os.environ.get("VINOR_WORKFLOW_HANDOFF_SUPERVISOR") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
