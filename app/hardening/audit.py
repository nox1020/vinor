# -*- coding: utf-8 -*-
"""Admin audit → Foundation Activity/Timeline (fail-open)."""
from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

from app.hardening.config import (
    hardening_audit_enabled,
    hardening_audit_required,
    hardening_enabled,
)

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def _actor_from_session() -> str:
    try:
        from flask import session

        for key in ("admin_phone", "username", "user_phone", "phone"):
            val = str(session.get(key) or "").strip()
            if val:
                return val
        if session.get("logged_in"):
            return "admin"
    except Exception:
        pass
    return ""


def record_admin_audit(
    *,
    action: str,
    actor_key: str = "",
    entity_type: str = "",
    entity_id: str = "",
    land_code: str = "",
    summary: str = "",
    payload: dict[str, Any] | None = None,
    subjects: list[tuple[str, str]] | None = None,
) -> Optional[Any]:
    """
    Append Activity + Timeline for admin mutations.
    Fail-open: never raises; when audit_required and write fails, logs warning.
    """
    if not hardening_enabled() or not hardening_audit_enabled():
        return None
    actor = (actor_key or "").strip() or _actor_from_session()
    try:
        from app.foundation.activity_store import append_activity
        from app.foundation.timeline_store import link_activity_to_timeline

        activity = append_activity(
            action=(action or "").strip() or "admin_event",
            actor_key=actor,
            actor_role="admin",
            entity_type=(entity_type or "").strip(),
            entity_id=(entity_id or "").strip(),
            land_code=str(land_code or "").strip(),
            object_type=(entity_type or "").strip() or "admin",
            summary=(summary or "").strip(),
            payload=dict(payload or {}),
            source="admin",
        )
        if activity is None:
            if hardening_audit_required():
                logger.warning(
                    "admin audit required but activity write skipped/failed action=%s",
                    action,
                )
            return None
        pairs = list(subjects or [])
        if entity_type and entity_id:
            pairs.append((entity_type, entity_id))
        if actor:
            pairs.append(("admin", actor))
        if land_code:
            pairs.append(("land", str(land_code).strip()))
        link_activity_to_timeline(activity, subjects=pairs or None)
        return activity
    except Exception:
        if hardening_audit_required():
            logger.warning(
                "admin audit required but failed action=%s",
                action,
                exc_info=True,
            )
        return None


def audit_admin_action(
    action: str,
    *,
    entity_type: str = "",
    summary: str = "",
) -> Callable[[F], F]:
    """
    Decorator: after successful view return, record audit.
    Does not audit redirects that are clearly errors unless status looks ok —
    records once per invocation after view returns without raising.
    """

    def decorator(view: F) -> F:
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any):
            result = view(*args, **kwargs)
            try:
                eid = ""
                for key in ("cid", "wid", "vid", "deal_id", "id"):
                    if key in kwargs and kwargs[key] is not None:
                        eid = str(kwargs[key])
                        break
                record_admin_audit(
                    action=action,
                    entity_type=entity_type,
                    entity_id=eid,
                    summary=summary or action,
                    payload={"kwargs_keys": list(kwargs.keys())},
                )
            except Exception:
                pass
            return result

        return wrapper  # type: ignore[return-value]

    return decorator
