"""ذخیره تاریخچه چت Vinor AI — جدا برای همکار و کاربر عادی."""
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

_MAX_MESSAGES = 80
_MAX_THREADS = 30
_GUEST_MAX_THREADS = 2
_MAX_CONTENT = 4000
_TITLE_LEN = 48
_MAX_PREVIEW = 80


def _is_guest_key(user_key: str) -> bool:
    return str(user_key or "").startswith("guest_")


def _thread_limit(user_key: str) -> int:
    return _GUEST_MAX_THREADS if _is_guest_key(user_key) else _MAX_THREADS


def _chats_dir() -> str:
    path = ai_data_file("ai_chats")
    os.makedirs(path, exist_ok=True)
    return path


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


def _clean_messages(raw: list) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()[:_MAX_CONTENT]
        if role in ("user", "assistant") and content:
            row: dict[str, Any] = {
                "role": role,
                "content": content,
                "created_at": item.get("created_at") or _now_iso(),
            }
            if item.get("source"):
                row["source"] = str(item.get("source"))
            if item.get("escalation_id"):
                row["escalation_id"] = str(item.get("escalation_id"))
            codes = item.get("land_codes")
            if isinstance(codes, list) and codes:
                row["land_codes"] = [str(c).strip() for c in codes if str(c).strip()][:5]
            actions = item.get("agent_actions")
            if isinstance(actions, list) and actions:
                cleaned_actions = [a for a in actions if isinstance(a, dict)][:5]
                if cleaned_actions:
                    row["agent_actions"] = cleaned_actions
            if item.get("hide_ui") or item.get("hide_user"):
                row["hide_ui"] = True
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


def create_thread(user_key: str, *, activate: bool = True, audience: str | None = None) -> str:
    record = load_user_record(user_key, audience)
    limit = _thread_limit(user_key)
    threads = list(record.get("threads") or [])
    if len(threads) >= limit:
        # سقف پر است — گفتگوی جدید نساز (مهمان: ۲)
        th = _active_thread(record) or (threads[0] if threads else None)
        if th:
            if activate:
                record["active_id"] = th["id"]
                _save_record(record, user_key, audience)
            return str(th["id"])
    tid = str(uuid.uuid4())
    ts = _now_iso()
    thread = {
        "id": tid,
        "title": "گفتگوی جدید",
        "created_at": ts,
        "updated_at": ts,
        "messages": [],
    }
    record["threads"] = [thread] + threads
    if activate:
        record["active_id"] = tid
    _save_record(record, user_key, audience)
    return tid


def guest_new_thread_blocked(user_key: str, audience: str | None = None) -> dict[str, Any] | None:
    """اگر مهمان به سقف ۲ گفتگو رسیده و گفتگوی خالی برای بازنشانی ندارد."""
    if not _is_guest_key(user_key):
        return None
    record = load_user_record(user_key, audience)
    threads = list(record.get("threads") or [])
    if len(threads) < _GUEST_MAX_THREADS:
        return None
    th = _active_thread(record)
    if th and not (th.get("messages") or []):
        return None
    return {
        "ok": False,
        "error": "بدون ورود حداکثر ۲ گفتگو مجاز است. برای گفتگوی بیشتر وارد شوید.",
        "need_login": True,
        "login_url": "/express/partner/home?menu=1",
        "thread_limit": _GUEST_MAX_THREADS,
    }


def clear_chat(user_key: str, audience: str | None = None) -> dict[str, Any]:
    """گفتگوی جدید — اگر گفتگوی فعال خالی است همان را بازنشانی می‌کند."""
    record = load_user_record(user_key, audience)
    th = _active_thread(record)
    if th and not (th.get("messages") or []):
        ts = _now_iso()
        th["title"] = "گفتگوی جدید"
        th["updated_at"] = ts
        record["active_id"] = th["id"]
        _save_record(record, user_key, audience)
        return {"ok": True, "thread_id": str(th["id"])}

    blocked = guest_new_thread_blocked(user_key, audience)
    if blocked:
        return blocked

    tid = create_thread(user_key, activate=True, audience=audience)
    return {"ok": True, "thread_id": tid}


def set_active_thread(user_key: str, thread_id: str, audience: str | None = None) -> bool:
    record = load_user_record(user_key, audience)
    if not _find_thread(record, thread_id):
        return False
    record["active_id"] = thread_id
    _save_record(record, user_key, audience)
    return True


def ensure_active_thread(user_key: str, audience: str | None = None) -> str:
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
    if source in ("admin_escalation", "postchi"):
        return False
    content = str(m.get("content") or "").strip()
    actions = m.get("agent_actions") or m.get("land_codes") or []
    if not content and not actions:
        return False
    return True


def threads_for_ui(user_key: str, audience: str | None = None) -> list[dict[str, Any]]:
    record = load_user_record(user_key, audience)
    active = record.get("active_id")
    out: list[dict[str, Any]] = []
    for th in record.get("threads") or []:
        msgs = th.get("messages") or []
        preview = ""
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("role") == "user":
                preview = str(m.get("content") or "")[:_MAX_PREVIEW]
                break
        out.append(
            {
                "id": th.get("id"),
                "title": th.get("title") or "گفتگو",
                "preview": preview,
                "updated_at": th.get("updated_at"),
                "created_at": th.get("created_at"),
                "message_count": len(msgs),
                "is_active": th.get("id") == active,
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


def _enrich_messages_for_ui(
    user_key: str,
    messages: list[dict[str, Any]],
    audience: str | None = None,
) -> list[dict[str, Any]]:
    from app.ai.agent_tools import render_agent_actions_html
    from app.ai.land_cards import land_cards_payload

    out: list[dict[str, Any]] = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        codes = row.get("land_codes") or []
        actions = row.get("agent_actions") or []
        if row.get("role") == "assistant" and (codes or actions):
            try:
                if codes:
                    row["land_cards"] = land_cards_payload(user_key, codes, audience=audience)
                actions_html = ""
                if isinstance(actions, list) and actions:
                    actions_html = render_agent_actions_html(actions) or ""
                # فقط کارت اکشن در چت؛ فایل‌ها فقط در land_cards → نوار بالای خانه
                row["cards_html"] = actions_html or ""
            except Exception:
                row["cards_html"] = ""
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
    if user_text:
        user_entry: dict[str, Any] = {
            "role": "user",
            "content": user_text,
            "created_at": ts,
        }
        if hide_user:
            user_entry["hide_ui"] = True
        msgs.append(user_entry)
        if th.get("title") in (None, "", "گفتگوی جدید") and len(msgs) == 1:
            if not hide_user:
                th["title"] = _title_from_text(user_text)
            else:
                th["title"] = "گفتگوی مأموریت"
    if assistant_text or assistant_agent_actions:
        entry: dict[str, Any] = {
            "role": "assistant",
            "content": assistant_text or "جزئیات را در کارت زیر بررسی کنید.",
            "created_at": ts,
            "quota": True,
        }
        codes = [str(c).strip() for c in (assistant_land_codes or []) if str(c).strip()]
        if codes:
            entry["land_codes"] = codes[:5]
        actions = [a for a in (assistant_agent_actions or []) if isinstance(a, dict)][:5]
        if actions:
            entry["agent_actions"] = actions
        msgs.append(entry)
    th["messages"] = msgs[-_MAX_MESSAGES:]
    th["updated_at"] = ts
    record["active_id"] = tid
    _save_record(record, user_key, audience)
    return _enrich_messages_for_ui(user_key, th["messages"], audience), tid


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

    ts = _now_iso()
    entry: dict[str, Any] = {
        "role": "assistant",
        "content": body[:_MAX_CONTENT],
        "created_at": ts,
        "source": "admin_escalation",
    }
    if eid:
        entry["escalation_id"] = eid

    msgs = list(th.get("messages") or [])
    msgs.append(entry)
    th["messages"] = msgs[-_MAX_MESSAGES:]
    th["updated_at"] = ts
    record["active_id"] = str(th["id"])
    _save_record(record, user_key, audience)
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
                "title": "گفتگوی جدید",
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
    _save_record(record, user_key, audience)
    return True
