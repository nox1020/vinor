# -*- coding: utf-8 -*-
"""Phase 2 Visit Result feature flags — all default ON (disable via env if needed)."""
from __future__ import annotations

import os

OUTCOMES = frozenset({"interested", "not_interested", "follow_up", "no_show"})


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def visit_result_enabled() -> bool:
    """Master switch for Phase 2 Visit Result / No-Show layer."""
    return _env_bool("VINOR_VISIT_RESULT_ENABLED", "1")


def visit_result_ui_enabled() -> bool:
    """Admin / Special inbox result actions. Requires visit_result_enabled."""
    if not visit_result_enabled():
        return False
    return _env_bool("VINOR_VISIT_RESULT_UI_ENABLED", "1")


def visit_result_ai_tools_enabled() -> bool:
    """propose_visit_result / propose_no_show. Requires master."""
    if not visit_result_enabled():
        return False
    return _env_bool("VINOR_VISIT_RESULT_AI_TOOLS_ENABLED", "1")


def visit_no_show_status_enabled() -> bool:
    """Allow writing status=no_show. Requires master."""
    if not visit_result_enabled():
        return False
    return _env_bool("VINOR_VISIT_NO_SHOW_STATUS_ENABLED", "1")


def visit_result_activity_hook_enabled() -> bool:
    """Emit Foundation Activity/Timeline on result writes. Requires master."""
    if not visit_result_enabled():
        return False
    return _env_bool("VINOR_VISIT_RESULT_ACTIVITY_HOOK_ENABLED", "1")
