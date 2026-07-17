# -*- coding: utf-8 -*-
"""Phase 1 CRM feature flags — all default ON (disable via env if needed)."""
from __future__ import annotations

import os

# Target visit-coordination number (North Star KPI).
VISIT_CALL_TARGET = "09121471301"


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def crm_enabled() -> bool:
    """Master switch for Phase 1 CRM layer."""
    return _env_bool("VINOR_CRM_ENABLED", "1")


def crm_ui_enabled() -> bool:
    """Partner customers UI. Requires crm_enabled."""
    if not crm_enabled():
        return False
    return _env_bool("VINOR_CRM_UI_ENABLED", "1")


def crm_ai_tools_enabled() -> bool:
    """propose_log_call / propose_followup. Requires crm_enabled."""
    if not crm_enabled():
        return False
    return _env_bool("VINOR_CRM_AI_TOOLS_ENABLED", "1")


def crm_visit_sync_enabled() -> bool:
    """Sync Contact from Visit customer_* fields. Requires crm_enabled."""
    if not crm_enabled():
        return False
    return _env_bool("VINOR_CRM_VISIT_SYNC_ENABLED", "1")


def crm_activity_hook_enabled() -> bool:
    """Emit Foundation Activity/Timeline on CRM writes. Requires crm_enabled."""
    if not crm_enabled():
        return False
    return _env_bool("VINOR_CRM_ACTIVITY_HOOK_ENABLED", "1")
