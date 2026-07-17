# -*- coding: utf-8 -*-
"""
Vinor Visit Result Layer (Phase 2)

Additive VisitResult entity + no_show status bridge.
All feature flags default ON — disable via env if needed. Existing Visit→Deal→Commission path unchanged when flags are off.
"""

from app.visit_result.config import (
    OUTCOMES,
    visit_no_show_status_enabled,
    visit_result_activity_hook_enabled,
    visit_result_ai_tools_enabled,
    visit_result_enabled,
    visit_result_ui_enabled,
)
from app.visit_result.service import (
    get_result,
    list_partner_results,
    register_no_show,
    register_result,
    valid_outcome,
    visit_result_status,
)
from app.visit_result.status_bridge import is_no_show_writable, no_show_status_value

__all__ = [
    "OUTCOMES",
    "visit_result_enabled",
    "visit_result_ui_enabled",
    "visit_result_ai_tools_enabled",
    "visit_no_show_status_enabled",
    "visit_result_activity_hook_enabled",
    "visit_result_status",
    "register_result",
    "register_no_show",
    "get_result",
    "list_partner_results",
    "valid_outcome",
    "is_no_show_writable",
    "no_show_status_value",
]
