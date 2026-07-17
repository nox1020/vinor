# -*- coding: utf-8 -*-
"""Append-only Activity store (JSON file). Never updates/deletes existing rows."""
from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from app.foundation.config import activity_store_enabled
from app.foundation.interfaces import Activity

_LOCK = threading.Lock()
_FILE_NAME = "foundation_activities.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path(app=None) -> str:
    from app.utils.storage import data_dir

    return os.path.join(data_dir(app), _FILE_NAME)


def _load_raw(app=None) -> List[dict[str, Any]]:
    from app.utils.storage import _load

    data = _load(_path(app))
    return data if isinstance(data, list) else []


def _save_raw(rows: List[dict[str, Any]], app=None) -> None:
    from app.utils.storage import _save

    _save(_path(app), rows)


def append_activity(
    *,
    action: str,
    actor_key: str = "",
    actor_role: str = "",
    entity_type: str = "",
    entity_id: str = "",
    land_code: str = "",
    workflow_id: str = "",
    object_type: str = "",
    summary: str = "",
    payload: dict[str, Any] | None = None,
    source: str = "foundation",
    metadata: dict[str, Any] | None = None,
    app=None,
) -> Optional[Activity]:
    """Append one activity. No-op (None) when store disabled. Fail-open on IO errors."""
    if not activity_store_enabled():
        return None
    activity = Activity(
        id=uuid.uuid4().hex[:16],
        created_at=_now_iso(),
        actor_key=(actor_key or "").strip(),
        actor_role=(actor_role or "").strip(),
        action=(action or "").strip() or "event",
        entity_type=(entity_type or "").strip(),
        entity_id=(entity_id or "").strip(),
        land_code=str(land_code or "").strip(),
        workflow_id=(workflow_id or "").strip(),
        object_type=(object_type or "").strip(),
        summary=(summary or "").strip(),
        payload=dict(payload or {}),
        source=(source or "foundation").strip() or "foundation",
        metadata=dict(metadata or {}),
    )
    try:
        with _LOCK:
            rows = _load_raw(app)
            rows.append(activity.to_dict())
            _save_raw(rows, app)
        return activity
    except Exception:
        return None


def list_activities(
    *,
    limit: int = 100,
    actor_key: str = "",
    land_code: str = "",
    workflow_id: str = "",
    app=None,
) -> List[Activity]:
    """Read activities newest-first. Empty when disabled or on error."""
    if not activity_store_enabled():
        return []
    try:
        rows = _load_raw(app)
    except Exception:
        return []
    out: List[Activity] = []
    ak = (actor_key or "").strip()
    lc = str(land_code or "").strip()
    wid = (workflow_id or "").strip()
    for row in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        if ak and str(row.get("actor_key") or "").strip() != ak:
            continue
        if lc and str(row.get("land_code") or "").strip() != lc:
            continue
        if wid and str(row.get("workflow_id") or "").strip() != wid:
            continue
        out.append(Activity.from_dict(row))
        if len(out) >= max(1, int(limit or 100)):
            break
    return out


def get_activity(activity_id: str, *, app=None) -> Optional[Activity]:
    if not activity_store_enabled():
        return None
    aid = (activity_id or "").strip()
    if not aid:
        return None
    try:
        for row in _load_raw(app):
            if isinstance(row, dict) and str(row.get("id") or "") == aid:
                return Activity.from_dict(row)
    except Exception:
        return None
    return None
