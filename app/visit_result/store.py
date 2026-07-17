# -*- coding: utf-8 -*-
"""Visit Result JSON store — fail-open, gated by visit_result_enabled."""
from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from app.visit_result.config import OUTCOMES, visit_result_enabled
from app.visit_result.interfaces import VisitResult

_LOCK = threading.Lock()
_FILE_NAME = "visit_results.json"


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


def upsert_visit_result(
    *,
    visit_request_id: str,
    partner_phone: str = "",
    land_code: str = "",
    outcome: str = "",
    notes: str = "",
    actor_key: str = "",
    source: str = "partner",
    metadata: dict[str, Any] | None = None,
    app=None,
) -> Optional[VisitResult]:
    """Create or update the result for a visit_request_id (one active row)."""
    if not visit_result_enabled():
        return None
    vid = (visit_request_id or "").strip()
    oc = (outcome or "").strip()
    if not vid or oc not in OUTCOMES:
        return None
    now = _now_iso()
    try:
        with _LOCK:
            rows = _load_raw(app)
            found: dict[str, Any] | None = None
            idx = -1
            for i, row in enumerate(rows):
                if isinstance(row, dict) and str(row.get("visit_request_id") or "").strip() == vid:
                    found = row
                    idx = i
                    break
            if found is None:
                result = VisitResult(
                    id=uuid.uuid4().hex[:16],
                    visit_request_id=vid,
                    partner_phone=(partner_phone or "").strip(),
                    land_code=str(land_code or "").strip(),
                    outcome=oc,
                    notes=(notes or "").strip(),
                    created_at=now,
                    updated_at=now,
                    actor_key=(actor_key or "").strip(),
                    source=(source or "partner").strip() or "partner",
                    metadata=dict(metadata or {}),
                )
                rows.append(result.to_dict())
                _save_raw(rows, app)
                return result
            result = VisitResult.from_dict(found)
            result.outcome = oc
            if notes:
                result.notes = notes
            if partner_phone:
                result.partner_phone = (partner_phone or "").strip()
            if land_code:
                result.land_code = str(land_code or "").strip()
            if actor_key:
                result.actor_key = (actor_key or "").strip()
            if source:
                result.source = (source or "partner").strip() or "partner"
            if metadata:
                result.metadata.update(metadata)
            result.updated_at = now
            rows[idx] = result.to_dict()
            _save_raw(rows, app)
            return result
    except Exception:
        return None


def get_result_for_visit(visit_request_id: str, *, app=None) -> Optional[VisitResult]:
    if not visit_result_enabled():
        return None
    vid = (visit_request_id or "").strip()
    if not vid:
        return None
    try:
        for row in _load_raw(app):
            if isinstance(row, dict) and str(row.get("visit_request_id") or "").strip() == vid:
                return VisitResult.from_dict(row)
    except Exception:
        return None
    return None


def list_results(
    *,
    partner_phone: str = "",
    land_code: str = "",
    limit: int = 200,
    app=None,
) -> List[VisitResult]:
    if not visit_result_enabled():
        return []
    pp = (partner_phone or "").strip()
    lc = str(land_code or "").strip()
    try:
        rows = _load_raw(app)
    except Exception:
        return []
    out: List[VisitResult] = []
    for row in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        if pp and str(row.get("partner_phone") or "").strip() != pp:
            continue
        if lc and str(row.get("land_code") or "").strip() != lc:
            continue
        out.append(VisitResult.from_dict(row))
        if len(out) >= max(1, int(limit or 200)):
            break
    return out
