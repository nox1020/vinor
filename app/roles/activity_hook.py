# -*- coding: utf-8 -*-
"""Roles activity hook — emit Foundation Activity/Timeline (fail-open)."""
from __future__ import annotations

from typing import Any, Optional

from app.roles.config import roles_activity_hook_enabled, roles_enabled


def record_roles_event(
    *,
    action: str,
    actor_key: str = "",
    actor_role: str = "admin",
    entity_type: str = "",
    entity_id: str = "",
    summary: str = "",
    payload: dict[str, Any] | None = None,
    subjects: list[tuple[str, str]] | None = None,
) -> Optional[Any]:
    """
    Append Activity + Timeline when Roles activity hook and Foundation are on.
    Mirror of CRM/integration hooks — no-op / fail-open otherwise.
    """
    if not roles_enabled() or not roles_activity_hook_enabled():
        return None
    try:
        from app.foundation.activity_store import append_activity
        from app.foundation.timeline_store import link_activity_to_timeline

        activity = append_activity(
            action=(action or "").strip() or "roles_event",
            actor_key=(actor_key or "").strip(),
            actor_role=(actor_role or "").strip() or "admin",
            entity_type=(entity_type or "").strip(),
            entity_id=(entity_id or "").strip(),
            object_type=(entity_type or "").strip() or "roles",
            summary=(summary or "").strip(),
            payload=dict(payload or {}),
            source="roles",
        )
        if activity is None:
            return None
        pairs = list(subjects or [])
        if entity_type and entity_id:
            pairs.append((entity_type, entity_id))
        if actor_key:
            pairs.append(("partner", actor_key))
        link_activity_to_timeline(activity, subjects=pairs or None)
        return activity
    except Exception:
        return None
