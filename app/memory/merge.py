"""ادغام حافظهٔ مهمان → کاربر لاگین‌شده."""
from __future__ import annotations

import os
from typing import Any

from app.memory.interfaces import MemoryItem, MemoryStore
from app.memory.lifecycle import resolve_conflicts
from app.memory.store import _safe_user_key, default_memory_dir


def merge_user_memory(from_key: str, to_key: str, *, store: MemoryStore | None = None) -> dict[str, Any]:
    """آیتم‌های from را به to منتقل می‌کند؛ فایل مهمان را پاک می‌کند.

    Returns: {merged, skipped, from_key, to_key}
    """
    src = str(from_key or "").strip()
    dst = str(to_key or "").strip()
    empty = {"merged": 0, "skipped": 0, "from_key": src, "to_key": dst}
    if not src or not dst or src == dst:
        return empty
    # فقط guest_* → شماره؛ جلوگیری از ادغام اشتباه
    if not src.startswith("guest_"):
        return empty

    try:
        from app.memory.config import memory_enabled
        from app.memory.di import make_memory_store

        if not memory_enabled():
            return empty
        st = store or make_memory_store()
        items = list(st.list_items(src) or [])
        if not items:
            _try_delete_file(src)
            return empty

        merged = 0
        skipped = 0
        for it in items:
            try:
                clone = MemoryItem(
                    id="",  # upsert جدید / ادغام با fingerprint
                    user_key=dst,
                    memory_type=it.memory_type,
                    key=it.key,
                    value=it.value,
                    score=float(it.score or 0.5),
                    metadata={**(it.metadata or {}), "merged_from": src},
                    created_at=it.created_at,
                    updated_at=it.updated_at,
                )
                resolve_conflicts(st, clone)
                st.upsert(clone)
                merged += 1
                if it.id:
                    st.delete(src, it.id)
            except Exception:
                skipped += 1

        _try_delete_file(src)
        return {"merged": merged, "skipped": skipped, "from_key": src, "to_key": dst}
    except Exception:
        return empty


def merge_guest_session_memory(phone: str, guest_id: str | None = None) -> dict[str, Any]:
    """از session یا guest_id صریح — برای فراخوانی بعد از OTP/لاگین."""
    from_key = ""
    if guest_id:
        gid = str(guest_id).strip()
        from_key = gid if gid.startswith("guest_") else f"guest_{gid}"
    else:
        try:
            from flask import session

            gid = str(session.get("ai_guest_id") or "").strip()
            if gid:
                from_key = f"guest_{gid}"
        except Exception:
            from_key = ""
    return merge_user_memory(from_key, phone)


def merge_guest_goals(from_key: str, to_key: str) -> int:
    """اهداف جلسهٔ مهمان را به کاربر منتقل می‌کند (بهترین‌تلاش)."""
    src = str(from_key or "").strip()
    dst = str(to_key or "").strip()
    if not src.startswith("guest_") or not dst or src == dst:
        return 0
    try:
        from app.goals.registry import SessionGoalRegistry

        reg = SessionGoalRegistry()
        guest_goals = reg.load(src) or []
        if not guest_goals:
            return 0
        existing = reg.load(dst) or []
        seen = {str(g.get("goal_id") or g.get("goal_type") or "") for g in existing if isinstance(g, dict)}
        added = 0
        for g in guest_goals:
            if not isinstance(g, dict):
                continue
            gid = str(g.get("goal_id") or g.get("goal_type") or "")
            if gid and gid in seen:
                continue
            existing.append(g)
            added += 1
        if added:
            reg.save(dst, existing[:20])
        return added
    except Exception:
        return 0


def _try_delete_file(user_key: str) -> None:
    key = _safe_user_key(user_key)
    if not key:
        return
    try:
        path = os.path.join(default_memory_dir(), f"{key}.json")
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass
