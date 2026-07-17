# -*- coding: utf-8 -*-
"""Public Integration service — journey timeline + status."""
from __future__ import annotations

from typing import Any, List

from app.integration.config import (
    integration_activity_hook_enabled,
    integration_ai_tools_enabled,
    integration_enabled,
    integration_journey_enabled,
    integration_ui_enabled,
    integration_workflows_enabled,
)
from app.integration.journey import JourneyEvent, build_journey_timeline


def integration_status() -> dict[str, Any]:
    return {
        "integration_enabled": integration_enabled(),
        "integration_ui_enabled": integration_ui_enabled(),
        "integration_journey_enabled": integration_journey_enabled(),
        "integration_workflows_enabled": integration_workflows_enabled(),
        "integration_ai_tools_enabled": integration_ai_tools_enabled(),
        "integration_activity_hook_enabled": integration_activity_hook_enabled(),
        "phase": 6,
    }


def get_journey_timeline(
    *,
    partner_phone: str = "",
    land_code: str = "",
    contact_phone: str = "",
    limit: int = 200,
) -> List[JourneyEvent]:
    return build_journey_timeline(
        partner_phone=partner_phone,
        land_code=land_code,
        contact_phone=contact_phone,
        limit=limit,
    )


def journey_as_dicts(**kwargs: Any) -> List[dict[str, Any]]:
    return [e.to_dict() for e in get_journey_timeline(**kwargs)]
