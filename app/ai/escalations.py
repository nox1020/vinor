"""ثبت سوالات بدون پاسخ AI و پاسخ ادمین — برای همان همکار در چت بعدی."""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from flask import current_app

from app.services.sms import send_sms_direct
from app.utils.storage import load_settings


def _data_path() -> str:
    try:
        base = current_app.instance_path
    except Exception:
        base = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "instance",
        )
    path = os.path.join(base, "data", "ai_escalations.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_phone(phone: str) -> str:
    digits = re.sub(r"\D+", "", str(phone or ""))
    if len(digits) >= 11:
        return digits[-11:]
    return digits


def _load_all() -> list[dict[str, Any]]:
    path = _data_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_all(items: list[dict[str, Any]]) -> None:
    path = _data_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def create_escalation(
    *,
    partner_phone: str,
    question: str,
    user_message: str = "",
    thread_id: str | None = None,
) -> dict[str, Any]:
    """ثبت سوال و اطلاع‌رسانی SMS به ادمین."""
    phone = _norm_phone(partner_phone)
    q = (question or user_message or "").strip()[:500]
    if not phone or not q:
        return {"ok": False, "error": "داده ناقص"}

    items = _load_all()
    rec = {
        "id": uuid.uuid4().hex[:12],
        "partner_phone": phone,
        "thread_id": (thread_id or "").strip(),
        "question": q,
        "user_message": (user_message or "").strip()[:2000],
        "status": "pending",
        "admin_answer": "",
        "created_at": _now_iso(),
        "answered_at": "",
        "delivered_at": "",
        "admin_notified_at": "",
    }
    items.append(rec)
    if len(items) > 5000:
        items = items[-5000:]
    _save_all(items)

    _notify_admin_sms(rec)
    return {"ok": True, "id": rec["id"], "record": rec}


def _notify_admin_sms(rec: dict[str, Any]) -> None:
    settings = load_settings() or {}
    admin_phone = _norm_phone(str(settings.get("partner_application_admin_phone") or "09121471301"))
    line = str(settings.get("sms_line_number") or "").strip() or None
    if not admin_phone or len(admin_phone) != 11:
        return
    q_short = str(rec.get("question") or "")[:120]
    partner = str(rec.get("partner_phone") or "")
    msg = (
        f"وینور AI — سوال همکار\n"
        f"همکار: {partner}\n"
        f"سوال: {q_short}\n"
        f"پنل ادمین: سوالات AI"
    )
    try:
        send_sms_direct(mobile=admin_phone, message=msg, line_number=line)
        items = _load_all()
        for it in items:
            if it.get("id") == rec.get("id"):
                it["admin_notified_at"] = _now_iso()
                break
        _save_all(items)
    except Exception:
        try:
            current_app.logger.exception("AI escalation SMS failed")
        except Exception:
            pass


def consume_pending_answers(partner_phone: str) -> list[dict[str, str]]:
    """پاسخ‌های آمادهٔ ادمین که هنوز به چت تزریق نشده — یک‌بار مصرف."""
    phone = _norm_phone(partner_phone)
    if not phone:
        return []
    items = _load_all()
    out: list[dict[str, str]] = []
    changed = False
    for it in items:
        if _norm_phone(str(it.get("partner_phone") or "")) != phone:
            continue
        if (it.get("status") or "") != "answered":
            continue
        if it.get("delivered_at"):
            continue
        ans = str(it.get("admin_answer") or "").strip()
        if not ans:
            continue
        out.append(
            {
                "id": str(it.get("id") or ""),
                "question": str(it.get("question") or "").strip(),
                "answer": ans,
            }
        )
        it["delivered_at"] = _now_iso()
        changed = True
    if changed:
        _save_all(items)
    return out


def list_pending_for_admin() -> list[dict[str, Any]]:
    items = _load_all()
    pending = [i for i in items if (i.get("status") or "") == "pending"]
    pending.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return pending


def list_recent_answered(limit: int = 30) -> list[dict[str, Any]]:
    items = _load_all()
    done = [i for i in items if (i.get("status") or "") == "answered"]
    done.sort(key=lambda x: str(x.get("answered_at") or ""), reverse=True)
    return done[:limit]


def answer_escalation(escalation_id: str, admin_answer: str) -> dict[str, Any]:
    eid = (escalation_id or "").strip()
    ans = (admin_answer or "").strip()
    if not eid or not ans:
        return {"ok": False, "error": "شناسه یا پاسخ خالی است."}
    items = _load_all()
    found = None
    for it in items:
        if str(it.get("id")) == eid:
            found = it
            break
    if not found:
        return {"ok": False, "error": "سوال یافت نشد."}
    if (found.get("status") or "") == "answered":
        return {"ok": False, "error": "قبلاً پاسخ داده شده."}
    found["status"] = "answered"
    found["admin_answer"] = ans[:4000]
    found["answered_at"] = _now_iso()
    _save_all(items)
    return {"ok": True, "record": found}
