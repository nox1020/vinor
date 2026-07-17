# -*- coding: utf-8 -*-
"""Visit Result activity hook — emit Foundation Activity/Timeline (fail-open)."""
from __future__ import annotations

from typing import Any, Optional

from app.visit_result.config import visit_result_activity_hook_enabled, visit_result_enabled


def record_visit_result_event(
    *,
    action: str,
    actor_key: str = "",
    actor_role: str = "partner",
    entity_type: str = "visit_result",
    entity_id: str = "",
    land_code: str = "",
    summary: str = "",
    payload: dict[str, Any] | None = None,
    subjects: list[tuple[str, str]] | None = None,
) -> Optional[Any]:
    if not visit_result_enabled() or not visit_result_activity_hook_enabled():
        return None
    try:
        from app.foundation.activity_store import append_activity
        from app.foundation.timeline_store import link_activity_to_timeline

        activity = append_activity(
            action=(action or "").strip() or "visit_result_event",
            actor_key=(actor_key or "").strip(),
            actor_role=(actor_role or "").strip() or "partner",
            entity_type=(entity_type or "").strip(),
            entity_id=(entity_id or "").strip(),
            land_code=str(land_code or "").strip(),
            object_type=(entity_type or "").strip() or "visit_result",
            summary=(summary or "").strip(),
            payload=dict(payload or {}),
            source="visit_result",
        )
        if activity is None:
            return None
        pairs = list(subjects or [])
        if entity_type and entity_id:
            pairs.append((entity_type, entity_id))
        if actor_key:
            pairs.append(("partner", actor_key))
        if land_code:
            pairs.append(("land", str(land_code).strip()))
        link_activity_to_timeline(activity, subjects=pairs or None)
        return activity
    except Exception:
        return None
