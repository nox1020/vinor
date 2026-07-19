"""Lightweight Case (پرونده) linked to an AI chat thread.

Stored as JSON under ``ai_cases/{audience}/{user_key}.json``.
Does not replace visit/commission domain stores; mirrors conversation lifecycle.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from flask import current_app

from app.ai.audience import AUDIENCE_PARTNER, AUDIENCE_PUBLIC
from app.ai.paths import ai_data_file

# Case states
CASE_OPEN = "open"
CASE_IN_PROGRESS = "in_progress"
CASE_WAITING = "waiting"
CASE_COMPLETED = "completed"
CASE_CANCELLED = "cancelled"
CASE_CLOSED = "closed"

CASE_TRANSITIONS: dict[str, frozenset[str]] = {
    CASE_OPEN: frozenset({CASE_IN_PROGRESS, CASE_WAITING, CASE_CANCELLED, CASE_CLOSED}),
    CASE_IN_PROGRESS: frozenset(
        {CASE_WAITING, CASE_COMPLETED, CASE_CANCELLED, CASE_CLOSED, CASE_IN_PROGRESS}
    ),
    CASE_WAITING: frozenset(
        {CASE_IN_PROGRESS, CASE_COMPLETED, CASE_CANCELLED, CASE_CLOSED, CASE_WAITING}
    ),
    CASE_COMPLETED: frozenset({CASE_CLOSED, CASE_COMPLETED}),
    CASE_CANCELLED: frozenset({CASE_CLOSED, CASE_CANCELLED}),
    CASE_CLOSED: frozenset({CASE_CLOSED}),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_audience(audience: str | None) -> str:
    return audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER


def _storage_key(user_key: str) -> str:
    digits = re.sub(r"\D+", "", str(user_key or ""))
    if len(digits) >= 11:
        return digits[-11:]
    if len(digits) >= 8:
        return digits
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", str(user_key or ""))
    return safe[:64] if safe else ""


def _cases_path(user_key: str, audience: str | None = None) -> str | None:
    aud = _normalize_audience(audience)
    key = _storage_key(user_key)
    if not key:
        return None
    root = ai_data_file("ai_cases")
    sub = os.path.join(root, aud)
    os.makedirs(sub, exist_ok=True)
    return os.path.join(sub, f"{key}.json")


def _load_all(user_key: str, audience: str | None = None) -> dict[str, Any]:
    path = _cases_path(user_key, audience)
    if not path or not os.path.isfile(path):
        return {"user_key": _storage_key(user_key), "cases": []}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"user_key": _storage_key(user_key), "cases": []}
        cases = [c for c in (data.get("cases") or []) if isinstance(c, dict)]
        return {"user_key": _storage_key(user_key), "cases": cases}
    except Exception:
        return {"user_key": _storage_key(user_key), "cases": []}


def _save_all(record: dict[str, Any], user_key: str, audience: str | None = None) -> None:
    path = _cases_path(user_key, audience)
    if not path:
        return
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as exc:
        try:
            current_app.logger.warning("case_store save failed: %s", exc)
        except Exception:
            pass


def get_case_for_thread(
    user_key: str,
    thread_id: str,
    audience: str | None = None,
) -> dict[str, Any] | None:
    tid = str(thread_id or "").strip()
    if not tid:
        return None
    for case in _load_all(user_key, audience).get("cases") or []:
        if str(case.get("thread_id") or "") == tid:
            return dict(case)
    return None


def ensure_case_for_thread(
    user_key: str,
    thread_id: str,
    *,
    audience: str | None = None,
    land_code: str = "",
    case_type: str = "conversation",
    title: str = "",
) -> dict[str, Any]:
    tid = str(thread_id or "").strip()
    existing = get_case_for_thread(user_key, tid, audience) if tid else None
    if existing:
        changed = False
        code = str(land_code or "").strip()
        if code and not str(existing.get("land_code") or "").strip():
            existing["land_code"] = code
            changed = True
        if changed:
            _upsert_case(user_key, existing, audience)
        return existing

    ts = _now_iso()
    case = {
        "id": uuid.uuid4().hex,
        "thread_id": tid,
        "type": str(case_type or "conversation"),
        "title": str(title or "پرونده گفتگو").strip() or "پرونده گفتگو",
        "land_code": str(land_code or "").strip(),
        "status": CASE_OPEN,
        "version": 1,
        "timeline": [],
        "created_at": ts,
        "updated_at": ts,
        "metadata": {},
    }
    _upsert_case(user_key, case, audience)
    return case


def _upsert_case(user_key: str, case: dict[str, Any], audience: str | None = None) -> None:
    record = _load_all(user_key, audience)
    cases = list(record.get("cases") or [])
    cid = str(case.get("id") or "")
    tid = str(case.get("thread_id") or "")
    replaced = False
    for i, row in enumerate(cases):
        if (cid and str(row.get("id") or "") == cid) or (
            tid and str(row.get("thread_id") or "") == tid
        ):
            cases[i] = case
            replaced = True
            break
    if not replaced:
        cases.insert(0, case)
    record["cases"] = cases[:80]
    _save_all(record, user_key, audience)


def append_case_timeline(
    user_key: str,
    thread_id: str,
    *,
    audience: str | None = None,
    event: str,
    label: str,
    land_code: str = "",
    meta: dict[str, Any] | None = None,
    case_status: str | None = None,
) -> dict[str, Any] | None:
    case = ensure_case_for_thread(
        user_key,
        thread_id,
        audience=audience,
        land_code=land_code,
    )
    entry = {
        "at": _now_iso(),
        "event": str(event or "").strip() or "update",
        "label": str(label or "").strip(),
        "meta": dict(meta or {}),
    }
    timeline = list(case.get("timeline") or [])
    timeline.append(entry)
    case["timeline"] = timeline[-100:]
    case["updated_at"] = entry["at"]
    case["version"] = int(case.get("version") or 1) + 1
    if land_code and not case.get("land_code"):
        case["land_code"] = str(land_code).strip()

    if case_status:
        cur = str(case.get("status") or CASE_OPEN)
        nxt = str(case_status).strip()
        allowed = CASE_TRANSITIONS.get(cur, frozenset())
        if nxt == cur or nxt in allowed:
            case["status"] = nxt

    _upsert_case(user_key, case, audience)
    return case


def touch_case_status(
    user_key: str,
    thread_id: str,
    status: str,
    *,
    audience: str | None = None,
) -> dict[str, Any] | None:
    return append_case_timeline(
        user_key,
        thread_id,
        audience=audience,
        event="status_change",
        label=f"وضعیت پرونده: {status}",
        case_status=status,
    )
