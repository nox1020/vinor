# -*- coding: utf-8 -*-
"""Role assignment JSON store — fail-open, gated by roles_enabled."""
from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from app.roles.config import roles_enabled
from app.roles.interfaces import ALL_PORTAL_ROLES, RoleAssignment

_LOCK = threading.Lock()
_FILE = "role_assignments.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path(app=None) -> str:
    from app.utils.storage import data_dir

    return os.path.join(data_dir(app), _FILE)


def _load_raw(app=None) -> List[dict[str, Any]]:
    from app.utils.storage import _load

    data = _load(_path(app))
    return data if isinstance(data, list) else []


def _save_raw(rows: List[dict[str, Any]], app=None) -> None:
    from app.utils.storage import _save

    _save(_path(app), rows)


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _norm_phone(phone: str) -> str:
    raw = (phone or "").strip()
    if not raw:
        return ""
    try:
        from app.services.sms import normalize_iran_mobile

        return normalize_iran_mobile(raw) or raw
    except Exception:
        return raw


def get_assignment(phone: str, *, app=None) -> Optional[RoleAssignment]:
    if not roles_enabled():
        return None
    pp = _norm_phone(phone)
    if not pp:
        return None
    try:
        for row in _load_raw(app):
            if isinstance(row, dict) and _norm_phone(str(row.get("phone") or "")) == pp:
                return RoleAssignment.from_dict(row)
    except Exception:
        return None
    return None


def upsert_assignment(
    *,
    phone: str,
    roles: list[str],
    source: str = "explicit",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    app=None,
) -> Optional[RoleAssignment]:
    if not roles_enabled():
        return None
    pp = _norm_phone(phone)
    if not pp:
        return None
    clean = [r for r in roles if str(r).strip() in ALL_PORTAL_ROLES]
    # dedupe preserve order
    seen: set[str] = set()
    ordered: list[str] = []
    for r in clean:
        if r not in seen:
            seen.add(r)
            ordered.append(r)
    now = _now_iso()
    try:
        with _LOCK:
            rows = _load_raw(app)
            for i, row in enumerate(rows):
                if isinstance(row, dict) and _norm_phone(str(row.get("phone") or "")) == pp:
                    existing = RoleAssignment.from_dict(row)
                    existing.roles = ordered
                    existing.source = (source or "explicit").strip() or "explicit"
                    if notes:
                        existing.notes = notes.strip()
                    if metadata:
                        existing.metadata.update(dict(metadata))
                    existing.updated_at = now
                    rows[i] = existing.to_dict()
                    _save_raw(rows, app)
                    return existing
            rec = RoleAssignment(
                id=_new_id(),
                phone=pp,
                roles=ordered,
                source=(source or "explicit").strip() or "explicit",
                notes=(notes or "").strip(),
                created_at=now,
                updated_at=now,
                metadata=dict(metadata or {}),
            )
            rows.append(rec.to_dict())
            _save_raw(rows, app)
            return rec
    except Exception:
        return None


def list_assignments(*, limit: int = 500, app=None) -> List[RoleAssignment]:
    if not roles_enabled():
        return []
    try:
        rows = _load_raw(app)
    except Exception:
        return []
    out: List[RoleAssignment] = []
    for row in reversed(rows if isinstance(rows, list) else []):
        if isinstance(row, dict):
            out.append(RoleAssignment.from_dict(row))
        if len(out) >= max(1, int(limit or 500)):
            break
    return out
