# -*- coding: utf-8 -*-
"""درخواست بازدید همکار از فایل اکسپرس."""
from __future__ import annotations

import os
import threading
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..utils.dates import (
    format_display_jalali_date,
    format_iso_date_jalali,
    parse_gregorian_iso_date,
    parse_jalali_date,
    to_en_digits,
    to_fa_digits,
)
from .commissions_flow import (
    commission_is_deal,
    commission_is_visit,
    has_finalized_deal_commission,
)

PENDING_STATUS = "pending"
APPROVED_STATUS = "approved"
DONE_PENDING_STATUS = "done_pending"
COMPLETED_STATUS = "completed"
CANCELLED_STATUS = "cancelled"
# Phase 2 additive — never remove the five statuses above.
NO_SHOW_STATUS = "no_show"

OPEN_VISIT_STATUSES = frozenset({PENDING_STATUS, APPROVED_STATUS, DONE_PENDING_STATUS})

PIPELINE_REQUESTS = "requests"
PIPELINE_VISITS = "visits"
PIPELINE_DEALS = "deals"
PIPELINE_TABS = frozenset({PIPELINE_REQUESTS, PIPELINE_VISITS, PIPELINE_DEALS})

STAGE_VISIT_REQUEST = "visit_request"
STAGE_VISIT = "visit"
STAGE_DEAL = "deal"
FOLLOW_STAGES = frozenset({STAGE_VISIT_REQUEST, STAGE_VISIT, STAGE_DEAL})
STAGE_LABELS = {
    STAGE_VISIT_REQUEST: "درخواست بازدید",
    STAGE_VISIT: "بازدید",
    STAGE_DEAL: "معامله",
}
DIRECTION_INCOMING = "incoming"
DIRECTION_OUTGOING = "outgoing"


def visit_is_deal_pipeline(
    *,
    visit_outcome: str = "",
    assignment_status: str = "",
    tx_status: str = "",
    deal_commission_status: str = "",
    deal_decision: str = "",
    can_start_deal: bool = False,
    can_approve_deal: bool = False,
    can_confirm_deal: bool = False,
) -> bool:
    """علاقه‌مند یا پروندهٔ در حال معامله — تب معامله."""
    del can_start_deal, can_approve_deal, can_confirm_deal
    oc = str(visit_outcome or "").strip().lower()
    if oc in ("not_interested", "follow_up"):
        return False
    if oc == "interested":
        return True
    gs = str(assignment_status or "").strip().lower()
    tx = str(tx_status or "").strip().lower()
    if gs in ("in_transaction", "sold") or tx in ("in_transaction", "sold"):
        return True
    ds = str(deal_commission_status or "").strip().lower()
    if ds in ("pending", "approved", "paid"):
        return True
    return str(deal_decision or "").strip().lower() == "approved"


def partner_request_pipeline_tab(
    status: str,
    assignment_status: str = "",
    *,
    plus_own: bool = False,
    visit_outcome: str = "",
    deal_decision: str = "",
    can_confirm_deal: bool = False,
    can_start_deal: bool = False,
    can_approve_deal: bool = False,
    deal_commission_status: str = "",
    tx_status: str = "",
) -> str:
    """ارسالی من؛ علاقه‌مند/معامله در تب معامله می‌رود."""
    del status, plus_own
    if visit_is_deal_pipeline(
        visit_outcome=visit_outcome,
        assignment_status=assignment_status,
        tx_status=tx_status,
        deal_commission_status=deal_commission_status,
        deal_decision=deal_decision,
        can_start_deal=can_start_deal,
        can_approve_deal=can_approve_deal,
        can_confirm_deal=can_confirm_deal,
    ):
        return PIPELINE_DEALS
    return PIPELINE_REQUESTS


def visit_requests_auto_approve_enabled() -> bool:
    """
    پیش‌فرض ON: درخواست بازدید و اعلام انجام بدون صف تأیید ادمین نهایی می‌شوند.
    خاموش با VINOR_VISIT_REQUESTS_AUTO_APPROVE=0
    """
    import os

    return (os.environ.get("VINOR_VISIT_REQUESTS_AUTO_APPROVE") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

VISIT_PROGRESS_STEP_KEYS = (
    ("visit_requested", "درخواست بازدید"),
    ("visit_approved", "نهایی شدن بازدید"),
    ("visit_done", "بازدید انجام شد"),
    ("deal_requested", "درخواست معامله"),
    ("deal_approved", "تأیید درخواست معامله"),
    ("deal_commission_paid", "واریز پورسانت فروش"),
)

# روز هفته برای تنظیمات ادمین (هم‌تراز recurrence_weekday در پیامک زمان‌دار)
VISIT_WEEKDAY_SAT = 5
VISIT_WEEKDAY_SUN = 6
VISIT_WEEKDAY_MON = 0
VISIT_WEEKDAY_TUE = 1
VISIT_WEEKDAY_WED = 2
VISIT_WEEKDAY_THU = 3
VISIT_WEEKDAY_FRI = 4

VISIT_WEEKDAY_LABELS: Dict[int, str] = {
    VISIT_WEEKDAY_SAT: "شنبه",
    VISIT_WEEKDAY_SUN: "یکشنبه",
    VISIT_WEEKDAY_MON: "دوشنبه",
    VISIT_WEEKDAY_TUE: "سه‌شنبه",
    VISIT_WEEKDAY_WED: "چهارشنبه",
    VISIT_WEEKDAY_THU: "پنجشنبه",
    VISIT_WEEKDAY_FRI: "جمعه",
}

VISIT_WEEKDAY_ORDER = (
    VISIT_WEEKDAY_SAT,
    VISIT_WEEKDAY_SUN,
    VISIT_WEEKDAY_MON,
    VISIT_WEEKDAY_TUE,
    VISIT_WEEKDAY_WED,
    VISIT_WEEKDAY_THU,
    VISIT_WEEKDAY_FRI,
)

DEFAULT_VISIT_ALLOWED_WEEKDAYS = list(VISIT_WEEKDAY_ORDER)

# ساعت‌های مجاز بازدید (تهران) — پیش‌فرض نوبت‌های معمول ملک
DEFAULT_VISIT_ALLOWED_HOURS = list(range(8, 18))  # ۸:۰۰ تا ۱۷:۰۰
VISIT_HOUR_UI_RANGE = range(7, 22)

# Python weekday (دوشنبه=۰ … جمعه=۴، شنبه=۵، یکشنبه=۶) → JS Date.getDay()
_PY_WEEKDAY_TO_JS = {
    VISIT_WEEKDAY_SAT: 6,
    VISIT_WEEKDAY_SUN: 0,
    VISIT_WEEKDAY_MON: 1,
    VISIT_WEEKDAY_TUE: 2,
    VISIT_WEEKDAY_WED: 3,
    VISIT_WEEKDAY_THU: 4,
    VISIT_WEEKDAY_FRI: 5,
}


def _today() -> date:
    try:
        from ..utils.dates import tehran_today
        return tehran_today()
    except Exception:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo("Asia/Tehran")).date()
        except Exception:
            return datetime.utcnow().date()


def visit_slot_has_passed(row: Dict[str, Any] | None) -> bool:
    """وقت برنامه‌ریزی‌شدهٔ بازدید نسبت به الان تهران گذشته است."""
    if not isinstance(row, dict):
        return False
    vd = _parse_visit_date(row.get("visit_date"))
    if vd is None:
        return False
    try:
        from ..utils.dates import tehran_now

        now = tehran_now()
    except Exception:
        now = datetime.utcnow()
    hour = parse_visit_hour(row.get("visit_time") or row.get("time") or "")
    if now.date() > vd:
        return True
    if now.date() < vd:
        return False
    if hour is None:
        plus = str(row.get("plus_user_phone") or "")
        return not remaining_visit_hours_for_date(vd, plus_user_phone=plus)
    return int(now.hour) > hour or (int(now.hour) == hour and int(getattr(now, "minute", 0) or 0) > 0)


def visit_date_min_iso() -> str:
    """حداقل تاریخ قابل انتخاب بازدید — اگر امروز نوبتی نمانده، اولین روز مجاز بعدی."""
    slot = next_auto_visit_date()
    if slot and slot.get("iso"):
        return str(slot["iso"])
    return _today().isoformat()


def visit_schedule_for_land(land_code: str) -> Dict[str, Any]:
    """همان مقادیر landDetailConfig: visitDateMin، visitAllowedWeekdays، visitAllowedHours."""
    code = str(land_code or "").strip()
    return {
        "visit_date_min": visit_date_min_iso(),
        "visit_date_max": (_today() + timedelta(days=90)).isoformat(),
        "visit_allowed_weekdays": list(visit_allowed_weekdays_for_js()),
        "visit_allowed_hours": list(get_visit_allowed_hours()),
        "visit_request_url": f"/express/partner/visit-requests/{code}" if code else "",
    }


def split_visitor_name(full: str) -> Tuple[str, str]:
    """«علی رضایی» → نام و نام خانوادگی. یک واژه فقط در نام می‌ماند."""
    parts = [p for p in str(full or "").split() if p.strip()]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _canonical_customer_mobile(raw: str) -> str:
    from app.services.sms import is_valid_iran_mobile, normalize_iran_mobile

    phone = normalize_iran_mobile(raw)
    return phone if is_valid_iran_mobile(phone) else ""


def resolve_visit_customer_fields(
    *,
    is_advisor: bool,
    account_name: str,
    account_phone: str,
    customer_first_name: str = "",
    customer_last_name: str = "",
    customer_phone_raw: str = "",
) -> Tuple[str, str, str, Optional[str]]:
    """نام و موبایل ذخیره‌شده روی درخواست بازدید.

    خریدار: نام و موبایل از پروفایل/حساب، بدون توجه به فیلدهای ارسالی.
    مشاور: نام مشتری اختیاری است؛ اگر خالی باشد نام خود مشاور ذخیره می‌شود.
    موبایل مشتری برای مشاور اختیاری است و فقط مقدار پرِ نامعتبر رد می‌شود.
    """
    account_name_s = str(account_name or "").strip()
    if is_advisor:
        first = str(customer_first_name or "").strip()
        last = str(customer_last_name or "").strip()
        if not first and not last:
            first, last = split_visitor_name(account_name_s)
        raw_phone = str(customer_phone_raw or "").strip()
        if not raw_phone:
            return first, last, "", None
        phone = _canonical_customer_mobile(raw_phone)
        if not phone:
            return "", "", "", "شماره تماس مشتری معتبر نیست."
        return first, last, phone, None

    first, last = split_visitor_name(account_name_s)
    phone = _canonical_customer_mobile(account_phone)
    if not phone:
        return "", "", "", "شماره تماس حساب شما معتبر نیست."
    return first, last, phone, None


def visit_booking_hints(
    *,
    is_advisor: bool,
    account_name: str,
    account_phone: str,
) -> Dict[str, Any]:
    """فیلدهایی که اپ برای فرم بازدید لازم دارد."""
    return {
        "is_advisor": bool(is_advisor),
        "prefilled_name": str(account_name or "").strip(),
        "prefilled_phone": _canonical_customer_mobile(account_phone),
        "show_customer_fields": bool(is_advisor),
        "customer_name_optional": True,
        "customer_phone_optional": True,
    }


def _normalize_weekday_list(raw: Any) -> List[int]:
    if not isinstance(raw, (list, tuple, set)):
        return list(DEFAULT_VISIT_ALLOWED_WEEKDAYS)
    out: List[int] = []
    for item in raw:
        try:
            wd = int(item)
        except (TypeError, ValueError):
            continue
        if wd in VISIT_WEEKDAY_LABELS and wd not in out:
            out.append(wd)
    return out or list(DEFAULT_VISIT_ALLOWED_WEEKDAYS)


def _plus_partner_record(phone: str) -> Optional[Dict[str, Any]]:
    ph = _canonical_visit_phone(phone) if phone else ""
    if not ph:
        ph = str(phone or "").strip()
    if not ph:
        return None
    try:
        from .partner_roles import partner_is_special
        from .partner_session_sync import find_partner_record
        from ..utils.storage import load_express_partners

        rec = find_partner_record(load_express_partners() or [], ph)
        if rec is None or not partner_is_special(rec):
            return None
        return rec
    except Exception:
        return None


def plus_phone_for_land_code(land_code: str) -> str:
    """شمارهٔ همکار پلاس مالک فایل — برای تقویم و وقت بازدید."""
    code = str(land_code or "").strip()
    if not code:
        return ""
    try:
        from .special_listings import plus_listing_owner_by_code

        owner = (plus_listing_owner_by_code() or {}).get(code) or {}
        return _canonical_visit_phone(owner.get("phone")) or str(owner.get("phone") or "").strip()
    except Exception:
        return ""


def _global_visit_allowed_weekdays() -> List[int]:
    try:
        from admin.routes import get_settings

        settings = get_settings() or {}
        return _normalize_weekday_list(settings.get("visit_allowed_weekdays"))
    except Exception:
        return list(DEFAULT_VISIT_ALLOWED_WEEKDAYS)


def get_visit_allowed_weekdays(*, plus_user_phone: str = "") -> List[int]:
    rec = _plus_partner_record(plus_user_phone) if plus_user_phone else None
    if rec is not None and rec.get("visit_allowed_weekdays") is not None:
        return _normalize_weekday_list(rec.get("visit_allowed_weekdays"))
    return _global_visit_allowed_weekdays()


def save_visit_allowed_weekdays(weekdays: List[int]) -> List[int]:
    from admin.routes import save_settings

    normalized = _normalize_weekday_list(weekdays)
    save_settings({"visit_allowed_weekdays": normalized})
    return normalized


def parse_visit_hour(raw: Any) -> Optional[int]:
    """«۱۰»، «10:00»، «۱۰:۳۰» → ساعت ۰…۲۳."""
    s = to_en_digits(str(raw or "")).strip()
    if not s:
        return None
    s = s.replace(".", ":").replace(" ", "")
    if ":" in s:
        s = s.split(":", 1)[0]
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return None
    try:
        h = int(digits)
    except ValueError:
        return None
    if 0 <= h <= 23:
        return h
    return None


def format_visit_hour_label(hour: int) -> str:
    return to_fa_digits(f"{int(hour):02d}:00")


def format_visit_time_stored(hour: int) -> str:
    return f"{int(hour):02d}:00"


def _normalize_hour_list(raw: Any) -> List[int]:
    if not isinstance(raw, (list, tuple, set)):
        return list(DEFAULT_VISIT_ALLOWED_HOURS)
    out: List[int] = []
    for item in raw:
        if isinstance(item, bool):
            continue
        h: Optional[int]
        if isinstance(item, int):
            h = item if 0 <= item <= 23 else None
        else:
            h = parse_visit_hour(item)
        if h is None or h in out:
            continue
        out.append(h)
    out.sort()
    return out or list(DEFAULT_VISIT_ALLOWED_HOURS)


def _legacy_hours_needs_reset(raw: Any) -> bool:
    return list(raw or []) == [10, 11, 12, 14, 15, 16]


def _global_visit_allowed_hours() -> List[int]:
    try:
        from admin.routes import get_settings

        settings = get_settings() or {}
        raw = settings.get("visit_allowed_hours")
        # پیش‌فرض قبلی ۱۰–۱۶ بدون ۸/۹/۱۳/۱۷ — اگر هنوز همان است، پیش‌فرض جدید اعمال شود
        if _legacy_hours_needs_reset(raw):
            raw = None
        return _normalize_hour_list(raw)
    except Exception:
        return list(DEFAULT_VISIT_ALLOWED_HOURS)


def get_visit_allowed_hours(*, plus_user_phone: str = "") -> List[int]:
    rec = _plus_partner_record(plus_user_phone) if plus_user_phone else None
    if rec is not None and rec.get("visit_allowed_hours") is not None:
        raw = rec.get("visit_allowed_hours")
        if _legacy_hours_needs_reset(raw):
            raw = None
        if raw is not None:
            return _normalize_hour_list(raw)
    return _global_visit_allowed_hours()


def save_visit_allowed_hours(hours: List[int]) -> List[int]:
    from admin.routes import save_settings

    normalized = _normalize_hour_list(hours)
    save_settings({"visit_allowed_hours": normalized})
    return normalized


def save_visit_schedule(*, weekdays: List[int], hours: List[int]) -> Tuple[List[int], List[int]]:
    """یک‌بار ذخیرهٔ روز + ساعت مجاز (سراسری — پیش‌فرض وقتی پلاس تنظیم نکرده)."""
    from admin.routes import save_settings

    days = _normalize_weekday_list(weekdays)
    hrs = _normalize_hour_list(hours)
    save_settings({
        "visit_allowed_weekdays": days,
        "visit_allowed_hours": hrs,
    })
    return days, hrs


def save_plus_visit_schedule(
    phone: str,
    *,
    weekdays: List[int],
    hours: List[int],
    presence_address: str | None = None,
) -> Tuple[Optional[List[int]], Optional[List[int]], str]:
    """ذخیرهٔ وقت بازدید روی رکورد همکار پلاس. خطای خالی یعنی موفق."""
    from .partner_roles import partner_is_special
    from .partner_session_sync import find_partner_record
    from ..utils.storage import load_express_partners, save_express_partners

    ph = _canonical_visit_phone(phone) or str(phone or "").strip()
    if not ph:
        return None, None, "کاربر شناسایی نشد."
    partners = load_express_partners() or []
    rec = find_partner_record(partners, ph)
    if rec is None or not partner_is_special(rec):
        return None, None, "فقط همکار پلاس می‌تواند وقت بازدید را تنظیم کند."
    days = _normalize_weekday_list(weekdays)
    hrs = _normalize_hour_list(hours)
    rec["visit_allowed_weekdays"] = days
    rec["visit_allowed_hours"] = hrs
    if presence_address is not None:
        rec["visit_presence_address"] = _normalize_presence_address(presence_address)
    save_express_partners(partners)
    return days, hrs, ""


VISIT_PRESENCE_ADDRESS_MAX = 200


def _normalize_presence_address(raw: Any) -> str:
    text = " ".join(str(raw or "").replace("\r", "\n").split())
    if len(text) > VISIT_PRESENCE_ADDRESS_MAX:
        text = text[:VISIT_PRESENCE_ADDRESS_MAX].rstrip()
    return text


def get_plus_visit_presence_address(phone: str = "") -> str:
    rec = _plus_partner_record(phone) if phone else None
    if rec is None:
        return ""
    return _normalize_presence_address(rec.get("visit_presence_address"))


def resolve_visit_presence_address(
    *,
    stored: str = "",
    plus_user_phone: str = "",
    land_code: str = "",
) -> str:
    """آدرس حضور ذخیره‌شده روی بازدید، وگرنه آدرس فعلی کاربر پلاس."""
    addr = _normalize_presence_address(stored)
    if addr:
        return addr
    plus = (plus_user_phone or "").strip()
    if not plus and land_code:
        plus = plus_phone_for_land_code(land_code)
    return get_plus_visit_presence_address(plus) if plus else ""


def visit_allowed_hours_summary(*, plus_user_phone: str = "") -> str:
    hours = get_visit_allowed_hours(plus_user_phone=plus_user_phone)
    return "، ".join(format_visit_hour_label(h) for h in hours)


def visit_hour_rows(
    *,
    selected: Optional[List[int]] = None,
    plus_user_phone: str = "",
) -> List[Dict[str, Any]]:
    chosen = set(
        selected if selected is not None else get_visit_allowed_hours(plus_user_phone=plus_user_phone)
    )
    hours = list(VISIT_HOUR_UI_RANGE)
    for h in sorted(chosen):
        if h not in hours:
            hours.append(h)
    hours.sort()
    return [
        {"hour": h, "label": f"{h:02d}:00", "selected": h in chosen}
        for h in hours
    ]


def remaining_visit_hours_for_date(
    d: date,
    *,
    hours: Optional[List[int]] = None,
    occupied: Optional[set] = None,
    plus_user_phone: str = "",
) -> List[int]:
    """نوبت‌های باقی‌ماندهٔ یک روز (تهران). امروز: ساعت‌های شروع‌نشده."""
    allowed = _normalize_hour_list(
        hours if hours is not None else get_visit_allowed_hours(plus_user_phone=plus_user_phone)
    )
    today = _today()
    if d < today:
        return []
    if d > today:
        remain = list(allowed)
    else:
        try:
            from ..utils.dates import tehran_now
            now_h = int(tehran_now().hour)
        except Exception:
            now_h = datetime.utcnow().hour
        remain = [h for h in allowed if h > now_h]
    if occupied:
        remain = [h for h in remain if h not in occupied]
    return remain


def _phone_digits(raw: Any) -> str:
    return "".join(ch for ch in to_en_digits(str(raw or "")) if ch.isdigit())


def _phones_match(left: Any, right: Any) -> bool:
    """09 و 98 و ده رقم آخر یکی‌اند."""
    a = _canonical_visit_phone(left)
    b = _canonical_visit_phone(right)
    if a and b and a == b:
        return True
    da = _phone_digits(left)
    db = _phone_digits(right)
    return len(da) >= 10 and len(db) >= 10 and da[-10:] == db[-10:]


def _canonical_visit_phone(raw: Any) -> str:
    phone = str(raw or "").strip()
    if not phone:
        return ""
    try:
        from .partner_session_sync import canonical_partner_phone

        return canonical_partner_phone(phone) or phone
    except Exception:
        return phone


def visit_card_call_phones(
    *,
    me_phone: str = "",
    visitor_phone: str = "",
    marketer_phone: str = "",
    customer_phone: str = "",
) -> Dict[str, str]:
    """شمارهٔ تماس روی کارت — شمارهٔ خودِ بیننده حذف می‌شود."""
    me = _canonical_visit_phone(me_phone)

    def pick(raw: str) -> str:
        p = str(raw or "").strip()
        if not p:
            return ""
        if me and _canonical_visit_phone(p) == me:
            return ""
        return p

    vis = pick(visitor_phone)
    mkt = pick(marketer_phone)
    cust = pick(customer_phone)
    vis_n = _canonical_visit_phone(vis)
    mkt_n = _canonical_visit_phone(mkt)
    cust_n = _canonical_visit_phone(cust)
    if mkt_n and vis_n and mkt_n == vis_n:
        mkt = ""
    if cust_n and vis_n and cust_n == vis_n:
        cust = ""
    if cust_n and mkt_n and cust_n == mkt_n:
        cust = ""
    return {
        "call_visitor_phone": vis,
        "call_marketer_phone": mkt,
        "call_customer_phone": cust,
    }


def _default_visit_admin_key() -> str:
    """تقویم مشترک وقتی کاربر پلاس انتخاب نشده — همان ادمین هماهنگی بازدید."""
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            from ..utils.storage import load_settings
            from ..services.sms import is_valid_iran_mobile, normalize_iran_mobile

            settings = load_settings(current_app) or {}
            raw = str(settings.get("partner_application_admin_phone") or "").strip()
            phone = normalize_iran_mobile(raw)
            if is_valid_iran_mobile(phone):
                return phone
    except Exception:
        pass
    try:
        from app.crm.config import VISIT_CALL_TARGET
        from ..services.sms import is_valid_iran_mobile, normalize_iran_mobile

        fallback = normalize_iran_mobile(str(VISIT_CALL_TARGET or "").strip())
        if is_valid_iran_mobile(fallback):
            return fallback
    except Exception:
        pass
    return "__default_admin__"


def visit_admin_identity(row: Dict[str, Any] | None = None, *, plus_phone: str = "") -> str:
    """کلید تقویم ادمین: کاربر پلاس انتخاب‌شده، وگرنه ادمین پیش‌فرض."""
    if isinstance(row, dict):
        plus = _canonical_visit_phone(row.get("plus_user_phone"))
        if plus:
            return plus
    extra = _canonical_visit_phone(plus_phone)
    if extra:
        return extra
    return _default_visit_admin_key()


def _load_visit_rows() -> List[Dict[str, Any]]:
    try:
        from ..utils.storage import load_express_visit_requests

        rows = load_express_visit_requests() or []
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def occupied_visit_hours(
    requests: Optional[List[Dict[str, Any]]],
    *,
    visit_day: date,
    admin_key: str,
) -> set:
    """ساعت‌هایی که برای این ادمین در آن روز بازدید باز دارند."""
    occupied: set = set()
    want = str(admin_key or "").strip()
    if not want:
        want = _default_visit_admin_key()
    iso = visit_day.isoformat()
    for row in requests or []:
        if not isinstance(row, dict):
            continue
        st = str(row.get("status") or "").strip()
        if st not in OPEN_VISIT_STATUSES:
            continue
        if str(row.get("visit_date") or "").strip() != iso:
            continue
        if visit_admin_identity(row) != want:
            continue
        hour = parse_visit_hour(row.get("visit_time") or row.get("time") or "")
        if hour is not None:
            occupied.add(int(hour))
    return occupied


def resolve_free_visit_slot(
    requests: Optional[List[Dict[str, Any]]] = None,
    *,
    visit_day: Optional[date] = None,
    visit_hour: Optional[int] = None,
    plus_user_phone: str = "",
    days_ahead: int = 90,
) -> Optional[Tuple[date, int]]:
    """اولین نوبت خالی این ادمین — اگر ساعت پر باشد، ساعت بعدی همان روز یا روز بعد."""
    rows = requests if requests is not None else _load_visit_rows()
    admin_key = visit_admin_identity(None, plus_phone=plus_user_phone)
    allowed_days = get_visit_allowed_weekdays(plus_user_phone=plus_user_phone)
    allowed_hours = get_visit_allowed_hours(plus_user_phone=plus_user_phone)
    today = _today()
    start = visit_day or today
    if start < today:
        start = today
    end = today + timedelta(days=max(1, int(days_ahead) or 90))
    d = start
    min_hour = int(visit_hour) if visit_hour is not None else None
    while d <= end:
        if is_visit_weekday_allowed(d, allowed=allowed_days):
            occ = occupied_visit_hours(rows, visit_day=d, admin_key=admin_key)
            remain = remaining_visit_hours_for_date(d, hours=allowed_hours, occupied=occ)
            if d == start and min_hour is not None:
                if min_hour in remain:
                    return d, min_hour
                remain = [h for h in remain if h > min_hour]
            if remain:
                return d, remain[0]
        d += timedelta(days=1)
        min_hour = None
    return None


def format_visit_slot_hint(slot: Optional[Dict[str, Any]]) -> str:
    if not isinstance(slot, dict):
        return ""
    weekday = str(slot.get("weekday") or "").strip()
    jalali = str(slot.get("jalali_fa") or slot.get("jalali") or "").strip()
    time_label = str(slot.get("time") or "").strip()
    parts = [p for p in (weekday, jalali) if p]
    label = " ".join(parts)
    if time_label:
        label = (label + " ساعت " + time_label).strip()
    return label


def visit_allowed_weekdays_for_js(*, plus_user_phone: str = "") -> List[int]:
    return [
        _PY_WEEKDAY_TO_JS[wd]
        for wd in get_visit_allowed_weekdays(plus_user_phone=plus_user_phone)
        if wd in _PY_WEEKDAY_TO_JS
    ]


def visit_weekday_label_for_date(d: date) -> str:
    return VISIT_WEEKDAY_LABELS.get(d.weekday(), "")


def is_visit_weekday_allowed(
    d: date,
    *,
    allowed: Optional[List[int]] = None,
    plus_user_phone: str = "",
) -> bool:
    days = _normalize_weekday_list(
        allowed if allowed is not None else get_visit_allowed_weekdays(plus_user_phone=plus_user_phone)
    )
    return d.weekday() in days


def visit_allowed_weekdays_summary(*, plus_user_phone: str = "") -> str:
    days = get_visit_allowed_weekdays(plus_user_phone=plus_user_phone)
    return "، ".join(VISIT_WEEKDAY_LABELS.get(wd, str(wd)) for wd in VISIT_WEEKDAY_ORDER if wd in days)


def list_upcoming_visit_dates(
    *,
    limit: int = 7,
    days_ahead: int = 90,
    plus_user_phone: str = "",
    requests: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """تاریخ‌های مجاز بعدی برای انتخاب در چت — شماره‌دار، فقط برچسب شمسی."""
    today = _today()
    end = today + timedelta(days=max(1, int(days_ahead) or 90))
    out: List[Dict[str, Any]] = []
    d = today
    n = 1
    lim = max(1, min(int(limit) or 7, 15))
    rows = requests if requests is not None else _load_visit_rows()
    admin_key = visit_admin_identity(None, plus_phone=plus_user_phone)
    allowed_days = get_visit_allowed_weekdays(plus_user_phone=plus_user_phone)
    allowed_hours = get_visit_allowed_hours(plus_user_phone=plus_user_phone)
    while d <= end and len(out) < lim:
        if is_visit_weekday_allowed(d, allowed=allowed_days):
            occ = occupied_visit_hours(rows, visit_day=d, admin_key=admin_key)
            remain = remaining_visit_hours_for_date(d, hours=allowed_hours, occupied=occ)
            if remain:
                iso = d.isoformat()
                jalali = format_iso_date_jalali(iso) or ""
                jalali_fa = format_display_jalali_date(iso)
                weekday = visit_weekday_label_for_date(d)
                n_fa = to_fa_digits(n)
                first_h = remain[0]
                time_label = format_visit_hour_label(first_h)
                time_en = format_visit_time_stored(first_h)
                out.append(
                    {
                        "n": n,
                        "iso": iso,  # داخلی — به کاربر نشان داده نشود
                        "jalali": jalali,
                        "jalali_fa": jalali_fa,
                        "weekday": weekday,
                        "hour": first_h,
                        "time": time_label,
                        "time_en": time_en,
                        "hours": remain,
                        "label": f"{n_fa}) {weekday} {jalali_fa}",
                    }
                )
                n += 1
        d += timedelta(days=1)
    return out


def next_auto_visit_date(
    *,
    plus_user_phone: str = "",
    requests: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """اولین نوبت خالی این ادمین — اگر ساعت پر باشد، ساعت بعدی."""
    dates = list_upcoming_visit_dates(
        limit=1,
        plus_user_phone=plus_user_phone,
        requests=requests,
    )
    return dates[0] if dates else None


def list_upcoming_visit_slots(
    *,
    limit: int = 10,
    days_ahead: int = 90,
    plus_user_phone: str = "",
    requests: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """نوبت‌های خالی بعدی (تاریخ + ساعت) برای انتخاب در مدال ثبت مشتری."""
    cap = max(1, min(int(limit) or 10, 16))
    dates = list_upcoming_visit_dates(
        limit=cap,
        days_ahead=days_ahead,
        plus_user_phone=plus_user_phone,
        requests=requests,
    )
    out: List[Dict[str, Any]] = []
    for row in dates:
        if not isinstance(row, dict):
            continue
        iso = str(row.get("iso") or "").strip()
        weekday = str(row.get("weekday") or "").strip()
        jalali_fa = str(row.get("jalali_fa") or row.get("jalali") or "").strip()
        hours = row.get("hours")
        if not isinstance(hours, list) or not hours:
            hour = row.get("hour")
            hours = [hour] if hour is not None else []
        for raw_h in hours:
            try:
                hour = int(raw_h)
            except (TypeError, ValueError):
                continue
            if hour < 0 or hour > 23:
                continue
            time_label = format_visit_hour_label(hour)
            time_en = format_visit_time_stored(hour)
            label = " ".join(p for p in (weekday, jalali_fa) if p)
            if time_label:
                label = f"{label} ساعت {time_label}".strip()
            out.append(
                {
                    "iso": iso,
                    "hour": hour,
                    "time": time_label,
                    "time_en": time_en,
                    "weekday": weekday,
                    "jalali_fa": jalali_fa,
                    "value": f"{iso}|{hour:02d}",
                    "label": label,
                    "sub": time_label,
                }
            )
            if len(out) >= cap:
                return out
    return out


def partner_visits_for_phone(
    requests: List[Dict[str, Any]],
    phone: str,
) -> List[Dict[str, Any]]:
    """همهٔ درخواست‌های بازدید یک همکار — جدید به قدیم."""
    ph = _canonical_visit_phone(phone) or (phone or "").strip()
    if not ph:
        return []
    out: List[Dict[str, Any]] = []
    for r in requests or []:
        if not isinstance(r, dict):
            continue
        rec_ph = str(r.get("partner_phone") or "").strip()
        if rec_ph != ph and _canonical_visit_phone(rec_ph) != ph:
            continue
        out.append(r)
    out.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return out


def list_plus_users_for_visit(exclude_phone: str = "") -> List[Dict[str, str]]:
    """همهٔ همکاران پلاس (ویژه) برای انتخاب در ثبت وقت بازدید."""
    from .partner_roles import PARTNER_TIER_SPECIAL
    from .partner_session_sync import canonical_partner_phone

    del exclude_phone  # همهٔ پلاس‌ها در لیست می‌مانند
    plus_tiers = {PARTNER_TIER_SPECIAL, "vip", "ویژه"}
    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    try:
        from ..utils.storage import load_express_partners

        partners = load_express_partners() or []
    except Exception:
        partners = []
    for p in partners:
        if not isinstance(p, dict):
            continue
        tier = str(p.get("partner_tier") or "").strip().lower()
        if tier not in plus_tiers:
            continue
        raw_phone = str(p.get("phone") or "").strip()
        phone = canonical_partner_phone(raw_phone) or raw_phone
        if not phone or phone in seen:
            continue
        seen.add(phone)
        name = str(p.get("name") or "").strip() or phone
        out.append({"phone": phone, "name": name})
    out.sort(key=lambda x: str(x.get("name") or ""))
    return out


def visit_request_display_title(row: Dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return "وقت بازدید"
    code = str(row.get("land_code") or "").strip()
    land_title = str(row.get("land_title") or "").strip()
    plus_name = str(row.get("plus_user_name") or "").strip()
    plus_phone = str(row.get("plus_user_phone") or "").strip()
    if land_title and land_title not in ("وقت بازدید", "فایل"):
        return land_title
    if code:
        return land_title or code
    if plus_name or plus_phone:
        return f"کاربر پلاس — {plus_name or plus_phone}"
    return "وقت بازدید"


def format_visit_stamp_label(raw: Any) -> str:
    """ISO یا تاریخ → برچسب شمسی برای جزئیات کارت."""
    s = str(raw or "").strip()
    if not s:
        return ""
    day = s[:10]
    jalali = ""
    try:
        jalali = format_display_jalali_date(day) or format_iso_date_jalali(day) or ""
    except Exception:
        jalali = ""
    time_bit = ""
    if "T" in s:
        time_bit = s.split("T", 1)[1][:5].replace("Z", "").strip()
    if jalali and time_bit:
        return f"{jalali} — {to_fa_digits(time_bit)}"
    return jalali or to_fa_digits(s)


def visit_card_when(row: Dict[str, Any] | None) -> Dict[str, str]:
    """تاریخ و ساعت بازدید برای روی کارت."""
    rec = row if isinstance(row, dict) else {}
    visit_date = str(rec.get("visit_date") or "").strip()
    jalali = ""
    try:
        jalali = format_display_jalali_date(visit_date) or format_iso_date_jalali(visit_date) or ""
    except Exception:
        jalali = format_iso_date_jalali(visit_date) if visit_date else ""
    weekday = ""
    try:
        d = parse_gregorian_iso_date(visit_date)
        if d is not None:
            weekday = visit_weekday_label_for_date(d)
    except Exception:
        weekday = ""
    visit_time_raw = str(rec.get("visit_time") or rec.get("time") or "").strip()
    hour = parse_visit_hour(visit_time_raw)
    if hour is not None:
        visit_time = format_visit_hour_label(hour)
    elif visit_time_raw:
        visit_time = to_fa_digits(visit_time_raw)
    else:
        visit_time = ""
    date_label = " ".join(p for p in (weekday, jalali) if p)
    visit_when = date_label
    if visit_time:
        visit_when = f"{visit_when} — ساعت {visit_time}".strip(" —")
    return {
        "visit_date": visit_date,
        "visit_date_jalali": jalali,
        "visit_weekday": weekday,
        "visit_date_label": date_label or "—",
        "visit_time": visit_time,
        "visit_when": visit_when,
    }


def visit_card_people(row: Dict[str, Any] | None) -> Dict[str, str]:
    """ویزیتور = میزبان تقویم پلاس · بازاریاب = همکار درخواست‌دهنده · مشتری."""
    rec = row if isinstance(row, dict) else {}
    first = str(rec.get("customer_first_name") or "").strip()
    last = str(rec.get("customer_last_name") or "").strip()
    cust_name = str(rec.get("customer_name") or "").strip() or f"{first} {last}".strip()
    cust_phone = str(rec.get("customer_phone") or "").strip()
    partner_phone = str(rec.get("partner_phone") or "").strip()
    partner_name = str(rec.get("partner_name") or "").strip() or partner_phone
    plus_phone = str(rec.get("plus_user_phone") or "").strip()
    plus_name = str(rec.get("plus_user_name") or "").strip() or plus_phone
    return {
        "customer_name": cust_name,
        "customer_phone": cust_phone,
        "partner_name": partner_name,
        "partner_phone": partner_phone,
        "plus_user_name": plus_name,
        "plus_user_phone": plus_phone,
        "marketer_name": partner_name or "—",
        "marketer_phone": partner_phone,
        "visitor_name": plus_name or "—",
        "visitor_phone": plus_phone,
    }


def partner_request_feed_item(
    row: Dict[str, Any],
    commissions: List[Dict[str, Any]] | None = None,
    *,
    can_revisit: bool = False,
    support_phone: str = "",
    assignment_status: str = "",
    allow_attendance: bool = False,
    allow_deal: bool = False,
    allow_revisit: bool = True,
    plus_own: bool = False,
    me_phone: str = "",
) -> Dict[str, Any]:
    """کارت سادهٔ صفحهٔ درخواست‌ها برای همکار."""
    del commissions  # پورسانت در کارت ساده لازم نیست
    st = (str(row.get("status") or PENDING_STATUS)).strip()
    assign_st = str(assignment_status or "").strip().lower()
    labels = {
        PENDING_STATUS: "در جریان",
        APPROVED_STATUS: "زمان‌بندی شده",
        DONE_PENDING_STATUS: "منتظر تأیید",
        COMPLETED_STATUS: "انجام شد",
        CANCELLED_STATUS: "لغو شده",
        NO_SHOW_STATUS: "عدم حضور",
    }
    deal_dec = visit_deal_decision(row)
    if st == COMPLETED_STATUS and deal_dec == DEAL_DECISION_APPROVED:
        labels[COMPLETED_STATUS] = "معامله تأیید شد"
    elif st == COMPLETED_STATUS and deal_dec == DEAL_DECISION_REJECTED:
        labels[COMPLETED_STATUS] = "معامله رد شد"
    elif st == COMPLETED_STATUS and deal_dec == DEAL_DECISION_CLOSED:
        labels[COMPLETED_STATUS] = "بسته شد"
    people = visit_card_people(row)
    when = visit_card_when(row)
    notes = str(row.get("notes") or "").strip()
    land_code = str(row.get("land_code") or "").strip()
    land_title = visit_request_display_title(row)
    plus_user_name = people["plus_user_name"]
    plus_user_phone = people["plus_user_phone"]
    presence_address = _normalize_presence_address(row.get("visit_presence_address"))
    if not presence_address and plus_user_phone:
        presence_address = get_plus_visit_presence_address(plus_user_phone)
    support = (support_phone or "").strip()
    can_cancel = st in (PENDING_STATUS, APPROVED_STATUS)
    can_delete = st in (CANCELLED_STATUS, NO_SHOW_STATUS, COMPLETED_STATUS)
    can_mark_attendance = bool(allow_attendance) and st in (APPROVED_STATUS, DONE_PENDING_STATUS)
    can_complete = can_mark_attendance
    can_no_show = can_mark_attendance
    outcome = visit_outcome(row)
    if st == COMPLETED_STATUS and outcome == VISIT_OUTCOME_INTERESTED:
        labels[COMPLETED_STATUS] = "علاقه‌مند — وقت دوم یا قرارداد"
    elif st == COMPLETED_STATUS and outcome == VISIT_OUTCOME_FOLLOW_UP:
        labels[COMPLETED_STATUS] = "پیگیری دوباره"
    elif st == COMPLETED_STATUS and outcome == VISIT_OUTCOME_NOT_INTERESTED:
        labels[COMPLETED_STATUS] = "بی‌علاقه — بدون پیگیری"
    deal_flags = visit_deal_action_flags(row, allowed=bool(allow_deal))
    waiting_result = st == COMPLETED_STATUS and not outcome and not deal_dec
    if waiting_result or outcome in (VISIT_OUTCOME_NOT_INTERESTED, VISIT_OUTCOME_FOLLOW_UP):
        deal_flags = {
            "can_confirm_deal": False,
            "can_reject_deal": False,
            "can_close_deal": False,
        }
    can_register_result = bool(allow_deal) and waiting_result
    gs_ok = assign_st not in ("sold", "in_transaction")
    show_revisit = bool(allow_revisit) and (
        bool(can_revisit)
        or (
            st == COMPLETED_STATUS
            and outcome in (VISIT_OUTCOME_FOLLOW_UP, VISIT_OUTCOME_INTERESTED)
            and bool(land_code)
            and gs_ok
        )
    )
    calls = visit_card_call_phones(
        me_phone=me_phone,
        visitor_phone=people["visitor_phone"] or plus_user_phone,
        marketer_phone=people["marketer_phone"] or people["partner_phone"],
        customer_phone=people["customer_phone"],
    )
    return {
        "id": str(row.get("id") or "").strip(),
        "kind": "visit",
        "land_code": land_code,
        "land_title": land_title,
        "plus_user_name": plus_user_name,
        "plus_user_phone": plus_user_phone,
        "partner_name": people["partner_name"],
        "partner_phone": people["partner_phone"],
        "visitor_name": people["visitor_name"],
        "visitor_phone": people["visitor_phone"],
        "marketer_name": people["marketer_name"],
        "marketer_phone": people["marketer_phone"],
        "visit_presence_address": presence_address,
        "title": land_title,
        "customer_name": people["customer_name"],
        "customer_phone": people["customer_phone"],
        "visit_date": when["visit_date"],
        "visit_date_jalali": when["visit_date_jalali"],
        "visit_weekday": when["visit_weekday"],
        "visit_date_label": when["visit_date_label"],
        "visit_time": when["visit_time"],
        "visit_when": when["visit_when"],
        "notes": notes,
        "created_at": str(row.get("created_at") or "").strip(),
        "created_at_label": format_visit_stamp_label(row.get("created_at")),
        "updated_at": str(row.get("updated_at") or row.get("created_at") or "").strip(),
        "updated_at_label": format_visit_stamp_label(row.get("updated_at") or row.get("completed_at")),
        "revisit_count": _as_int(row.get("revisit_count")),
        "history": [dict(item) for item in (row.get("history") or []) if isinstance(item, dict)],
        "owner_phone": str(row.get("owner_phone") or "").strip(),
        "archived": card_is_archived(row),
        "archived_at": str(row.get("archived_at") or "").strip(),
        "archived_reason": str(row.get("archived_reason") or "").strip(),
        "support_phone": support,
        "status": st,
        "status_label": labels.get(st, st or "در جریان"),
        "can_cancel": can_cancel,
        "can_delete": can_delete,
        "can_complete": can_complete,
        "can_no_show": can_no_show,
        "can_confirm_deal": deal_flags["can_confirm_deal"],
        "can_reject_deal": deal_flags["can_reject_deal"],
        "can_close_deal": deal_flags["can_close_deal"],
        "can_register_result": can_register_result,
        "visit_outcome": outcome,
        "visit_outcome_label": visit_outcome_label(outcome),
        "visit_outcome_hint": visit_outcome_hint(outcome),
        "can_revisit": show_revisit,
        "can_remove": can_cancel or can_delete,
        "is_own_request": True,
        "call_visitor_phone": calls["call_visitor_phone"],
        "call_marketer_phone": calls["call_marketer_phone"],
        "call_customer_phone": calls["call_customer_phone"],
        "assignment_status": assign_st,
        "pipeline_tab": partner_request_pipeline_tab(
            st,
            assign_st,
            plus_own=plus_own,
            visit_outcome=outcome,
            deal_decision=deal_dec,
            can_confirm_deal=bool(deal_flags.get("can_confirm_deal")),
        ),
    }


def follow_card_stage(item: Dict[str, Any] | None) -> str:
    """visit_request تا تأیید، visit برای وقت و انجام، deal برای معامله."""
    row = item if isinstance(item, dict) else {}
    status = str(row.get("status") or "").strip()
    if status == PENDING_STATUS:
        return STAGE_VISIT_REQUEST
    if visit_is_deal_pipeline(
        visit_outcome=str(row.get("visit_outcome") or ""),
        assignment_status=str(row.get("assignment_status") or ""),
        tx_status=str(row.get("tx_status") or ""),
        deal_commission_status=str(row.get("deal_commission_status") or ""),
        deal_decision=str(row.get("deal_decision") or ""),
    ):
        return STAGE_DEAL
    return STAGE_VISIT


def annotate_follow_card(item: Dict[str, Any], direction: str) -> Dict[str, Any]:
    """فیلدهای مشترک لیست واحد. pipeline_tab با stage یکی می‌شود تا tab_counts درست بماند."""
    stage = follow_card_stage(item)
    item["stage"] = stage
    item["stage_label"] = STAGE_LABELS[stage]
    item["direction"] = direction if direction in (DIRECTION_INCOMING, DIRECTION_OUTGOING) else DIRECTION_OUTGOING
    item["direction_label"] = "دریافتی" if item["direction"] == DIRECTION_INCOMING else "ارسالی"
    item["updated_at"] = str(item.get("updated_at") or item.get("created_at") or "")
    item["pipeline_tab"] = {
        STAGE_VISIT_REQUEST: PIPELINE_REQUESTS,
        STAGE_VISIT: PIPELINE_VISITS,
        STAGE_DEAL: PIPELINE_DEALS,
    }[stage]
    item["revisit_count"] = _as_int(item.get("revisit_count"))
    history = item.get("history")
    item["history"] = [dict(row) for row in history if isinstance(row, dict)] if isinstance(history, list) else []
    item["owner_phone"] = str(item.get("owner_phone") or "")
    item.update(follow_archive_fields(item))
    return item


def card_is_archived(row: Dict[str, Any] | None) -> bool:
    if not isinstance(row, dict):
        return False
    flag = row.get("archived")
    if flag is True:
        return True
    return str(flag or "").strip().lower() in ("1", "true", "yes", "on")


def follow_archive_fields(row: Dict[str, Any] | None) -> Dict[str, Any]:
    """کلیدهای بایگانی کارت. کارت فعال هم همین فیلدها را خالی برمی‌گرداند."""
    archived = card_is_archived(row)
    reason = ""
    stamp = ""
    if archived and isinstance(row, dict):
        raw = str(row.get("archived_reason") or "").strip().lower()
        reason = raw if raw in ("manual", "inactive", "closed") else ""
        stamp = str(row.get("archived_at") or "").strip()
    return {
        "archived": archived,
        "is_archived": archived,
        "archived_at": stamp,
        "archived_reason": reason,
    }


def _actor_can_touch_card(row: Dict[str, Any], actor: str, lands: List[Dict[str, Any]] | None = None) -> bool:
    """درخواست‌کننده، مالکِ ثبت‌شده، کاربر پلاسِ همین کارت، یا مالک آگهی."""
    me = _canonical_visit_phone(actor) or str(actor or "").strip()
    if not me or not isinstance(row, dict):
        return False
    for key in ("partner_phone", "owner_phone", "plus_user_phone"):
        if _phones_match(row.get(key), me):
            return True
    owner = owner_phone_for_listing(str(row.get("land_code") or ""), lands)
    return _phones_match(owner, me)


def follow_card_permissions(
    card: Dict[str, Any] | None,
    actor: str,
    lands: List[Dict[str, Any]] | None = None,
) -> Dict[str, bool]:
    """can_archive و پرچم نمایش ملک. هر دو پرچم ملک فقط وقتی جزئیات برای همین کاربر باز می‌شود."""
    row = card if isinstance(card, dict) else {}
    code = str(row.get("land_code") or "").strip()
    visible = False
    if code:
        rows = lands if lands is not None else _visit_lands()
        try:
            from .special_listings import viewer_can_open_listing

            visible = viewer_can_open_listing(rows, code, actor)
        except Exception:
            visible = False
    kind = str(row.get("kind") or "").strip()
    return {
        "can_archive": False if kind == "offer" else _actor_can_touch_card(row, actor, lands),
        "land_available": visible,
        "can_view_land": visible,
    }


def _touch_visit_card_archive(
    requests: List[Dict[str, Any]],
    visit_id: str,
    actor: str,
    *,
    archived: bool,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
    rid = str(visit_id or "").strip()
    rec = _find_visit_request(requests, rid) if rid else None
    if not rec:
        return None, "not_found", False
    lands = _visit_lands()
    if not _actor_can_touch_card(rec, actor, lands):
        return None, "forbidden", False
    from app.listings.service import _archive_now

    now_iso = _archive_now()
    if archived:
        if card_is_archived(rec):
            return rec, None, False
        rec["archived"] = True
        rec["archived_at"] = now_iso
        rec["archived_reason"] = "manual"
        rec.pop("archive_restored_at", None)
        rec["updated_at"] = now_iso
        return rec, None, True
    if not card_is_archived(rec):
        return rec, None, False
    rec["archived"] = False
    rec["archived_at"] = ""
    rec["archived_reason"] = ""
    rec["archive_restored_at"] = now_iso
    rec["updated_at"] = now_iso
    return rec, None, True


def submit_visit_card_archive(
    visit_id: str,
    actor: str,
    *,
    archived: bool,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], bool]:
    """بایگانی یا بازگردانی یک کارت پیگیری، برای مالک یا درخواست‌کننده."""
    from app.utils.storage import save_express_visit_requests

    held: Dict[str, Any] = {}

    def _mutate(rows: List[Dict[str, Any]]) -> bool:
        rec, err, changed = _touch_visit_card_archive(rows, visit_id, actor, archived=archived)
        held["rec"] = rec
        held["err"] = err
        held["changed"] = changed
        return changed

    with visit_store_lock():
        rows = load_visit_requests_fresh()
        if _mutate(rows):
            save_express_visit_requests(rows)
    return held.get("rec"), held.get("err"), bool(held.get("changed"))


def sync_archived_listing_cards(code: str, reason: str, listing_archived_at: str = "") -> int:
    """کارت‌های همین آگهی را بایگانی می‌کند. کارتِ بازگردانده‌شده بعد از این رویداد نمی‌رود."""
    from app.utils.storage import save_express_visit_requests

    lands = _visit_lands()
    want = canonical_land_code(code, lands)
    if not want:
        return 0
    clean = reason if reason in ("manual", "inactive", "closed") else "inactive"
    from app.listings.service import _archive_now

    stamp = str(listing_archived_at or "").strip() or _archive_now()
    with visit_store_lock():
        rows = load_visit_requests_fresh()
        changed = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            if canonical_land_code(str(row.get("land_code") or ""), lands) != want:
                continue
            if card_is_archived(row):
                continue
            restored = str(row.get("archive_restored_at") or "").strip()
            if restored and stamp and restored >= stamp:
                continue
            row["archived"] = True
            row["archived_at"] = stamp
            row["archived_reason"] = clean
            row.pop("archive_restored_at", None)
            changed += 1
        if changed:
            save_express_visit_requests(rows)
    return changed


def partner_cancel_own_visit(
    requests: List[Dict[str, Any]],
    *,
    request_id: str,
    partner_phone: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """لغو درخواست بازدید باز توسط خود همکار."""
    ph = (partner_phone or "").strip()
    rid = (request_id or "").strip()
    if not ph or not rid:
        return None, "invalid"
    rec = _find_visit_request(requests, rid)
    if not rec:
        return None, "not_found"
    if str(rec.get("partner_phone") or "").strip() != ph:
        return None, "forbidden"
    st = (str(rec.get("status") or PENDING_STATUS)).strip()
    if st not in (PENDING_STATUS, APPROVED_STATUS):
        return None, "not_cancellable"
    return admin_update_visit_request_status(requests, rid, CANCELLED_STATUS)


def partner_delete_own_visit(
    requests: List[Dict[str, Any]],
    *,
    request_id: str,
    partner_phone: str,
) -> Tuple[bool, Optional[str]]:
    """حذف قطعی درخواست لغو/عدم‌حضور/انجام‌شده از لیست همکار."""
    ph = (partner_phone or "").strip()
    rid = (request_id or "").strip()
    if not ph or not rid:
        return False, "invalid"
    for i, r in enumerate(list(requests or [])):
        if not isinstance(r, dict):
            continue
        if str(r.get("id") or "").strip() != rid:
            continue
        if str(r.get("partner_phone") or "").strip() != ph:
            return False, "forbidden"
        st = (str(r.get("status") or "")).strip()
        if st not in (CANCELLED_STATUS, NO_SHOW_STATUS, COMPLETED_STATUS):
            return False, "not_deletable"
        requests.pop(i)
        return True, None
    return False, "not_found"


_VISIT_DATE_ORDINALS: Dict[str, int] = {
    "1": 1, "۱": 1, "اول": 1, "اولی": 1, "یک": 1, "یکه": 1, "نخست": 1, "نخستین": 1,
    "2": 2, "۲": 2, "دوم": 2, "دومی": 2, "دو": 2,
    "3": 3, "۳": 3, "سوم": 3, "سومی": 3, "سه": 3,
    "4": 4, "۴": 4, "چهارم": 4, "چهارمی": 4, "چهار": 4,
    "5": 5, "۵": 5, "پنجم": 5, "پنجمی": 5, "پنج": 5,
    "6": 6, "۶": 6, "ششم": 6, "ششمی": 6, "شش": 6,
    "7": 7, "۷": 7, "هفتم": 7, "هفتمی": 7, "هفت": 7,
    "8": 8, "۸": 8, "هشتم": 8, "هشتمی": 8, "هشت": 8,
    "9": 9, "۹": 9, "نهم": 9, "نهمی": 9, "نه": 9,
    "10": 10, "۱۰": 10, "دهم": 10, "دهمی": 10, "ده": 10,
}


def _extract_choice_index(raw: str) -> Optional[int]:
    """شماره گزینه ۱…۱۰ از پاسخ کاربر/مدل."""
    s = to_en_digits(raw or "").strip()
    if not s:
        return None
    head = s
    for junk in ("گزینه", "تاریخ", "روز", "شماره"):
        if head.startswith(junk):
            head = head[len(junk):].strip()
    head_token = head.split()[0] if head.split() else head
    head_token = head_token.strip(").]:،-/")
    idx = _VISIT_DATE_ORDINALS.get(head_token) or _VISIT_DATE_ORDINALS.get(to_en_digits(head_token))
    if idx is None and head_token.isdigit() and len(head_token) <= 2:
        try:
            idx = int(head_token)
        except Exception:
            idx = None
    if idx is None:
        key = (
            s.replace("گزینه", " ")
            .replace("تاریخ", " ")
            .replace("روز", " ")
            .replace("‌", " ")
            .strip()
        )
        key = " ".join(key.split())
        idx = _VISIT_DATE_ORDINALS.get(key) or _VISIT_DATE_ORDINALS.get(to_en_digits(key))
        if idx is None and key.endswith("م"):
            idx = _VISIT_DATE_ORDINALS.get(key[:-1])
    return idx if idx and idx >= 1 else None


def resolve_visit_date_choice(
    raw: Any,
    *,
    options: Optional[List[Dict[str, Any]]] = None,
) -> Optional[date]:
    """شماره گزینه / شمسی / میلادی واقعی — سال شمسی را هرگز میلادی نمی‌خواند."""
    s = (str(raw or "")).strip()
    if not s:
        return None

    # اولویت ۱: شمارهٔ لیست (۱…۵) تا با تاریخ قاطی نشود
    idx = _extract_choice_index(s)
    opts = options if options is not None else list_upcoming_visit_dates(limit=max(idx or 7, 7))
    if idx and 1 <= idx <= len(opts):
        return _parse_visit_date(opts[idx - 1].get("iso"))

    # اولویت ۲: شمسی (مثلاً ۱۴۰۵/۰۴/۲۴)
    j = parse_jalali_date(s)
    if j is not None:
        return j

    # اولویت ۳: میلادی واقعی فقط اگر سال ۱۹۰۰–۲۲۰۰ باشد
    g = parse_gregorian_iso_date(s)
    if g is not None:
        for opt in opts:
            if str(opt.get("iso") or "") == g.isoformat():
                return g
        return g

    # تطبیق با جلالی داخل لیست
    compact = (
        to_en_digits(s)
        .replace(" ", "")
        .replace("-", "/")
        .replace(".", "/")
    )
    for opt in opts:
        jalali = str(opt.get("jalali") or "").strip()
        jalali_fa = str(opt.get("jalali_fa") or "").strip()
        for cand in (jalali, jalali_fa, to_en_digits(jalali_fa)):
            if not cand:
                continue
            j_compact = to_en_digits(cand).replace(" ", "").replace("-", "/")
            if j_compact and (j_compact in compact or compact in j_compact):
                return _parse_visit_date(opt.get("iso"))
            j_digits = "".join(ch for ch in j_compact if ch.isdigit())
            s_digits = "".join(ch for ch in compact if ch.isdigit())
            if j_digits and s_digits == j_digits:
                return _parse_visit_date(opt.get("iso"))

    return None


def split_customer_full_name(full_name: str) -> Tuple[str, str]:
    """یک فیلد نام کامل → نام + نام خانوادگی برای ذخیره‌سازی."""
    parts = [p for p in (full_name or "").strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], " ".join(parts[1:])


def _parse_visit_date(raw: Any) -> Optional[date]:
    """ISO میلادی یا شمسی — سال ۱۳xx/۱۴xx میلادی فرض نمی‌شود."""
    s = (str(raw or "")).strip()
    if not s:
        return None
    return parse_gregorian_iso_date(s) or parse_jalali_date(s)

def _match_partner_land(r: Dict[str, Any], phone: str, land_code: str) -> bool:
    if not isinstance(r, dict):
        return False
    return (
        str(r.get("partner_phone") or "").strip() == phone
        and str(r.get("land_code") or "").strip() == land_code
    )


def visit_progress_steps(
    row: Dict[str, Any],
    commissions: List[Dict[str, Any]] | None = None,
    *,
    partner_phone: str | None = None,
    visit_requests: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """مراحل یکسان روند بازدید/معامله برای پنل همکار و ادمین."""
    if not isinstance(row, dict):
        row = {}
    status = str(row.get("status") or PENDING_STATUS).strip() or PENDING_STATUS
    ph = str(partner_phone if partner_phone is not None else row.get("partner_phone") or "").strip()
    code = str(row.get("land_code") or "").strip()
    related = [
        c for c in (commissions or [])
        if isinstance(c, dict)
        and (not ph or str(c.get("partner_phone") or "").strip() == ph)
        and (not code or str(c.get("land_code") or "").strip() == code)
    ]
    visit_id = str(row.get("id") or "").strip()
    if visit_id:
        matched_vc = commission_for_visit_request(
            related, ph, code, visit_id, kind="visit", visit_requests=visit_requests,
        )
        visit_commissions = [matched_vc] if matched_vc else []
    else:
        visit_commissions = [c for c in related if commission_is_visit(c)]
    deal_commissions = [c for c in related if commission_is_deal(c)]
    deal_requested = bool(deal_commissions)
    deal_approved = any(
        str(c.get("status") or "").strip().lower() in ("approved", "paid")
        for c in deal_commissions
    )
    deal_paid = any(
        str(c.get("status") or "").strip().lower() == "paid"
        for c in deal_commissions
    )

    visit_requested = row.get("visit_requested")
    visit_requested_done = False if visit_requested is False else True
    was_approved = bool(row.get("approved_at"))
    visit_approved_done = (
        status in (APPROVED_STATUS, DONE_PENDING_STATUS, COMPLETED_STATUS, NO_SHOW_STATUS)
        or (status == CANCELLED_STATUS and was_approved)
    )
    visit_done = status == COMPLETED_STATUS
    # پورسانت بازدید حذف شده — بعد از انجام بازدید مستقیم مسیر معامله
    _ = visit_commissions
    done = [
        visit_requested_done,
        visit_approved_done,
        visit_done,
        visit_done and deal_requested,
        visit_done and deal_approved,
        visit_done and deal_paid,
    ]
    current_idx = next((idx for idx, is_done in enumerate(done) if not is_done), None)
    steps: List[Dict[str, Any]] = []
    for idx, (key, label) in enumerate(VISIT_PROGRESS_STEP_KEYS):
        state = "done" if done[idx] else "todo"
        if idx == current_idx and state == "todo" and status not in (CANCELLED_STATUS, NO_SHOW_STATUS):
            state = "current"
            if key == "visit_done":
                label = "ثبت نتیجه بازدید"
        steps.append({"key": key, "label": label, "state": state})
    if status == CANCELLED_STATUS:
        reject_key = _visit_cancelled_reject_step_key(row)
        for step in steps:
            if step.get("key") == reject_key and step["state"] != "done":
                step["state"] = "rejected"
            elif step["state"] != "done":
                step["state"] = "blocked"
    elif status == NO_SHOW_STATUS:
        for step in steps:
            if step.get("key") == "visit_done" and step["state"] != "done":
                step["state"] = "rejected"
                step["label"] = "عدم حضور (No-Show)"
            elif step["state"] != "done":
                step["state"] = "blocked"
    return steps


def visit_progress_summary(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    done_count = 0
    current_label = ""
    for step in steps or []:
        if step.get("state") == "done":
            done_count += 1
        elif not current_label and step.get("state") in ("current", "blocked", "rejected"):
            if step.get("state") == "rejected":
                current_label = "رد شده"
            else:
                current_label = str(step.get("label") or "")
    total = len(steps or [])
    if not current_label and total and done_count >= total:
        current_label = "تکمیل شد"
    return {
        "done_count": done_count,
        "total": total,
        "current_label": current_label or "در جریان",
    }


def partner_most_recent_visit(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> Optional[Dict[str, Any]]:
    """آخرین پرونده بازدید همکار برای یک فایل (هر وضعیتی)."""
    ph = (phone or "").strip()
    code = (land_code or "").strip()
    if not ph or not code:
        return None
    for r in reversed(requests or []):
        if _match_partner_land(r, ph, code):
            return r
    return None


def _visit_cancelled_reject_step_key(row: Dict[str, Any]) -> str:
    """مرحله‌ای که درخواست در آن رد شده است."""
    if row.get("visit_done_requested_at"):
        return "visit_done"
    if row.get("approved_at"):
        return "visit_done"
    return "visit_approved"


def partner_open_visit(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> Optional[Dict[str, Any]]:
    """درخواست بازدید فعال (در انتظار تأیید یا تأییدشده)."""
    rec = partner_most_recent_visit(requests, phone, land_code)
    if rec and (str(rec.get("status") or "")).strip() in OPEN_VISIT_STATUSES:
        return rec
    return None


def partner_visit_awaiting_admin(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> Optional[Dict[str, Any]]:
    rec = partner_open_visit(requests, phone, land_code)
    if rec and (str(rec.get("status") or "")).strip() == PENDING_STATUS:
        return rec
    return None


def partner_visit_approved_for_deal(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> Optional[Dict[str, Any]]:
    rec = partner_most_recent_visit(requests, phone, land_code)
    if rec and (str(rec.get("status") or "")).strip() == APPROVED_STATUS:
        return rec
    return None


def partner_visit_done_pending(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> Optional[Dict[str, Any]]:
    rec = partner_most_recent_visit(requests, phone, land_code)
    if rec and (str(rec.get("status") or "")).strip() == DONE_PENDING_STATUS:
        return rec
    return None


def partner_latest_visit(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> Optional[Dict[str, Any]]:
    ph = (phone or "").strip()
    code = (land_code or "").strip()
    if not ph or not code:
        return None
    for r in reversed(requests or []):
        if not _match_partner_land(r, ph, code):
            continue
        if (str(r.get("status") or "")).strip() != CANCELLED_STATUS:
            return r
    return None


def partner_visit_completed(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> Optional[Dict[str, Any]]:
    ph = (phone or "").strip()
    code = (land_code or "").strip()
    if not ph or not code:
        return None
    for r in reversed(requests or []):
        if not _match_partner_land(r, ph, code):
            continue
        if (str(r.get("status") or "")).strip() == COMPLETED_STATUS:
            return r
    return None


def partner_visit_no_show(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> Optional[Dict[str, Any]]:
    """Most recent no_show visit for partner+land (Phase 2)."""
    ph = (phone or "").strip()
    code = (land_code or "").strip()
    if not ph or not code:
        return None
    # Only surface when Phase 2 no_show writes are enabled — else treat as absent.
    try:
        from app.visit_result.status_bridge import is_no_show_writable

        if not is_no_show_writable():
            return None
    except Exception:
        return None
    for r in reversed(requests or []):
        if not _match_partner_land(r, ph, code):
            continue
        if (str(r.get("status") or "")).strip() == NO_SHOW_STATUS:
            return r
    return None


def partner_active_visit_record(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> Optional[Dict[str, Any]]:
    """بازدید باز، یا آخرین پروندهٔ معنادار.

    اگر جدیدترین رد شده باشد ولی پروندهٔ تکمیل‌شدهٔ قبلی باشد، تکمیل‌شده را برمی‌گرداند
    تا متادیتا/قیف با «بازاریابی مجدد» اشتباه نشود.
    """
    open_rec = partner_open_visit(requests, phone, land_code)
    if open_rec:
        return open_rec
    recent = partner_most_recent_visit(requests, phone, land_code)
    if not recent:
        return None
    st = (str(recent.get("status") or "")).strip()
    if st == CANCELLED_STATUS:
        non_cancelled = partner_latest_visit(requests, phone, land_code)
        if non_cancelled:
            return non_cancelled
    return recent


def partner_has_pending_deal_commission(
    commissions: List[Dict[str, Any]] | None, phone: str, land_code: str
) -> bool:
    ph = (phone or "").strip()
    code = (land_code or "").strip()
    if not ph or not code:
        return False
    for c in commissions or []:
        if not isinstance(c, dict):
            continue
        if str(c.get("partner_phone") or "").strip() != ph:
            continue
        if str(c.get("land_code") or "").strip() != code:
            continue
        if not commission_is_deal(c):
            continue
        if str(c.get("status") or "").strip().lower() == "pending":
            return True
    return False


def partner_deal_commission_rejected(
    commissions: List[Dict[str, Any]] | None, phone: str, land_code: str
) -> bool:
    ph = (phone or "").strip()
    code = (land_code or "").strip()
    if not ph or not code:
        return False
    for c in reversed(commissions or []):
        if not isinstance(c, dict):
            continue
        if str(c.get("partner_phone") or "").strip() != ph:
            continue
        if str(c.get("land_code") or "").strip() != code:
            continue
        if not commission_is_deal(c):
            continue
        return str(c.get("status") or "").strip().lower() == "rejected"
    return False


def partner_visit_customer_phone(
    requests: List[Dict[str, Any]] | None, phone: str, land_code: str
) -> str:
    """شماره مشتری ثبت‌شده در بازدید فعال/مرتبط این همکار برای فایل."""
    rec = partner_active_visit_record(requests or [], phone, land_code)
    if not rec:
        return ""
    return str(rec.get("customer_phone") or "").strip()


def partner_can_request_new_visit(
    assignment_status: str,
    visit_requests: List[Dict[str, Any]] | None,
    phone: str,
    land_code: str,
) -> bool:
    if partner_open_visit(visit_requests or [], phone, land_code):
        return False
    gs = (assignment_status or "active").strip().lower()
    if gs in ("sold", "in_transaction"):
        return False
    return True


def partner_requests_can_revisit(
    row: Dict[str, Any] | None,
    *,
    assignment_status: str,
    visit_requests: List[Dict[str, Any]] | None = None,
    phone: str = "",
) -> bool:
    """دکمهٔ بازدید مجدد در صفحهٔ درخواست‌ها — بعد از اتمام/لغو، یا وقتی وقت بازدید گذشته."""
    if not isinstance(row, dict):
        return False
    code = str(row.get("land_code") or "").strip()
    if not code:
        return False
    gs = (assignment_status or "active").strip().lower()
    if gs in ("sold", "in_transaction"):
        return False
    st = str(row.get("status") or "").strip()
    if st in (COMPLETED_STATUS, CANCELLED_STATUS, NO_SHOW_STATUS):
        return partner_can_request_new_visit(gs, visit_requests or [], phone, code)
    if st in (PENDING_STATUS, APPROVED_STATUS) and visit_slot_has_passed(row):
        return True
    return False


_VISIT_GUARD = threading.RLock()
_VISIT_LOCK_DEPTH = 0
_VISIT_LOCK_HANDLE = None


def _code_text(raw: Any) -> str:
    return to_en_digits(str(raw or "")).strip()


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _visit_lands() -> List[Dict[str, Any]]:
    try:
        from app.utils.storage import load_ads_cached

        lands = load_ads_cached() or []
    except Exception:
        return []
    return [land for land in lands if isinstance(land, dict)] if isinstance(lands, list) else []


def resolve_listing_for_visit_code(
    code: str,
    lands: List[Dict[str, Any]] | None = None,
) -> Optional[Dict[str, Any]]:
    """آگهیِ همین کد. کد فعلی بر previous_code مقدم است تا ملک دیگری کد را نگیرد."""
    key = _code_text(code)
    if not key:
        return None
    rows = lands if lands is not None else _visit_lands()
    previous_hits: List[Dict[str, Any]] = []
    for land in rows:
        current = _code_text(land.get("code"))
        extras = land.get("extras") if isinstance(land.get("extras"), dict) else {}
        prev = _code_text(extras.get("previous_code"))
        if current and key == current:
            return land
        if prev and key == prev:
            previous_hits.append(land)
    if len(previous_hits) == 1:
        return previous_hits[0]
    return None


def canonical_land_code(code: str, lands: List[Dict[str, Any]] | None = None) -> str:
    """کد فعلی آگهی. previous_code فقط وقتی کد فعلیِ هیچ آگهی‌ای نباشد."""
    key = _code_text(code)
    if not key:
        return ""
    land = resolve_listing_for_visit_code(key, lands)
    if land is None:
        return key
    return _code_text(land.get("code")) or key


def owner_phone_for_listing(code: str, lands: List[Dict[str, Any]] | None = None) -> str:
    """شمارهٔ canonical مالک همان آگهی. کد خالی و previous_codeِ ملک دیگر مالک نمی‌سازند."""
    land = resolve_listing_for_visit_code(code, lands)
    if not isinstance(land, dict):
        return ""
    try:
        from app.listings.service import owner_phone as listing_owner_phone
    except Exception:
        listing_owner_phone = None
    raw = listing_owner_phone(land) if listing_owner_phone else ""
    return _canonical_visit_phone(raw) or ""


def _customer_key(phone: Any) -> str:
    return _canonical_visit_phone(phone) or ""


def _partner_key(phone: Any) -> str:
    return _canonical_visit_phone(phone) or str(phone or "").strip()


def visit_identity(row: Dict[str, Any], lands: List[Dict[str, Any]] | None = None) -> Tuple[str, str, str]:
    """یک کارت: کد ملک، درخواست‌کننده، و شماره مشتری اگر باشد."""
    return (
        canonical_land_code(str(row.get("land_code") or ""), lands),
        _partner_key(row.get("partner_phone")),
        _customer_key(row.get("customer_phone")),
    )


def _same_visit_card(
    left: Dict[str, Any],
    right: Dict[str, Any],
    lands: List[Dict[str, Any]] | None = None,
) -> bool:
    return visit_identity(left, lands) == visit_identity(right, lands) and bool(
        visit_identity(left, lands)[1]
    )


def _history_snapshot(row: Dict[str, Any]) -> Dict[str, str]:
    return {
        "id": str(row.get("id") or ""),
        "visit_date": str(row.get("visit_date") or ""),
        "visit_time": str(row.get("visit_time") or ""),
        "status": str(row.get("status") or ""),
        "updated_at": str(row.get("updated_at") or ""),
        "created_at": str(row.get("created_at") or ""),
        "visit_outcome": str(row.get("visit_outcome") or ""),
        "notes": str(row.get("notes") or ""),
    }


def _stamp_owner_phone(row: Dict[str, Any], lands: List[Dict[str, Any]] | None = None) -> None:
    if str(row.get("owner_phone") or "").strip():
        row["owner_phone"] = _canonical_visit_phone(row.get("owner_phone")) or str(row.get("owner_phone")).strip()
        return
    owner = owner_phone_for_listing(str(row.get("land_code") or ""), lands)
    if owner:
        row["owner_phone"] = owner


def _merge_visit_copies(bucket: List[Dict[str, Any]]) -> Dict[str, Any]:
    ordered = sorted(
        bucket,
        key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""),
        reverse=True,
    )
    primary = dict(ordered[0])
    history = [dict(item) for item in (primary.get("history") or []) if isinstance(item, dict)]
    count = _as_int(primary.get("revisit_count"))
    for older in ordered[1:]:
        for past in older.get("history") or []:
            if isinstance(past, dict):
                history.append(dict(past))
        history.append(_history_snapshot(older))
        count += 1 + _as_int(older.get("revisit_count"))
    primary["history"] = history
    primary["revisit_count"] = count
    return primary


def collapse_visit_rows(rows: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    """ردیف‌های تکراری یک کارت را در حافظه یکی می‌کند. فایل دست نمی‌خورد."""
    lands = _visit_lands()
    groups: List[Tuple[str, str, str]] = []
    index: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = visit_identity(row, lands)
        if key not in index:
            index[key] = []
            groups.append(key)
        index[key].append(row)
    out: List[Dict[str, Any]] = []
    for key in groups:
        bucket = index[key]
        item = dict(bucket[0]) if len(bucket) == 1 else _merge_visit_copies(bucket)
        _stamp_owner_phone(item, lands)
        out.append(item)
    return out


def _fold_duplicate_visits(
    requests: List[Dict[str, Any]],
    primary: Dict[str, Any],
    lands: List[Dict[str, Any]],
) -> None:
    extras = [
        row for row in requests
        if isinstance(row, dict) and row is not primary and _same_visit_card(row, primary, lands)
    ]
    if not extras:
        return
    history = [dict(item) for item in (primary.get("history") or []) if isinstance(item, dict)]
    count = _as_int(primary.get("revisit_count"))
    for older in extras:
        for past in older.get("history") or []:
            if isinstance(past, dict):
                history.append(dict(past))
        history.append(_history_snapshot(older))
        count += 1 + _as_int(older.get("revisit_count"))
        requests.remove(older)
    primary["history"] = history
    primary["revisit_count"] = count


def _apply_revisit(
    rec: Dict[str, Any],
    *,
    visit_day: date,
    hour: int,
    note: str,
    stored_title: str,
    first: str,
    last: str,
    full_name: str,
    cust_phone: str,
    plus_phone: str,
    plus_name: str,
    owner_phone: str,
    auto: bool,
    now_iso: str,
) -> None:
    history = [dict(item) for item in (rec.get("history") or []) if isinstance(item, dict)]
    history.append(_history_snapshot(rec))
    rec["history"] = history
    rec["revisit_count"] = _as_int(rec.get("revisit_count")) + 1
    rec["visit_date"] = visit_day.isoformat()
    rec["visit_time"] = format_visit_time_stored(hour)
    rec["status"] = APPROVED_STATUS if auto else PENDING_STATUS
    rec["updated_at"] = now_iso
    rec["auto_approved"] = bool(auto)
    if stored_title:
        rec["land_title"] = stored_title
    if first:
        rec["customer_first_name"] = first
    if last:
        rec["customer_last_name"] = last
    if full_name:
        rec["customer_name"] = full_name
    if cust_phone:
        rec["customer_phone"] = cust_phone
    if note:
        rec["notes"] = note
    if plus_phone:
        rec["plus_user_phone"] = plus_phone
        rec["plus_user_name"] = plus_name or plus_phone
    if owner_phone:
        rec["owner_phone"] = owner_phone
    for key in (
        "visit_outcome",
        "deal_decision",
        "completed_at",
        "visit_done_requested_at",
        "cancelled_at",
        "no_show_at",
    ):
        rec.pop(key, None)
    if auto:
        rec["approved_at"] = now_iso
    else:
        rec.pop("approved_at", None)


@contextmanager
def visit_store_lock(app=None):
    """قفل فایل درخواست بازدید تا دو ثبت هم‌زمان دو کارت نسازند."""
    global _VISIT_LOCK_DEPTH, _VISIT_LOCK_HANDLE
    import fcntl

    with _VISIT_GUARD:
        _VISIT_LOCK_DEPTH += 1
        try:
            if _VISIT_LOCK_DEPTH == 1:
                from app.utils.storage import ensure_file

                path = ensure_file(
                    "EXPRESS_VISIT_REQUESTS_FILE",
                    "express_visit_requests.json",
                    [],
                    app,
                ) + ".lock"
                os.makedirs(os.path.dirname(path), exist_ok=True)
                handle = open(path, "a+", encoding="utf-8")
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                except Exception:
                    handle.close()
                    raise
                _VISIT_LOCK_HANDLE = handle
            yield
        finally:
            _VISIT_LOCK_DEPTH -= 1
            if _VISIT_LOCK_DEPTH == 0 and _VISIT_LOCK_HANDLE is not None:
                fcntl.flock(_VISIT_LOCK_HANDLE.fileno(), fcntl.LOCK_UN)
                _VISIT_LOCK_HANDLE.close()
                _VISIT_LOCK_HANDLE = None


def load_visit_requests_fresh(app=None) -> List[Dict[str, Any]]:
    from app.utils.storage import _load, ensure_file

    path = ensure_file("EXPRESS_VISIT_REQUESTS_FILE", "express_visit_requests.json", [], app)
    data = _load(path)
    return data if isinstance(data, list) else []


def create_visit_request(
    requests: List[Dict[str, Any]],
    *,
    partner_phone: str,
    partner_name: str,
    land_code: str,
    land_title: str,
    visit_date: str,
    customer_first_name: str = "",
    customer_last_name: str = "",
    customer_phone: str = "",
    notes: str = "",
    visit_time: str = "",
    require_customer: bool = True,
    plus_user_phone: str = "",
    plus_user_name: str = "",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    ph = (partner_phone or "").strip()
    code = (land_code or "").strip()
    first = (customer_first_name or "").strip()
    last = (customer_last_name or "").strip()
    cust_phone = (customer_phone or "").strip()
    note = (notes or "").strip()
    plus_phone = (plus_user_phone or "").strip()
    plus_name = (plus_user_name or "").strip()
    if code:
        listing_owner = owner_phone_for_listing(code)
        plus_owner = plus_phone_for_land_code(code)
        if plus_owner:
            plus_phone = plus_owner
            try:
                from .special_listings import plus_listing_owner_by_code

                owner = (plus_listing_owner_by_code() or {}).get(code) or {}
                plus_name = str(owner.get("name") or "").strip() or plus_name
            except Exception:
                pass
        elif listing_owner:
            supplied = _canonical_visit_phone(plus_phone) or plus_phone
            if supplied and supplied != listing_owner:
                plus_phone = ""
                plus_name = ""
    plus_phone = _canonical_visit_phone(plus_phone) or plus_phone
    vd = _parse_visit_date(visit_date)
    if not ph:
        return None, "invalid"
    if require_customer and (not first or not last or not cust_phone):
        return None, "customer_required"
    if vd is None:
        return None, "invalid_date"
    if vd < _today():
        return None, "past_date"
    if vd > _today() + timedelta(days=90):
        return None, "date_too_far"
    if not is_visit_weekday_allowed(vd, plus_user_phone=plus_phone):
        return None, "weekday_not_allowed"
    requested_hour = parse_visit_hour(visit_time)
    lands = _visit_lands()
    probe = {
        "land_code": code,
        "partner_phone": ph,
        "customer_phone": cust_phone,
    }
    matches = [
        row for row in requests
        if isinstance(row, dict) and code and _same_visit_card(row, probe, lands)
    ]
    match = None
    if matches:
        match = max(
            matches,
            key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""),
        )
    # ردیف‌های همین کارت نباید ساعت خودشان را اشغال کنند.
    match_ids = {id(row) for row in matches}
    slot_rows = [row for row in requests if id(row) not in match_ids] if match_ids else requests
    picked = resolve_free_visit_slot(
        slot_rows,
        visit_day=vd,
        visit_hour=requested_hour,
        plus_user_phone=plus_phone,
    )
    if not picked:
        return None, "no_hours"
    vd, hour = picked

    now_iso = datetime.utcnow().isoformat() + "Z"
    full_name = f"{first} {last}".strip()
    stored_title = (land_title or "").strip() or code
    if not stored_title:
        stored_title = (
            f"کاربر پلاس — {plus_name or plus_phone}"
            if (plus_name or plus_phone)
            else "وقت بازدید"
        )
    # پیش‌فرض: بدون صف تأیید ادمین — فقط اطلاع‌رسانی
    auto = visit_requests_auto_approve_enabled()
    rec: Dict[str, Any] = {
        "id": uuid.uuid4().hex[:16],
        "partner_phone": ph,
        "partner_name": (partner_name or "").strip() or ph,
        "land_code": code,
        "land_title": stored_title,
        "visit_date": vd.isoformat(),
        "visit_time": format_visit_time_stored(hour),
        "customer_first_name": first,
        "customer_last_name": last,
        "customer_name": full_name,
        "customer_phone": cust_phone,
        "status": APPROVED_STATUS if auto else PENDING_STATUS,
        "created_at": now_iso,
        "updated_at": now_iso,
        "auto_approved": bool(auto),
    }
    if note:
        rec["notes"] = note
    if plus_phone:
        rec["plus_user_phone"] = plus_phone
        rec["plus_user_name"] = plus_name or plus_phone
        addr = get_plus_visit_presence_address(plus_phone)
        if addr:
            rec["visit_presence_address"] = addr
    if auto:
        rec["approved_at"] = now_iso
    owner_phone = owner_phone_for_listing(code, lands)
    if owner_phone:
        rec["owner_phone"] = owner_phone
    rec["revisit_count"] = 0
    rec["history"] = []
    if match is not None:
        _fold_duplicate_visits(requests, match, lands)
        _apply_revisit(
            match,
            visit_day=vd,
            hour=hour,
            note=note,
            stored_title=stored_title,
            first=first,
            last=last,
            full_name=full_name,
            cust_phone=cust_phone,
            plus_phone=plus_phone,
            plus_name=plus_name,
            owner_phone=owner_phone,
            auto=auto,
            now_iso=now_iso,
        )
        rec = match
    else:
        requests.append(rec)
        _record_listing_visit_requested(rec)
    try:
        from .special_visit_inbox import notify_special_owner_new_visit

        notify_special_owner_new_visit(rec)
    except Exception:
        pass
    try:
        _notify_plus_user_new_visit(rec)
    except Exception:
        pass
    return rec, None


def submit_visit_request(**kwargs: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """ثبت یا به‌روزرسانی کارت زیر قفل فایل. همان آرگومان‌های create_visit_request بدون لیست."""
    from app.utils.storage import save_express_visit_requests

    held: Dict[str, Any] = {}

    def _mutate(rows: List[Dict[str, Any]]) -> bool:
        rec, err = create_visit_request(rows, **kwargs)
        held["rec"] = rec
        held["err"] = err
        return rec is not None

    with visit_store_lock():
        rows = load_visit_requests_fresh()
        if _mutate(rows):
            save_express_visit_requests(rows)
    return held.get("rec"), held.get("err")


def _record_listing_visit_requested(rec: Dict[str, Any] | None) -> None:
    """فعالیت listing_visit_requested. شکست ثبت، درخواست بازدید را برنمی‌گرداند."""
    if not isinstance(rec, dict):
        return
    try:
        from app.foundation.activity_store import append_activity

        code = str(rec.get("land_code") or "").strip()
        append_activity(
            action="listing_visit_requested",
            actor_key=str(rec.get("partner_phone") or "").strip(),
            actor_role="partner",
            entity_type="visit_request",
            entity_id=str(rec.get("id") or "").strip(),
            land_code=code,
            summary="درخواست بازدید ثبت شد",
            payload={
                "visit_date": str(rec.get("visit_date") or ""),
                "created_at": str(rec.get("created_at") or ""),
            },
            source="visit_requests",
        )
    except Exception:
        pass


def _notify_plus_user_new_visit(rec: Dict[str, Any] | None) -> None:
    """اعلان درون‌برنامه برای کاربر پلاس انتخاب‌شده در وقت بازدید."""
    if not isinstance(rec, dict):
        return
    plus_phone = str(rec.get("plus_user_phone") or "").strip()
    if not plus_phone:
        return
    requester = str(rec.get("partner_phone") or "").strip()
    if _canonical_visit_phone(plus_phone) == _canonical_visit_phone(requester):
        return
    code = str(rec.get("land_code") or "").strip()
    if code and resolve_listing_for_visit_code(code) is not None:
        return
    partner_name = str(rec.get("partner_name") or "").strip() or "یک همکار"
    title = visit_request_display_title(rec)
    date_bit = ""
    visit_date = str(rec.get("visit_date") or "").strip()
    if visit_date:
        jalali = format_iso_date_jalali(visit_date)
        if jalali:
            date_bit = f" — {jalali}"
    try:
        from flask import url_for

        from app.services.notifications import add_notification

        try:
            action_url = url_for("express_partner.requests", tab="visits")
        except Exception:
            action_url = "/express/partner/requests?tab=visits"
        add_notification(
            user_id=plus_phone,
            title="درخواست بازدید",
            body=f"{partner_name} برای «{title}» وقت بازدید ثبت کرد{date_bit}.",
            ntype="visit",
            ad_id=str(rec.get("land_code") or "") or None,
            action_url=action_url,
            source="visit_plus_user",
        )
    except Exception:
        try:
            from flask import current_app

            current_app.logger.exception(
                "notify plus user visit failed plus=%s", plus_phone
            )
        except Exception:
            pass


ADMIN_VISIT_STATUSES = frozenset({
    PENDING_STATUS,
    APPROVED_STATUS,
    DONE_PENDING_STATUS,
    COMPLETED_STATUS,
    CANCELLED_STATUS,
    NO_SHOW_STATUS,
})


def _find_visit_request(
    requests: List[Dict[str, Any]], request_id: str
) -> Optional[Dict[str, Any]]:
    rid = (request_id or "").strip()
    if not rid:
        return None
    for r in requests:
        if isinstance(r, dict) and str(r.get("id") or "") == rid:
            return r
    return None


def admin_update_visit_request_status(
    requests: List[Dict[str, Any]],
    request_id: str,
    new_status: str,
    *,
    admin_note: str | None = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """تغییر وضعیت درخواست بازدید توسط ادمین — از هر وضعیت به هر وضعیت مجاز."""
    target = (new_status or "").strip()
    if target not in ADMIN_VISIT_STATUSES:
        return None, "invalid_status"
    rec = _find_visit_request(requests, request_id)
    if not rec:
        return None, "not_found"
    current = (str(rec.get("status") or PENDING_STATUS)).strip()
    if current == target:
        if admin_note is not None:
            new_note = admin_note.strip()
            prev_note = (str(rec.get("admin_note") or "")).strip()
            if new_note != prev_note:
                if new_note:
                    rec["admin_note"] = new_note
                else:
                    rec.pop("admin_note", None)
                rec["updated_at"] = datetime.utcnow().isoformat() + "Z"
                return rec, "note_updated"
        return rec, "unchanged"
    now_iso = datetime.utcnow().isoformat() + "Z"
    rec["status"] = target
    rec["updated_at"] = now_iso
    if admin_note is not None:
        note = admin_note.strip()
        if note:
            rec["admin_note"] = note
        else:
            rec.pop("admin_note", None)
    if target == APPROVED_STATUS:
        rec["approved_at"] = now_iso
        rec.pop("visit_done_requested_at", None)
        rec.pop("completed_at", None)
    elif target == DONE_PENDING_STATUS:
        rec["visit_done_requested_at"] = now_iso
        rec.pop("completed_at", None)
        if not rec.get("approved_at"):
            rec["approved_at"] = now_iso
    elif target == COMPLETED_STATUS:
        rec["completed_at"] = now_iso
        if not rec.get("approved_at"):
            rec["approved_at"] = now_iso
    elif target == PENDING_STATUS:
        rec.pop("approved_at", None)
        rec.pop("visit_done_requested_at", None)
        rec.pop("completed_at", None)
    elif target == CANCELLED_STATUS:
        # تاریخچهٔ تأیید/انجام را نگه می‌داریم تا روند بسته‌شده قابل‌خواندن بماند
        rec["cancelled_at"] = now_iso
    elif target == NO_SHOW_STATUS:
        rec["no_show_at"] = now_iso
        rec.pop("completed_at", None)
    return rec, None


def mark_visit_no_show(
    requests: List[Dict[str, Any]],
    *,
    visit_request_id: str = "",
    partner_phone: str = "",
    land_code: str = "",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Phase 2: set visit status to no_show (gated by visit_result flags).
    Never creates commission. Soft-fails when flags OFF.
    """
    try:
        from app.visit_result.status_bridge import is_no_show_writable
    except Exception:
        return None, "disabled"
    if not is_no_show_writable():
        return None, "disabled"

    rid = (visit_request_id or "").strip()
    ph = (partner_phone or "").strip()
    code = (land_code or "").strip()
    rec: Optional[Dict[str, Any]] = None
    if rid:
        rec = _find_visit_request(requests, rid)
    elif ph and code:
        rec = partner_visit_approved_for_deal(requests, ph, code) or partner_visit_done_pending(
            requests, ph, code
        )
    if not rec:
        return None, "not_found"
    current = (str(rec.get("status") or "")).strip()
    if current == NO_SHOW_STATUS:
        return rec, None
    if current not in (APPROVED_STATUS, DONE_PENDING_STATUS):
        return None, "invalid_status"
    if not admin_can_transition_visit(current, NO_SHOW_STATUS):
        return None, "invalid_transition"
    return admin_update_visit_request_status(
        requests, str(rec.get("id") or ""), NO_SHOW_STATUS
    )


def _first_completed_visit_without_commission(
    visit_requests: List[Dict[str, Any]] | None,
    commissions: List[Dict[str, Any]] | None,
    phone: str,
    land_code: str,
) -> Optional[str]:
    """قدیمی‌ترین بازدید تکمیل‌شده بدون پورسانت مرتبط با visit_request_id."""
    ph = (phone or "").strip()
    code = (land_code or "").strip()
    if not ph or not code:
        return None
    linked = {
        str(c.get("visit_request_id") or "").strip()
        for c in (commissions or [])
        if isinstance(c, dict)
        and str(c.get("partner_phone") or "").strip() == ph
        and str(c.get("land_code") or "").strip() == code
        and commission_is_visit(c)
        and str(c.get("visit_request_id") or "").strip()
    }
    completed = [
        r for r in (visit_requests or [])
        if isinstance(r, dict)
        and _match_partner_land(r, ph, code)
        and (str(r.get("status") or "")).strip() == COMPLETED_STATUS
    ]
    completed.sort(
        key=lambda r: str(r.get("completed_at") or r.get("updated_at") or r.get("created_at") or "")
    )
    for r in completed:
        rid = str(r.get("id") or "").strip()
        if rid and rid not in linked:
            return rid
    return None


def commission_for_visit_request(
    commissions: List[Dict[str, Any]] | None,
    phone: str,
    land_code: str,
    visit_request_id: str,
    *,
    kind: str = "visit",
    visit_requests: List[Dict[str, Any]] | None = None,
) -> Optional[Dict[str, Any]]:
    """پورسانت مرتبط با یک درخواست بازدید مشخص (یا قدیمی بدون visit_request_id)."""
    ph = (phone or "").strip()
    code = (land_code or "").strip()
    vid = (visit_request_id or "").strip()
    if not ph or not code:
        return None
    predicate = commission_is_visit if kind == "visit" else commission_is_deal
    legacy: Optional[Dict[str, Any]] = None
    for c in reversed(commissions or []):
        if not isinstance(c, dict):
            continue
        if str(c.get("partner_phone") or "").strip() != ph:
            continue
        if str(c.get("land_code") or "").strip() != code:
            continue
        if not predicate(c):
            continue
        cid = str(c.get("visit_request_id") or "").strip()
        if vid and cid == vid:
            return c
        if not cid and legacy is None:
            legacy = c
    if vid:
        if legacy and visit_requests is not None:
            owner = _first_completed_visit_without_commission(
                visit_requests, commissions, ph, code
            )
            if owner == vid:
                return legacy
        return None
    return legacy


def request_visit_done_confirmation(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    اعلام «بازدید انجام شد».
    با auto-approve پیش‌فرض: مستقیم completed (بدون صف ادمین).
    """
    done = partner_visit_completed(requests, phone, land_code)
    if done:
        return done, "already_completed"

    pending = partner_visit_done_pending(requests, phone, land_code)
    now_iso = datetime.utcnow().isoformat() + "Z"
    auto = visit_requests_auto_approve_enabled()

    if pending:
        if auto:
            pending["status"] = COMPLETED_STATUS
            pending["updated_at"] = now_iso
            pending["completed_at"] = now_iso
            pending["auto_completed"] = True
            if not pending.get("visit_done_requested_at"):
                pending["visit_done_requested_at"] = now_iso
            return pending, None
        return pending, "already_pending"

    rec = partner_visit_approved_for_deal(requests, phone, land_code)
    if not rec:
        return None, "not_approved"

    rec["updated_at"] = now_iso
    rec["visit_done_requested_at"] = now_iso
    if auto:
        rec["status"] = COMPLETED_STATUS
        rec["completed_at"] = now_iso
        rec["auto_completed"] = True
        if not rec.get("approved_at"):
            rec["approved_at"] = now_iso
    else:
        rec["status"] = DONE_PENDING_STATUS
        if not rec.get("approved_at"):
            rec["approved_at"] = now_iso
    return rec, None


def mark_visit_done_by_id(
    requests: List[Dict[str, Any]],
    visit_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """اعلام/ثبت «بازدید انجام شد» روی همان رکورد (پلاس یا ویزیتور)."""
    rec = _find_visit_request(requests, str(visit_id or "").strip())
    if not rec:
        return None, "not_found"
    st = (str(rec.get("status") or "")).strip()
    if st == COMPLETED_STATUS:
        return rec, "already_completed"
    now_iso = datetime.utcnow().isoformat() + "Z"
    auto = visit_requests_auto_approve_enabled()
    if st == APPROVED_STATUS:
        rec["updated_at"] = now_iso
        rec["visit_done_requested_at"] = now_iso
        if auto:
            rec["status"] = COMPLETED_STATUS
            rec["completed_at"] = now_iso
            rec["auto_completed"] = True
        else:
            rec["status"] = DONE_PENDING_STATUS
        if not rec.get("approved_at"):
            rec["approved_at"] = now_iso
        return rec, None
    if st == DONE_PENDING_STATUS:
        rec["status"] = COMPLETED_STATUS
        rec["completed_at"] = now_iso
        rec["updated_at"] = now_iso
        rec["auto_completed"] = True
        if not rec.get("visit_done_requested_at"):
            rec["visit_done_requested_at"] = now_iso
        return rec, None
    return None, "invalid_status"


def record_visit_attendance(
    requests: List[Dict[str, Any]],
    visit_id: str,
    *,
    outcome: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """نتیجه حضور: done | no_show — بدون وابستگی به فلگ نتیجهٔ بازدید."""
    oc = (outcome or "").strip().lower()
    if oc in ("done", "complete", "completed"):
        return mark_visit_done_by_id(requests, visit_id)
    if oc not in ("no_show", "noshow"):
        return None, "invalid_outcome"
    rec = _find_visit_request(requests, str(visit_id or "").strip())
    if not rec:
        return None, "not_found"
    st = (str(rec.get("status") or "")).strip()
    if st == NO_SHOW_STATUS:
        return rec, None
    if st not in (APPROVED_STATUS, DONE_PENDING_STATUS):
        return None, "invalid_status"
    now_iso = datetime.utcnow().isoformat() + "Z"
    rec["status"] = NO_SHOW_STATUS
    rec["no_show_at"] = now_iso
    rec["updated_at"] = now_iso
    rec.pop("completed_at", None)
    return rec, None


DEAL_DECISION_APPROVED = "approved"
DEAL_DECISION_REJECTED = "rejected"
DEAL_DECISION_CLOSED = "closed"
_DEAL_DECISION_ALIASES = {
    "approved": DEAL_DECISION_APPROVED,
    "approve": DEAL_DECISION_APPROVED,
    "confirm": DEAL_DECISION_APPROVED,
    "rejected": DEAL_DECISION_REJECTED,
    "reject": DEAL_DECISION_REJECTED,
    "decline": DEAL_DECISION_REJECTED,
    "closed": DEAL_DECISION_CLOSED,
    "close": DEAL_DECISION_CLOSED,
}

VISIT_OUTCOME_INTERESTED = "interested"
VISIT_OUTCOME_FOLLOW_UP = "follow_up"
VISIT_OUTCOME_NOT_INTERESTED = "not_interested"
_VISIT_OUTCOME_ALIASES = {
    "interested": VISIT_OUTCOME_INTERESTED,
    "interest": VISIT_OUTCOME_INTERESTED,
    "liked": VISIT_OUTCOME_INTERESTED,
    "follow_up": VISIT_OUTCOME_FOLLOW_UP,
    "followup": VISIT_OUTCOME_FOLLOW_UP,
    "follow-up": VISIT_OUTCOME_FOLLOW_UP,
    "not_interested": VISIT_OUTCOME_NOT_INTERESTED,
    "not-interested": VISIT_OUTCOME_NOT_INTERESTED,
    "uninterested": VISIT_OUTCOME_NOT_INTERESTED,
}
_VISIT_OUTCOME_LABELS = {
    VISIT_OUTCOME_INTERESTED: "علاقه‌مند",
    VISIT_OUTCOME_FOLLOW_UP: "پیگیری دوباره",
    VISIT_OUTCOME_NOT_INTERESTED: "بی‌علاقه",
}
_VISIT_OUTCOME_HINTS = {
    VISIT_OUTCOME_INTERESTED: "وقت بازدید دوباره یا وقت قرارداد نهایی را تنظیم کنید.",
    VISIT_OUTCOME_FOLLOW_UP: "بازاریاب پیگیری می‌کند تا وقت بازدید دوم تعیین شود.",
    VISIT_OUTCOME_NOT_INTERESTED: "بدون پیگیری — پرونده بسته شد.",
}


def visit_outcome(row: Dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return ""
    raw = str(row.get("visit_outcome") or row.get("visit_result_outcome") or "").strip().lower()
    return _VISIT_OUTCOME_ALIASES.get(raw, "")


def visit_outcome_label(outcome: str) -> str:
    return _VISIT_OUTCOME_LABELS.get((outcome or "").strip().lower(), "")


def visit_outcome_hint(outcome: str) -> str:
    return _VISIT_OUTCOME_HINTS.get((outcome or "").strip().lower(), "")


def record_visit_outcome(
    requests: List[Dict[str, Any]],
    visit_id: str,
    *,
    outcome: str,
    notes: str = "",
    actor_phone: str = "",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """ثبت نتیجه بازدید بعد از «بازدید انجام شد»."""
    rec = _find_visit_request(requests, str(visit_id or "").strip())
    if not rec:
        return None, "not_found"
    st = str(rec.get("status") or "").strip()
    if st != COMPLETED_STATUS:
        return None, "invalid_status"
    oc = _VISIT_OUTCOME_ALIASES.get((outcome or "").strip().lower(), "")
    if not oc:
        return None, "invalid_outcome"
    now_iso = datetime.utcnow().isoformat() + "Z"
    rec["visit_outcome"] = oc
    rec["visit_outcome_at"] = now_iso
    rec["visit_outcome_by"] = str(actor_phone or "").strip()
    rec["visit_outcome_notes"] = str(notes or "").strip()
    rec["updated_at"] = now_iso
    if oc == VISIT_OUTCOME_NOT_INTERESTED:
        rec["deal_decision"] = DEAL_DECISION_CLOSED
        rec["deal_decided_at"] = now_iso
        rec["deal_decided_by"] = str(actor_phone or "").strip()
    try:
        from app.visit_result.service import register_result

        register_result(
            visit_request_id=str(rec.get("id") or ""),
            partner_phone=str(rec.get("partner_phone") or actor_phone),
            land_code=str(rec.get("land_code") or ""),
            outcome=oc,
            notes=str(notes or "").strip(),
            actor_key=str(actor_phone or ""),
            source="partner",
        )
    except Exception:
        pass
    return rec, None


def visit_deal_decision(row: Dict[str, Any] | None) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("deal_decision") or "").strip().lower()


def visit_deal_action_flags(row: Dict[str, Any] | None, *, allowed: bool) -> Dict[str, bool]:
    """تأیید / رد / بستن روی پروندهٔ انجام‌شده."""
    empty = {
        "can_confirm_deal": False,
        "can_reject_deal": False,
        "can_close_deal": False,
    }
    if not allowed or not isinstance(row, dict):
        return empty
    st = str(row.get("status") or "").strip()
    if st != COMPLETED_STATUS:
        return empty
    dec = visit_deal_decision(row)
    if dec in (DEAL_DECISION_REJECTED, DEAL_DECISION_CLOSED):
        return empty
    if dec == DEAL_DECISION_APPROVED:
        return {
            "can_confirm_deal": False,
            "can_reject_deal": False,
            "can_close_deal": True,
        }
    # بستن فقط بعد از تأیید معامله (پرونده در جریان). قبل از آن دکمه نیست.
    return {
        "can_confirm_deal": True,
        "can_reject_deal": True,
        "can_close_deal": False,
    }


def record_visit_deal_decision(
    requests: List[Dict[str, Any]],
    visit_id: str,
    *,
    decision: str,
    actor_phone: str = "",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """ثبت تأیید / رد / بستن معامله روی پروندهٔ بازدید انجام‌شده."""
    rec = _find_visit_request(requests, str(visit_id or "").strip())
    if not rec:
        return None, "not_found"
    st = str(rec.get("status") or "").strip()
    if st != COMPLETED_STATUS:
        return None, "invalid_status"
    dec = _DEAL_DECISION_ALIASES.get((decision or "").strip().lower(), "")
    if not dec:
        return None, "invalid_decision"
    current = visit_deal_decision(rec)
    if current in (DEAL_DECISION_REJECTED, DEAL_DECISION_CLOSED):
        return rec, "already_decided"
    if current == DEAL_DECISION_APPROVED and dec == DEAL_DECISION_APPROVED:
        return rec, None
    now_iso = datetime.utcnow().isoformat() + "Z"
    rec["deal_decision"] = dec
    rec["deal_decided_at"] = now_iso
    rec["deal_decided_by"] = str(actor_phone or "").strip()
    rec["updated_at"] = now_iso
    return rec, None


def visit_commission_ready_for_deal(
    commissions: List[Dict[str, Any]] | None, phone: str, land_code: str
) -> bool:
    """پورسانت بازدید حذف شده — همیشه آمادهٔ معامله بعد از بازدید."""
    return True


def restore_visit_approved_after_deal_release(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> bool:
    """در جریان جدید، انجام بازدید حفظ می‌شود و با رفع معامله به تأییدشده برنمی‌گردد."""
    return False


def visit_tx_mode(
    assignment_status: str,
    *,
    has_visit_awaiting_admin: bool,
    has_approved_visit: bool,
    has_visit_done_pending: bool = False,
    has_completed_visit: bool = False,
    has_visit_no_show: bool = False,
    visit_commission_ready: bool = False,
    visit_commission_required: bool = False,
    has_pending_deal_commission: bool = False,
    deal_commission_rejected: bool = False,
    is_approved: bool,
    is_sold: bool,
) -> str:
    st = (assignment_status or "active").strip().lower()
    if is_sold:
        return "hidden"
    if not is_approved:
        # خریدار لاگین‌شده بازدید ثبت می‌کند؛ دکمه‌های معامله مخصوص مشاور می‌ماند.
        if has_visit_awaiting_admin:
            return "visit_pending"
        if has_visit_done_pending:
            return "visit_done_pending"
        if has_approved_visit:
            return "visit_done"
        if has_visit_no_show:
            return "visit_no_show"
        if has_completed_visit:
            return "visit_done"
        return "visit"
    if st == "in_transaction":
        return "release"
    if has_visit_awaiting_admin:
        return "visit_pending"
    if has_visit_done_pending:
        return "visit_done_pending"
    if has_approved_visit:
        return "visit_done"
    # Phase 2: no_show branch (only meaningful when flag-enabled callers pass True)
    if has_visit_no_show:
        return "visit_no_show"
    if has_completed_visit:
        # پورسانت بازدید حذف شده — بعد از بازدید مستقیم مسیر معامله
        _ = (visit_commission_required, visit_commission_ready)
        if has_pending_deal_commission:
            return "deal_pending"
        # رد معامله یا بعد از تکمیل بازدید → مسیر معامله (نه فقط بازدید مجدد)
        _ = deal_commission_rejected  # نگه‌داشت API؛ وضعیت active بعد از رد است
        return "deal"
    return "visit"


def resolve_partner_land_tx_state(
    *,
    me_phone: str,
    land_code: str,
    assignments: List[Dict[str, Any]],
    visit_requests: List[Dict[str, Any]],
    is_partner_approved: bool,
    global_assignment_status: str,
    commissions: List[Dict[str, Any]] | None = None,
    visit_commission_required: bool = False,
) -> Dict[str, Any]:
    """وضعیت دکمه معامله/بازدید برای همکار روی یک فایل."""
    code = (land_code or "").strip()
    gs = (global_assignment_status or "active").strip().lower()
    holder_phone = None
    for a in assignments or []:
        if str(a.get("land_code")) == str(code) and a.get("transaction_holder"):
            holder_phone = str(a.get("transaction_holder") or "").strip()
            break

    ph = (me_phone or "").strip()
    open_visit = partner_open_visit(visit_requests, ph, code) if ph else None
    awaiting = partner_visit_awaiting_admin(visit_requests, ph, code) if ph else None
    approved = partner_visit_approved_for_deal(visit_requests, ph, code) if ph else None
    done_pending = partner_visit_done_pending(visit_requests, ph, code) if ph else None
    completed = partner_visit_completed(visit_requests, ph, code) if ph else None
    no_show_rec = partner_visit_no_show(visit_requests, ph, code) if ph else None
    active_visit = partner_active_visit_record(visit_requests, ph, code) if ph else None
    visit_ready = visit_commission_ready_for_deal(commissions, ph, code) if ph else False
    pending_deal = partner_has_pending_deal_commission(commissions, ph, code) if ph else False
    deal_rejected = partner_deal_commission_rejected(commissions, ph, code) if ph else False
    can_revisit = partner_can_request_new_visit(gs, visit_requests, ph, code) if ph else False
    has_my_assignment = False
    if ph and code:
        for a in assignments or []:
            if not isinstance(a, dict):
                continue
            if str(a.get("partner_phone") or "").strip() != ph:
                continue
            if str(a.get("land_code") or "").strip() != code:
                continue
            has_my_assignment = True
            break
    deal_finalized = (
        bool(has_finalized_deal_commission(commissions, ph, code)) if ph and code else False
    )
    visit_date = (active_visit or {}).get("visit_date") or ""
    visit_date_jalali = format_iso_date_jalali(str(visit_date))
    visit_time = str((active_visit or {}).get("visit_time") or (active_visit or {}).get("time") or "").strip()
    if visit_date_jalali and visit_time:
        visit_date_jalali = f"{visit_date_jalali} — ساعت {to_fa_digits(visit_time)}"
    customer_phone = str((active_visit or {}).get("customer_phone") or "").strip()
    customer_name = str((active_visit or {}).get("customer_name") or "").strip()
    if not customer_name and active_visit:
        first = str(active_visit.get("customer_first_name") or "").strip()
        last = str(active_visit.get("customer_last_name") or "").strip()
        customer_name = f"{first} {last}".strip()

    if gs == "in_transaction":
        if ph and holder_phone == ph:
            # فروش نهایی ثبت شده و منتظر تأیید ادمین است
            if pending_deal:
                mode = "deal_pending"
            else:
                mode = "release"
        elif holder_phone:
            mode = "blocked"
        else:
            mode = "release"
    else:
        mode = visit_tx_mode(
            gs,
            has_visit_awaiting_admin=bool(awaiting),
            has_approved_visit=bool(approved),
            has_visit_done_pending=bool(done_pending),
            has_completed_visit=bool(completed),
            has_visit_no_show=bool(no_show_rec),
            visit_commission_ready=bool(visit_ready),
            visit_commission_required=bool(visit_commission_required),
            has_pending_deal_commission=bool(pending_deal),
            deal_commission_rejected=bool(deal_rejected),
            is_approved=is_partner_approved,
            is_sold=gs == "sold",
        )
        # ثبت معامله فقط روی فایلِ اختصاص‌یافته؛ کاتالوگ عمومی کافی نیست
        if mode == "deal" and not has_my_assignment:
            mode = "hidden"

    show_revisit = bool(
        can_revisit
        and (completed or no_show_rec)
        and not open_visit
        and not awaiting
        and not done_pending
        and not (
            completed
            and visit_commission_required
            and not visit_ready
        )
        and not pending_deal
        and gs not in ("sold", "in_transaction")
    )

    return {
        "tx_mode": mode,
        "assignment_status": gs,
        "visit_date": visit_date,
        "visit_date_jalali": visit_date_jalali,
        "visit_status": (str((active_visit or {}).get("status") or "")).strip(),
        "customer_phone": customer_phone,
        "customer_name": customer_name,
        "can_revisit": show_revisit,
        "has_assignment": has_my_assignment,
        "deal_finalized": deal_finalized,
    }


def admin_row_dict(
    row: Dict[str, Any],
    commissions: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    st = (str(row.get("status") or PENDING_STATUS)).strip()
    labels = {
        PENDING_STATUS: "در انتظار تأیید",
        APPROVED_STATUS: "تأیید شده — منتظر بازدید",
        DONE_PENDING_STATUS: "تأیید انجام",
        COMPLETED_STATUS: "انجام شد",
        CANCELLED_STATUS: "بسته شده",
        NO_SHOW_STATUS: "عدم حضور",
    }
    hints = {
        PENDING_STATUS: "تأیید = بازاریاب می‌تواند بازدید را هماهنگ کند.",
        APPROVED_STATUS: "منتظر اعلام «بازدید انجام شد» از چت بازاریاب.",
        DONE_PENDING_STATUS: "بازاریاب اعلام کرده — تأیید = معامله آزاد می‌شود.",
        COMPLETED_STATUS: "بازدید انجام شده؛ معامله از چت ممکن است.",
        CANCELLED_STATUS: "این درخواست بسته شده است.",
        NO_SHOW_STATUS: "مشتری حاضر نشد؛ بازدید مجدد از چت ممکن است.",
    }
    progress_steps = visit_progress_steps(row, commissions)
    progress_summary = visit_progress_summary(progress_steps)
    first = str(row.get("customer_first_name") or "").strip()
    last = str(row.get("customer_last_name") or "").strip()
    cust_name = str(row.get("customer_name") or "").strip() or f"{first} {last}".strip()
    return {
        "id": row.get("id"),
        "partner_phone": row.get("partner_phone") or "",
        "partner_name": row.get("partner_name") or "",
        "land_code": row.get("land_code") or "",
        "land_title": row.get("land_title") or "",
        "visit_date": row.get("visit_date") or "",
        "visit_date_jalali": format_iso_date_jalali(str(row.get("visit_date") or "")),
        "visit_time": str(row.get("visit_time") or row.get("time") or "").strip(),
        "customer_first_name": first,
        "customer_last_name": last,
        "customer_name": cust_name,
        "customer_phone": str(row.get("customer_phone") or "").strip(),
        "plus_user_phone": str(row.get("plus_user_phone") or "").strip(),
        "plus_user_name": str(row.get("plus_user_name") or "").strip(),
        "status": st,
        "status_label": labels.get(st, st),
        "status_hint": hints.get(st, ""),
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
        "approved_at": row.get("approved_at") or "",
        "visit_done_requested_at": row.get("visit_done_requested_at") or "",
        "completed_at": row.get("completed_at") or "",
        "admin_note": row.get("admin_note") or "",
        "notes": str(row.get("notes") or "").strip(),
        "progress_steps": progress_steps,
        "progress_summary": progress_summary,
        "filter_bucket": visit_filter_bucket(st),
        "is_editable": st in (PENDING_STATUS, APPROVED_STATUS, DONE_PENDING_STATUS),
        "needs_action": st in (PENDING_STATUS, DONE_PENDING_STATUS),
    }


def mark_admin_visit_plus(
    item: Dict[str, Any],
    *,
    plus_map: Dict[str, Any] | None = None,
    owner_by_code: Dict[str, Dict[str, str]] | None = None,
) -> None:
    """پرچم پلاس برای مانیتور ادمین: درخواست‌دهنده، تقویم پلاس، یا مالک آگهی."""
    if not isinstance(item, dict):
        return
    from .special_listings import _plus_display_name, plus_listing_owner_by_code, plus_partner_map

    pmap = plus_map if plus_map is not None else plus_partner_map()
    owners = owner_by_code if owner_by_code is not None else plus_listing_owner_by_code()

    def _lookup(phone: str) -> Any:
        raw = str(phone or "").strip()
        if not raw:
            return None
        rec = pmap.get(raw) or pmap.get(_canonical_visit_phone(raw))
        if rec is None:
            digits = "".join(ch for ch in raw if ch.isdigit())
            rec = pmap.get(digits)
        return rec

    requester_phone = str(item.get("partner_phone") or "").strip()
    calendar_phone = str(item.get("plus_user_phone") or "").strip()
    code = str(item.get("land_code") or "").strip()
    requester_rec = _lookup(requester_phone)
    calendar_rec = _lookup(calendar_phone) if calendar_phone else None
    owner = owners.get(code) if code else None

    item["is_plus"] = bool(requester_rec or calendar_phone or owner)
    if calendar_phone:
        item["plus_user_phone"] = _canonical_visit_phone(calendar_phone) or calendar_phone
        item["plus_user_name"] = (
            str(item.get("plus_user_name") or "").strip()
            or _plus_display_name(calendar_rec, calendar_phone)
        )
        item["plus_role"] = "calendar"
    elif requester_rec:
        item["plus_user_phone"] = _canonical_visit_phone(requester_phone) or requester_phone
        item["plus_user_name"] = _plus_display_name(requester_rec, requester_phone)
        item["plus_role"] = "requester"
    if owner:
        item["land_owner_phone"] = str(owner.get("phone") or "").strip()
        item["land_owner_name"] = str(owner.get("name") or "").strip()
        if not item.get("plus_role"):
            item["plus_role"] = "owner"

    marketer_phone = _canonical_visit_phone(requester_phone) or requester_phone
    item["marketer_phone"] = marketer_phone
    item["marketer_name"] = (
        str(item.get("partner_name") or "").strip()
        or _plus_display_name(requester_rec, marketer_phone)
        or marketer_phone
        or "بازاریاب"
    )
    colleague_phone = str(item.get("plus_user_phone") or "").strip()
    colleague_name = str(item.get("plus_user_name") or "").strip()
    if not colleague_phone and owner:
        colleague_phone = str(owner.get("phone") or "").strip()
        colleague_name = str(owner.get("name") or "").strip()
    item["colleague_phone"] = colleague_phone
    item["colleague_name"] = colleague_name or colleague_phone or "همکار پلاس"


def is_admin_legacy_visit(
    row: Dict[str, Any] | None,
    *,
    plus_map: Dict[str, Any] | None = None,
    owner_by_code: Dict[str, Dict[str, str]] | None = None,
    admin_land_codes: set[str] | None = None,
) -> bool:
    """بازدید قدیمی پنل ادمین — بدون کاربر/آگهی پلاس."""
    if not isinstance(row, dict):
        return False
    from .special_listings import plus_listing_owner_by_code, plus_partner_map

    pmap = plus_map if plus_map is not None else plus_partner_map()
    owners = owner_by_code if owner_by_code is not None else plus_listing_owner_by_code()
    admin_codes = admin_land_codes if admin_land_codes is not None else set()

    plus_phone = str(row.get("plus_user_phone") or "").strip()
    if plus_phone:
        return False
    partner = _canonical_visit_phone(row.get("partner_phone"))
    digits = "".join(ch for ch in partner if ch.isdigit())
    if partner and (pmap.get(partner) or pmap.get(digits)):
        return False
    code = str(row.get("land_code") or "").strip()
    if code and owners.get(code):
        return False
    if code and code in admin_codes:
        return True
    return True


def purge_admin_legacy_visits() -> int:
    """حذف بازدیدهایی که از پنل ادمین / بدون پلاس مانده‌اند."""
    from app.utils.storage import load_ads_cached, load_express_visit_requests, save_express_visit_requests

    from .special_listings import is_admin_created_express_listing, plus_listing_owner_by_code, plus_partner_map

    plus_map = plus_partner_map() or {}
    owners = plus_listing_owner_by_code() or {}
    admin_codes: set[str] = set()
    try:
        for land in load_ads_cached() or []:
            if is_admin_created_express_listing(land if isinstance(land, dict) else None):
                code = str((land or {}).get("code") or "").strip()
                if code:
                    admin_codes.add(code)
    except Exception:
        admin_codes = set()
    rows = load_express_visit_requests() or []
    if not isinstance(rows, list):
        return 0
    keep: List[Dict[str, Any]] = []
    removed = 0
    for row in rows:
        if is_admin_legacy_visit(
            row if isinstance(row, dict) else None,
            plus_map=plus_map,
            owner_by_code=owners,
            admin_land_codes=admin_codes,
        ):
            removed += 1
            continue
        keep.append(row)
    if removed:
        save_express_visit_requests(keep)
    return removed


ADMIN_VISIT_TRANSITIONS: Dict[str, frozenset] = {
    PENDING_STATUS: frozenset({PENDING_STATUS, APPROVED_STATUS, CANCELLED_STATUS}),
    APPROVED_STATUS: frozenset({APPROVED_STATUS, CANCELLED_STATUS}),
    DONE_PENDING_STATUS: frozenset({DONE_PENDING_STATUS, COMPLETED_STATUS, CANCELLED_STATUS, APPROVED_STATUS}),
    # بازدید تکمیل‌شده را نمی‌بندیم — مسیر معامله را خراب می‌کند
    COMPLETED_STATUS: frozenset({COMPLETED_STATUS}),
    CANCELLED_STATUS: frozenset({CANCELLED_STATUS}),
    # Phase 2: no_show transitions added dynamically via status_bridge when flags ON
    NO_SHOW_STATUS: frozenset({NO_SHOW_STATUS}),
}


def _admin_transitions() -> Dict[str, frozenset]:
    try:
        from app.visit_result.status_bridge import extend_admin_transitions

        return extend_admin_transitions(ADMIN_VISIT_TRANSITIONS)
    except Exception:
        return ADMIN_VISIT_TRANSITIONS


def visit_filter_bucket(status: str) -> str:
    st = (status or PENDING_STATUS).strip()
    if st == PENDING_STATUS:
        return "pending"
    if st == APPROVED_STATUS:
        return "approved"
    if st == DONE_PENDING_STATUS:
        return "done_pending"
    if st == COMPLETED_STATUS:
        return "done"
    if st == CANCELLED_STATUS:
        return "closed"
    if st == NO_SHOW_STATUS:
        return "no_show"
    return "other"


def admin_can_transition_visit(old_status: str, new_status: str) -> bool:
    old = (old_status or PENDING_STATUS).strip()
    new = (new_status or "").strip()
    if old == new:
        return True
    if new == COMPLETED_STATUS and old != DONE_PENDING_STATUS:
        return False
    if new == NO_SHOW_STATUS:
        try:
            from app.visit_result.status_bridge import is_no_show_writable

            if not is_no_show_writable():
                return False
        except Exception:
            return False
    allowed = _admin_transitions().get(old, frozenset({old}))
    return new in allowed


def admin_visit_workflow_steps(
    item: Dict[str, Any],
    *,
    visit_commission: Dict[str, Any] | None = None,
    deal_commission: Dict[str, Any] | None = None,
    visit_commission_required: bool = False,
) -> List[Dict[str, Any]]:
    """مراحل اقدام ادمین برای یک پرونده — همه در یک صفحه."""
    st = (str(item.get("status") or PENDING_STATUS)).strip()
    vc = visit_commission if isinstance(visit_commission, dict) else {}
    dc = deal_commission if isinstance(deal_commission, dict) else {}
    vc_st = (str(vc.get("status") or "")).strip().lower()
    dc_st = (str(dc.get("status") or "")).strip().lower()

    def _paid(status: str) -> bool:
        return status in ("approved", "paid")

    steps: List[Dict[str, Any]] = []

    if st == CANCELLED_STATUS:
        if item.get("approved_at"):
            s1, hint, action = "done", "", False
        else:
            s1, hint, action = "rejected", "درخواست بازدید رد شد.", False
    elif st == PENDING_STATUS:
        # سازگاری با درخواست‌های قدیمی که هنوز در صف تأیید بودند
        s1, hint, action = "current", "درخواست بازدید قدیمی — تأیید یا رد کنید (ثبت‌های جدید خودکار نهایی می‌شوند).", True
    else:
        s1, hint, action = "done", "درخواست بازدید نهایی شده است.", False
    steps.append({
        "key": "visit_request",
        "label": "ثبت درخواست بازدید",
        "state": s1,
        "hint": hint,
        "needs_action": action,
        "action_kind": "visit_status",
        "approve_status": APPROVED_STATUS,
        "reject_status": CANCELLED_STATUS,
    })

    if st == CANCELLED_STATUS:
        if item.get("visit_done_requested_at"):
            s2, hint, action = "rejected", "تأیید انجام بازدید رد شد.", False
        elif item.get("approved_at"):
            s2, hint, action = "rejected", "انجام بازدید لغو شد.", False
        else:
            s2, hint, action = "blocked", "", False
    elif st == DONE_PENDING_STATUS:
        s2, hint, action = "current", "اعلام انجام رسیده — تأیید یا رد کنید (معامله آزاد).", True
    elif st == COMPLETED_STATUS:
        s2, hint, action = "done", "", False
    elif st == APPROVED_STATUS:
        s2, hint, action = "waiting", "منتظر «بازدید انجام شد» از چت.", False
    else:
        s2, hint, action = "waiting", "پس از تأیید درخواست.", False
    steps.append({
        "key": "visit_done",
        "label": "تأیید انجام",
        "state": s2,
        "hint": hint,
        "needs_action": action,
        "action_kind": "visit_status",
        "approve_status": COMPLETED_STATUS,
        "reject_status": APPROVED_STATUS,
    })

    # پورسانت بازدید حذف شده — مرحلهٔ تأیید فروش نهایی بلافاصله بعد از بازدید
    _ = (visit_commission_required, vc, vc_st)

    if st == CANCELLED_STATUS:
        s4, hint, action = "blocked", "", False
    elif dc_st == "pending":
        s4, hint, action = (
            "current",
            "همکار فروش نهایی را ثبت کرده؛ با تأیید، فایل بسته و پورسانت فروش به کیف پول اضافه می‌شود.",
            True,
        )
    elif _paid(dc_st):
        s4, hint, action = "done", "فروش تأیید شد — فایل بسته و پورسانت فروش در کیف پول همکار است.", False
    elif dc_st == "rejected":
        s4, hint, action = "waiting", "معامله رد شد؛ همکار می‌تواند دوباره درخواست معامله بزند.", False
    elif st == COMPLETED_STATUS:
        s4, hint, action = "waiting", "منتظر فروش نهایی از سمت همکار.", False
    else:
        s4, hint, action = "waiting", "", False
    steps.append({
        "key": "deal_commission",
        "label": "تأیید فروش نهایی",
        "state": s4,
        "hint": hint,
        "needs_action": action,
        "action_kind": "commission" if action else "",
        "commission_id": dc.get("id"),
        "commission_amount": dc.get("commission_amount"),
    })

    return steps


def admin_visit_workflow_needs_action(steps: List[Dict[str, Any]]) -> bool:
    return any(
        s.get("needs_action")
        for s in (steps or [])
        if s.get("state") != "skipped"
    )


def admin_visit_in_workflow(
    item: Dict[str, Any],
    steps: List[Dict[str, Any]] | None = None,
) -> bool:
    st = (str(item.get("status") or "")).strip()
    if st == CANCELLED_STATUS:
        return False
    wf_steps = steps or []
    if admin_visit_workflow_needs_action(wf_steps):
        return True
    deal_step = next((s for s in wf_steps if s.get("key") == "deal_commission"), None)
    if deal_step and deal_step.get("state") == "done":
        return False
    return st in (PENDING_STATUS, APPROVED_STATUS, DONE_PENDING_STATUS, COMPLETED_STATUS)


def _admin_visit_activity_ts(item: Dict[str, Any]) -> str:
    return str(item.get("updated_at") or item.get("created_at") or "")


def _admin_visit_action_stage_rank(item: Dict[str, Any]) -> int:
    """اولویت مرحلهٔ اقدام: فروش نهایی > انجام بازدید > درخواست."""
    for step in item.get("admin_workflow_steps") or []:
        if not isinstance(step, dict):
            continue
        if step.get("state") == "skipped" or not step.get("needs_action"):
            continue
        key = str(step.get("key") or "")
        if key == "deal_commission":
            return 0
        if key == "visit_commission":
            return 1
        if key == "visit_done":
            return 2
        if key == "visit_request":
            return 3
        return 4
    return 9


def _pick_primary_admin_visit(group: List[Dict[str, Any]]) -> Dict[str, Any]:
    """اولویت کارت ادغام‌شده: مرحلهٔ مهم‌تر ادمین → اقدام لازم → در روند → جدیدتر."""

    def _rank(x: Dict[str, Any]) -> tuple:
        st = (str(x.get("status") or "")).strip()
        return (
            _admin_visit_action_stage_rank(x),
            0 if x.get("workflow_needs_action") else 1,
            0 if x.get("in_workflow") else 1,
            0 if st != CANCELLED_STATUS else 1,
        )

    best = min((_rank(x) for x in group), default=(9, 9, 9, 9))
    candidates = [x for x in group if _rank(x) == best]
    return max(candidates, key=_admin_visit_activity_ts)


def merge_admin_visit_cards_by_partner_land(
    items: List[Dict[str, Any]] | None,
) -> List[Dict[str, Any]]:
    """ادغام چند بازدید همان همکار روی همان فایل در یک کارت ادمین."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        ph = str(item.get("partner_phone") or "").strip()
        code = str(item.get("land_code") or "").strip()
        key = f"{ph}|{code}" if ph and code else f"solo:{item.get('id')}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    merged: List[Dict[str, Any]] = []
    for key in order:
        group = groups[key]
        history = sorted(group, key=_admin_visit_activity_ts, reverse=True)
        primary = _pick_primary_admin_visit(group)
        card = dict(primary)
        primary_id = str(primary.get("id") or "").strip()
        card["merged_visit_count"] = len(history)
        card["merged_visits"] = [
            {
                "id": h.get("id"),
                "visit_date": h.get("visit_date") or "",
                "visit_date_jalali": h.get("visit_date_jalali") or h.get("visit_date") or "",
                "visit_time": h.get("visit_time") or "",
                "customer_name": h.get("customer_name") or "",
                "customer_phone": h.get("customer_phone") or "",
                "status": h.get("status") or "",
                "status_label": h.get("status_label") or "",
                "admin_note": h.get("admin_note") or "",
                "workflow_needs_action": bool(h.get("workflow_needs_action")),
                "in_workflow": bool(h.get("in_workflow")),
                "plus_user_name": h.get("plus_user_name") or "",
                "plus_user_phone": h.get("plus_user_phone") or "",
                "is_plus": bool(h.get("is_plus")),
                "is_primary": str(h.get("id") or "").strip() == primary_id,
            }
            for h in history
        ]
        card["workflow_needs_action"] = any(bool(h.get("workflow_needs_action")) for h in history)
        card["in_workflow"] = any(bool(h.get("in_workflow")) for h in history)
        card["group_all_cancelled"] = all(
            (str(h.get("status") or "")).strip() == CANCELLED_STATUS for h in history
        )
        card["is_plus"] = any(bool(h.get("is_plus")) for h in history) or bool(card.get("is_plus"))
        if not card.get("plus_user_name"):
            for h in history:
                if h.get("plus_user_name") or h.get("plus_user_phone"):
                    card["plus_user_name"] = h.get("plus_user_name") or ""
                    card["plus_user_phone"] = h.get("plus_user_phone") or ""
                    break
        if not card.get("land_owner_name"):
            for h in history:
                if h.get("land_owner_name") or h.get("land_owner_phone"):
                    card["land_owner_name"] = h.get("land_owner_name") or ""
                    card["land_owner_phone"] = h.get("land_owner_phone") or ""
                    break
        if not card.get("colleague_name"):
            for h in history:
                if h.get("colleague_name") or h.get("colleague_phone"):
                    card["colleague_name"] = h.get("colleague_name") or ""
                    card["colleague_phone"] = h.get("colleague_phone") or ""
                    break
        if not card.get("marketer_name"):
            card["marketer_name"] = card.get("partner_name") or ""
            card["marketer_phone"] = card.get("partner_phone") or ""
        merged.append(card)
    return merged


def admin_visit_status_options(old_status: str) -> List[Dict[str, str]]:
    old = (old_status or PENDING_STATUS).strip()
    keys = _admin_transitions().get(old, frozenset({old}))
    order = (
        PENDING_STATUS,
        APPROVED_STATUS,
        DONE_PENDING_STATUS,
        COMPLETED_STATUS,
        CANCELLED_STATUS,
        NO_SHOW_STATUS,
    )
    labels = {
        PENDING_STATUS: "در انتظار تأیید",
        APPROVED_STATUS: "تأیید بازدید",
        DONE_PENDING_STATUS: "در انتظار تأیید انجام بازدید",
        COMPLETED_STATUS: "تأیید انجام بازدید",
        CANCELLED_STATUS: "بستن پرونده",
        NO_SHOW_STATUS: "عدم حضور (No-Show)",
    }
    out: List[Dict[str, str]] = []
    for key in order:
        if key in keys:
            out.append({"value": key, "label": labels.get(key, key)})
    return out
