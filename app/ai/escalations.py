"""ثبت سوالات بدون پاسخ AI و پاسخ ادمین — برای همان همکار در چت بعدی."""
from __future__ import annotations

import json
import os
import re
import threading
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
    if audience == AUDIENCE_PARTNER:
        return "همکار"
    return "کاربر عادی"


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
    key = _norm_key(str(rec.get("user_key") or rec.get("partner_phone") or ""))
    if not key:
        return False
    aud = rec.get("audience") if rec.get("audience") in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    tid = str(rec.get("thread_id") or "").strip()
    q = str(rec.get("question") or "")
    eid = str(rec.get("id") or "")

    # همکار / پستچی: پاسخ فقط در پستچی وینور (جدا از چت فروش AI)
    try:
        from app.services.postchi import deliver_support_reply, is_postchi_thread

        if aud == AUDIENCE_PARTNER or is_postchi_thread(tid):
            ok = deliver_support_reply(
                key,
                answer,
                question=q,
                escalation_id=eid,
            )
            if ok:
                rec["delivered_at"] = _now_iso()
                rec["delivered_via"] = "postchi"
            return ok
    except Exception:
        try:
            current_app.logger.exception(
                "Postchi support delivery failed | user=%s | esc=%s",
                key,
                eid,
            )
        except Exception:
            pass

    from app.ai.chat_store import inject_admin_reply

    ok = inject_admin_reply(
        key,
        answer,
        thread_id=tid or None,
        audience=aud,
        question=q,
        escalation_id=eid,
    )
    if ok:
        rec["delivered_at"] = _now_iso()
        rec["delivered_via"] = "ai_chat"
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
    reason: str = "",
    notify_admin: bool | None = None,
) -> dict[str, Any]:
    """ثبت سوال و اطلاع‌رسانی SMS به ادمین.

    reason=\"balance\": معلق به‌خاطر اتمام موجودی API — بدون SMS ادمین (پیامک اتمام موجودی جداست).
    """
    key = _norm_key(user_key or partner_phone)
    aud = audience if audience in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
    q = (question or user_message or "").strip()[:500]
    reason_s = (reason or "").strip().lower()
    if not key or not q:
        return {"ok": False, "error": "داده ناقص"}

    items = _load_all()

    # جلوگیری از ثبت تکراری همان سوال معلق به‌خاطر موجودی
    if reason_s == "balance":
        for it in items:
            if (it.get("status") or "") != "pending":
                continue
            if str(it.get("reason") or "").strip().lower() != "balance":
                continue
            it_key = _norm_key(str(it.get("user_key") or it.get("partner_phone") or ""))
            if it_key != key:
                continue
            it_aud = it.get("audience") if it.get("audience") in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC) else AUDIENCE_PARTNER
            if it_aud != aud:
                continue
            if str(it.get("thread_id") or "").strip() != (thread_id or "").strip():
                continue
            if questions_similar(str(it.get("question") or ""), q):
                return {"ok": True, "id": it["id"], "record": it, "sms_ok": False, "deduped": True}

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
        "reason": reason_s,
    }
    items.append(rec)
    if len(items) > 5000:
        items = items[-5000:]
    try:
        _save_all(items)
    except Exception as exc:
        return {"ok": False, "error": f"ذخیره سوال ممکن نشد: {exc}"}

    if notify_admin is None:
        notify_admin = reason_s != "balance"
    sms_ok = False
    if notify_admin:
        sms_ok = _notify_admin_sms(rec)
    try:
        current_app.logger.info(
            "AI escalation created | id=%s | user=%s | reason=%s | path=%s | sms=%s",
            rec["id"],
            key,
            reason_s or "-",
            escalations_path(),
            sms_ok,
        )
    except Exception:
        pass
    return {"ok": True, "id": rec["id"], "record": rec, "sms_ok": sms_ok}


def _admin_sms_target() -> tuple[str, str | None]:
    settings = load_settings() or {}
    raw_admin = str(settings.get("partner_application_admin_phone") or "09121471301")
    admin_phone = normalize_iran_mobile(raw_admin) or _norm_phone(raw_admin)
    line = str(settings.get("sms_line_number") or "").strip() or None
    return admin_phone, line


def send_admin_balance_depleted_sms() -> bool:
    """پیامک اتمام موجودی DeepSeek به ادمین."""
    admin_phone, line = _admin_sms_target()
    if not admin_phone or len(admin_phone) != 11 or not admin_phone.startswith("09"):
        try:
            current_app.logger.warning(
                "AI balance SMS skipped — invalid admin phone | norm=%s",
                admin_phone,
            )
        except Exception:
            pass
        return False
    msg = (
        "وینور AI\n"
        "موجودی حساب DeepSeek تمام شده است.\n"
        "لطفاً حساب را شارژ کنید.\n"
        "پنل ادمین: سوالات AI"
    )
    try:
        result = send_sms_direct(mobile=admin_phone, message=msg, line_number=line, history_source='ai_escalation', recipient_name='ادمین')
        ok = bool(result.get("ok"))
        if not ok:
            try:
                current_app.logger.error(
                    "AI balance SMS failed | admin=%s | status=%s | body=%s",
                    admin_phone,
                    result.get("status"),
                    result.get("body"),
                )
            except Exception:
                pass
        return ok
    except Exception:
        try:
            current_app.logger.exception("AI balance SMS exception | admin=%s", admin_phone)
        except Exception:
            pass
        return False


def send_admin_spend_fuse_sms(
    *,
    tokens: int,
    requests: int,
    max_tokens: int,
    max_requests: int,
) -> bool:
    """پیامک قطع مصرف به‌خاطر سقف ایمنی — تا ادمین دوباره فعال نکند API قطع است."""
    admin_phone, line = _admin_sms_target()
    if not admin_phone or len(admin_phone) != 11 or not admin_phone.startswith("09"):
        try:
            current_app.logger.warning(
                "AI spend fuse SMS skipped — invalid admin phone | norm=%s",
                admin_phone,
            )
        except Exception:
            pass
        return False
    msg = (
        "وینور AI — شیر اطمینان\n"
        "مصرف بیش از سقف بود؛ API قطع شد.\n"
        f"توکن: {int(tokens):,}/{int(max_tokens):,}\n"
        f"درخواست: {int(requests):,}/{int(max_requests):,}\n"
        "فعال‌سازی: پنل ادمین ← سوالات AI"
    )
    try:
        result = send_sms_direct(mobile=admin_phone, message=msg, line_number=line, history_source='ai_escalation', recipient_name='ادمین')
        ok = bool(result.get("ok"))
        if not ok:
            try:
                current_app.logger.error(
                    "AI spend fuse SMS failed | admin=%s | status=%s | body=%s",
                    admin_phone,
                    result.get("status"),
                    result.get("body"),
                )
            except Exception:
                pass
        return ok
    except Exception:
        try:
            current_app.logger.exception(
                "AI spend fuse SMS exception | admin=%s", admin_phone
            )
        except Exception:
            pass
        return False


def _notify_admin_sms(rec: dict[str, Any]) -> bool:
    from app.ai.runtime_settings import get_ai_settings

    if not get_ai_settings().get("escalation_sms_enabled", True):
        return False
    admin_phone, line = _admin_sms_target()
    if not admin_phone or len(admin_phone) != 11 or not admin_phone.startswith("09"):
        try:
            current_app.logger.warning(
                "AI escalation SMS skipped — invalid admin phone | norm=%s",
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
        result = send_sms_direct(mobile=admin_phone, message=msg, line_number=line, history_source='ai_escalation', recipient_name='ادمین')
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
    injected_chat_keys: set[tuple[str, str]] = set()
    for rec in targets:
        rec["status"] = "answered"
        rec["admin_answer"] = ans[:4000]
        rec["answered_at"] = ts
        if str(rec.get("id")) != eid:
            rec["matched_from"] = eid
        chat_key = (
            _norm_key(str(rec.get("user_key") or rec.get("partner_phone") or "")),
            str(rec.get("thread_id") or "").strip(),
        )
        if chat_key[0] and chat_key in injected_chat_keys:
            rec["delivered_at"] = _now_iso()
            continue
        if _deliver_answer_to_chat(rec, ans):
            delivered += 1
            if chat_key[0]:
                injected_chat_keys.add(chat_key)

    _save_all(items)
    return {
        "ok": True,
        "record": found,
        "delivered_count": delivered,
        "similar_count": len(similar_ids),
        "similar_ids": similar_ids,
        "total_answered": len(targets),
    }


# --- ادامه خودکار پس از شارژ موجودی API ---

_RESUME_LOCK = threading.Lock()
_RESUME_RUNNING = False

ANSWER_READY_TITLE = "وینور AI"
ANSWER_READY_BODY = "جواب شما آماده است"


def list_pending_balance_deferred() -> list[dict[str, Any]]:
    items = _load_all()
    out = [
        i
        for i in items
        if (i.get("status") or "") == "pending"
        and str(i.get("reason") or "").strip().lower() == "balance"
    ]
    out.sort(key=lambda x: str(x.get("created_at") or ""))
    return out


def count_pending_balance_deferred() -> int:
    return len(list_pending_balance_deferred())


def _ai_chat_action_url(audience: str, thread_id: str = "") -> str:
    tid = (thread_id or "").strip()
    if audience == AUDIENCE_PARTNER:
        base = "/express/partner/home?ai=1"
    else:
        base = "/express/partner/home?ai=1"
    if tid:
        return f"{base}&thread={tid}"
    return base


def _notify_answer_ready(
    user_key: str,
    *,
    audience: str,
    thread_id: str = "",
    escalation_id: str = "",
) -> bool:
    phone = _norm_phone(user_key)
    if len(phone) != 11 or not phone.startswith("09"):
        return False
    try:
        from app.services.notifications import add_notification

        eid = (escalation_id or "").strip()
        add_notification(
            phone,
            title=ANSWER_READY_TITLE,
            body=ANSWER_READY_BODY,
            ntype="info",
            action_url=_ai_chat_action_url(audience, thread_id),
            source="ai_balance_resume",
            escalation_id=eid or None,
        )
        return True
    except Exception:
        try:
            current_app.logger.exception(
                "balance resume notify failed | user=%s", phone
            )
        except Exception:
            pass
        return False


def _deliver_balance_resume_to_chat(
    rec: dict[str, Any],
    answer: str,
    *,
    land_codes: list[str] | None = None,
    agent_actions: list[dict[str, Any]] | None = None,
) -> bool:
    """پاسخ AI را در همان گفتگوی اصلی تزریق کن (نه پستچی پشتیبانی)."""
    key = _norm_key(str(rec.get("user_key") or rec.get("partner_phone") or ""))
    if not key:
        return False
    aud = (
        rec.get("audience")
        if rec.get("audience") in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC)
        else AUDIENCE_PARTNER
    )
    tid = str(rec.get("thread_id") or "").strip()
    eid = str(rec.get("id") or "")
    text = (answer or "").strip()
    if not text:
        return False

    from app.ai.chat_store import append_typed_message, load_user_record
    from app.ai.message_types import MSG_AI

    # جلوگیری از دوباره‌ارسال
    if eid:
        try:
            record = load_user_record(key, aud)
            for th in record.get("threads") or []:
                if tid and str(th.get("id") or "") != tid:
                    continue
                for item in th.get("messages") or []:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("escalation_id") or "") == eid:
                        rec["delivered_at"] = _now_iso()
                        rec["delivered_via"] = "ai_chat_balance_resume"
                        return True
                    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
                    if str(meta.get("escalation_id") or "") == eid:
                        rec["delivered_at"] = _now_iso()
                        rec["delivered_via"] = "ai_chat_balance_resume"
                        return True
        except Exception:
            pass

    try:
        append_typed_message(
            key,
            text,
            thread_id=tid or None,
            audience=aud,
            msg_type=MSG_AI,
            source="ai_balance_resume",
            land_codes=land_codes,
            agent_actions=agent_actions,
            event="balance_resume_replied",
            meta={"escalation_id": eid, "provider": "balance_resume"},
            quota=False,
            escalation_id=eid,
        )
        rec["delivered_at"] = _now_iso()
        rec["delivered_via"] = "ai_chat_balance_resume"
        return True
    except Exception:
        try:
            current_app.logger.exception(
                "balance resume deliver failed | user=%s | esc=%s", key, eid
            )
        except Exception:
            pass
        return False


def _claim_balance_deferred(limit: int = 25) -> list[dict[str, Any]]:
    """علامت‌گذاری atomic برای جلوگیری از پاسخ دوباره."""
    items = _load_all()
    claimed: list[dict[str, Any]] = []
    changed = False
    now = datetime.now(timezone.utc)
    for it in items:
        status = (it.get("status") or "")
        reason = str(it.get("reason") or "").strip().lower()
        if reason != "balance":
            continue
        # بازیابی موارد گیرکرده در resuming (کرش ورکر)
        if status == "resuming":
            started = str(it.get("resume_started_at") or "")
            stale = True
            if started:
                try:
                    ts = datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ").replace(
                        tzinfo=timezone.utc
                    )
                    stale = (now - ts).total_seconds() > 600
                except Exception:
                    stale = True
            if not stale:
                continue
            it["status"] = "pending"
            changed = True
            status = "pending"
        if status != "pending":
            continue
        if len(claimed) >= limit:
            continue
        it["status"] = "resuming"
        it["resume_started_at"] = _now_iso()
        claimed.append(dict(it))
        changed = True
    if changed:
        _save_all(items)
    return claimed


def _finalize_balance_deferred(
    escalation_id: str,
    *,
    status: str,
    answer: str = "",
    delivered: bool = False,
    delivered_via: str = "",
    error: str = "",
) -> None:
    items = _load_all()
    eid = (escalation_id or "").strip()
    for it in items:
        if str(it.get("id") or "") != eid:
            continue
        it["status"] = status
        if answer:
            it["admin_answer"] = answer[:4000]
            it["answered_at"] = _now_iso()
            it["answered_by"] = "auto_balance_resume"
        if delivered:
            it["delivered_at"] = _now_iso()
            if delivered_via:
                it["delivered_via"] = delivered_via
        if error:
            it["resume_error"] = error[:500]
        if status == "pending":
            it.pop("resume_started_at", None)
            it.pop("resume_error", None)
        break
    _save_all(items)


def resume_balance_deferred_escalations(
    *,
    limit: int = 25,
    trigger: str = "",
) -> dict[str, Any]:
    """پاسخ خودکار به سوالات معلق به‌خاطر اتمام موجودی — پس از شارژ."""
    from app.ai.credits import is_api_balance_depleted

    if is_api_balance_depleted():
        return {"ok": False, "skipped": True, "reason": "still_depleted", "processed": 0}

    claimed = _claim_balance_deferred(limit=limit)
    if not claimed:
        return {"ok": True, "processed": 0, "answered": 0, "trigger": trigger}

    from app.ai.chat_store import history_for_api
    from app.ai.services import generate_reply

    answered = 0
    failed = 0
    requeued = 0

    try:
        from flask import g

        g.ai_balance_resume = True
    except Exception:
        pass

    for rec in claimed:
        eid = str(rec.get("id") or "")
        key = _norm_key(str(rec.get("user_key") or rec.get("partner_phone") or ""))
        aud = (
            rec.get("audience")
            if rec.get("audience") in (AUDIENCE_PARTNER, AUDIENCE_PUBLIC)
            else AUDIENCE_PARTNER
        )
        tid = str(rec.get("thread_id") or "").strip() or None
        msg = str(rec.get("user_message") or rec.get("question") or "").strip()
        if not key or not msg:
            _finalize_balance_deferred(eid, status="pending", error="missing_data")
            requeued += 1
            continue

        try:
            history = history_for_api(key, tid, audience=aud)
            result = generate_reply(
                msg,
                history=history,
                user_key=key,
                audience=aud,
                thread_id=tid,
            )
        except Exception as exc:
            failed += 1
            _finalize_balance_deferred(eid, status="pending", error=str(exc)[:300])
            requeued += 1
            try:
                current_app.logger.exception(
                    "balance resume generate failed | esc=%s", eid
                )
            except Exception:
                pass
            continue

        if not result.get("ok"):
            if result.get("balance_depleted") or is_api_balance_depleted():
                _finalize_balance_deferred(eid, status="pending", error="balance_again")
                requeued += 1
                break
            # پاسخ placeholder از fallback را دوباره صف نکن اگر escalate شده
            meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
            if meta.get("reason") == "balance":
                _finalize_balance_deferred(eid, status="pending", error="balance_fallback")
                requeued += 1
                break
            failed += 1
            _finalize_balance_deferred(
                eid,
                status="pending",
                error=str(result.get("error") or result.get("error_code") or "fail")[:300],
            )
            requeued += 1
            continue

        reply = str(result.get("reply") or "").strip()
        # اگر دوباره همان پیام «به زودی» برگشت، موفق حساب نکن
        if not reply or reply == "به زودی به شما پاسخ خواهم داد.":
            meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
            if meta.get("provider") == "escalation" and meta.get("reason") == "balance":
                _finalize_balance_deferred(eid, status="pending", error="still_deferred")
                requeued += 1
                break
            if not reply:
                failed += 1
                _finalize_balance_deferred(eid, status="pending", error="empty_reply")
                requeued += 1
                continue

        delivered = _deliver_balance_resume_to_chat(
            rec,
            reply,
            land_codes=list(result.get("land_codes") or []),
            agent_actions=list(result.get("agent_actions") or []),
        )
        _finalize_balance_deferred(
            eid,
            status="answered",
            answer=reply,
            delivered=delivered,
            delivered_via=str(rec.get("delivered_via") or "ai_chat_balance_resume"),
        )
        if delivered:
            _notify_answer_ready(
                key,
                audience=aud,
                thread_id=tid or "",
                escalation_id=eid,
            )
            answered += 1
        else:
            failed += 1

    try:
        current_app.logger.info(
            "balance deferred resume done | trigger=%s | claimed=%s | answered=%s | failed=%s | requeued=%s",
            trigger or "-",
            len(claimed),
            answered,
            failed,
            requeued,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "processed": len(claimed),
        "answered": answered,
        "failed": failed,
        "requeued": requeued,
        "trigger": trigger,
    }


def schedule_resume_balance_deferred(*, trigger: str = "") -> None:
    """اجرای پس‌زمینهٔ resume — یک‌بار در هر لحظه."""
    global _RESUME_RUNNING
    with _RESUME_LOCK:
        if _RESUME_RUNNING:
            return
        _RESUME_RUNNING = True

    try:
        app = current_app._get_current_object()
    except Exception:
        with _RESUME_LOCK:
            _RESUME_RUNNING = False
        return

    trig = (trigger or "").strip() or "balance_restored"

    def _worker() -> None:
        global _RESUME_RUNNING
        try:
            with app.app_context():
                try:
                    resume_balance_deferred_escalations(trigger=trig)
                except Exception:
                    try:
                        app.logger.exception(
                            "balance deferred resume worker failed | trigger=%s", trig
                        )
                    except Exception:
                        pass
        finally:
            with _RESUME_LOCK:
                _RESUME_RUNNING = False

    threading.Thread(
        target=_worker,
        daemon=True,
        name="vinor-ai-balance-resume",
    ).start()

