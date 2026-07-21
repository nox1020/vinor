"""TTL و حل تناقض حافظه — قبل از ذخیره / هنگام بازیابی."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.memory.config import memory_short_ttl_hours
from app.memory.interfaces import (
    MEMORY_RELATIONSHIP,
    MEMORY_SHORT,
    MemoryItem,
    MemoryStore,
)

_LAND_REL_RE = re.compile(r"^(liked|rejected|viewed|visit|visit_done|deal|deal_release):(.+)$")


def _parse_iso(ts: str) -> datetime | None:
    s = (ts or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def is_expired(item: MemoryItem, *, now: datetime | None = None) -> bool:
    """فقط short_term منقضی می‌شود (پیش‌فرض ۴۸ ساعت)."""
    if item.memory_type != MEMORY_SHORT:
        return False
    created = _parse_iso(item.updated_at or item.created_at)
    if not created:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    ref = now or datetime.now(timezone.utc)
    return ref - created > timedelta(hours=memory_short_ttl_hours())


def purge_expired(store: MemoryStore, user_key: str) -> int:
    """حذف short_term منقضی؛ تعداد حذف‌شده را برمی‌گرداند."""
    if not user_key:
        return 0
    removed = 0
    now = datetime.now(timezone.utc)
    for it in list(store.list_items(user_key, memory_type=MEMORY_SHORT) or []):
        if is_expired(it, now=now) and it.id:
            if store.delete(user_key, it.id):
                removed += 1
    return removed


def _land_code_from_key(key: str) -> str:
    m = _LAND_REL_RE.match(str(key or "").strip())
    return m.group(2).strip() if m else ""


def conflicting_ids(existing: list[MemoryItem], incoming: MemoryItem) -> list[str]:
    """آیتم‌هایی که با مورد جدید تناقض دارند و باید حذف شوند."""
    key = str(incoming.key or "").strip()
    mtype = str(incoming.memory_type or "")
    out: list[str] = []

    def _collect(pred: Callable[[MemoryItem], bool]) -> list[str]:
        ids: list[str] = []
        for it in existing:
            if not it.id:
                continue
            # همان رکورد (upsert) را نگه دار
            if it.key == key and it.memory_type == mtype:
                continue
            if pred(it):
                ids.append(it.id)
        return ids

    # بودجه: فقط یک کلید فعال
    if key == "budget" or key.startswith("budget"):
        return _collect(lambda it: it.key == "budget" or str(it.key or "").startswith("budget"))

    # یک شهر / یک دستهٔ ملک
    if key.startswith("city:"):
        return _collect(lambda it: str(it.key or "").startswith("city:"))
    if key.startswith("category:"):
        return _collect(lambda it: str(it.key or "").startswith("category:"))

    # liked ↔ rejected برای همان فایل
    land = _land_code_from_key(key)
    if land and mtype == MEMORY_RELATIONSHIP:
        prefix = key.split(":", 1)[0]
        kill: set[str] = set()
        if prefix == "liked":
            kill = {f"rejected:{land}"}
        elif prefix == "rejected":
            kill = {f"liked:{land}"}
        elif prefix == "deal":
            kill = {f"rejected:{land}"}
        return _collect(lambda it: it.key in kill)

    return out


def resolve_conflicts(store: MemoryStore, incoming: MemoryItem) -> int:
    """حذف متناقض‌ها قبل از upsert. تعداد حذف."""
    if not incoming.user_key:
        return 0
    existing = store.list_items(incoming.user_key) or []
    removed = 0
    for mid in conflicting_ids(existing, incoming):
        if store.delete(incoming.user_key, mid):
            removed += 1
    return removed


def filter_active(items: list[MemoryItem], *, now: datetime | None = None) -> list[MemoryItem]:
    ref = now or datetime.now(timezone.utc)
    return [it for it in items if not is_expired(it, now=ref)]
