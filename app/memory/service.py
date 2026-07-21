from __future__ import annotations

import threading
from typing import Any

from app.memory.config import memory_budget_chars, memory_enabled, memory_top_k
from app.memory.di import make_memory_provider
from app.memory.interfaces import (
    MemoryExtractRequest,
    MemoryProvider,
    MemoryRetrieveRequest,
    MemoryRetrieveResult,
)

_LOCK = threading.Lock()
_PROVIDER: MemoryProvider | None = None


def get_memory_provider() -> MemoryProvider | None:
    global _PROVIDER
    if not memory_enabled():
        return None
    if _PROVIDER is not None:
        return _PROVIDER
    with _LOCK:
        if _PROVIDER is None:
            _PROVIDER = make_memory_provider()
    return _PROVIDER


def _resolve_stage(explicit: str = "") -> str:
    stage = (explicit or "").strip().lower()
    if stage:
        return stage
    # اولویت با ناظر قیف
    try:
        from flask import g, has_request_context

        if has_request_context():
            uk = str(getattr(g, "ai_user_key", "") or "")
            if uk:
                from app.supervisor.funnel_service import current_stage

                fs = current_stage(uk)
                if fs:
                    return fs
    except Exception:
        pass
    try:
        from app.goals.service import get_goals

        data = get_goals() or {}
        goals = data.get("goals") or []
        primary = str(data.get("primary_goal_id") or "")
        if primary and isinstance(goals, list):
            for g in goals:
                if isinstance(g, dict) and str(g.get("goal_id") or "") == primary:
                    return str(g.get("goal_type") or "").strip().lower()
        if isinstance(goals, list) and goals:
            g0 = goals[0]
            if isinstance(g0, dict):
                return str(g0.get("goal_type") or "").strip().lower()
    except Exception:
        pass
    return ""


def retrieve_memory_for_prompt(
    *,
    user_key: str,
    query: str,
    audience: str = "",
    thread_id: str | None = None,
    budget_chars: int | None = None,
    stage: str = "",
) -> MemoryRetrieveResult:
    provider = get_memory_provider()
    if provider is None or not user_key:
        return MemoryRetrieveResult([], "", 0, 0, 0)
    try:
        budget = memory_budget_chars() if budget_chars is None else max(40, int(budget_chars))
        return provider.get_prompt_memory(
            MemoryRetrieveRequest(
                user_key=user_key,
                query=query or "",
                audience=audience,
                thread_id=thread_id,
                budget_chars=budget,
                top_k=memory_top_k(),
                stage=_resolve_stage(stage),
            )
        )
    except Exception:
        return MemoryRetrieveResult([], "", 0, 0, 0)


def learn_from_exchange(
    *,
    user_key: str,
    user_message: str,
    assistant_reply: str,
    audience: str = "",
    thread_id: str | None = None,
    land_codes: list[str] | None = None,
) -> int:
    provider = get_memory_provider()
    if provider is None or not user_key:
        return 0
    try:
        saved = provider.learn_from_exchange(
            MemoryExtractRequest(
                user_key=user_key,
                user_message=user_message or "",
                assistant_reply=assistant_reply or "",
                audience=audience,
                thread_id=thread_id,
                land_codes=tuple(str(c).strip() for c in (land_codes or []) if str(c).strip()),
            )
        )
        return len(saved)
    except Exception:
        return 0


def memory_quota_for_user(user_key: str) -> dict[str, int]:
    """مصرف و سقف حافظهٔ اختصاصی یک کاربر (بایت)."""
    from app.memory.config import memory_max_bytes
    from app.memory.di import make_memory_store

    max_b = memory_max_bytes()
    used = 0
    if user_key:
        try:
            store = make_memory_store()
            used_fn = getattr(store, "usage_bytes", None)
            if callable(used_fn):
                used = int(used_fn(user_key) or 0)
            max_fn = getattr(store, "max_bytes", None)
            if callable(max_fn):
                max_b = int(max_fn() or max_b)
        except Exception:
            used = 0
    return {"bytes_used": used, "max_bytes": max_b}


def forget_memories(
    user_key: str,
    *,
    memory_ids: list[str] | None = None,
    keys: list[str] | None = None,
    key_prefix: str = "",
) -> dict[str, Any]:
    """حذف حافظه با id یا کلید — برای کارت تأیید forget."""
    uk = str(user_key or "").strip()
    if not uk or not memory_enabled():
        return {"ok": False, "deleted": 0, "error": "حافظه در دسترس نیست."}
    try:
        from app.memory.di import make_memory_store

        store = make_memory_store()
        deleted = 0
        ids = [str(x).strip() for x in (memory_ids or []) if str(x).strip()]
        for mid in ids:
            if store.delete(uk, mid):
                deleted += 1
        want_keys = {str(k).strip() for k in (keys or []) if str(k).strip()}
        prefix = str(key_prefix or "").strip()
        if want_keys or prefix:
            for it in list(store.list_items(uk) or []):
                k = str(it.key or "")
                if (k in want_keys) or (prefix and k.startswith(prefix)):
                    if it.id and store.delete(uk, it.id):
                        deleted += 1
        return {"ok": True, "deleted": deleted}
    except Exception as exc:
        return {"ok": False, "deleted": 0, "error": str(exc)}


def list_memory_brief(user_key: str, *, limit: int = 12) -> list[dict[str, Any]]:
    """خلاصهٔ خواندنی برای کارت forget / ops."""
    uk = str(user_key or "").strip()
    if not uk or not memory_enabled():
        return []
    try:
        from app.memory.di import make_memory_store
        from app.memory.lifecycle import filter_active

        items = filter_active(make_memory_store().list_items(uk) or [])
        items = sorted(items, key=lambda x: float(x.score or 0), reverse=True)[: max(1, limit)]
        return [
            {
                "id": it.id,
                "key": it.key,
                "type": it.memory_type,
                "value": (it.value or "")[:120],
            }
            for it in items
        ]
    except Exception:
        return []


def upsert_live_summary(user_key: str, summary: str) -> None:
    """همگام‌سازی خلاصهٔ partner_live → منبع حقیقت ai_memory."""
    uk = str(user_key or "").strip()
    text = (summary or "").strip()
    if not uk or not text or not memory_enabled():
        return
    try:
        import uuid
        from datetime import datetime, timezone

        from app.memory.di import make_memory_store
        from app.memory.interfaces import MEMORY_LONG, MemoryItem
        from app.memory.lifecycle import resolve_conflicts

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        item = MemoryItem(
            id=str(uuid.uuid4()),
            user_key=uk,
            memory_type=MEMORY_LONG,
            key="live_summary",
            value=text[:500],
            score=0.88,
            metadata={"source": "partner_live"},
            created_at=now,
            updated_at=now,
        )
        store = make_memory_store()
        resolve_conflicts(store, item)
        store.upsert(item)
    except Exception:
        pass
