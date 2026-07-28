# -*- coding: utf-8 -*-
"""سرویس گفتگوی وکیل ملکی — ترد پین‌شده مثل پستچی، با LLM."""
from __future__ import annotations

from typing import Any

from app.lawyer.config import (
    get_lawyer_settings,
    lawyer_display_name,
    lawyer_enabled,
    lawyer_welcome_text,
)

LAWYER_THREAD_ID = "__lawyer__"


def is_lawyer_thread(thread_id: str | None) -> bool:
    return str(thread_id or "").strip() == LAWYER_THREAD_ID


def ensure_lawyer_thread(
    user_key: str,
    *,
    audience: str | None = None,
    activate: bool = True,
) -> str:
    """ترد ثابت وکیل را در chat_store بساز؛ در صورت خالی‌بودن خوش‌آمد بگذار.

    activate=True فقط هنگام باز کردن/ارسال (نه هنگام لیست‌کردن تردها).
    وقتی سیستم وکیل خاموش است، ترد ساخته نمی‌شود.
    """
    from app.ai.chat_store import (
        _find_thread,
        _now_iso,
        _save_record,
        load_user_record,
        set_active_thread,
    )

    if not lawyer_enabled():
        return LAWYER_THREAD_ID

    key = str(user_key or "").strip()
    if not key:
        return LAWYER_THREAD_ID
    record = load_user_record(key, audience)
    th = _find_thread(record, LAWYER_THREAD_ID)
    ts = _now_iso()
    title = lawyer_display_name()
    if not th:
        th = {
            "id": LAWYER_THREAD_ID,
            "title": title,
            "kind": "lawyer",
            "created_at": ts,
            "updated_at": ts,
            "messages": [],
        }
        threads = list(record.get("threads") or [])
        # وکیل را اول لیست نگه دار (جدا از UI پین)
        record["threads"] = [th] + [
            t for t in threads if str(t.get("id") or "") != LAWYER_THREAD_ID
        ]
        _save_record(record, key, audience)
    else:
        th["kind"] = "lawyer"
        th["title"] = title
        _save_record(record, key, audience)

    msgs = [m for m in (th.get("messages") or []) if isinstance(m, dict)]
    if not msgs:
        welcome = lawyer_welcome_text()
        if welcome:
            from app.ai.chat_store import _new_message_id, _now_iso as now_iso
            from app.ai.message_types import MSG_AI

            record = load_user_record(key, audience)
            th = _find_thread(record, LAWYER_THREAD_ID)
            if th is not None:
                th["messages"] = [
                    {
                        "id": _new_message_id(),
                        "role": "assistant",
                        "type": MSG_AI,
                        "content": welcome[:4000],
                        "created_at": now_iso(),
                        "source": "lawyer",
                        "meta": {"welcome": True},
                        "quota": False,
                    }
                ]
                th["title"] = title
                th["kind"] = "lawyer"
                th["updated_at"] = now_iso()
                _save_record(record, key, audience)
    if activate:
        set_active_thread(key, LAWYER_THREAD_ID, audience=audience)
    return LAWYER_THREAD_ID


def lawyer_thread_for_ui(
    user_key: str,
    *,
    audience: str | None = None,
    active_thread_id: str | None = None,
) -> dict[str, Any] | None:
    if not lawyer_enabled():
        return None
    from app.ai.chat_store import _find_thread, load_user_record, messages_for_ui

    key = str(user_key or "").strip()
    cfg = get_lawyer_settings()
    title = str(cfg.get("display_name") or "وکیل ملکی")
    preview = "مشاوره حقوقی املاک ایران"
    updated_at = ""
    created_at = ""
    message_count = 0
    if key:
        try:
            record = load_user_record(key, audience)
            th = _find_thread(record, LAWYER_THREAD_ID) or {}
            if th:
                updated_at = str(th.get("updated_at") or "")
                created_at = str(th.get("created_at") or "")
                msgs = messages_for_ui(key, LAWYER_THREAD_ID, audience) or []
                message_count = len(msgs)
                for m in reversed(msgs):
                    if not isinstance(m, dict):
                        continue
                    body = str(m.get("content") or "").strip()
                    if body:
                        preview = body.replace("\n", " ")[:80]
                        break
        except Exception:
            pass
    active = str(active_thread_id or "").strip()
    return {
        "id": LAWYER_THREAD_ID,
        "title": title,
        "preview": preview,
        "updated_at": updated_at,
        "created_at": created_at,
        "message_count": message_count,
        "is_active": is_lawyer_thread(active),
        "kind": "lawyer",
        "unread": 0,
    }


def threads_with_lawyer(
    user_key: str,
    *,
    audience: str | None = None,
    active_thread_id: str | None = None,
    base_threads: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """وکیل را بالای لیست گفتگوها پین کن (بدون پستچی)."""
    if base_threads is None:
        from app.ai.chat_store import threads_for_ui

        threads = list(threads_for_ui(user_key, audience=audience) or [])
    else:
        threads = list(base_threads)
    threads = [
        t
        for t in threads
        if not (
            isinstance(t, dict)
            and (
                str(t.get("id") or "") == LAWYER_THREAD_ID
                or str(t.get("kind") or "") == "lawyer"
            )
        )
    ]
    lawyer_th = lawyer_thread_for_ui(
        user_key,
        audience=audience,
        active_thread_id=active_thread_id,
    )
    if not lawyer_th:
        return threads
    if is_lawyer_thread(active_thread_id):
        threads = [dict(t, is_active=False) for t in threads]
        lawyer_th = dict(lawyer_th)
        lawyer_th["is_active"] = True
    return [lawyer_th] + threads


def threads_with_lawyer_and_postchi(
    user_key: str,
    *,
    audience: str | None = None,
    active_thread_id: str | None = None,
) -> list[dict[str, Any]]:
    """ترتیب: وکیل → پستچی → بقیه گفتگوها."""
    from app.services.postchi import threads_with_postchi

    threads = threads_with_postchi(
        user_key,
        audience=audience,
        active_thread_id=active_thread_id,
    )
    return threads_with_lawyer(
        user_key,
        audience=audience,
        active_thread_id=active_thread_id,
        base_threads=threads,
    )
