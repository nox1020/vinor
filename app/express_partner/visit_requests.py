# -*- coding: utf-8 -*-
"""درخواست بازدید همکار از فایل اکسپرس."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..utils.dates import format_iso_date_jalali
from .commissions_flow import commission_is_deal, commission_is_visit

PENDING_STATUS = "pending"
APPROVED_STATUS = "approved"
COMPLETED_STATUS = "completed"
CANCELLED_STATUS = "cancelled"

OPEN_VISIT_STATUSES = frozenset({PENDING_STATUS, APPROVED_STATUS})

VISIT_PROGRESS_STEP_KEYS = (
    ("visit_requested", "درخواست بازدید"),
    ("visit_approved", "تأیید درخواست"),
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


def _parse_visit_date(raw: Any) -> Optional[date]:
    s = (str(raw or "")).strip()[:10]
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


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
    visit_commissions = [c for c in related if commission_is_visit(c)]
    deal_commissions = [c for c in related if commission_is_deal(c)]
    visit_commission_paid = any(
        str(c.get("status") or "").strip().lower() == "paid"
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
    done = [
        visit_requested_done,
        status in (APPROVED_STATUS, COMPLETED_STATUS),
        status == COMPLETED_STATUS,
        visit_commission_paid,
        deal_requested,
        deal_approved,
        deal_paid,
    ]
    highest_done_idx = max((idx for idx, is_done in enumerate(done) if is_done), default=-1)
    current_idx = next(
        (idx for idx, is_done in enumerate(done) if idx > highest_done_idx and not is_done),
        None,
    )
    if current_idx is None:
        current_idx = next((idx for idx, is_done in enumerate(done) if not is_done), None)
    steps: List[Dict[str, Any]] = []
    for idx, (key, label) in enumerate(VISIT_PROGRESS_STEP_KEYS):
        state = "done" if done[idx] else "todo"
        if idx == current_idx and state == "todo" and status != CANCELLED_STATUS:
            state = "current"
        steps.append({"key": key, "label": label, "state": state})
    if status == CANCELLED_STATUS:
        for step in steps:
            if step["state"] != "done":
                step["state"] = "blocked"
    return steps


def visit_progress_summary(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    done_count = 0
    current_label = ""
    for step in steps or []:
        if step.get("state") == "done":
            done_count += 1
        elif not current_label and step.get("state") in ("current", "blocked"):
            current_label = str(step.get("label") or "")
    total = len(steps or [])
    if not current_label and total and done_count >= total:
        current_label = "تکمیل شد"
    return {
        "done_count": done_count,
        "total": total,
        "current_label": current_label or "در جریان",
    }


def partner_open_visit(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> Optional[Dict[str, Any]]:
    """درخواست بازدید فعال (در انتظار تأیید یا تأییدشده)."""
    ph = (phone or "").strip()
    code = (land_code or "").strip()
    if not ph or not code:
        return None
    for r in requests:
        if not _match_partner_land(r, ph, code):
            continue
        if (str(r.get("status") or "")).strip() in OPEN_VISIT_STATUSES:
            return r
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
    ph = (phone or "").strip()
    code = (land_code or "").strip()
    if not ph or not code:
        return None
    for r in requests:
        if not _match_partner_land(r, ph, code):
            continue
        if (str(r.get("status") or "")).strip() == APPROVED_STATUS:
            return r
    return None


def partner_has_open_visit(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> bool:
    return partner_open_visit(requests, phone, land_code) is not None


# سازگاری با کد قبلی
def partner_pending_visit(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> Optional[Dict[str, Any]]:
    return partner_open_visit(requests, phone, land_code)


def partner_has_pending_visit(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> bool:
    return partner_visit_approved_for_deal(requests, phone, land_code) is not None


def create_visit_request(
    requests: List[Dict[str, Any]],
    *,
    partner_phone: str,
    partner_name: str,
    land_code: str,
    land_title: str,
    visit_date: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    ph = (partner_phone or "").strip()
    code = (land_code or "").strip()
    vd = _parse_visit_date(visit_date)
    if not ph or not code:
        return None, "invalid"
    if vd is None:
        return None, "invalid_date"
    if vd < _today():
        return None, "past_date"
    if vd > _today() + timedelta(days=90):
        return None, "date_too_far"
    if not is_visit_weekday_allowed(vd):
        return None, "weekday_not_allowed"
    if partner_has_open_visit(requests, ph, code):
        return None, "already_pending"

    now_iso = datetime.utcnow().isoformat() + "Z"
    rec: Dict[str, Any] = {
        "id": uuid.uuid4().hex[:16],
        "partner_phone": ph,
        "partner_name": (partner_name or "").strip() or ph,
        "land_code": code,
        "land_title": (land_title or "").strip() or code,
        "visit_date": vd.isoformat(),
        "status": PENDING_STATUS,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    requests.append(rec)
    return rec, None


def approve_visit_request(
    requests: List[Dict[str, Any]], request_id: str
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    rid = (request_id or "").strip()
    if not rid:
        return None, "not_found"
    for r in requests:
        if not isinstance(r, dict):
            continue
        if str(r.get("id") or "") != rid:
            continue
        st = (str(r.get("status") or "")).strip()
        if st == APPROVED_STATUS:
            return r, "already_approved"
        if st != PENDING_STATUS:
            return None, "invalid_status"
        now_iso = datetime.utcnow().isoformat() + "Z"
        r["status"] = APPROVED_STATUS
        r["updated_at"] = now_iso
        r["approved_at"] = now_iso
        return r, None
    return None, "not_found"


ADMIN_VISIT_STATUSES = frozenset({
    PENDING_STATUS,
    APPROVED_STATUS,
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
        rec.pop("completed_at", None)
    elif target == COMPLETED_STATUS:
        rec["completed_at"] = now_iso
        if not rec.get("approved_at"):
            rec["approved_at"] = now_iso
    elif target == PENDING_STATUS:
        rec.pop("approved_at", None)
        rec.pop("completed_at", None)
    elif target == CANCELLED_STATUS:
        rec.pop("approved_at", None)
        rec.pop("completed_at", None)
    return rec, None


def reject_visit_request(
    requests: List[Dict[str, Any]], request_id: str, *, admin_note: str = ""
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    rid = (request_id or "").strip()
    if not rid:
        return None, "not_found"
    for r in requests:
        if not isinstance(r, dict):
            continue
        if str(r.get("id") or "") != rid:
            continue
        st = (str(r.get("status") or "")).strip()
        if st != PENDING_STATUS:
            return None, "invalid_status"
        now_iso = datetime.utcnow().isoformat() + "Z"
        r["status"] = CANCELLED_STATUS
        r["updated_at"] = now_iso
        if admin_note:
            r["admin_note"] = admin_note.strip()
        return r, None
    return None, "not_found"


def complete_visit_for_deal(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> bool:
    rec = partner_visit_approved_for_deal(requests, phone, land_code)
    if not rec:
        return False
    now_iso = datetime.utcnow().isoformat() + "Z"
    rec["status"] = COMPLETED_STATUS
    rec["updated_at"] = now_iso
    rec["completed_at"] = now_iso
    return True


def restore_visit_approved_after_deal_release(
    requests: List[Dict[str, Any]], phone: str, land_code: str
) -> bool:
    """پس از رفع معامله، بازدید تأییدشده را برمی‌گرداند تا معامله دوباره ممکن شود."""
    ph = (phone or "").strip()
    code = (land_code or "").strip()
    if not ph or not code:
        return False
    for r in requests:
        if not _match_partner_land(r, ph, code):
            continue
        if (str(r.get("status") or "")).strip() != COMPLETED_STATUS:
            continue
        now_iso = datetime.utcnow().isoformat() + "Z"
        r["status"] = APPROVED_STATUS
        r["updated_at"] = now_iso
        r.pop("completed_at", None)
        return True
    return False


def visit_tx_mode(
    assignment_status: str,
    *,
    has_visit_awaiting_admin: bool,
    has_approved_visit: bool,
    is_approved: bool,
    is_sold: bool,
) -> str:
    st = (assignment_status or "active").strip().lower()
    if not is_approved or is_sold:
        return "hidden"
    if st == "in_transaction":
        return "release"
    if has_approved_visit:
        return "deal"
    if has_visit_awaiting_admin:
        return "visit_pending"
    return "visit"


def resolve_partner_land_tx_state(
    *,
    me_phone: str,
    land_code: str,
    assignments: List[Dict[str, Any]],
    visit_requests: List[Dict[str, Any]],
    is_partner_approved: bool,
    global_assignment_status: str,
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
    visit_date = (open_visit or {}).get("visit_date") or ""
    visit_date_jalali = format_iso_date_jalali(str(visit_date))

    if gs == "in_transaction":
        if ph and holder_phone == ph:
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
            is_approved=is_partner_approved,
            is_sold=gs == "sold",
        )

    return {
        "tx_mode": mode,
        "assignment_status": gs,
        "visit_date": visit_date,
        "visit_date_jalali": visit_date_jalali,
        "visit_status": (str((open_visit or {}).get("status") or "")).strip(),
    }


def tx_button_mode(
    assignment_status: str,
    *,
    has_pending_visit: bool,
    is_approved: bool,
    is_sold: bool,
    has_visit_awaiting_admin: bool = False,
) -> str:
    return visit_tx_mode(
        assignment_status,
        has_visit_awaiting_admin=has_visit_awaiting_admin,
        has_approved_visit=has_pending_visit,
        is_approved=is_approved,
        is_sold=is_sold,
    )


def admin_row_dict(
    row: Dict[str, Any],
    commissions: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    st = (str(row.get("status") or PENDING_STATUS)).strip()
    labels = {
        PENDING_STATUS: "در انتظار تأیید",
        APPROVED_STATUS: "تأیید شده — آماده معامله",
        COMPLETED_STATUS: "معامله ثبت شد",
        CANCELLED_STATUS: "رد شده",
    }
    hints = {
        PENDING_STATUS: "تأیید کنید تا همکار بتواند «درخواست معامله» بزند.",
        APPROVED_STATUS: "همکار می‌تواند درخواست معامله ثبت کند.",
        COMPLETED_STATUS: "همکار معامله را شروع کرده — پورسانت در بخش پورسانت‌ها.",
        CANCELLED_STATUS: "این درخواست بسته شده است.",
    }
    progress_steps = visit_progress_steps(row, commissions)
    progress_summary = visit_progress_summary(progress_steps)
    return {
        "id": row.get("id"),
        "partner_phone": row.get("partner_phone") or "",
        "partner_name": row.get("partner_name") or "",
        "land_code": row.get("land_code") or "",
        "land_title": row.get("land_title") or "",
        "visit_date": row.get("visit_date") or "",
        "visit_date_jalali": format_iso_date_jalali(str(row.get("visit_date") or "")),
        "status": st,
        "status_label": labels.get(st, st),
        "status_hint": hints.get(st, ""),
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
        "approved_at": row.get("approved_at") or "",
        "completed_at": row.get("completed_at") or "",
        "admin_note": row.get("admin_note") or "",
        "progress_steps": progress_steps,
        "progress_summary": progress_summary,
        "filter_bucket": visit_filter_bucket(st),
        "is_editable": st in (PENDING_STATUS, APPROVED_STATUS),
        "needs_action": st == PENDING_STATUS,
    }


ADMIN_VISIT_TRANSITIONS: Dict[str, frozenset] = {
    PENDING_STATUS: frozenset({PENDING_STATUS, APPROVED_STATUS, CANCELLED_STATUS}),
    APPROVED_STATUS: frozenset({APPROVED_STATUS, CANCELLED_STATUS}),
    COMPLETED_STATUS: frozenset({COMPLETED_STATUS}),
    CANCELLED_STATUS: frozenset({CANCELLED_STATUS}),
}


def visit_filter_bucket(status: str) -> str:
    st = (status or PENDING_STATUS).strip()
    if st == PENDING_STATUS:
        return "pending"
    if st == APPROVED_STATUS:
        return "approved"
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
    if new == COMPLETED_STATUS:
        return False
    allowed = ADMIN_VISIT_TRANSITIONS.get(old, frozenset({old}))
    return new in allowed


def admin_visit_status_options(old_status: str) -> List[Dict[str, str]]:
    old = (old_status or PENDING_STATUS).strip()
    keys = ADMIN_VISIT_TRANSITIONS.get(old, frozenset({old}))
    order = (PENDING_STATUS, APPROVED_STATUS, CANCELLED_STATUS)
    labels = {
        PENDING_STATUS: "در انتظار تأیید",
        APPROVED_STATUS: "تأیید بازدید",
        CANCELLED_STATUS: "رد درخواست",
    }
    out: List[Dict[str, str]] = []
    for key in order:
        if key in keys:
            out.append({"value": key, "label": labels.get(key, key)})
    return out
