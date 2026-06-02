# -*- coding: utf-8 -*-
"""درخواست بازدید همکار از فایل اکسپرس."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ..utils.dates import format_iso_date_jalali

PENDING_STATUS = "pending"
APPROVED_STATUS = "approved"
COMPLETED_STATUS = "completed"
CANCELLED_STATUS = "cancelled"

OPEN_VISIT_STATUSES = frozenset({PENDING_STATUS, APPROVED_STATUS})


def _today() -> date:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Tehran")).date()
    except Exception:
        return datetime.utcnow().date()


def visit_date_min_iso() -> str:
    """حداقل تاریخ قابل انتخاب بازدید (امروز به وقت تهران)."""
    return _today().isoformat()


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


def admin_row_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    st = (str(row.get("status") or PENDING_STATUS)).strip()
    labels = {
        PENDING_STATUS: "در انتظار تأیید",
        APPROVED_STATUS: "تأیید شده",
        COMPLETED_STATUS: "معامله ثبت شد",
        CANCELLED_STATUS: "رد شده",
    }
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
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
        "approved_at": row.get("approved_at") or "",
        "admin_note": row.get("admin_note") or "",
    }
