# -*- coding: utf-8 -*-
"""
Vinor Integration Layer (Phase 6)

Unified Lead→Settlement journey timeline + thin workflows + AI gaps.
Does not deprecate propose_deal / mark_in_transaction / commissions.
All feature flags default ON.
"""

from app.integration.config import (
    integration_activity_hook_enabled,
    integration_ai_tools_enabled,
    integration_enabled,
    integration_journey_enabled,
    integration_ui_enabled,
    integration_workflows_enabled,
)
from app.integration.service import (
    get_journey_timeline,
    integration_status,
    journey_as_dicts,
)

__all__ = [
    "integration_enabled",
    "integration_ui_enabled",
    "integration_journey_enabled",
    "integration_workflows_enabled",
    "integration_ai_tools_enabled",
    "integration_activity_hook_enabled",
    "integration_status",
    "get_journey_timeline",
    "journey_as_dicts",
]
