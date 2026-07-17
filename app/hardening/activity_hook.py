# -*- coding: utf-8 -*-
"""Hardening activity hook — thin alias to admin audit (fail-open)."""
from __future__ import annotations

from typing import Any, Optional

from app.hardening.audit import record_admin_audit


def record_hardening_event(
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
    return record_admin_audit(
        action=action,
        actor_key=actor_key,
        entity_type=entity_type,
        entity_id=entity_id,
        land_code=land_code,
        summary=summary,
        payload=payload,
        subjects=subjects,
    )
