"""ذخیره تاریخچه چت Vinor AI — چند گفتگو به ازای هر شماره موبایل."""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from flask import current_app

_MAX_MESSAGES = 80
_MAX_THREADS = 30
_MAX_CONTENT = 4000
_TITLE_LEN = 48


def _chats_dir() -> str:
    try:
        base = current_app.instance_path
    except Exception:
        base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "instance",
        )
    path = os.path.join(base, "data", "ai_chats")
    os.makedirs(path, exist_ok=True)
    return path


def _phone_key(phone: str) -> str:
    digits = re.sub(r"\D+", "", str(phone or ""))
    if not digits:
        return ""
    return digits[-11:] if len(digits) >= 11 else digits


def _chat_path(phone: str) -> str | None:
    key = _phone_key(phone)
    if not key:
        return None
    return os.path.join(_chats_dir(), f"{key}.json")


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


def _clean_messages(raw: list) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()[:_MAX_CONTENT]
        if role in ("user", "assistant") and content:
            cleaned.append(
                {
                    "role": role,
                    "content": content,
                    "created_at": item.get("created_at") or _now_iso(),
                }
            )
    return cleaned[-_MAX_MESSAGES:]


def _migrate_legacy(data: dict[str, Any], phone: str) -> dict[str, Any]:
    if isinstance(data.get("threads"), list):
        return data
    msgs = _clean_messages(data.get("messages") if isinstance(data.get("messages"), list) else [])
    if not msgs:
        return {"phone": _phone_key(phone), "active_id": None, "threads": []}
    tid = str(uuid.uuid4())
    ts = data.get("updated_at") or _now_iso()
    return {
        "phone": _phone_key(phone),
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


def load_user_record(phone: str) -> dict[str, Any]:
    path = _chat_path(phone)
    key = _phone_key(phone)
    if not path or not os.path.isfile(path):
        return {"phone": key, "active_id": None, "threads": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("invalid record")
        record = _migrate_legacy(data, phone)
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
        threads.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
        threads = threads[:_MAX_THREADS]
        active_id = record.get("active_id")
        if active_id and not any(t["id"] == active_id for t in threads):
            active_id = threads[0]["id"] if threads else None
        return {"phone": key, "active_id": active_id, "threads": threads}
    except Exception as exc:
        try:
            current_app.logger.warning("ai chat load failed | phone=%s | %s", phone, exc)
        except Exception:
            pass
        return {"phone": key, "active_id": None, "threads": []}


def _save_record(record: dict[str, Any], phone: str) -> None:
    path = _chat_path(phone)
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        try:
            current_app.logger.error("ai chat save failed | phone=%s | %s", phone, exc)
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


def create_thread(phone: str, *, activate: bool = True) -> str:
    record = load_user_record(phone)
    tid = str(uuid.uuid4())
    ts = _now_iso()
    thread = {
        "id": tid,
        "title": "گفتگوی جدید",
        "created_at": ts,
        "updated_at": ts,
        "messages": [],
    }
    threads = [thread] + list(record.get("threads") or [])
    record["threads"] = threads[:_MAX_THREADS]
    if activate:
        record["active_id"] = tid
    _save_record(record, phone)
    return tid


def set_active_thread(phone: str, thread_id: str) -> bool:
    record = load_user_record(phone)
    if not _find_thread(record, thread_id):
        return False
    record["active_id"] = thread_id
    _save_record(record, phone)
    return True


def ensure_active_thread(phone: str) -> str:
    record = load_user_record(phone)
    th = _active_thread(record)
    if th:
        return str(th["id"])
    return create_thread(phone, activate=True)


def threads_for_ui(phone: str) -> list[dict[str, Any]]:
    record = load_user_record(phone)
    active = record.get("active_id")
    out: list[dict[str, Any]] = []
    for th in record.get("threads") or []:
        msgs = th.get("messages") or []
        preview = ""
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("role") == "user":
                preview = str(m.get("content") or "")[:80]
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


def messages_for_ui(phone: str, thread_id: str | None = None) -> list[dict[str, Any]]:
    record = load_user_record(phone)
    th = _find_thread(record, thread_id) if thread_id else _active_thread(record)
    if not th:
        return []
    return _enrich_messages_for_ui(phone, list(th.get("messages") or []))


def _enrich_messages_for_ui(phone: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.ai.land_cards import render_land_cards_html

    out: list[dict[str, Any]] = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        codes = row.get("land_codes") or []
        if row.get("role") == "assistant" and codes:
            try:
                row["cards_html"] = render_land_cards_html(phone, codes)
            except Exception:
                row["cards_html"] = ""
        out.append(row)
    return out


def history_for_api(phone: str, thread_id: str | None = None) -> list[dict[str, str]]:
    msgs = messages_for_ui(phone, thread_id)
    out: list[dict[str, str]] = []
    for item in msgs:
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            out.append({"role": role, "content": content})
    return out


def append_exchange(
    phone: str,
    user_text: str,
    assistant_text: str,
    *,
    thread_id: str | None = None,
    assistant_land_codes: list[str] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    record = load_user_record(phone)
    tid = thread_id or record.get("active_id") or ensure_active_thread(phone)
    record = load_user_record(phone)
    th = _find_thread(record, tid)
    if not th:
        tid = create_thread(phone, activate=True)
        record = load_user_record(phone)
        th = _find_thread(record, tid)
    assert th is not None

    msgs: list[dict[str, Any]] = list(th.get("messages") or [])
    ts = _now_iso()
    user_text = (user_text or "").strip()[:_MAX_CONTENT]
    assistant_text = (assistant_text or "").strip()[:_MAX_CONTENT]
    if user_text:
        msgs.append({"role": "user", "content": user_text, "created_at": ts})
        if th.get("title") in (None, "", "گفتگوی جدید") and len(msgs) == 1:
            th["title"] = _title_from_text(user_text)
    if assistant_text:
        entry: dict[str, Any] = {
            "role": "assistant",
            "content": assistant_text,
            "created_at": ts,
        }
        codes = [str(c).strip() for c in (assistant_land_codes or []) if str(c).strip()]
        if codes:
            entry["land_codes"] = codes[:5]
        msgs.append(entry)
    th["messages"] = msgs[-_MAX_MESSAGES:]
    th["updated_at"] = ts
    record["active_id"] = tid
    _save_record(record, phone)
    return _enrich_messages_for_ui(phone, th["messages"]), tid


def clear_chat(phone: str) -> str:
    """گفتگوی جدید خالی — thread جدید فعال."""
    return create_thread(phone, activate=True)


def delete_thread(phone: str, thread_id: str) -> bool:
    record = load_user_record(phone)
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
    elif record.get("active_id") == thread_id:
        record["active_id"] = record["threads"][0]["id"]
    _save_record(record, phone)
    return True
