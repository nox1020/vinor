# -*- coding: utf-8 -*-
"""صندوق بازدید همکار ویژه — فقط آگهی‌های مالک خودش."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from app.utils.dates import format_iso_date_jalali
from app.utils.storage import load_express_visit_requests

from .special_listings import listings_owned_by
from .visit_requests import (
    APPROVED_STATUS,
    CANCELLED_STATUS,
    COMPLETED_STATUS,
    DONE_PENDING_STATUS,
    NO_SHOW_STATUS,
    PENDING_STATUS,
    admin_can_transition_visit,
    admin_update_visit_request_status,
)


def _norm_phone(phone: str) -> str:
    return re.sub(r"[^\d]", "", str(phone or "").strip())


def owned_land_codes(phone: str) -> Set[str]:
    return {
        str(land.get("code") or "").strip()
        for land in listings_owned_by(phone)
        if str(land.get("code") or "").strip()
    }


def visits_for_special_owner(phone: str) -> List[Dict[str, Any]]:
    codes = owned_land_codes(phone)
    if not codes:
        return []
    rows = load_express_visit_requests() or []
    out: List[Dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("land_code") or "").strip()
        if code not in codes:
            continue
        st = str(row.get("status") or PENDING_STATUS).strip() or PENDING_STATUS
        first = str(row.get("customer_first_name") or "").strip()
        last = str(row.get("customer_last_name") or "").strip()
        cust_name = str(row.get("customer_name") or "").strip() or f"{first} {last}".strip()
        visit_date = str(row.get("visit_date") or "").strip()
        can_approve = st == PENDING_STATUS
        can_reject = st == PENDING_STATUS
        can_complete = st == DONE_PENDING_STATUS
        can_no_show = False
        can_register_result = False
        try:
            from app.visit_result.config import visit_result_ui_enabled
            from app.visit_result.status_bridge import is_no_show_writable

            if visit_result_ui_enabled():
                can_register_result = st in (APPROVED_STATUS, DONE_PENDING_STATUS, COMPLETED_STATUS)
                can_no_show = is_no_show_writable() and st in (APPROVED_STATUS, DONE_PENDING_STATUS)
        except Exception:
            pass
        labels = {
            PENDING_STATUS: "منتظر تأیید (قدیمی)",
            APPROVED_STATUS: "نهایی شده",
            DONE_PENDING_STATUS: "منتظر تأیید انجام",
            COMPLETED_STATUS: "انجام شد",
            CANCELLED_STATUS: "رد شده",
            NO_SHOW_STATUS: "عدم حضور",
        }
        out.append({
            "id": str(row.get("id") or ""),
            "land_code": code,
            "land_title": str(row.get("land_title") or code),
            "partner_name": str(row.get("partner_name") or "").strip(),
            "partner_phone": str(row.get("partner_phone") or "").strip(),
            "customer_name": cust_name,
            "customer_phone": str(row.get("customer_phone") or "").strip(),
            "visit_date": visit_date,
            "visit_date_jalali": format_iso_date_jalali(visit_date) if visit_date else "",
            "status": st,
            "status_label": labels.get(st, st),
            "can_approve": can_approve,
            "can_reject": can_reject,
            "can_complete": can_complete,
            "can_no_show": can_no_show,
            "can_register_result": can_register_result,
            "created_at": str(row.get("created_at") or ""),
            "updated_at": str(row.get("updated_at") or ""),
            "needs_action": can_approve or can_complete or can_no_show,
        })

    def _sort_key(item: Dict[str, Any]) -> tuple:
        needs = 0 if item.get("needs_action") else 1
        return (needs, str(item.get("updated_at") or item.get("created_at") or ""))

    out.sort(key=_sort_key)
    return out


def special_can_manage_visit(owner_phone: str, visit_row: Dict[str, Any] | None) -> bool:
    if not isinstance(visit_row, dict):
        return False
    code = str(visit_row.get("land_code") or "").strip()
    return bool(code) and code in owned_land_codes(owner_phone)


def apply_special_visit_action(
    requests: List[Dict[str, Any]],
    *,
    owner_phone: str,
    visit_id: str,
    action: str,
    outcome: str = "",
    notes: str = "",
) -> tuple:
    """action: approve | reject | complete | no_show | result"""
    rid = (visit_id or "").strip()
    act = (action or "").strip().lower()
    rec = None
    for r in requests:
        if isinstance(r, dict) and str(r.get("id") or "") == rid:
            rec = r
            break
    if not rec:
        return None, "not_found"
    if not special_can_manage_visit(owner_phone, rec):
        return None, "forbidden"

    current = (str(rec.get("status") or PENDING_STATUS)).strip()

    if act == "approve":
        if not admin_can_transition_visit(current, APPROVED_STATUS):
            return None, "invalid_transition"
        return admin_update_visit_request_status(requests, rid, APPROVED_STATUS)
    if act == "reject":
        if not admin_can_transition_visit(current, CANCELLED_STATUS):
            return None, "invalid_transition"
        return admin_update_visit_request_status(requests, rid, CANCELLED_STATUS)
    if act == "complete":
        # فقط از done_pending — مثل ادمین؛ وگرنه فایل روی visit_commission_pending گیر می‌کند
        if not admin_can_transition_visit(current, COMPLETED_STATUS):
            return None, "invalid_transition"
        return admin_update_visit_request_status(requests, rid, COMPLETED_STATUS)
    if act == "no_show":
        try:
            from app.visit_result.config import visit_result_ui_enabled
            from app.visit_result.service import register_no_show

            if not visit_result_ui_enabled():
                return None, "disabled"
            updated, _result, err = register_no_show(
                requests,
                visit_request_id=rid,
                notes=notes,
                actor_key=owner_phone,
                source="special",
            )
            if err:
                return None, err
            return updated, None
        except Exception:
            return None, "failed"
    if act == "result":
        try:
            from app.visit_result.config import visit_result_ui_enabled
            from app.visit_result.service import register_result, valid_outcome

            if not visit_result_ui_enabled():
                return None, "disabled"
            oc = (outcome or "").strip() or "follow_up"
            if not valid_outcome(oc) or oc == "no_show":
                # no_show must go through act=no_show (status change)
                if oc != "no_show" and not valid_outcome(oc):
                    return None, "invalid_outcome"
                if oc == "no_show":
                    return None, "use_no_show_action"
            result = register_result(
                visit_request_id=rid,
                partner_phone=str(rec.get("partner_phone") or ""),
                land_code=str(rec.get("land_code") or ""),
                outcome=oc,
                notes=notes,
                actor_key=owner_phone,
                source="special",
            )
            if result is None:
                return None, "failed"
            return rec, None
        except Exception:
            return None, "failed"
    return None, "invalid_action"
