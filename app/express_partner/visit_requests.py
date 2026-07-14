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

OPEN_VISIT_STATUSES = frozenset({PENDING_STATUS, APPROVED_STATUS, DONE_PENDING_STATUS})

VISIT_PROGRESS_STEP_KEYS = (
    ("visit_requested", "درخواست بازدید"),
    ("visit_approved", "نهایی شدن بازدید"),
    ("visit_done", "بازدید انجام شد"),
    ("visit_commission_paid", "واریز پورسانت بازدید"),
    ("deal_requested", "درخواست معامله"),
    ("deal_approved", "تأیید درخواست معامله"),
    ("deal_commission_paid", "واریز پورسانت معامله"),
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


def visit_date_min_iso() -> str:
    """حداقل تاریخ قابل انتخاب بازدید (امروز به وقت تهران)."""
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


def get_visit_allowed_weekdays() -> List[int]:
    try:
        from admin.routes import get_settings

        settings = get_settings() or {}
        return _normalize_weekday_list(settings.get("visit_allowed_weekdays"))
    except Exception:
        return list(DEFAULT_VISIT_ALLOWED_WEEKDAYS)


def save_visit_allowed_weekdays(weekdays: List[int]) -> List[int]:
    from admin.routes import get_settings, save_settings

    normalized = _normalize_weekday_list(weekdays)
    save_settings({"visit_allowed_weekdays": normalized})
    return normalized


def visit_allowed_weekdays_for_js() -> List[int]:
    return [_PY_WEEKDAY_TO_JS[wd] for wd in get_visit_allowed_weekdays() if wd in _PY_WEEKDAY_TO_JS]


def visit_weekday_label_for_date(d: date) -> str:
    return VISIT_WEEKDAY_LABELS.get(d.weekday(), "")


def is_visit_weekday_allowed(d: date, *, allowed: Optional[List[int]] = None) -> bool:
    days = _normalize_weekday_list(allowed if allowed is not None else get_visit_allowed_weekdays())
    return d.weekday() in days


def visit_allowed_weekdays_summary() -> str:
    days = get_visit_allowed_weekdays()
    return "، ".join(VISIT_WEEKDAY_LABELS.get(wd, str(wd)) for wd in VISIT_WEEKDAY_ORDER if wd in days)


def list_upcoming_visit_dates(*, limit: int = 7, days_ahead: int = 90) -> List[Dict[str, Any]]:
    """تاریخ‌های مجاز بعدی برای انتخاب در چت — شماره‌دار، فقط برچسب شمسی."""
    today = _today()
    end = today + timedelta(days=max(1, int(days_ahead) or 90))
    out: List[Dict[str, Any]] = []
    d = today
    n = 1
    lim = max(1, min(int(limit) or 7, 15))
    while d <= end and len(out) < lim:
        if is_visit_weekday_allowed(d):
            iso = d.isoformat()
            jalali = format_iso_date_jalali(iso) or ""
            jalali_fa = format_display_jalali_date(iso)
            weekday = visit_weekday_label_for_date(d)
            n_fa = to_fa_digits(n)
            out.append(
                {
                    "n": n,
                    "iso": iso,  # داخلی — به کاربر نشان داده نشود
                    "jalali": jalali,
                    "jalali_fa": jalali_fa,
                    "weekday": weekday,
                    "label": f"{n_fa}) {weekday} {jalali_fa}",
                }
            )
            n += 1
        d += timedelta(days=1)
    return out


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
    visit_commission_required_raw = row.get("visit_commission_required")
    visit_commission_required = (
        bool(visit_commission_required_raw)
        if visit_commission_required_raw is not None
        else bool(visit_commissions)
    )
    visit_commission_paid = any(
        str(c.get("status") or "").strip().lower() in ("approved", "paid")
        for c in visit_commissions
    )
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
        status in (APPROVED_STATUS, DONE_PENDING_STATUS, COMPLETED_STATUS)
        or (status == CANCELLED_STATUS and was_approved)
    )
    visit_done = status == COMPLETED_STATUS
    visit_commission_done = visit_done and (not visit_commission_required or visit_commission_paid)
    done = [
        visit_requested_done,
        visit_approved_done,
        visit_done,
        visit_commission_done,
        visit_done and deal_requested,
        visit_done and deal_approved,
        visit_done and deal_paid,
    ]
    current_idx = next((idx for idx, is_done in enumerate(done) if not is_done), None)
    steps: List[Dict[str, Any]] = []
    for idx, (key, label) in enumerate(VISIT_PROGRESS_STEP_KEYS):
        state = "done" if done[idx] else "todo"
        if idx == current_idx and state == "todo" and status != CANCELLED_STATUS:
            state = "current"
        steps.append({"key": key, "label": label, "state": state})
    if status == CANCELLED_STATUS:
        reject_key = _visit_cancelled_reject_step_key(row)
        for step in steps:
            if step.get("key") == reject_key and step["state"] != "done":
                step["state"] = "rejected"
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
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    ph = (partner_phone or "").strip()
    code = (land_code or "").strip()
    first = (customer_first_name or "").strip()
    last = (customer_last_name or "").strip()
    cust_phone = (customer_phone or "").strip()
    vd = _parse_visit_date(visit_date)
    if not ph or not code:
        return None, "invalid"
    if not first or not last or not cust_phone:
        return None, "customer_required"
    if vd is None:
        return None, "invalid_date"
    if vd < _today():
        return None, "past_date"
    if vd > _today() + timedelta(days=90):
        return None, "date_too_far"
    if not is_visit_weekday_allowed(vd):
        return None, "weekday_not_allowed"
    if partner_open_visit(requests, ph, code):
        return None, "already_pending"

    now_iso = datetime.utcnow().isoformat() + "Z"
    full_name = f"{first} {last}".strip()
    # درخواست بازدید بدون صف تأیید ادمین نهایی می‌شود؛ فقط پیامک اطلاع‌رسانی می‌رود.
    rec: Dict[str, Any] = {
        "id": uuid.uuid4().hex[:16],
        "partner_phone": ph,
        "partner_name": (partner_name or "").strip() or ph,
        "land_code": code,
        "land_title": (land_title or "").strip() or code,
        "visit_date": vd.isoformat(),
        "customer_first_name": first,
        "customer_last_name": last,
        "customer_name": full_name,
        "customer_phone": cust_phone,
        "status": APPROVED_STATUS,
        "created_at": now_iso,
        "updated_at": now_iso,
        "approved_at": now_iso,
        "auto_approved": True,
    }
    requests.append(rec)
    return rec, None


ADMIN_VISIT_STATUSES = frozenset({
    PENDING_STATUS,
    APPROVED_STATUS,
    DONE_PENDING_STATUS,
    COMPLETED_STATUS,
    CANCELLED_STATUS,
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
    return rec, None


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
    pending = partner_visit_done_pending(requests, phone, land_code)
    if pending:
        return pending, "already_pending"
    rec = partner_visit_approved_for_deal(requests, phone, land_code)
    if not rec:
        return None, "not_approved"
    now_iso = datetime.utcnow().isoformat() + "Z"
    rec["status"] = DONE_PENDING_STATUS
    rec["updated_at"] = now_iso
    rec["visit_done_requested_at"] = now_iso
    return rec, None


def visit_commission_ready_for_deal(
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
        if not commission_is_visit(c):
            continue
        if str(c.get("status") or "").strip().lower() in ("approved", "paid"):
            return True
    return False


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
    if has_completed_visit:
        if visit_commission_required and not visit_commission_ready:
            return "visit_commission_pending"
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
        and completed
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
        APPROVED_STATUS: "تأیید شده — در انتظار انجام بازدید",
        DONE_PENDING_STATUS: "در انتظار تأیید انجام بازدید",
        COMPLETED_STATUS: "بازدید انجام شد",
        CANCELLED_STATUS: "بسته شده",
    }
    hints = {
        PENDING_STATUS: "تأیید کنید تا همکار پس از انجام بازدید، آن را روی فایل ثبت کند.",
        APPROVED_STATUS: "همکار باید پس از انجام بازدید، آن را از روی فایل ثبت کند.",
        DONE_PENDING_STATUS: "همکار انجام بازدید را ثبت کرده؛ پس از تأیید شما، پورسانت بازدید در صف تأیید قرار می‌گیرد.",
        COMPLETED_STATUS: "بازدید انجام شده؛ پس از تأیید پورسانت بازدید، درخواست معامله فعال می‌شود.",
        CANCELLED_STATUS: "این درخواست بسته شده است.",
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
        "customer_first_name": first,
        "customer_last_name": last,
        "customer_name": cust_name,
        "customer_phone": str(row.get("customer_phone") or "").strip(),
        "status": st,
        "status_label": labels.get(st, st),
        "status_hint": hints.get(st, ""),
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
        "approved_at": row.get("approved_at") or "",
        "visit_done_requested_at": row.get("visit_done_requested_at") or "",
        "completed_at": row.get("completed_at") or "",
        "admin_note": row.get("admin_note") or "",
        "progress_steps": progress_steps,
        "progress_summary": progress_summary,
        "filter_bucket": visit_filter_bucket(st),
        "is_editable": st in (PENDING_STATUS, APPROVED_STATUS, DONE_PENDING_STATUS),
        "needs_action": st in (PENDING_STATUS, DONE_PENDING_STATUS),
    }


ADMIN_VISIT_TRANSITIONS: Dict[str, frozenset] = {
    PENDING_STATUS: frozenset({PENDING_STATUS, APPROVED_STATUS, CANCELLED_STATUS}),
    APPROVED_STATUS: frozenset({APPROVED_STATUS, CANCELLED_STATUS}),
    DONE_PENDING_STATUS: frozenset({DONE_PENDING_STATUS, COMPLETED_STATUS, CANCELLED_STATUS, APPROVED_STATUS}),
    # بازدید تکمیل‌شده را نمی‌بندیم — مسیر معامله را خراب می‌کند
    COMPLETED_STATUS: frozenset({COMPLETED_STATUS}),
    CANCELLED_STATUS: frozenset({CANCELLED_STATUS}),
}


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
    return "other"


def admin_can_transition_visit(old_status: str, new_status: str) -> bool:
    old = (old_status or PENDING_STATUS).strip()
    new = (new_status or "").strip()
    if old == new:
        return True
    if new == COMPLETED_STATUS and old != DONE_PENDING_STATUS:
        return False
    allowed = ADMIN_VISIT_TRANSITIONS.get(old, frozenset({old}))
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
        s2, hint, action = "current", "همکار «بازدید انجام شد» را ثبت کرده؛ تأیید یا رد کنید.", True
    elif st == COMPLETED_STATUS:
        s2, hint, action = "done", "", False
    elif st == APPROVED_STATUS:
        s2, hint, action = "waiting", "منتظر ثبت «بازدید انجام شد» توسط همکار روی فایل.", False
    else:
        s2, hint, action = "waiting", "پس از تأیید درخواست بازدید.", False
    steps.append({
        "key": "visit_done",
        "label": "تأیید انجام بازدید",
        "state": s2,
        "hint": hint,
        "needs_action": action,
        "action_kind": "visit_status",
        "approve_status": COMPLETED_STATUS,
        "reject_status": APPROVED_STATUS,
    })

    skip_visit_commission = (
        not visit_commission_required
        and (not vc or vc_st == "rejected")
    )
    if skip_visit_commission:
        steps.append({
            "key": "visit_commission",
            "label": "پورسانت بازدید",
            "state": "skipped",
            "hint": "",
            "needs_action": False,
            "action_kind": "",
        })
    else:
        if st == CANCELLED_STATUS:
            s3, hint, action = "blocked", "", False
        elif st != COMPLETED_STATUS:
            s3, hint, action = "waiting", "بعد از تأیید انجام بازدید.", False
        elif vc_st == "pending":
            s3, hint, action = "current", "پورسانت بازدید منتظر تأیید یا رد شماست.", True
        elif _paid(vc_st):
            s3, hint, action = "done", "به کیف پول همکار اضافه شد.", False
        elif vc_st == "rejected":
            s3, hint, action = "current", "پورسانت بازدید رد شده؛ برای ادامه، مجدداً ثبت کنید.", True
        else:
            s3, hint, action = "waiting", "بعد از تأیید انجام بازدید ساخته می‌شود.", False
        steps.append({
            "key": "visit_commission",
            "label": "تأیید پورسانت بازدید",
            "state": s3,
            "hint": hint,
            "needs_action": action,
            "action_kind": "recreate_commission" if (action and vc_st == "rejected") else ("commission" if action else ""),
            "commission_id": vc.get("id"),
            "commission_amount": vc.get("commission_amount"),
            "withdrawal_locked": bool(vc.get("withdrawal_locked")),
        })

    if not visit_commission_required:
        visit_gate = True
    else:
        visit_gate = _paid(vc_st)

    if st == CANCELLED_STATUS:
        s4, hint, action = "blocked", "", False
    elif dc_st == "pending":
        # همکار فروش را ثبت کرده — حتی اگر پیوند پورسانت بازدید ناقص باشد، کارت تأیید نشان بده
        s4, hint, action = (
            "current",
            "همکار فروش نهایی را ثبت کرده؛ با تأیید، فایل بسته و پورسانت به کیف پول اضافه می‌شود.",
            True,
        )
    elif not visit_gate:
        s4, hint, action = "waiting", "بعد از تأیید پورسانت بازدید، همکار درخواست معامله می‌زند.", False
    elif _paid(dc_st):
        s4, hint, action = "done", "فروش تأیید شد — فایل بسته و پورسانت در کیف پول همکار است.", False
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
    """اولویت مرحلهٔ اقدام: فروش نهایی > پورسانت بازدید > انجام بازدید > درخواست."""
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
                "customer_name": h.get("customer_name") or "",
                "customer_phone": h.get("customer_phone") or "",
                "status": h.get("status") or "",
                "status_label": h.get("status_label") or "",
                "admin_note": h.get("admin_note") or "",
                "workflow_needs_action": bool(h.get("workflow_needs_action")),
                "in_workflow": bool(h.get("in_workflow")),
                "is_primary": str(h.get("id") or "").strip() == primary_id,
            }
            for h in history
        ]
        card["workflow_needs_action"] = any(bool(h.get("workflow_needs_action")) for h in history)
        card["in_workflow"] = any(bool(h.get("in_workflow")) for h in history)
        card["group_all_cancelled"] = all(
            (str(h.get("status") or "")).strip() == CANCELLED_STATUS for h in history
        )
        merged.append(card)
    return merged


def admin_visit_status_options(old_status: str) -> List[Dict[str, str]]:
    old = (old_status or PENDING_STATUS).strip()
    keys = ADMIN_VISIT_TRANSITIONS.get(old, frozenset({old}))
    order = (PENDING_STATUS, APPROVED_STATUS, DONE_PENDING_STATUS, COMPLETED_STATUS, CANCELLED_STATUS)
    labels = {
        PENDING_STATUS: "در انتظار تأیید",
        APPROVED_STATUS: "تأیید بازدید",
        DONE_PENDING_STATUS: "در انتظار تأیید انجام بازدید",
        COMPLETED_STATUS: "تأیید انجام بازدید",
        CANCELLED_STATUS: "بستن پرونده",
    }
    out: List[Dict[str, str]] = []
    for key in order:
        if key in keys:
            out.append({"value": key, "label": labels.get(key, key)})
    return out
