"""ذخیره تاریخچه چت Vinor AI — جدا برای همکار و کاربر عادی."""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from flask import current_app

from app.ai.audience import AUDIENCE_ADMIN, AUDIENCE_PARTNER, AUDIENCE_PUBLIC
from app.ai.paths import ai_data_file

_MAX_MESSAGES = 200  # Chat-First: keep longer case history in-thread
_MAX_THREADS = 30
_MAX_CONTENT = 4000
_TITLE_LEN = 48
_MAX_PREVIEW = 80
VINOR_THREAD_TITLE = "وینور"
LAND_DETAIL_SOURCE = "land_detail"


def _is_guest_key(user_key: str) -> bool:
    return str(user_key or "").startswith("guest_")


def _thread_limit(user_key: str) -> int:
    if _is_guest_key(user_key):
        from app.ai.credits import guest_max_threads

        return guest_max_threads()
    return _MAX_THREADS


def _chats_dir() -> str:
    path = ai_data_file("ai_chats")
    os.makedirs(path, exist_ok=True)
    return path


def _normalize_audience(audience: str | None) -> str:
    return (
        audience
        if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC, AUDIENCE_ADMIN)
        else AUDIENCE_PARTNER
    )


def _storage_key(user_key: str) -> str:
    digits = re.sub(r"\D+", "", str(user_key or ""))
    if len(digits) >= 11:
        return digits[-11:]
    if len(digits) >= 8:
        return digits
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", str(user_key or ""))
    return safe[:64] if safe else ""


def _chat_path(user_key: str, audience: str | None = None) -> str | None:
    aud = _normalize_audience(audience)
    key = _storage_key(user_key)
    if not key:
        return None
    subdir = os.path.join(_chats_dir(), aud)
    os.makedirs(subdir, exist_ok=True)
    path = os.path.join(subdir, f"{key}.json")
    if aud == AUDIENCE_PARTNER:
        legacy = os.path.join(_chats_dir(), f"{key}.json")
        if os.path.isfile(legacy) and not os.path.isfile(path):
            try:
                os.replace(legacy, path)
            except OSError:
                pass
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _title_from_text(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= _TITLE_LEN:
        return t or "گفتگوی جدید"
    return t[: _TITLE_LEN - 1] + "…"


def _title_from_messages(messages: list[dict[str, Any]]) -> str:
    for item in messages:
        if isinstance(item, dict) and item.get("role") == "user":
            return _title_from_text(str(item.get("content") or ""))
    return "گفتگوی جدید"


def _thread_sort_key(th: dict[str, Any]) -> str:
    return str(th.get("updated_at") or th.get("created_at") or "")


def _sort_threads(threads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(threads, key=_thread_sort_key, reverse=True)


def _prune_threads(
    record: dict[str, Any],
    *,
    max_threads: int = _MAX_THREADS,
) -> tuple[dict[str, Any], int]:
    """حداکثر max_threads گفتگو — قدیمی‌ترین حذف می‌شود."""
    cap = max(1, int(max_threads or _MAX_THREADS))
    threads = list(record.get("threads") or [])
    if len(threads) <= cap:
        return record, 0

    ordered = _sort_threads(threads)
    kept = ordered[:cap]
    removed = len(ordered) - len(kept)
    active_id = record.get("active_id")
    if active_id and not any(t.get("id") == active_id for t in kept):
        record["active_id"] = kept[0]["id"] if kept else None
    record["threads"] = kept
    return record, removed


def _finalize_record(
    record: dict[str, Any],
    *,
    user_key: str = "",
) -> tuple[dict[str, Any], int]:
    """مرتب‌سازی + محدودیت تعداد گفتگو."""
    threads = _sort_threads(list(record.get("threads") or []))
    record["threads"] = threads
    return _prune_threads(record, max_threads=_thread_limit(user_key))


def _new_message_id() -> str:
    return uuid.uuid4().hex


def _normalize_actions(actions: list | None) -> list[dict[str, Any]]:
    from app.ai.card_registry import normalize_card

    out: list[dict[str, Any]] = []
    for a in actions or []:
        if isinstance(a, dict):
            out.append(normalize_card(a))
        if len(out) >= 5:
            break
    return out


def _clean_messages(raw: list) -> list[dict[str, Any]]:
    from app.ai.message_types import normalize_message_type

    cleaned: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()[:_MAX_CONTENT]
        actions = item.get("agent_actions")
        codes = item.get("land_codes")
        has_actions = isinstance(actions, list) and any(isinstance(a, dict) for a in actions)
        has_codes = isinstance(codes, list) and any(str(c).strip() for c in codes)
        # Allow system/card messages with actions even if content empty-ish
        if role not in ("user", "assistant"):
            continue
        if not content and not has_actions and not has_codes:
            continue
        if not content and (has_actions or has_codes):
            content = str(item.get("content") or "جزئیات را در کارت زیر بررسی کنید.")[:_MAX_CONTENT]
        row: dict[str, Any] = {
            "id": str(item.get("id") or "").strip() or _new_message_id(),
            "role": role,
            "content": content,
            "created_at": item.get("created_at") or _now_iso(),
            "type": normalize_message_type(
                item.get("type"),
                role=role,
                source=str(item.get("source") or ""),
            ),
        }
        if item.get("source"):
            row["source"] = str(item.get("source"))
        if item.get("escalation_id"):
            row["escalation_id"] = str(item.get("escalation_id"))
        if item.get("event"):
            row["event"] = str(item.get("event"))
        if isinstance(item.get("meta"), dict) and item.get("meta"):
            row["meta"] = dict(item["meta"])
        if has_codes:
            row["land_codes"] = [str(c).strip() for c in codes if str(c).strip()][:5]
        if has_actions:
            row["agent_actions"] = _normalize_actions(actions)
        if item.get("hide_ui") or item.get("hide_user"):
            row["hide_ui"] = True
        if item.get("case_id"):
            row["case_id"] = str(item.get("case_id"))
        cleaned.append(row)
    return cleaned[-_MAX_MESSAGES:]


def _migrate_legacy(data: dict[str, Any], user_key: str) -> dict[str, Any]:
    if isinstance(data.get("threads"), list):
        return data
    msgs = _clean_messages(data.get("messages") if isinstance(data.get("messages"), list) else [])
    if not msgs:
        return {"user_key": _storage_key(user_key), "active_id": None, "threads": []}
    tid = str(uuid.uuid4())
    ts = data.get("updated_at") or _now_iso()
    return {
        "user_key": _storage_key(user_key),
        "active_id": tid,
        "threads": [
            {
                "id": tid,
                "title": _title_from_messages(msgs),
                "created_at": ts,
                "updated_at": ts,
                "messages": msgs,
            }
        ],
    }


def load_user_record(user_key: str, audience: str | None = None) -> dict[str, Any]:
    path = _chat_path(user_key, audience)
    key = _storage_key(user_key)
    if not path or not os.path.isfile(path):
        return {"user_key": key, "active_id": None, "threads": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("invalid record")
        record = _migrate_legacy(data, user_key)
        threads = []
        for th in record.get("threads") or []:
            if not isinstance(th, dict):
                continue
            tid = str(th.get("id") or "").strip() or str(uuid.uuid4())
            msgs = _clean_messages(th.get("messages") if isinstance(th.get("messages"), list) else [])
            threads.append(
                {
                    "id": tid,
                    "title": str(th.get("title") or _title_from_messages(msgs)),
                    "created_at": th.get("created_at") or _now_iso(),
                    "updated_at": th.get("updated_at") or _now_iso(),
                    "messages": msgs,
                }
            )
        out = {"user_key": key, "active_id": record.get("active_id"), "threads": threads}
        out, removed = _finalize_record(out, user_key=user_key)
        active_id = out.get("active_id")
        if active_id and not any(t["id"] == active_id for t in out["threads"]):
            out["active_id"] = out["threads"][0]["id"] if out["threads"] else None
        if removed > 0:
            _save_record(out, user_key, audience)
        return out
    except Exception as exc:
        try:
            current_app.logger.warning("ai chat load failed | key=%s | %s", user_key, exc)
        except Exception:
            pass
        return {"user_key": key, "active_id": None, "threads": []}


def _save_record(record: dict[str, Any], user_key: str, audience: str | None = None) -> None:
    path = _chat_path(user_key, audience)
    if not path:
        return
    record, _ = _finalize_record(record, user_key=user_key)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        try:
            current_app.logger.error("ai chat save failed | key=%s | %s", user_key, exc)
        except Exception:
            pass


def promote_public_chat_to_partner(user_key: str) -> dict[str, Any]:
    """
    بعد از تأیید بازاریاب: تاریخچهٔ چت public را به partner منتقل/ادغام کن
    تا همان thread با ابزارهای کامل ادامه پیدا کند.
    """
    key = _storage_key(user_key)
    if not key:
        return {"ok": False, "migrated": 0, "error": "invalid_key"}
    pub = load_user_record(user_key, AUDIENCE_PUBLIC)
    pub_threads = [t for t in (pub.get("threads") or []) if isinstance(t, dict)]
    if not pub_threads:
        return {"ok": True, "migrated": 0, "active_id": None}

    part = load_user_record(user_key, AUDIENCE_PARTNER)
    by_id = {
        str(t.get("id") or ""): t
        for t in (part.get("threads") or [])
        if isinstance(t, dict) and str(t.get("id") or "").strip()
    }
    migrated = 0
    for th in pub_threads:
        tid = str(th.get("id") or "").strip()
        if not tid:
            continue
        if tid not in by_id:
            by_id[tid] = dict(th)
            migrated += 1
            continue
        # ادغام پیام‌ها اگر thread از قبل در partner هست
        existing = by_id[tid]
        old_msgs = list(existing.get("messages") or [])
        old_ids = {str(m.get("id") or "") for m in old_msgs if isinstance(m, dict)}
        added = 0
        for m in th.get("messages") or []:
            if not isinstance(m, dict):
                continue
            mid = str(m.get("id") or "")
            if mid and mid in old_ids:
                continue
            old_msgs.append(m)
            if mid:
                old_ids.add(mid)
            added += 1
        if added:
            existing["messages"] = old_msgs[-_MAX_MESSAGES:]
            existing["updated_at"] = th.get("updated_at") or existing.get("updated_at") or _now_iso()
            if th.get("title") and existing.get("title") in (None, "", "گفتگوی جدید"):
                existing["title"] = th.get("title")
            migrated += 1

    threads = list(by_id.values())
    active = str(pub.get("active_id") or "").strip() or str(part.get("active_id") or "").strip()
    if active and not any(str(t.get("id")) == active for t in threads):
        active = str(threads[0].get("id")) if threads else ""
    out = {"user_key": key, "active_id": active or None, "threads": threads}
    _save_record(out, user_key, AUDIENCE_PARTNER)
    return {"ok": True, "migrated": migrated, "active_id": out.get("active_id")}


def _find_thread(record: dict[str, Any], thread_id: str | None) -> dict[str, Any] | None:
    tid = str(thread_id or "").strip()
    if not tid:
        return None
    for th in record.get("threads") or []:
        if th.get("id") == tid:
            return th
    return None


def _active_thread(record: dict[str, Any]) -> dict[str, Any] | None:
    return _find_thread(record, record.get("active_id"))


def consolidate_ai_threads(user_key: str, audience: str | None = None) -> str | None:
    """همهٔ گفتگوهای عادی را در یک ترد «وینور» ادغام کن (پستچی/وکیل جدا می‌مانند).

    پیام‌ها به‌ترتیب زمان در ترد اصلی جمع می‌شوند؛ بقیهٔ تردها حذف می‌شوند.
    """
    record = load_user_record(user_key, audience)
    threads = [t for t in (record.get("threads") or []) if isinstance(t, dict)]
    if not threads:
        return None

    active = str(record.get("active_id") or "").strip()
    # پستچی/وکیل id مصنوعی‌اند و داخل threads نیستند — active را دست نزن
    active_is_special = active.startswith("__") or active in (
        "__postchi__",
        "__lawyer__",
    )
    primary = None if active_is_special else (_find_thread(record, active) if active else None)
    if not primary:
        primary = max(
            threads,
            key=lambda t: (
                str(t.get("updated_at") or t.get("created_at") or ""),
                len(t.get("messages") or []),
            ),
        )

    primary_id = str(primary.get("id") or "").strip()
    if not primary_id:
        return None

    def _commit(primary_th: dict[str, Any], *, force_active: bool) -> None:
        record["threads"] = [primary_th]
        if force_active or not active_is_special:
            record["active_id"] = primary_id
        _save_record(record, user_key, audience)

    if len(threads) == 1:
        changed = False
        if str(primary.get("title") or "").strip() != VINOR_THREAD_TITLE:
            primary["title"] = VINOR_THREAD_TITLE
            changed = True
        if primary.get("kind"):
            primary.pop("kind", None)
            changed = True
        if changed:
            _commit(primary, force_active=False)
        return primary_id

    all_msgs: list[dict[str, Any]] = []
    for th in threads:
        for m in th.get("messages") or []:
            if isinstance(m, dict):
                all_msgs.append(m)
    all_msgs.sort(key=lambda m: str(m.get("created_at") or ""))

    seen_ids: set[str] = set()
    merged: list[dict[str, Any]] = []
    for m in all_msgs:
        mid = str(m.get("id") or "").strip()
        if mid:
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
        merged.append(m)
    if len(merged) > _MAX_MESSAGES:
        merged = merged[-_MAX_MESSAGES:]

    ts = _now_iso()
    primary["messages"] = merged
    primary["title"] = VINOR_THREAD_TITLE
    primary.pop("kind", None)
    primary["updated_at"] = ts
    if not primary.get("created_at"):
        primary["created_at"] = ts

    _commit(primary, force_active=False)
    return primary_id


def create_thread(user_key: str, *, activate: bool = True, audience: str | None = None) -> str:
    """یک گفتگوی وینور — اگر از قبل هست همان را برمی‌گرداند (بدون ساختن ترد جدید)."""
    consolidate_ai_threads(user_key, audience)
    record = load_user_record(user_key, audience)
    threads = list(record.get("threads") or [])
    th = _active_thread(record) or (threads[0] if threads else None)
    if th:
        th["title"] = VINOR_THREAD_TITLE
        th.pop("kind", None)
        if activate:
            record["active_id"] = th["id"]
        _save_record(record, user_key, audience)
        return str(th["id"])

    tid = str(uuid.uuid4())
    ts = _now_iso()
    thread = {
        "id": tid,
        "title": VINOR_THREAD_TITLE,
        "created_at": ts,
        "updated_at": ts,
        "messages": [],
    }
    record["threads"] = [thread]
    if activate:
        record["active_id"] = tid
    _save_record(record, user_key, audience)
    return tid


def _is_welcome_msg(m: Any) -> bool:
    if not isinstance(m, dict):
        return False
    if str(m.get("source") or "").strip().lower() == "welcome":
        return True
    meta = m.get("meta")
    return isinstance(meta, dict) and bool(meta.get("welcome"))


def is_thread_open_slate(th: dict[str, Any] | None) -> bool:
    """ترد خالی یا فقط با پیام شروع وینور — قابل بازنشانی برای گفتگوی جدید."""
    if not th:
        return True
    msgs = [m for m in (th.get("messages") or []) if isinstance(m, dict)]
    if not msgs:
        return True
    return all(_is_welcome_msg(m) for m in msgs)


def guest_new_thread_blocked(user_key: str, audience: str | None = None) -> dict[str, Any] | None:
    """اگر مهمان به سقف گفتگو رسیده و گفتگوی خالی برای بازنشانی ندارد."""
    if not _is_guest_key(user_key):
        return None
    from app.ai.credits import guest_ai_limits_enabled, guest_max_threads

    if not guest_ai_limits_enabled():
        return None
    max_th = guest_max_threads()
    record = load_user_record(user_key, audience)
    threads = list(record.get("threads") or [])
    if len(threads) < max_th:
        return None
    th = _active_thread(record)
    if th and is_thread_open_slate(th):
        return None
    return {
        "ok": False,
        "error": (
            f"بدون ورود حداکثر {max_th} گفتگو مجاز است. برای گفتگوی بیشتر وارد شوید."
        ),
        "need_login": True,
        "login_url": "/express/partner/home?menu=1",
        "thread_limit": max_th,
    }


def clear_chat(
    user_key: str,
    audience: str | None = None,
    *,
    opening_text: str | None = None,
) -> dict[str, Any]:
    """گفتگوی جدید — همان ترد واحد «وینور» را خالی/بازنشانی می‌کند."""
    # قطع ادامهٔ فرم سراسری قدیمی؛ پیش‌نویس تردهای دیگر دست‌نخورده می‌ماند
    try:
        from app.ai.agent_tools import clear_legacy_visit_draft

        clear_legacy_visit_draft(user_key)
    except Exception:
        pass
    try:
        from flask import g

        if hasattr(g, "ai_focus_land_code"):
            g.ai_focus_land_code = ""
    except Exception:
        pass

    consolidate_ai_threads(user_key, audience)
    record = load_user_record(user_key, audience)
    th = _active_thread(record)

    if th and is_thread_open_slate(th):
        ts = _now_iso()
        th["title"] = VINOR_THREAD_TITLE
        th["updated_at"] = ts
        th["messages"] = []
        record["active_id"] = th["id"]
        _save_record(record, user_key, audience)
        tid = str(th["id"])
        _clear_thread_side_state(user_key, tid)
        if opening_text:
            msgs, tid = ensure_vinor_opening(
                user_key,
                opening_text,
                audience=audience,
                thread_id=tid,
            )
            return {"ok": True, "thread_id": tid, "messages": msgs}
        return {"ok": True, "thread_id": tid}

    # تک‌ترد: حتی اگر پر باشد همان را خالی کن (مهمان هم اجازهٔ ریست دارد)
    if not th:
        tid = create_thread(user_key, activate=True, audience=audience)
        record = load_user_record(user_key, audience)
        th = _find_thread(record, tid)
    assert th is not None
    tid = str(th["id"])
    ts = _now_iso()
    th["title"] = VINOR_THREAD_TITLE
    th["updated_at"] = ts
    th["messages"] = []
    th.pop("kind", None)
    record["active_id"] = tid
    record["threads"] = [th]
    _save_record(record, user_key, audience)
    _clear_thread_side_state(user_key, tid)
    if opening_text:
        msgs, tid = ensure_vinor_opening(
            user_key,
            opening_text,
            audience=audience,
            thread_id=tid,
        )
        return {"ok": True, "thread_id": tid, "messages": msgs}
    return {"ok": True, "thread_id": tid}


def _clear_thread_side_state(user_key: str, thread_id: str | None) -> None:
    """پاک‌کردن وضعیت فرم گفتگو برای ترد (موتور conversation)."""
    tid = str(thread_id or "").strip()
    try:
        from app.conversation.session import FileConversationSessionStore

        store = FileConversationSessionStore()
        store.clear(user_key)  # سراسری قدیمی
        if tid:
            store.clear(user_key, thread_id=tid)
    except Exception:
        pass
    try:
        from app.ai.agent_tools import clear_lead_draft, clear_visit_draft

        clear_visit_draft(user_key, thread_id=tid or None)
        clear_lead_draft(user_key, thread_id=tid or None)
    except Exception:
        pass


def ensure_vinor_opening(
    user_key: str,
    text: str,
    *,
    audience: str | None = None,
    thread_id: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """وینور شروع‌کنندهٔ چت: اگر ترد بدون گفتگوی واقعی است، پیام اول را بگذار."""
    body = (text or "").strip()[:_MAX_CONTENT]
    if not body:
        tid = thread_id or ensure_active_thread(user_key, audience=audience)
        return messages_for_ui(user_key, thread_id=tid, audience=audience), tid

    record = load_user_record(user_key, audience)
    tid = (thread_id or record.get("active_id") or "").strip()
    th = _find_thread(record, tid) if tid else _active_thread(record)
    if not th:
        tid = create_thread(user_key, activate=True, audience=audience)
        record = load_user_record(user_key, audience)
        th = _find_thread(record, tid)
    assert th is not None
    tid = str(th["id"])

    msgs = [m for m in (th.get("messages") or []) if isinstance(m, dict)]
    if msgs and not is_thread_open_slate(th):
        return _enrich_messages_for_ui(user_key, list(th.get("messages") or []), audience), tid
    if msgs and all(_is_welcome_msg(m) for m in msgs):
        return _enrich_messages_for_ui(user_key, list(th.get("messages") or []), audience), tid

    ts = _now_iso()
    entry: dict[str, Any] = {
        "id": _new_message_id(),
        "role": "assistant",
        "type": "ai",
        "content": body,
        "created_at": ts,
        "source": "welcome",
        "quota": False,
        "meta": {"welcome": True},
    }
    th["messages"] = [entry]
    th["updated_at"] = ts
    th["title"] = VINOR_THREAD_TITLE
    record["active_id"] = tid
    _save_record(record, user_key, audience)
    return _enrich_messages_for_ui(user_key, th["messages"], audience), tid


def set_active_thread(user_key: str, thread_id: str, audience: str | None = None) -> bool:
    record = load_user_record(user_key, audience)
    if not _find_thread(record, thread_id):
        return False
    record["active_id"] = thread_id
    _save_record(record, user_key, audience)
    return True


def ensure_active_thread(user_key: str, audience: str | None = None) -> str:
    consolidate_ai_threads(user_key, audience)
    record = load_user_record(user_key, audience)
    th = _active_thread(record)
    if th:
        return str(th["id"])
    return create_thread(user_key, activate=True, audience=audience)


def count_assistant_replies(user_key: str, audience: str | None = None) -> int:
    """تعداد پاسخ‌های قابل‌شمارش assistant برای سقف رایگان مهمان."""
    record = load_user_record(user_key, audience)
    total = 0
    for th in record.get("threads") or []:
        for m in th.get("messages") or []:
            if _counts_toward_guest_quota(m):
                total += 1
    return total


def _counts_toward_guest_quota(m: Any) -> bool:
    """فقط پاسخ‌های چت AI — نه پستچی/ادمین و نه پیام خالی."""
    if not isinstance(m, dict):
        return False
    if str(m.get("role") or "") != "assistant":
        return False
    if m.get("quota") is False:
        return False
    source = str(m.get("source") or "").strip().lower()
    if source in ("admin_escalation", "postchi", "system", "welcome", LAND_DETAIL_SOURCE):
        return False
    mtype = str(m.get("type") or "").strip().lower()
    if mtype in ("system", "timeline", "admin", "progress", "status", "warning", "error"):
        return False
    content = str(m.get("content") or "").strip()
    actions = m.get("agent_actions") or m.get("land_codes") or []
    if not content and not actions:
        return False
    return True


def threads_for_ui(user_key: str, audience: str | None = None) -> list[dict[str, Any]]:
    consolidate_ai_threads(user_key, audience)
    record = load_user_record(user_key, audience)
    active = record.get("active_id")
    thread_rows = list(record.get("threads") or [])
    # تک‌ترد وینور — حداکثر یک آیتم در لیست
    th = _active_thread(record) or (thread_rows[0] if thread_rows else None)
    thread_rows = [th] if th else []
    out: list[dict[str, Any]] = []
    for th in thread_rows:
        msgs = th.get("messages") or []
        preview = ""
        for m in reversed(msgs):
            if not isinstance(m, dict):
                continue
            if m.get("role") == "user":
                preview = str(m.get("content") or "")[:_MAX_PREVIEW]
                break
            if str(m.get("source") or "") == LAND_DETAIL_SOURCE and not preview:
                preview = str(m.get("content") or "")[:_MAX_PREVIEW]
        out.append(
            {
                "id": th.get("id"),
                "title": VINOR_THREAD_TITLE,
                "preview": preview,
                "updated_at": th.get("updated_at"),
                "created_at": th.get("created_at"),
                "message_count": len(msgs),
                "is_active": th.get("id") == active,
                "kind": "vinor",
            }
        )
    if not out:
        # منوی ساید همیشه یک آیتم «وینور» دارد — حتی قبل از شروع مکالمه
        out.append(
            {
                "id": active or "",
                "title": VINOR_THREAD_TITLE,
                "preview": "",
                "updated_at": "",
                "created_at": "",
                "message_count": 0,
                "is_active": True,
                "kind": "vinor",
            }
        )
    return out


def messages_for_api(
    user_key: str,
    thread_id: str | None = None,
    audience: str | None = None,
) -> list[dict[str, str]]:
    """پیام‌های خام برای مدل — بدون رندر کارت (سبک‌تر)."""
    record = load_user_record(user_key, audience)
    th = _find_thread(record, thread_id) if thread_id else _active_thread(record)
    if not th:
        return []
    out: list[dict[str, str]] = []
    for item in th.get("messages") or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if str(item.get("source") or "").strip().lower() == LAND_DETAIL_SOURCE:
            continue
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out


def messages_for_ui(
    user_key: str,
    thread_id: str | None = None,
    audience: str | None = None,
) -> list[dict[str, Any]]:
    record = load_user_record(user_key, audience)
    th = _find_thread(record, thread_id) if thread_id else _active_thread(record)
    if not th:
        return []
    return _enrich_messages_for_ui(user_key, list(th.get("messages") or []), audience)


def _collapse_duplicate_land_detail_messages(
    messages: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """در نمایش چت، برای هر فایل فقط آخرین کارت جزئیات را نگه دار."""
    rows = [m for m in (messages or []) if isinstance(m, dict)]
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in reversed(rows):
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        is_land = (
            str(item.get("source") or "").strip().lower() == LAND_DETAIL_SOURCE
            or bool(meta.get("land_chat_detail"))
        )
        if is_land:
            codes = item.get("land_codes") or []
            code = str(
                (codes[0] if codes else "") or meta.get("land_code") or ""
            ).strip()
            if code:
                if code in seen:
                    continue
                seen.add(code)
        out.append(item)
    out.reverse()
    return out


def _enrich_messages_for_ui(
    user_key: str,
    messages: list[dict[str, Any]],
    audience: str | None = None,
) -> list[dict[str, Any]]:
    from app.ai.agent_tools import render_agent_actions_html
    from app.ai.audience import AUDIENCE_ADMIN
    from app.ai.land_cards import land_cards_payload

    aud = (audience or "").strip().lower()
    rows = _collapse_duplicate_land_detail_messages(messages)
    out: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        is_land_detail = (
            str(row.get("source") or "").strip().lower() == LAND_DETAIL_SOURCE
            or bool(meta.get("land_chat_detail"))
        )
        if is_land_detail:
            codes = row.get("land_codes") or []
            code = str(
                (codes[0] if codes else "") or meta.get("land_code") or ""
            ).strip()
            if code:
                try:
                    from app.express_partner.land_chat_detail import (
                        render_land_chat_detail_html,
                    )

                    payload = render_land_chat_detail_html(code)
                    if payload and payload.get("html"):
                        row["land_detail_html"] = payload["html"]
                        row["land_code"] = str(payload.get("code") or code).strip()
                        row["content"] = ""
                except Exception:
                    pass
            out.append(row)
            continue
        # پیام‌های قدیمی ناظر با متن فنی (مثل workflow_complete:VisitRequest)
        if str(row.get("source") or "") == "supervisor_agent":
            try:
                from app.supervisor_agent.renderer import humanize_supervisor_message_content

                meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
                land = ""
                if meta.get("land_code"):
                    land = str(meta.get("land_code") or "")
                elif row.get("land_codes"):
                    land = str((row.get("land_codes") or [""])[0] or "")
                human = humanize_supervisor_message_content(
                    str(row.get("content") or ""),
                    land_code=land,
                    meta=meta,
                )
                if human:
                    row["content"] = human
                # برچسب لینک ملک اگر خام بود — بدون نشان دادن کد خام
                if land and meta.get("entity_label") == land:
                    meta = dict(meta)
                    meta["entity_label"] = "مشاهده فایل"
                    row["meta"] = meta
                if land and not row.get("land_codes"):
                    row["land_codes"] = [land]
            except Exception:
                pass
        codes = row.get("land_codes") or []
        if str(row.get("source") or "") == "supervisor_agent" and codes and row.get("content"):
            try:
                from app.ai.land_cards import strip_visible_land_codes

                row["content"] = strip_visible_land_codes(str(row.get("content") or ""), codes)
            except Exception:
                pass
        actions = row.get("agent_actions") or []
        # ادمین: کارت فایل فقط با meta.show_land_cards؛ کارت تأیید اکشن می‌ماند
        show_land = aud != AUDIENCE_ADMIN or bool(
            (row.get("meta") or {}).get("show_land_cards")
            if isinstance(row.get("meta"), dict)
            else False
        )
        # وقتی کارت فایل هست، کد خام را از متن قابل‌نمایش بردار
        if row.get("role") == "assistant" and codes and show_land and row.get("content"):
            try:
                from app.ai.land_cards import strip_visible_land_codes

                row["content"] = strip_visible_land_codes(str(row.get("content") or ""), codes)
            except Exception:
                pass
        # اکشن‌های confirm با land_code هم کارت فایل می‌گیرند
        action_land_codes: list[str] = []
        if isinstance(actions, list):
            for a in actions:
                if isinstance(a, dict):
                    ac = str(a.get("land_code") or "").strip()
                    if ac and ac not in action_land_codes:
                        action_land_codes.append(ac)
        if row.get("role") == "assistant" and ((codes and show_land) or actions):
            parts: list[str] = []
            # کارت‌های جدا فقط برای land_codes پیام؛ confirm خودش کارت را داخل دارد
            show_codes = [c for c in codes if str(c).strip() and str(c).strip() not in action_land_codes]
            if show_codes and show_land:
                try:
                    from app.ai.land_cards import render_land_cards_html

                    row["land_cards"] = land_cards_payload(user_key, show_codes, audience=audience)
                    land_html = render_land_cards_html(user_key, show_codes, audience=audience) or ""
                    if land_html:
                        parts.append(land_html)
                except Exception:
                    row.pop("land_cards", None)
            elif codes and not show_land:
                row.pop("land_cards", None)
            if isinstance(actions, list) and actions:
                try:
                    actions_html = render_agent_actions_html(
                        actions, phone=user_key, audience=audience
                    ) or ""
                    if actions_html:
                        parts.append(actions_html)
                except Exception:
                    pass
            # فایل + تأیید + کپی + ماموریت — همه داخل نخ گفتگو
            row["cards_html"] = "".join(parts)
        out.append(row)
    return out


def history_for_api(
    user_key: str,
    thread_id: str | None = None,
    audience: str | None = None,
) -> list[dict[str, str]]:
    return messages_for_api(user_key, thread_id, audience)


def recent_thread_land_codes(
    user_key: str,
    thread_id: str | None = None,
    audience: str | None = None,
    *,
    limit: int = 5,
) -> list[str]:
    """کد فایل‌هایی که اخیراً به‌صورت کارت روی همین گفتگو آمده‌اند (جدیدترین اول)."""
    record = load_user_record(user_key, audience)
    th = _find_thread(record, thread_id) if thread_id else _active_thread(record)
    if not th:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in reversed(list(th.get("messages") or [])):
        if not isinstance(item, dict):
            continue
        if str(item.get("role") or "") != "assistant":
            continue
        codes = list(item.get("land_codes") or [])
        for action in item.get("agent_actions") or []:
            if isinstance(action, dict):
                ac = str(action.get("land_code") or "").strip()
                if ac:
                    codes.append(ac)
        for raw in codes:
            code = str(raw or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            out.append(code)
            if len(out) >= max(1, int(limit or 5)):
                return out
    return out


def append_exchange(
    user_key: str,
    user_text: str,
    assistant_text: str,
    *,
    thread_id: str | None = None,
    assistant_land_codes: list[str] | None = None,
    assistant_agent_actions: list[dict[str, Any]] | None = None,
    audience: str | None = None,
    hide_user: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    from app.ai.message_types import MSG_AI, MSG_CARD, MSG_TEXT

    record = load_user_record(user_key, audience)
    tid = thread_id or record.get("active_id") or ""
    th = _find_thread(record, tid) if tid else _active_thread(record)
    if not th:
        tid = create_thread(user_key, activate=True, audience=audience)
        record = load_user_record(user_key, audience)
        th = _find_thread(record, tid)
    assert th is not None
    tid = str(th["id"])

    msgs: list[dict[str, Any]] = list(th.get("messages") or [])
    ts = _now_iso()
    user_text = (user_text or "").strip()[:_MAX_CONTENT]
    assistant_text = (assistant_text or "").strip()[:_MAX_CONTENT]
    actions = _normalize_actions(assistant_agent_actions)
    codes = [str(c).strip() for c in (assistant_land_codes or []) if str(c).strip()][:5]
    if user_text:
        user_entry: dict[str, Any] = {
            "id": _new_message_id(),
            "role": "user",
            "type": MSG_TEXT,
            "content": user_text,
            "created_at": ts,
        }
        if hide_user:
            user_entry["hide_ui"] = True
        msgs.append(user_entry)
        if th.get("title") in (None, "", "گفتگوی جدید", VINOR_THREAD_TITLE) and len(msgs) == 1:
            if str(th.get("kind") or "") == "lawyer" or tid == "__lawyer__":
                th["title"] = "وکیل ملکی"
                th["kind"] = "lawyer"
            else:
                th["title"] = VINOR_THREAD_TITLE
    if assistant_text or actions or codes:
        msg_type = MSG_CARD if actions else MSG_AI
        entry: dict[str, Any] = {
            "id": _new_message_id(),
            "role": "assistant",
            "type": msg_type,
            "content": assistant_text or "جزئیات را در کارت زیر بررسی کنید.",
            "created_at": ts,
            "quota": True,
        }
        if codes:
            entry["land_codes"] = codes
            # ادمین: فقط وقتی land_codes عمداً پاس شده (show_cards) کارت نشان بده
            if (audience or "").strip().lower() == "admin":
                entry["meta"] = {"show_land_cards": True}
        if actions:
            entry["agent_actions"] = actions
        msgs.append(entry)
    th["messages"] = msgs[-_MAX_MESSAGES:]
    th["updated_at"] = ts
    record["active_id"] = tid
    _save_record(record, user_key, audience)
    # Soft-link Case to thread (non-fatal)
    try:
        from app.ai.case_store import ensure_case_for_thread

        land = codes[0] if codes else ""
        for a in actions:
            if not land and isinstance(a, dict):
                land = str(a.get("land_code") or "").strip()
        ensure_case_for_thread(
            user_key,
            tid,
            audience=audience,
            land_code=land,
            title=str(th.get("title") or ""),
        )
    except Exception:
        pass
    return _enrich_messages_for_ui(user_key, th["messages"], audience), tid


def append_typed_message(
    user_key: str,
    text: str,
    *,
    thread_id: str | None = None,
    audience: str | None = None,
    msg_type: str = "system",
    source: str = "system",
    land_codes: list[str] | None = None,
    agent_actions: list[dict[str, Any]] | None = None,
    event: str = "",
    meta: dict[str, Any] | None = None,
    quota: bool = False,
    escalation_id: str = "",
) -> tuple[list[dict[str, Any]], str]:
    """Append a single assistant-side typed message (system / timeline / …)."""
    from app.ai.message_types import normalize_message_type

    record = load_user_record(user_key, audience)
    tid = thread_id or record.get("active_id") or ""
    th = _find_thread(record, tid) if tid else _active_thread(record)
    if not th:
        tid = create_thread(user_key, activate=True, audience=audience)
        record = load_user_record(user_key, audience)
        th = _find_thread(record, tid)
    assert th is not None
    tid = str(th["id"])

    body = (text or "").strip()[:_MAX_CONTENT]
    actions = _normalize_actions(agent_actions)
    codes = [str(c).strip() for c in (land_codes or []) if str(c).strip()][:5]
    if not body and not actions and not codes:
        return _enrich_messages_for_ui(user_key, list(th.get("messages") or []), audience), tid

    eid = (escalation_id or "").strip()
    if eid:
        for item in th.get("messages") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("escalation_id") or "") == eid:
                return _enrich_messages_for_ui(user_key, list(th.get("messages") or []), audience), tid

    ts = _now_iso()
    entry: dict[str, Any] = {
        "id": _new_message_id(),
        "role": "assistant",
        "type": normalize_message_type(msg_type, role="assistant", source=source),
        "content": body or "—",
        "created_at": ts,
        "source": str(source or "system"),
        "quota": bool(quota),
    }
    if event:
        entry["event"] = str(event)
    if meta:
        entry["meta"] = dict(meta)
    if eid:
        entry["escalation_id"] = eid
    if codes:
        entry["land_codes"] = codes
    if actions:
        entry["agent_actions"] = actions

    msgs = list(th.get("messages") or [])
    msgs.append(entry)
    th["messages"] = msgs[-_MAX_MESSAGES:]
    th["updated_at"] = ts
    record["active_id"] = tid
    _save_record(record, user_key, audience)
    return _enrich_messages_for_ui(user_key, th["messages"], audience), tid


def record_land_chat_view(
    user_key: str,
    land_code: str,
    *,
    audience: str | None = None,
    title: str = "",
    thread_id: str | None = None,
) -> str | None:
    """نمایش جزئیات فایل در چت را در همان ترد وینور ذخیره کن تا در منوی ساید بماند."""
    code = str(land_code or "").strip()
    if not (user_key or "").strip() or not code:
        return None
    tid = (thread_id or "").strip() or ensure_active_thread(user_key, audience=audience)
    record = load_user_record(user_key, audience)
    th = _find_thread(record, tid) if tid else _active_thread(record)
    if not th:
        tid = ensure_active_thread(user_key, audience=audience)
        record = load_user_record(user_key, audience)
        th = _find_thread(record, tid)
    if not th:
        return None
    tid = str(th.get("id") or tid)
    for item in list(th.get("messages") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("source") or "").strip().lower() != LAND_DETAIL_SOURCE:
            continue
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        codes = item.get("land_codes") or []
        last = str(
            (codes[0] if codes else "") or meta.get("land_code") or ""
        ).strip()
        if last == code:
            return tid
    label = str(title or "").strip()
    body = f"جزئیات فایل {code}"
    if label:
        body = f"{body} — {label}"
    _, tid = append_typed_message(
        user_key,
        body,
        thread_id=tid,
        audience=audience,
        msg_type="card",
        source=LAND_DETAIL_SOURCE,
        land_codes=[code],
        meta={"land_chat_detail": True, "land_code": code},
        quota=False,
    )
    return tid


def update_agent_action_by_token(
    user_key: str,
    token: str,
    *,
    thread_id: str | None = None,
    audience: str | None = None,
    new_state: str,
    event: str = "",
    result: dict[str, Any] | None = None,
    lines: list[str] | None = None,
    note: str = "",
    actor: str = "",
) -> tuple[bool, list[dict[str, Any]], str]:
    """Update a living card in-place by token (or card_id if passed as token)."""
    from app.ai.card_registry import apply_card_transition

    tok = (token or "").strip()
    if not tok:
        return False, [], ""

    record = load_user_record(user_key, audience)
    tid = (thread_id or "").strip() or str(record.get("active_id") or "")
    threads = list(record.get("threads") or [])
    # Prefer active thread, then scan all (card may be in mission thread)
    order: list[dict[str, Any]] = []
    primary = _find_thread(record, tid) if tid else _active_thread(record)
    if primary:
        order.append(primary)
    for th in threads:
        if primary and th.get("id") == primary.get("id"):
            continue
        order.append(th)

    found = False
    out_tid = tid
    for th in order:
        msgs = list(th.get("messages") or [])
        changed = False
        for msg in msgs:
            if not isinstance(msg, dict):
                continue
            actions = msg.get("agent_actions")
            if not isinstance(actions, list):
                continue
            new_actions: list[dict[str, Any]] = []
            for action in actions:
                if not isinstance(action, dict):
                    continue
                match = (
                    str(action.get("token") or "") == tok
                    or str(action.get("card_id") or "") == tok
                )
                if match:
                    new_actions.append(
                        apply_card_transition(
                            action,
                            new_state,
                            event=event,
                            result=result,
                            lines=lines,
                            note=note,
                            actor=actor,
                        )
                    )
                    found = True
                    changed = True
                else:
                    new_actions.append(action)
            if changed:
                msg["agent_actions"] = new_actions
                msg["updated_at"] = _now_iso()
        if changed:
            th["messages"] = msgs
            th["updated_at"] = _now_iso()
            out_tid = str(th.get("id") or out_tid)
            break

    if not found:
        return False, [], out_tid

    record["active_id"] = out_tid or record.get("active_id")
    _save_record(record, user_key, audience)
    ui = messages_for_ui(user_key, out_tid, audience)
    return True, ui, out_tid


def inject_admin_reply(
    user_key: str,
    answer: str,
    *,
    thread_id: str | None = None,
    audience: str | None = None,
    question: str = "",
    escalation_id: str = "",
) -> bool:
    """درج پاسخ تیم وینور در همان گفتگو — بلافاصله قابل نمایش در چت."""
    text = (answer or "").strip()
    if not text:
        return False

    record = load_user_record(user_key, audience)
    tid = (thread_id or "").strip() or str(record.get("active_id") or "").strip()
    th = _find_thread(record, tid) if tid else _active_thread(record)
    if not th and tid:
        ts = _now_iso()
        th = {
            "id": tid,
            "title": "گفتگوی پشتیبانی",
            "created_at": ts,
            "updated_at": ts,
            "messages": [],
        }
        record["threads"] = [th] + list(record.get("threads") or [])
        record["active_id"] = tid
        _save_record(record, user_key, audience)
        record = load_user_record(user_key, audience)
        th = _find_thread(record, tid)
    if not th:
        tid = ensure_active_thread(user_key, audience)
        record = load_user_record(user_key, audience)
        th = _find_thread(record, tid)
    if not th:
        return False

    eid = (escalation_id or "").strip()
    for item in th.get("messages") or []:
        if not isinstance(item, dict):
            continue
        if eid and str(item.get("escalation_id") or "") == eid:
            return True

    q = (question or "").strip()
    intro = "پاسخ تیم وینور"
    if q:
        intro += f" (در پاسخ به: {q[:120]}{'…' if len(q) > 120 else ''})"
    body = f"{intro}:\n\n{text}"

    for item in th.get("messages") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("source") or "") != "admin_escalation":
            continue
        existing = str(item.get("content") or "").strip()
        if existing == body.strip():
            return True

    from app.ai.message_types import MSG_ADMIN

    ts = _now_iso()
    entry: dict[str, Any] = {
        "id": _new_message_id(),
        "role": "assistant",
        "type": MSG_ADMIN,
        "content": body[:_MAX_CONTENT],
        "created_at": ts,
        "source": "admin_escalation",
        "event": "admin_replied",
        "quota": False,
    }
    if eid:
        entry["escalation_id"] = eid

    msgs = list(th.get("messages") or [])
    msgs.append(entry)
    th["messages"] = msgs[-_MAX_MESSAGES:]
    th["updated_at"] = ts
    record["active_id"] = str(th["id"])
    _save_record(record, user_key, audience)
    try:
        from app.ai.case_store import append_case_timeline

        append_case_timeline(
            user_key,
            str(th["id"]),
            audience=audience,
            event="admin_replied",
            label="پاسخ تیم وینور ثبت شد",
        )
    except Exception:
        pass
    return True


def messages_since(
    user_key: str,
    thread_id: str | None,
    after_iso: str = "",
    audience: str | None = None,
    *,
    after_count: int = 0,
    exclude_escalation_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """پیام‌های جدید گفتگوی فعال — برای polling (پاسخ ادمین + پیام‌های بعدی)."""
    all_msgs = messages_for_ui(user_key, thread_id, audience)
    if not all_msgs:
        return []

    exclude = {str(x).strip() for x in (exclude_escalation_ids or []) if str(x).strip()}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    included_esc: set[str] = set()

    def _push(item: dict[str, Any]) -> None:
        eid = str(item.get("escalation_id") or "").strip()
        ts = str(item.get("created_at") or "").strip()
        role = str(item.get("role") or "").strip()
        key = eid or (f"{role}:{ts}" if role and ts else ts) or str(item.get("content") or "")[:80]
        if key in seen:
            return
        seen.add(key)
        if eid:
            included_esc.add(eid)
        out.append(item)

    # برش بر اساس تعداد پیام‌های ذخیره‌شده در کلاینت (قابل‌اعتمادتر از timestamp)
    if after_count > 0:
        if after_count < len(all_msgs):
            for item in all_msgs[after_count:]:
                _push(item)
    else:
        after = (after_iso or "").strip()
        if after:
            for item in all_msgs:
                ts = str(item.get("created_at") or "")
                if ts > after:
                    _push(item)

    # پاسخ ادمین ممکن است timestamp قدیمی‌تر از آخرین پیام کاربر داشته باشد — فقط موارد جدید
    for item in all_msgs:
        if str(item.get("source") or "") != "admin_escalation":
            continue
        eid = str(item.get("escalation_id") or "").strip()
        if eid and eid in exclude:
            continue
        if eid and eid in included_esc:
            continue
        _push(item)

    out.sort(key=lambda x: str(x.get("created_at") or ""))
    return out


def delete_thread(user_key: str, thread_id: str, audience: str | None = None) -> bool:
    if _is_guest_key(user_key):
        from app.ai.credits import guest_ai_limits_enabled

        if guest_ai_limits_enabled():
            return False
    record = load_user_record(user_key, audience)
    before = len(record.get("threads") or [])
    record["threads"] = [t for t in (record.get("threads") or []) if t.get("id") != thread_id]
    if len(record["threads"]) == before:
        return False
    if not record["threads"]:
        tid = str(uuid.uuid4())
        ts = _now_iso()
        record["threads"] = [
            {
                "id": tid,
                "title": VINOR_THREAD_TITLE,
                "created_at": ts,
                "updated_at": ts,
                "messages": [],
            }
        ]
        record["active_id"] = tid
    else:
        record, _ = _finalize_record(record)
        if record.get("active_id") == thread_id:
            record["active_id"] = record["threads"][0]["id"] if record["threads"] else None
        # پس از حذف، بقیه را در یک وینور ادغام کن
        _save_record(record, user_key, audience)
        consolidate_ai_threads(user_key, audience)
        return True
    _save_record(record, user_key, audience)
    return True
