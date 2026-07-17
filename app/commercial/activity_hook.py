# -*- coding: utf-8 -*-
"""Commercial activity hook — emit Foundation Activity/Timeline (fail-open)."""
from __future__ import annotations

from typing import Any, Optional

from app.commercial.config import commercial_activity_hook_enabled, commercial_enabled


def record_commercial_event(
    *,
    action: str,
    actor_key: str = "",
    actor_role: str = "partner",
    entity_type: str = "",
    entity_id: str = "",
    land_code: str = "",
    summary: str = "",
    payload: dict[str, Any] | None = None,
    subjects: list[tuple[str, str]] | None = None,
) -> Optional[Any]:
    if not commercial_enabled() or not commercial_activity_hook_enabled():
        return None
    try:
        from app.foundation.activity_store import append_activity
        from app.foundation.timeline_store import link_activity_to_timeline

        activity = append_activity(
            action=(action or "").strip() or "commercial_event",
            actor_key=(actor_key or "").strip(),
            actor_role=(actor_role or "").strip() or "partner",
            entity_type=(entity_type or "").strip(),
            entity_id=(entity_id or "").strip(),
            land_code=str(land_code or "").strip(),
            object_type=(entity_type or "").strip() or "commercial",
            summary=(summary or "").strip(),
            payload=dict(payload or {}),
            source="commercial",
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
