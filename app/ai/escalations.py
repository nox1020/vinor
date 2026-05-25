"""ثبت سوالات بدون پاسخ AI و پاسخ ادمین — برای همان همکار در چت بعدی."""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from flask import current_app

from app.ai.audience import AUDIENCE_PARTNER, AUDIENCE_PUBLIC
from app.ai.paths import ensure_escalations_file, escalations_path
from app.services.sms import normalize_iran_mobile, send_sms_direct
from app.utils.storage import load_settings


def _data_path() -> str:
    return ensure_escalations_file()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_phone(phone: str) -> str:
    digits = re.sub(r"\D+", "", str(phone or ""))
    if len(digits) >= 11:
        return digits[-11:]
    return digits


def _norm_key(user_key: str) -> str:
    digits = re.sub(r"\D+", "", str(user_key or ""))
    if len(digits) >= 11:
        return digits[-11:]
    if len(digits) >= 8:
        return digits
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", str(user_key or ""))
    return safe[:64] if safe else ""


def _audience_label(audience: str | None) -> str:
    return "همکار" if audience == AUDIENCE_PARTNER else "کاربر عادی"


def _normalize_question(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    t = re.sub(r"[؟?!.،,:;«»\"'()\[\]{}]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _question_tokens(text: str) -> set[str]:
    words = re.findall(r"[\w\u0600-\u06FF]{2,}", _normalize_question(text))
    stop = {
        "که", "از", "به", "در", "با", "برای", "این", "آن", "را", "و", "یا",
        "من", "شما", "است", "هست", "چی", "چه", "چطور", "کی", "کجا",
    }
    return {w for w in words if w not in stop}


def questions_similar(a: str, b: str, threshold: float = 0.52) -> bool:
    """تشخیص سوال مشابه برای پاسخ یکسان ادمین."""
    ka = _normalize_question(a)
    kb = _normalize_question(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    if len(ka) >= 8 and len(kb) >= 8 and (ka in kb or kb in ka):
        return True
    ta = _question_tokens(a)
    tb = _question_tokens(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    union = len(ta | tb)
    return union > 0 and (inter / union) >= threshold


def _deliver_answer_to_chat(rec: dict[str, Any], answer: str) -> bool:
    from app.ai.chat_store import inject_admin_reply

    key = _norm_key(str(rec.get("user_key") or rec.get("partner_phone") or ""))
    if not key:
        return False
    aud = rec.get("audience") if rec.get("audience") in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    ok = inject_admin_reply(
        key,
        answer,
        thread_id=str(rec.get("thread_id") or "").strip() or None,
        audience=aud,
        question=str(rec.get("question") or ""),
        escalation_id=str(rec.get("id") or ""),
    )
    if ok:
        rec["delivered_at"] = _now_iso()
    return ok


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
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as exc:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass
        try:
            current_app.logger.error(
                "AI escalations save failed | path=%s | err=%s",
                path,
                exc,
            )
        except Exception:
            pass
        raise


def create_escalation(
    *,
    user_key: str = "",
    partner_phone: str = "",
    audience: str | None = None,
    question: str = "",
    user_message: str = "",
    thread_id: str | None = None,
) -> dict[str, Any]:
    """ثبت سوال و اطلاع‌رسانی SMS به ادمین."""
    key = _norm_key(user_key or partner_phone)
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    q = (question or user_message or "").strip()[:500]
    if not key or not q:
        return {"ok": False, "error": "داده ناقص"}

    items = _load_all()
    rec = {
        "id": uuid.uuid4().hex[:12],
        "user_key": key,
        "partner_phone": key,
        "audience": aud,
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
    try:
        _save_all(items)
    except Exception as exc:
        return {"ok": False, "error": f"ذخیره سوال ممکن نشد: {exc}"}

    sms_ok = _notify_admin_sms(rec)
    try:
        current_app.logger.info(
            "AI escalation created | id=%s | user=%s | path=%s | sms=%s",
            rec["id"],
            key,
            escalations_path(),
            sms_ok,
        )
    except Exception:
        pass
    return {"ok": True, "id": rec["id"], "record": rec, "sms_ok": sms_ok}


def _notify_admin_sms(rec: dict[str, Any]) -> bool:
    settings = load_settings() or {}
    raw_admin = str(settings.get("partner_application_admin_phone") or "09121471301")
    admin_phone = normalize_iran_mobile(raw_admin) or _norm_phone(raw_admin)
    line = str(settings.get("sms_line_number") or "").strip() or None
    if not admin_phone or len(admin_phone) != 11 or not admin_phone.startswith("09"):
        try:
            current_app.logger.warning(
                "AI escalation SMS skipped — invalid admin phone | raw=%s | norm=%s",
                raw_admin,
                admin_phone,
            )
        except Exception:
            pass
        return False

    q_short = str(rec.get("question") or "")[:120]
    user = str(rec.get("user_key") or rec.get("partner_phone") or "")
    label = _audience_label(rec.get("audience"))
    msg = (
        f"وینور AI — سوال {label}\n"
        f"کاربر: {user}\n"
        f"سوال: {q_short}\n"
        f"پنل ادمین: سوالات AI"
    )
    try:
        result = send_sms_direct(mobile=admin_phone, message=msg, line_number=line)
        ok = bool(result.get("ok"))
        if not ok:
            try:
                current_app.logger.error(
                    "AI escalation SMS failed | admin=%s | status=%s | body=%s",
                    admin_phone,
                    result.get("status"),
                    result.get("body"),
                )
            except Exception:
                pass
            return False

        items = _load_all()
        for it in items:
            if it.get("id") == rec.get("id"):
                it["admin_notified_at"] = _now_iso()
                break
        _save_all(items)
        return True
    except Exception:
        try:
            current_app.logger.exception("AI escalation SMS exception | admin=%s", admin_phone)
        except Exception:
            pass
        return False


def has_pending_answers(
    user_key: str,
    audience: str | None = None,
) -> bool:
    """آیا پاسخ ادمین آماده است (بدون مصرف — برای مسیریابی API)."""
    key = _norm_key(user_key)
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else None
    if not key:
        return False
    for it in _load_all():
        it_key = _norm_key(str(it.get("user_key") or it.get("partner_phone") or ""))
        if it_key != key:
            continue
        if aud and (it.get("audience") or AUDIENCE_PARTNER) != aud:
            continue
        if (it.get("status") or "") != "answered":
            continue
        if it.get("delivered_at"):
            continue
        if str(it.get("admin_answer") or "").strip():
            return True
    return False


def consume_pending_answers(
    user_key: str,
    audience: str | None = None,
) -> list[dict[str, str]]:
    """پاسخ‌های آمادهٔ ادمین که هنوز به چت تزریق نشده — یک‌بار مصرف."""
    key = _norm_key(user_key)
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else None
    if not key:
        return []
    items = _load_all()
    out: list[dict[str, str]] = []
    changed = False
    for it in items:
        it_key = _norm_key(str(it.get("user_key") or it.get("partner_phone") or ""))
        if it_key != key:
            continue
        if aud and (it.get("audience") or AUDIENCE_PARTNER) != aud:
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


def answer_escalation(
    escalation_id: str,
    admin_answer: str,
    *,
    apply_similar: bool = True,
) -> dict[str, Any]:
    """ثبت پاسخ ادمین، تزریق فوری در چت همان کاربر، و پاسخ به سوالات مشابه معلق."""
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

    primary_q = str(found.get("question") or "").strip()
    primary_aud = found.get("audience") if found.get("audience") in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    targets: list[dict[str, Any]] = [found]
    similar_ids: list[str] = []

    if apply_similar and primary_q:
        for it in items:
            if (it.get("status") or "") != "pending":
                continue
            if str(it.get("id")) == eid:
                continue
            it_aud = it.get("audience") if it.get("audience") in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
            if it_aud != primary_aud:
                continue
            if questions_similar(str(it.get("question") or ""), primary_q):
                targets.append(it)
                similar_ids.append(str(it.get("id") or ""))

    delivered = 0
    ts = _now_iso()
    for rec in targets:
        rec["status"] = "answered"
        rec["admin_answer"] = ans[:4000]
        rec["answered_at"] = ts
        if str(rec.get("id")) != eid:
            rec["matched_from"] = eid
        if _deliver_answer_to_chat(rec, ans):
            delivered += 1

    _save_all(items)
    return {
        "ok": True,
        "record": found,
        "delivered_count": delivered,
        "similar_count": len(similar_ids),
        "similar_ids": similar_ids,
        "total_answered": len(targets),
    }
