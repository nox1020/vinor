# -*- coding: utf-8 -*-
"""تبدیل رویداد دامنه به گزارش فارسی برای چت ادمین."""
from __future__ import annotations

import re
from typing import Any

from app.supervisor_agent.categories import (
    REPORT_CUSTOMER,
    REPORT_DEAL,
    REPORT_FOLLOWUP,
    REPORT_PARTNER,
    REPORT_SYSTEM,
    REPORT_VISIT,
    STATUS_ERROR,
    STATUS_IN_PROGRESS,
    STATUS_INFO,
    STATUS_REMINDER,
    STATUS_SUCCESS,
)

_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _fa_num(value: Any) -> str:
    return str(value).translate(_PERSIAN_DIGITS)


def _person_label(name: str = "", phone: str = "") -> str:
    name = (name or "").strip()
    if name:
        if name.startswith(("آقای", "خانم", "مشتری", "همکار")):
            return name
        return f"آقای/خانم {name}"
    digits = re.sub(r"\D+", "", str(phone or ""))
    if len(digits) >= 4:
        return f"مشتری {digits[-4:]}"
    return "مشتری"


def _land_ref(land_code: str = "") -> str:
    code = str(land_code or "").strip()
    return f"ملک {code}" if code else "ملک"


def _partner_count(n: Any) -> str:
    try:
        count = int(n or 0)
    except (TypeError, ValueError):
        count = 0
    if count <= 0:
        return ""
    return _fa_num(count)


def render_report(
    event: str,
    *,
    body: str = "",
    land_code: str = "",
    customer_name: str = "",
    customer_phone: str = "",
    partner_count: int = 0,
    response_count: int = 0,
    region: str = "",
    visit_time: str = "",
    deal_code: str = "",
    retry_minutes: int = 0,
    reviewed_count: int = 0,
    followup_count: int = 0,
    sent_count: int = 0,
    failed_count: int = 0,
    channel: str = "",
    meta: dict[str, Any] | None = None,
) -> tuple[str, str, str] | None:
    """
    برگرداند (متن، دسته، وضعیت) یا None اگر نباید گزارش شود.
    """
    ev = (event or "").strip()
    if body and ev == "custom":
        category = str((meta or {}).get("report_category") or REPORT_SYSTEM)
        status = str((meta or {}).get("report_status") or STATUS_INFO)
        return body.strip(), category, status

    person = _person_label(customer_name, customer_phone)
    land = str(land_code or deal_code or "").strip()
    land_phrase = _land_ref(land)

    # --- پیگیری / مشتری ---
    if ev == "followup_started":
        n = _partner_count(partner_count)
        lines = [f"درخواست {person} را بررسی کردم."]
        if n:
            lines.append(f"برای {n} همکار مرتبط ارسال شد.")
        lines.append("در حال انتظار پاسخ هستم.")
        return "\n".join(lines), REPORT_FOLLOWUP, STATUS_IN_PROGRESS

    if ev == "followup_completed":
        rc = _partner_count(response_count)
        lines = [f"پیگیری درخواست {person} به پایان رسید."]
        if rc:
            lines.append(f"{rc} همکار پاسخ دادند.")
        lines.append("بهترین پیشنهاد برای مشتری ارسال شد.")
        return "\n".join(lines), REPORT_FOLLOWUP, STATUS_SUCCESS

    if ev == "followup_responses":
        rc = _partner_count(response_count) or "چند"
        return (
            f"{rc} همکار پاسخ دادند.",
            REPORT_FOLLOWUP,
            STATUS_IN_PROGRESS,
        )

    if ev == "customer_request_received":
        return "درخواست خرید جدید دریافت شد.", REPORT_CUSTOMER, STATUS_INFO

    if ev == "customer_matched":
        n = _partner_count(partner_count)
        text = "مشتری را بررسی کردم و همکاران مناسب انتخاب شدند."
        if n:
            text = f"مشتری را بررسی کردم و {n} همکار مناسب انتخاب شدند."
        return text, REPORT_CUSTOMER, STATUS_IN_PROGRESS

    if ev == "customer_visit_confirmed":
        return "مشتری زمان بازدید را تأیید کرد.", REPORT_CUSTOMER, STATUS_SUCCESS

    # --- بازدید ---
    if ev in ("visit_requested", "visit_scheduled"):
        when = (visit_time or "").strip()
        if when:
            return (
                f"بازدید {land_phrase} برای {when} هماهنگ شد.",
                REPORT_VISIT,
                STATUS_SUCCESS,
            )
        return (
            f"بازدید {land_phrase} درخواست شد.",
            REPORT_VISIT,
            STATUS_IN_PROGRESS,
        )

    if ev == "visit_approved":
        return f"بازدید {land_phrase} تأیید شد.", REPORT_VISIT, STATUS_SUCCESS

    if ev == "visit_completed":
        return f"بازدید {land_phrase} انجام شد.", REPORT_VISIT, STATUS_SUCCESS

    if ev == "visit_cancelled":
        return f"بازدید {land_phrase} لغو شد.", REPORT_VISIT, STATUS_INFO

    if ev == "visit_no_show":
        return f"عدم حضور در بازدید {land_phrase} ثبت شد.", REPORT_VISIT, STATUS_REMINDER

    if ev == "visit_pending_confirm":
        return (
            "یکی از بازدیدهای امروز هنوز تأیید نهایی نشده است.\n"
            "در حال پیگیری از همکار مربوطه هستم.",
            REPORT_VISIT,
            STATUS_REMINDER,
        )

    # --- معامله ---
    if ev in ("deal_started", "deal_pending"):
        code = land or deal_code
        ref = _land_ref(code) if code else "پرونده معامله"
        return (
            f"{ref} وارد مرحله تنظیم قرارداد شد.",
            REPORT_DEAL,
            STATUS_IN_PROGRESS,
        )

    if ev == "deal_approved":
        return (
            f"معامله {land_phrase} با موفقیت نهایی شد.\n"
            "پورسانت‌ها محاسبه و برای بررسی ارسال شدند.",
            REPORT_DEAL,
            STATUS_SUCCESS,
        )

    if ev == "deal_released":
        return f"معامله {land_phrase} بسته شد.", REPORT_DEAL, STATUS_INFO

    if ev == "commission_created":
        return f"پورسانت {land_phrase} ثبت شد.", REPORT_DEAL, STATUS_INFO

    # --- همکار ---
    if ev == "partner_application_pending":
        return "درخواست همکاری جدید برای بررسی ثبت شد.", REPORT_PARTNER, STATUS_INFO

    if ev == "partner_approved":
        return "درخواست همکاری تأیید شد.", REPORT_PARTNER, STATUS_SUCCESS

    if ev == "partner_rejected":
        return "درخواست همکاری رد شد.", REPORT_PARTNER, STATUS_INFO

    if ev == "reach_nudge_sent":
        sc = _partner_count(sent_count)
        if sc:
            return (
                f"پیگیری خودکار برای {sc} مشتری ارسال شد.",
                REPORT_FOLLOWUP,
                STATUS_SUCCESS,
            )
        return "پیگیری خودکار برای مشتریان ارسال شد.", REPORT_FOLLOWUP, STATUS_SUCCESS

    if ev == "partner_followup_sent":
        n = _partner_count(sent_count or partner_count)
        lines: list[str] = []
        if n:
            lines.append(f"به {n} همکار دارای فایل باز یادآوری فروش ارسال شد.")
        else:
            lines.append("یادآوری فروش برای همکاران ارسال شد.")
        if int(failed_count or 0) > 0:
            lines.append(
                f"برای {_fa_num(failed_count)} همکار ارسال کامل نشد؛ در نوبت بعدی دوباره تلاش می‌کنم."
            )
            return "\n".join(lines), REPORT_FOLLOWUP, STATUS_INFO
        return "\n".join(lines), REPORT_FOLLOWUP, STATUS_SUCCESS

    if ev == "admin_broadcast_sms":
        group = (region or "").strip() or "همکاران"
        n = _partner_count(sent_count)
        if int(failed_count or 0) > 0 and int(sent_count or 0) > 0:
            return (
                f"پیامک همگانی به {n or 'چند'} نفر از «{group}» ارسال شد.\n"
                f"برای {_fa_num(failed_count)} نفر ارسال نشد.",
                REPORT_PARTNER,
                STATUS_INFO,
            )
        if int(failed_count or 0) > 0 and int(sent_count or 0) <= 0:
            return (
                f"ارسال پیامک همگانی به «{group}» ناموفق بود.",
                REPORT_PARTNER,
                STATUS_ERROR,
            )
        if n:
            return (
                f"پیامک همگانی به {n} نفر از «{group}» ارسال شد.",
                REPORT_PARTNER,
                STATUS_SUCCESS,
            )
        return f"پیامک همگانی به «{group}» ارسال شد.", REPORT_PARTNER, STATUS_SUCCESS

    if ev == "admin_broadcast_push":
        n = _partner_count(sent_count)
        title = (body or "").strip()
        if int(failed_count or 0) > 0 and int(sent_count or 0) > 0:
            text = f"اعلان همگانی برای {n or 'چند'} همکار ثبت شد."
            if title:
                text = f"{text}\nموضوع: {title}"
            text += f"\nبرای {_fa_num(failed_count)} همکار ثبت نشد."
            return text, REPORT_PARTNER, STATUS_INFO
        if int(failed_count or 0) > 0 and int(sent_count or 0) <= 0:
            return "ثبت اعلان همگانی برای همکاران ناموفق بود.", REPORT_PARTNER, STATUS_ERROR
        if n:
            text = f"اعلان همگانی برای {n} همکار ثبت شد."
        else:
            text = "اعلان همگانی برای همکاران ثبت شد."
        if title:
            text = f"{text}\nموضوع: {title}"
        return text, REPORT_PARTNER, STATUS_SUCCESS

    if ev == "partner_broadcast":
        reg = (region or "").strip() or "همکاران"
        n = _partner_count(sent_count)
        if n:
            return (
                f"به {n} همکار از منطقه {reg} اطلاع داده شد که مشتری جدید آماده بازدید است.",
                REPORT_PARTNER,
                STATUS_SUCCESS,
            )
        return (
            f"به همکاران منطقه {reg} اطلاع داده شد که مشتری جدید آماده بازدید است.",
            REPORT_PARTNER,
            STATUS_SUCCESS,
        )

    # --- سیستم / خطا ---
    if ev == "daily_review":
        rc = _fa_num(reviewed_count or 0)
        fc = _fa_num(followup_count or 0)
        return (
            f"امروز {rc} پرونده را بررسی کردم.\n"
            f"{fc} مورد نیاز به پیگیری داشت که اقدامات لازم انجام شد.",
            REPORT_SYSTEM,
            STATUS_SUCCESS,
        )

    if ev == "send_error":
        mins = retry_minutes or 5
        return (
            "در ارسال پیام به یکی از همکاران خطا رخ داد.\n"
            f"سیستم تا {_fa_num(mins)} دقیقه دیگر دوباره تلاش خواهد کرد.",
            REPORT_SYSTEM,
            STATUS_ERROR,
        )

    if ev == "card_confirmed":
        cleaned = _humanize_technical_body(body, land_code=land)
        if cleaned:
            return cleaned, REPORT_SYSTEM, STATUS_SUCCESS
        return "اقدام تأیید و انجام شد.", REPORT_SYSTEM, STATUS_SUCCESS

    # نگاشت رویدادهای timeline چت
    _CHAT_EVENT_MAP: dict[str, tuple[str, str]] = {
        "land_suggested": (REPORT_CUSTOMER, STATUS_INFO),
        "visit_done_pending": (REPORT_VISIT, STATUS_IN_PROGRESS),
        "mission_started": (REPORT_CUSTOMER, STATUS_INFO),
        "mission_completed": (REPORT_CUSTOMER, STATUS_SUCCESS),
        "case_closed": (REPORT_CUSTOMER, STATUS_SUCCESS),
        "contract_created": (REPORT_DEAL, STATUS_IN_PROGRESS),
        "payment_recorded": (REPORT_DEAL, STATUS_SUCCESS),
        "commission_approved": (REPORT_DEAL, STATUS_SUCCESS),
        "commission_paid": (REPORT_DEAL, STATUS_SUCCESS),
    }
    if ev in _CHAT_EVENT_MAP:
        cat, st = _CHAT_EVENT_MAP[ev]
        from app.ai.chat_events import EVENT_LABELS

        text = _humanize_technical_body(body, land_code=land) or EVENT_LABELS.get(ev, "")
        if land and ev == "land_suggested":
            text = f"فایل {land} برای {person} پیشنهاد شد."
        return text, cat, st

    cleaned = _humanize_technical_body(body, land_code=land)
    if cleaned:
        return cleaned, REPORT_SYSTEM, STATUS_INFO
    return None


_TECHNICAL_BODY_RE = re.compile(
    r"^(?:workflow_complete|workflow_completed)[:\s]+([A-Za-z][\w]*)$",
    re.IGNORECASE,
)

_OBJECT_TYPE_FA: dict[str, str] = {
    "VisitRequest": "درخواست بازدید",
    "DealRequest": "درخواست معامله",
    "PartnerApplication": "درخواست همکاری",
    "PropertyRegistration": "ثبت فایل",
    "PropertyEditing": "ویرایش فایل",
    "SupportTicket": "تیکت پشتیبانی",
    "OfferRequest": "پیشنهاد قیمت",
    "VisitResultRequest": "نتیجه بازدید",
    "FollowupRequest": "پیگیری",
    "ContractRequest": "قرارداد",
}

# object_typeهایی که از مسیر واقعی چت (emit_chat_event) هم گزارش می‌شوند
_SHADOW_SKIP_OBJECT_TYPES = frozenset(
    {
        "VisitRequest",
        "DealRequest",
        "VisitResultRequest",
        "OfferRequest",
        "ContractRequest",
        "PartnerApplication",
    }
)

_WORKFLOW_OBJECT_EVENT: dict[str, str] = {
    "VisitRequest": "visit_requested",
    "DealRequest": "deal_started",
    "PartnerApplication": "partner_application_pending",
    "VisitResultRequest": "visit_completed",
    "OfferRequest": "deal_pending",
    "ContractRequest": "contract_created",
    "FollowupRequest": "followup_started",
    "PropertyRegistration": "customer_request_received",
}


def _looks_technical_body(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _TECHNICAL_BODY_RE.match(t):
        return True
    if ":" in t and re.search(r"[A-Za-z]{3,}", t) and not re.search(r"[\u0600-\u06FF]", t):
        return True
    return False


def _humanize_technical_body(body: str = "", *, land_code: str = "") -> str:
    """تبدیل متن فنی ذخیره‌شده به فارسی؛ اگر عادی بود همان را برمی‌گرداند."""
    raw = (body or "").strip()
    if not raw:
        return ""
    if not _looks_technical_body(raw):
        return raw
    m = _TECHNICAL_BODY_RE.match(raw)
    obj = m.group(1) if m else ""
    label = _OBJECT_TYPE_FA.get(obj) or _OBJECT_TYPE_FA.get(obj.replace("_", "")) or ""
    land = _land_ref(land_code) if land_code else ""
    if label and land:
        return f"{label} برای {land} تکمیل شد."
    if label:
        return f"{label} تکمیل شد."
    if land:
        return f"اقدام مربوط به {land} تکمیل شد."
    return "اقدام گردش‌کار تکمیل شد."


def humanize_supervisor_message_content(
    content: str,
    *,
    land_code: str = "",
    meta: dict[str, Any] | None = None,
) -> str:
    """برای نمایش پیام‌های قدیمی ناظر که هنوز متن فنی دارند."""
    meta = meta if isinstance(meta, dict) else {}
    land = str(land_code or meta.get("land_code") or "").strip()
    return _humanize_technical_body(content, land_code=land) or (content or "").strip()


def render_from_activity(
    action: str,
    *,
    summary: str = "",
    land_code: str = "",
    entity_type: str = "",
    entity_id: str = "",
    payload: dict[str, Any] | None = None,
) -> tuple[str, str, str, str] | None:
    """نگاشت فعالیت Foundation به (event, body, category, status)."""
    act = (action or "").strip()
    pl = dict(payload or {})
    fields = pl.get("fields") if isinstance(pl.get("fields"), dict) else {}
    storage = pl.get("storage") if isinstance(pl.get("storage"), dict) else {}
    land = str(
        land_code
        or pl.get("land_code")
        or fields.get("land_code")
        or fields.get("code")
        or ""
    ).strip()
    object_type = str(
        entity_type or pl.get("object_type") or fields.get("type") or ""
    ).strip()
    if not object_type and summary:
        m = _TECHNICAL_BODY_RE.match(summary.strip())
        if m:
            object_type = m.group(1)

    # phase0 shadow: مسیر واقعی چت قبلاً گزارش می‌دهد — از تکرار متن فنی پرهیز کن
    reason = str(storage.get("reason") or "").strip()
    shadowed = bool(storage.get("shadowed"))
    persisted = bool(storage.get("persisted"))
    if act == "workflow_completed" and shadowed and not persisted:
        if reason.startswith("phase0") or object_type in _SHADOW_SKIP_OBJECT_TYPES:
            return None

    if act == "workflow_completed":
        ev = _WORKFLOW_OBJECT_EVENT.get(object_type) or "card_confirmed"
        visit_time = str(
            fields.get("visit_at")
            or fields.get("scheduled_at")
            or fields.get("visit_time")
            or ""
        ).strip()
        customer_name = str(
            fields.get("visitor_name")
            or fields.get("customer_name")
            or fields.get("display_name")
            or pl.get("customer_name")
            or ""
        ).strip()
        customer_phone = str(
            fields.get("visitor_phone")
            or fields.get("customer_phone")
            or fields.get("buyer_phone")
            or pl.get("customer_phone")
            or ""
        ).strip()
        # متن فنی summary را به مدل نده
        body = ""
        if ev == "card_confirmed":
            body = _humanize_technical_body(
                summary or f"workflow_complete:{object_type or 'unknown'}",
                land_code=land,
            )
        rendered = render_report(
            ev,
            land_code=land,
            customer_phone=customer_phone,
            customer_name=customer_name,
            deal_code=land,
            visit_time=visit_time,
            body=body,
            meta={"entity_type": object_type or entity_type, "entity_id": entity_id},
        )
        if not rendered:
            return None
        text, cat, status = rendered
        return ev, text, cat, status

    _ACTIVITY_MAP: dict[str, str] = {
        "crm_lead_created": "customer_request_received",
        "commercial_negotiation_opened": "deal_started",
        "commercial_offer_proposed": "deal_pending",
        "commercial_reservation_created": "deal_pending",
        "visit_result_registered": "visit_completed",
        "visit_no_show_registered": "visit_no_show",
        "closing_contract_created": "contract_created",
        "roles_partner_approved": "partner_approved",
        "roles_partner_rejected": "partner_rejected",
    }
    ev = _ACTIVITY_MAP.get(act)
    if not ev:
        return None
    rendered = render_report(
        ev,
        land_code=land,
        customer_phone=str(
            pl.get("customer_phone")
            or pl.get("buyer_phone")
            or fields.get("visitor_phone")
            or ""
        ),
        customer_name=str(
            pl.get("display_name")
            or pl.get("customer_name")
            or fields.get("visitor_name")
            or ""
        ),
        deal_code=land,
        body="" if _looks_technical_body(summary) else summary,
        meta={"entity_type": entity_type, "entity_id": entity_id},
    )
    if not rendered:
        return None
    text, cat, status = rendered
    return ev, text, cat, status
