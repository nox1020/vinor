# -*- coding: utf-8 -*-
"""درخواست بازدید همکار از فایل اکسپرس."""
from __future__ import annotations

import uuid
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
    save_express_partners(partners)
    return days, hrs, ""


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


def _canonical_visit_phone(raw: Any) -> str:
    phone = str(raw or "").strip()
    if not phone:
        return ""
    try:
        from .partner_session_sync import canonical_partner_phone

        return canonical_partner_phone(phone) or phone
    except Exception:
        return phone


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


def partner_visits_for_phone(
    requests: List[Dict[str, Any]],
    phone: str,
) -> List[Dict[str, Any]]:
    """همهٔ درخواست‌های بازدید یک همکار — جدید به قدیم."""
    ph = (phone or "").strip()
    if not ph:
        return []
    out: List[Dict[str, Any]] = []
    for r in requests or []:
        if not isinstance(r, dict):
            continue
        if (str(r.get("partner_phone") or "").strip()) != ph:
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


def partner_request_feed_item(
    row: Dict[str, Any],
    commissions: List[Dict[str, Any]] | None = None,
    *,
    can_revisit: bool = False,
    support_phone: str = "",
) -> Dict[str, Any]:
    """کارت سادهٔ صفحهٔ درخواست‌ها برای همکار."""
    del commissions  # پورسانت در کارت ساده لازم نیست
    st = (str(row.get("status") or PENDING_STATUS)).strip()
    labels = {
        PENDING_STATUS: "در جریان",
        APPROVED_STATUS: "زمان‌بندی شده",
        DONE_PENDING_STATUS: "منتظر تأیید",
        COMPLETED_STATUS: "انجام شد",
        CANCELLED_STATUS: "لغو شده",
        NO_SHOW_STATUS: "عدم حضور",
    }
    first = str(row.get("customer_first_name") or "").strip()
    last = str(row.get("customer_last_name") or "").strip()
    cust_name = str(row.get("customer_name") or "").strip() or f"{first} {last}".strip()
    visit_date = str(row.get("visit_date") or "").strip()
    jalali = format_display_jalali_date(visit_date) or format_iso_date_jalali(visit_date) or ""
    weekday = ""
    try:
        d = parse_gregorian_iso_date(visit_date)
        if d is not None:
            weekday = visit_weekday_label_for_date(d)
    except Exception:
        weekday = ""
    visit_time_raw = str(row.get("visit_time") or row.get("time") or "").strip()
    hour = parse_visit_hour(visit_time_raw)
    if hour is not None:
        visit_time = format_visit_hour_label(hour)
    elif visit_time_raw:
        visit_time = to_fa_digits(visit_time_raw)
    else:
        visit_time = ""
    when_parts = [p for p in (weekday, jalali) if p]
    visit_when = " ".join(when_parts)
    if visit_time:
        visit_when = f"{visit_when} — ساعت {visit_time}".strip(" —")
    notes = str(row.get("notes") or "").strip()
    land_code = str(row.get("land_code") or "").strip()
    land_title = visit_request_display_title(row)
    plus_user_name = str(row.get("plus_user_name") or "").strip()
    plus_user_phone = str(row.get("plus_user_phone") or "").strip()
    support = (support_phone or "").strip()
    can_cancel = st in (PENDING_STATUS, APPROVED_STATUS)
    can_delete = st in (CANCELLED_STATUS, NO_SHOW_STATUS, COMPLETED_STATUS)
    return {
        "id": str(row.get("id") or "").strip(),
        "kind": "visit",
        "land_code": land_code,
        "land_title": land_title,
        "plus_user_name": plus_user_name,
        "plus_user_phone": plus_user_phone,
        "title": land_title,
        "customer_name": cust_name,
        "visit_date": visit_date,
        "visit_date_jalali": jalali,
        "visit_weekday": weekday,
        "visit_time": visit_time,
        "visit_when": visit_when,
        "notes": notes,
        "support_phone": support,
        "status": st,
        "status_label": labels.get(st, st or "در جریان"),
        "can_cancel": can_cancel,
        "can_delete": can_delete,
        "can_revisit": bool(can_revisit),
        "can_remove": can_cancel or can_delete,
    }


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
    if not plus_phone and code:
        plus_phone = plus_phone_for_land_code(code)
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
    picked = resolve_free_visit_slot(
        requests,
        visit_day=vd,
        visit_hour=requested_hour,
        plus_user_phone=plus_phone,
    )
    if not picked:
        return None, "no_hours"
    vd, hour = picked
    if code and partner_open_visit(requests, ph, code):
        return None, "already_pending"

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
    if auto:
        rec["approved_at"] = now_iso
    requests.append(rec)
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


def _notify_plus_user_new_visit(rec: Dict[str, Any] | None) -> None:
    """اعلان درون‌برنامه برای کاربر پلاس انتخاب‌شده در وقت بازدید."""
    if not isinstance(rec, dict):
        return
    plus_phone = str(rec.get("plus_user_phone") or "").strip()
    if not plus_phone:
        return
    requester = str(rec.get("partner_phone") or "").strip()
    if plus_phone == requester:
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
            action_url = url_for("express_partner.requests")
        except Exception:
            action_url = "/express/partner/requests"
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
    if not is_approved or is_sold:
        return "hidden"
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
