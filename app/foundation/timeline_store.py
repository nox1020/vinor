# -*- coding: utf-8 -*-
"""Append-only Timeline store — indexes subjects to activities."""
from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from app.foundation.config import timeline_store_enabled
from app.foundation.interfaces import Activity, TimelineEntry

_LOCK = threading.Lock()
_FILE_NAME = "foundation_timeline.json"


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


def append_timeline_entry(
    *,
    subject_type: str,
    subject_id: str,
    activity_id: str,
    action: str = "",
    summary: str = "",
    land_code: str = "",
    metadata: dict[str, Any] | None = None,
    created_at: str = "",
    app=None,
) -> Optional[TimelineEntry]:
    """Append timeline row. No-op when disabled."""
    if not timeline_store_enabled():
        return None
    entry = TimelineEntry(
        id=uuid.uuid4().hex[:16],
        created_at=(created_at or "").strip() or _now_iso(),
        subject_type=(subject_type or "").strip() or "unknown",
        subject_id=(subject_id or "").strip() or "",
        activity_id=(activity_id or "").strip(),
        action=(action or "").strip(),
        summary=(summary or "").strip(),
        land_code=str(land_code or "").strip(),
        metadata=dict(metadata or {}),
    )
    if not entry.subject_id or not entry.activity_id:
        return None
    try:
        with _LOCK:
            rows = _load_raw(app)
            rows.append(entry.to_dict())
            _save_raw(rows, app)
        return entry
    except Exception:
        return None


def link_activity_to_timeline(
    activity: Activity,
    *,
    subjects: list[tuple[str, str]] | None = None,
    app=None,
) -> List[TimelineEntry]:
    """
    Create timeline entries for an activity.
    Default subjects: actor, land (if any), workflow (if any).
    """
    if not timeline_store_enabled() or activity is None:
        return []
    pairs: list[tuple[str, str]] = []
    if subjects:
        pairs.extend(subjects)
    else:
        if activity.actor_key:
            pairs.append(("actor", activity.actor_key))
        if activity.land_code:
            pairs.append(("land", activity.land_code))
        if activity.workflow_id:
            pairs.append(("workflow", activity.workflow_id))
        if activity.entity_type and activity.entity_id:
            pairs.append((activity.entity_type, activity.entity_id))
    # de-dupe
    seen: set[tuple[str, str]] = set()
    out: List[TimelineEntry] = []
    for st, sid in pairs:
        key = ((st or "").strip(), (sid or "").strip())
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        entry = append_timeline_entry(
            subject_type=key[0],
            subject_id=key[1],
            activity_id=activity.id,
            action=activity.action,
            summary=activity.summary,
            land_code=activity.land_code,
            created_at=activity.created_at,
            metadata={"object_type": activity.object_type, "source": activity.source},
            app=app,
        )
        if entry:
            out.append(entry)
    return out


def list_timeline(
    *,
    subject_type: str = "",
    subject_id: str = "",
    land_code: str = "",
    limit: int = 100,
    app=None,
) -> List[TimelineEntry]:
    """Newest-first timeline filter. Empty when disabled."""
    if not timeline_store_enabled():
        return []
    try:
        rows = _load_raw(app)
    except Exception:
        return []
    st = (subject_type or "").strip()
    sid = (subject_id or "").strip()
    lc = str(land_code or "").strip()
    out: List[TimelineEntry] = []
    for row in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        if st and str(row.get("subject_type") or "").strip() != st:
            continue
        if sid and str(row.get("subject_id") or "").strip() != sid:
            continue
        if lc and str(row.get("land_code") or "").strip() != lc:
            continue
        out.append(TimelineEntry.from_dict(row))
        if len(out) >= max(1, int(limit or 100)):
            break
    return out
