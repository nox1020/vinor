# -*- coding: utf-8 -*-
"""صندوق بازدید همکار ویژه — بازدید تا فروش نهایی روی آگهی‌های مالک."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from app.utils.dates import format_iso_date_jalali, iso_z, to_fa_digits, utcnow
from app.utils.storage import (
    load_ads_cached,
    load_express_assignments,
    load_express_commissions,
    load_express_commissions_cached,
    load_express_partners,
    load_express_visit_requests,
    load_partner_withdrawals,
    save_ads,
    save_express_assignments,
    save_express_commissions,
    save_express_partners,
)

from .commissions_flow import (
    PENDING_STATUS as COMMISSION_PENDING,
    commission_blocks_new_deal_record,
    commission_is_deal,
    commission_reject_blocked_reason,
    has_finalized_deal_commission,
    latest_deal_commission_for_partner,
    mark_assignments_sold_for_land,
    revert_land_assignments_after_deal_cancel,
)
from .special_listings import listings_owned_by
from .visit_requests import (
    APPROVED_STATUS,
    CANCELLED_STATUS,
    COMPLETED_STATUS,
    DONE_PENDING_STATUS,
    NO_SHOW_STATUS,
    OPEN_VISIT_STATUSES,
    PENDING_STATUS,
    admin_can_transition_visit,
    admin_update_visit_request_status,
    admin_visit_workflow_steps,
    get_plus_visit_presence_address,
    visit_progress_steps,
    visit_progress_summary,
    visit_request_display_title,
)


def _norm_phone(phone: str) -> str:
    return re.sub(r"[^\d]", "", str(phone or "").strip())


def _canon_phone(phone: str) -> str:
    raw = str(phone or "").strip()
    if not raw:
        return ""
    try:
        from .partner_session_sync import canonical_partner_phone

        return canonical_partner_phone(raw) or _norm_phone(raw)
    except Exception:
        return _norm_phone(raw)


def owned_land_codes(phone: str) -> Set[str]:
    return {
        str(land.get("code") or "").strip()
        for land in listings_owned_by(phone)
        if str(land.get("code") or "").strip()
    }


def _visit_row_for_plus_owner(
    row: Dict[str, Any],
    owner_phone: str,
    codes: Set[str] | None = None,
) -> bool:
    """بازدید روی آگهی مالک، یا وقت ثبت‌شده روی تقویم همین پلاس (حتی بدون فایل)."""
    if not isinstance(row, dict):
        return False
    me = _canon_phone(owner_phone)
    if not me:
        return False
    requester = _canon_phone(str(row.get("partner_phone") or ""))
    if requester and requester == me:
        return False
    land_codes = codes if codes is not None else owned_land_codes(owner_phone)
    code = str(row.get("land_code") or "").strip()
    if code and code in land_codes:
        return True
    plus = _canon_phone(str(row.get("plus_user_phone") or ""))
    return bool(plus) and plus == me


def _land_tx_status(assignments: List[Dict[str, Any]] | None, land_code: str) -> Tuple[str, str]:
    """وضعیت نمایشی فایل: sold | in_transaction | active + holder."""
    code = str(land_code or "").strip()
    holder = ""
    sold = False
    in_tx = False
    for a in assignments or []:
        if not isinstance(a, dict):
            continue
        if str(a.get("land_code") or "").strip() != code:
            continue
        st = str(a.get("status") or "").strip().lower()
        th = str(a.get("transaction_holder") or "").strip()
        if st == "sold":
            sold = True
        if th:
            holder = th
            in_tx = True
        if st == "in_transaction":
            in_tx = True
    if sold:
        return "sold", holder
    if in_tx:
        return "in_transaction", holder
    return "active", holder


def _partner_has_assignment(
    assignments: List[Dict[str, Any]] | None, phone: str, land_code: str
) -> bool:
    ph = _norm_phone(phone)
    code = str(land_code or "").strip()
    if not ph or not code:
        return False
    for a in assignments or []:
        if not isinstance(a, dict):
            continue
        if str(a.get("land_code") or "").strip() != code:
            continue
        if _norm_phone(str(a.get("partner_phone") or "")) == ph:
            return True
    return False


def _partner_open_tx_count(assignments: List[Dict[str, Any]] | None, phone: str) -> int:
    ph = _norm_phone(phone)
    if not ph:
        return 0
    n = 0
    for a in assignments or []:
        if not isinstance(a, dict):
            continue
        if _norm_phone(str(a.get("transaction_holder") or "")) == ph:
            n += 1
    return n


def special_inbox_pipeline_tab(item: Dict[str, Any] | None) -> str:
    """بازدید صندوق پلاس → تب بازدید؛ معامله/فروش → تب معامله."""
    from .visit_requests import PIPELINE_DEALS, PIPELINE_VISITS

    if not isinstance(item, dict):
        return PIPELINE_VISITS
    if item.get("can_start_deal") or item.get("can_approve_deal") or item.get("can_reject_deal"):
        return PIPELINE_DEALS
    tx = str(item.get("tx_status") or "").strip().lower()
    if tx in ("in_transaction", "sold"):
        return PIPELINE_DEALS
    deal_st = str(item.get("deal_commission_status") or "").strip().lower()
    if deal_st in ("pending", "approved", "paid"):
        return PIPELINE_DEALS
    return PIPELINE_VISITS


def _deal_status_label(status: str) -> str:
    st = str(status or "").strip().lower()
    return {
        COMMISSION_PENDING: "منتظر تأیید فروش",
        "approved": "فروش تأیید شد",
        "paid": "پورسانت واریز شد",
        "rejected": "معامله رد شد",
        "in_transaction": "در حال معامله",
        "sold": "فروخته شد",
        "active": "فعال",
    }.get(st, st)


def _mark_land_sold(land_code: str) -> None:
    code = str(land_code or "").strip()
    if not code:
        return
    lands = load_ads_cached() or []
    if not isinstance(lands, list):
        return
    changed = False
    for land in lands:
        if not isinstance(land, dict):
            continue
        if str(land.get("code") or "").strip() != code:
            continue
        if str(land.get("express_status") or "").strip().lower() != "sold":
            land["express_status"] = "sold"
            changed = True
        break
    if changed:
        save_ads(lands)


def visit_inbox_badge_count(phone: str) -> int:
    """بازدید باز + فروش نهایی در انتظار تأیید مالک — برای بج منو."""
    codes = owned_land_codes(phone)
    me = _norm_phone(phone)
    if not codes and not me:
        return 0
    rows = load_express_visit_requests() or []
    need: Set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if not _visit_row_for_plus_owner(row, phone, codes):
            continue
        st = str(row.get("status") or PENDING_STATUS).strip() or PENDING_STATUS
        if st in OPEN_VISIT_STATUSES:
            vid = str(row.get("id") or "").strip() or f"v:{row.get('land_code')}:{row.get('partner_phone')}"
            need.add(f"visit:{vid}")
    try:
        commissions = load_express_commissions_cached() or []
    except Exception:
        commissions = []
    for c in commissions if isinstance(commissions, list) else []:
        if not isinstance(c, dict) or not commission_is_deal(c):
            continue
        code = str(c.get("land_code") or "").strip()
        if code not in codes:
            continue
        if str(c.get("status") or "").strip().lower() != COMMISSION_PENDING:
            continue
        cid = str(c.get("id") or "").strip() or f"{c.get('partner_phone')}|{code}"
        need.add(f"deal:{cid}")
    try:
        from app.commercial.config import commercial_ui_enabled
        if commercial_ui_enabled():
            from .special_offer_inbox import offers_for_special_owner
            for off in offers_for_special_owner(phone) or []:
                oid = str((off or {}).get("id") or "").strip()
                if oid:
                    need.add(f"offer:{oid}")
    except Exception:
        pass
    return len(need)


def notify_special_owner_new_visit(rec: Dict[str, Any] | None) -> None:
    """اعلان سریع (درون‌برنامه + پوش) برای مالک آگهی ویژه وقتی بازدید ثبت می‌شود."""
    if not isinstance(rec, dict):
        return
    code = str(rec.get("land_code") or "").strip()
    requester = _norm_phone(rec.get("partner_phone") or "")
    if not code:
        return
    try:
        from app.utils.storage import load_ads_cached

        lands = load_ads_cached() or []
    except Exception:
        lands = []
    land = None
    for item in lands if isinstance(lands, list) else []:
        if isinstance(item, dict) and str(item.get("code") or "").strip() == code:
            land = item
            break
    if not isinstance(land, dict) or not land.get("is_express"):
        return
    owner = _norm_phone(str(land.get("owner") or land.get("user_phone") or ""))
    if not owner or len(owner) != 11 or owner == requester:
        return
    if code not in owned_land_codes(owner):
        return
    title = str(rec.get("land_title") or land.get("title") or code).strip() or code
    partner_name = str(rec.get("partner_name") or "").strip() or "یک همکار"
    date_bit = ""
    visit_date = str(rec.get("visit_date") or "").strip()
    if visit_date:
        try:
            jalali = format_iso_date_jalali(visit_date)
            if jalali:
                date_bit = f" — {jalali}"
        except Exception:
            pass
    try:
        from flask import url_for

        from app.services.notifications import add_notification

        try:
            action_url = url_for("express_partner.requests", tab="visits")
        except Exception:
            action_url = "/express/partner/requests?tab=visits"
        add_notification(
            user_id=owner,
            title="بازدید جدید",
            body=f"{partner_name} برای «{title}» درخواست بازدید ثبت کرد{date_bit}.",
            ntype="visit",
            ad_id=code,
            action_url=action_url,
            source="visit_inbox",
        )
    except Exception:
        try:
            from flask import current_app

            current_app.logger.exception(
                "notify_special_owner_new_visit failed code=%s owner=%s",
                code,
                owner,
            )
        except Exception:
            pass


def visits_for_special_owner(phone: str) -> List[Dict[str, Any]]:
    codes = owned_land_codes(phone)
    me = _norm_phone(phone)
    if not codes and not me:
        return []
    rows = load_express_visit_requests() or []
    try:
        commissions = load_express_commissions_cached() or []
    except Exception:
        commissions = []
    if not isinstance(commissions, list):
        commissions = []
    try:
        assignments = load_express_assignments() or []
    except Exception:
        assignments = []
    if not isinstance(assignments, list):
        assignments = []
    owner_addr = get_plus_visit_presence_address(phone)

    visit_result_on = False
    no_show_ok = False
    try:
        from app.visit_result.config import visit_result_ui_enabled
        from app.visit_result.status_bridge import is_no_show_writable

        visit_result_on = bool(visit_result_ui_enabled())
        no_show_ok = bool(is_no_show_writable()) if visit_result_on else False
    except Exception:
        pass

    labels = {
        PENDING_STATUS: "منتظر تأیید (قدیمی)",
        APPROVED_STATUS: "نهایی شده — منتظر بازدید",
        DONE_PENDING_STATUS: "منتظر تأیید انجام",
        COMPLETED_STATUS: "بازدید انجام شد",
        CANCELLED_STATUS: "رد شده",
        NO_SHOW_STATUS: "عدم حضور",
    }
    out: List[Dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("land_code") or "").strip()
        if not _visit_row_for_plus_owner(row, phone, codes):
            continue
        st = str(row.get("status") or PENDING_STATUS).strip() or PENDING_STATUS
        first = str(row.get("customer_first_name") or "").strip()
        last = str(row.get("customer_last_name") or "").strip()
        cust_name = str(row.get("customer_name") or "").strip() or f"{first} {last}".strip()
        visit_date = str(row.get("visit_date") or "").strip()
        visit_time = str(row.get("visit_time") or row.get("time") or "").strip()
        partner_phone = str(row.get("partner_phone") or "").strip()
        deal = latest_deal_commission_for_partner(commissions, partner_phone, code)
        deal_st = str((deal or {}).get("status") or "").strip().lower()
        deal_pending = bool(deal) and deal_st == COMMISSION_PENDING
        deal_final = bool(deal) and deal_st in ("approved", "paid")
        deal_rejected = bool(deal) and deal_st == "rejected"
        tx_status, tx_holder = _land_tx_status(assignments, code)
        has_assignment = _partner_has_assignment(assignments, partner_phone, code)
        holder_is_partner = bool(tx_holder) and _norm_phone(tx_holder) == _norm_phone(partner_phone)
        other_holder = bool(tx_holder) and not holder_is_partner

        can_approve = st == PENDING_STATUS
        can_reject = st == PENDING_STATUS
        can_complete = st == DONE_PENDING_STATUS
        can_reject_done = st == DONE_PENDING_STATUS
        can_no_show = no_show_ok and st in (APPROVED_STATUS, DONE_PENDING_STATUS)
        can_approve_deal = deal_pending and st == COMPLETED_STATUS
        can_reject_deal = can_approve_deal
        can_start_deal = (
            st == COMPLETED_STATUS
            and not deal_pending
            and not deal_final
            and tx_status != "sold"
            and has_assignment
            and not other_holder
        )
        can_register_result = visit_result_on and st in (
            APPROVED_STATUS,
            DONE_PENDING_STATUS,
            COMPLETED_STATUS,
        ) and not deal_pending and not deal_final

        owned_listing = bool(code) and code in codes
        if not owned_listing:
            can_approve = False
            can_reject = False
            can_complete = False
            can_reject_done = False
            can_no_show = False
            can_approve_deal = False
            can_reject_deal = False
            can_start_deal = False
            can_register_result = False

        progress_steps = visit_progress_steps(
            row,
            commissions,
            partner_phone=partner_phone,
            visit_requests=rows if isinstance(rows, list) else None,
        )
        progress_summary = visit_progress_summary(progress_steps)
        wf_steps = admin_visit_workflow_steps(
            {"status": st, "approved_at": row.get("approved_at"), "visit_done_requested_at": row.get("visit_done_requested_at")},
            deal_commission=deal,
        )
        current_step = next(
            (s for s in wf_steps if isinstance(s, dict) and s.get("state") == "current"),
            None,
        )
        if can_start_deal and not current_step:
            current_hint = "بازدید انجام شده. معامله را ثبت کنید یا منتظر ثبت همکار بمانید."
            stage_label = "درخواست معامله"
        elif can_approve_deal:
            current_hint = str((current_step or {}).get("hint") or "همکار فروش نهایی را ثبت کرده — تأیید یعنی فایل بسته می‌شود.")
            stage_label = "تأیید فروش نهایی"
        else:
            current_hint = str((current_step or {}).get("hint") or "")
            stage_label = str(
                (current_step or {}).get("label")
                or progress_summary.get("current_label")
                or labels.get(st, st)
            )
        if st == APPROVED_STATUS and not current_hint:
            current_hint = "منتظر اعلام «بازدید انجام شد» از سمت همکار."
        if deal_final:
            stage_label = "فروش نهایی شد"
            current_hint = "فایل بسته شد و پورسانت فروش به کیف پول همکار اضافه شد."
        elif tx_status == "sold":
            stage_label = "فروخته شد"

        needs_action = bool(
            can_approve or can_complete or can_no_show or can_approve_deal
        )
        status_label = labels.get(st, st)
        if deal_pending:
            status_label = "منتظر تأیید فروش"
        elif deal_final:
            status_label = "فروش تأیید شد"
        elif deal_rejected and st == COMPLETED_STATUS:
            status_label = "معامله رد شد — قابل ثبت مجدد"
        elif tx_status == "in_transaction" and st == COMPLETED_STATUS:
            status_label = "در حال معامله"

        visit_date_jalali = format_iso_date_jalali(visit_date) if visit_date else ""
        if visit_date_jalali and visit_time:
            visit_date_jalali = f"{visit_date_jalali} — ساعت {to_fa_digits(visit_time)}"

        try:
            deal_amount = int((deal or {}).get("commission_amount") or 0)
        except (TypeError, ValueError):
            deal_amount = 0
        try:
            sale_amount = int((deal or {}).get("sale_amount") or 0)
        except (TypeError, ValueError):
            sale_amount = 0

        out.append({
            "id": str(row.get("id") or ""),
            "land_code": code,
            "land_title": visit_request_display_title(row),
            "inbox_origin": "listing" if owned_listing else "calendar",
            "partner_name": str(row.get("partner_name") or "").strip(),
            "partner_phone": partner_phone,
            "customer_name": cust_name,
            "customer_phone": str(row.get("customer_phone") or "").strip(),
            "visit_date": visit_date,
            "visit_time": visit_time,
            "visit_date_jalali": visit_date_jalali,
            "visit_presence_address": str(row.get("visit_presence_address") or "").strip() or owner_addr,
            "status": st,
            "status_label": status_label,
            "stage_label": stage_label,
            "current_hint": current_hint,
            "tx_status": tx_status,
            "tx_status_label": _deal_status_label(tx_status),
            "progress_steps": progress_steps,
            "progress_summary": progress_summary,
            "deal_commission_id": (deal or {}).get("id"),
            "deal_commission_status": deal_st,
            "deal_commission_amount": deal_amount,
            "sale_amount": sale_amount,
            "can_approve": can_approve,
            "can_reject": can_reject,
            "can_complete": can_complete,
            "can_reject_done": can_reject_done,
            "can_no_show": can_no_show,
            "can_register_result": can_register_result,
            "can_start_deal": can_start_deal,
            "can_approve_deal": can_approve_deal,
            "can_reject_deal": can_reject_deal,
            "created_at": str(row.get("created_at") or ""),
            "updated_at": str(row.get("updated_at") or ""),
            "needs_action": needs_action,
            "has_actions": needs_action
            or can_start_deal
            or can_register_result
            or can_reject
            or can_reject_done,
        })
        out[-1]["pipeline_tab"] = special_inbox_pipeline_tab(out[-1])

    def _sort_key(item: Dict[str, Any]) -> tuple:
        if item.get("can_approve_deal"):
            rank = 0
        elif item.get("needs_action"):
            rank = 1
        elif item.get("can_start_deal"):
            rank = 2
        else:
            rank = 3
        return (rank, str(item.get("updated_at") or item.get("created_at") or ""))

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
    """action: approve | reject | complete | reject_done | no_show | result | start_deal | approve_deal | reject_deal"""
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
    if act == "reject_done":
        if current != DONE_PENDING_STATUS:
            return None, "invalid_transition"
        if not admin_can_transition_visit(current, APPROVED_STATUS):
            return None, "invalid_transition"
        return admin_update_visit_request_status(
            requests, rid, APPROVED_STATUS, admin_note=notes or "انجام بازدید رد شد",
        )
    if act in ("start_deal", "approve_deal", "reject_deal"):
        return _apply_special_deal_action(rec, owner_phone=owner_phone, action=act)
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


def _apply_special_deal_action(
    rec: Dict[str, Any],
    *,
    owner_phone: str,
    action: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not special_can_manage_visit(owner_phone, rec):
        return None, "forbidden"
    st = str(rec.get("status") or "").strip()
    if st != COMPLETED_STATUS:
        return None, "invalid_transition"
    act = (action or "").strip().lower()
    try:
        if act == "start_deal":
            err = _start_deal_for_visit(rec)
            return (rec, None) if not err else (None, err)
        if act == "approve_deal":
            err = _decide_deal_commission(rec, decision="approve")
            return (rec, None) if not err else (None, err)
        if act == "reject_deal":
            err = _decide_deal_commission(rec, decision="reject")
            return (rec, None) if not err else (None, err)
    except Exception:
        return None, "failed"
    return None, "invalid_action"


def _start_deal_for_visit(rec: Dict[str, Any]) -> Optional[str]:
    """ثبت فروش نهایی به نام همکار بازدیدکننده — همان مسیر mark-in-transaction."""
    code = str(rec.get("land_code") or "").strip()
    partner_phone = str(rec.get("partner_phone") or "").strip()
    if not code or not partner_phone:
        return "failed"
    assignments = load_express_assignments() or []
    if not isinstance(assignments, list):
        assignments = []
    if not _partner_has_assignment(assignments, partner_phone, code):
        return "no_assignment"
    tx_status, holder = _land_tx_status(assignments, code)
    if tx_status == "sold":
        return "already_sold"
    holder_n = _norm_phone(holder)
    partner_n = _norm_phone(partner_phone)
    if holder_n and holder_n != partner_n:
        return "held_by_other"
    commissions = load_express_commissions() or []
    if not isinstance(commissions, list):
        commissions = []
    if has_finalized_deal_commission(commissions, partner_phone, code):
        return "already_sold"
    if commission_blocks_new_deal_record(commissions, partner_phone, code):
        return "already_pending"
    if not holder_n and _partner_open_tx_count(assignments, partner_phone) >= 2:
        return "deal_limit"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for a in assignments:
        if not isinstance(a, dict):
            continue
        if str(a.get("land_code") or "").strip() != code:
            continue
        cur = str(a.get("status") or "active").strip().lower()
        if cur in ("active", "pending", "approved", "closed", "in_transaction"):
            a["status"] = "in_transaction"
            a["updated_at"] = now
            a["transaction_holder"] = partner_phone
            a["transaction_started_at"] = now
    save_express_assignments(assignments)

    lands = load_ads_cached() or []
    land = next(
        (l for l in (lands or []) if isinstance(l, dict) and str(l.get("code") or "").strip() == code),
        None,
    )
    from .new_land_sms import (
        resolve_express_land_commission_amount,
        resolve_express_land_commission_pct,
    )
    commission_pct = resolve_express_land_commission_pct(land) if land else 0
    commission_amount = resolve_express_land_commission_amount(land) if land else 0
    try:
        price_total = int(
            str((land or {}).get("price_total") or (land or {}).get("price") or "0")
            .replace(",", "").replace(" ", "").strip() or "0"
        )
    except Exception:
        price_total = 0
    new_id = (max([int(x.get("id", 0) or 0) for x in commissions if isinstance(x, dict)], default=0) or 0) + 1
    try:
        safe_amount = max(0, int(commission_amount or 0))
    except Exception:
        safe_amount = 0
    try:
        safe_pct = float(commission_pct or 0)
    except Exception:
        safe_pct = 0.0
    commissions.append({
        "id": new_id,
        "commission_type": "deal",
        "partner_phone": partner_phone,
        "land_code": code,
        "sale_amount": price_total,
        "commission_pct": safe_pct,
        "commission_amount": safe_amount,
        "status": COMMISSION_PENDING,
        "created_at": now,
        "source": "special_inbox",
    })
    save_express_commissions(commissions)
    try:
        from .admin_action_sms import notify_admin_pending_action
        notify_admin_pending_action(
            "commission",
            partner_phone=partner_phone,
            partner_name=str(rec.get("partner_name") or ""),
            land_code=code,
            amount=safe_amount,
        )
    except Exception:
        pass
    try:
        from .commission_sms import notify_partner_commission_txn
        notify_partner_commission_txn(
            partner_phone=partner_phone,
            event="commission_pending",
            amount=safe_amount,
            land_code=code,
            reference_id=str(new_id),
        )
    except Exception:
        pass
    try:
        from .visit_sms import notify_partner_land_tx_sms
        notify_partner_land_tx_sms(
            partner_phone=partner_phone,
            event="deal_started",
            land_code=code,
            land_title=str(rec.get("land_title") or ""),
            visit_date=str(rec.get("visit_date") or ""),
        )
    except Exception:
        pass
    try:
        from app.closing.deal_bridge import maybe_sync_deal_from_commission
        maybe_sync_deal_from_commission(
            partner_phone=partner_phone,
            land_code=code,
            commission_id=str(new_id),
            sale_amount=price_total,
            assignment_status="in_transaction",
            deal_status="in_transaction",
        )
    except Exception:
        pass
    return None


def _decide_deal_commission(rec: Dict[str, Any], *, decision: str) -> Optional[str]:
    code = str(rec.get("land_code") or "").strip()
    partner_phone = str(rec.get("partner_phone") or "").strip()
    commissions = load_express_commissions() or []
    if not isinstance(commissions, list):
        return "failed"
    deal = latest_deal_commission_for_partner(commissions, partner_phone, code)
    if not deal:
        return "not_found"
    deal_st = str(deal.get("status") or "").strip().lower()
    if deal_st != COMMISSION_PENDING:
        if deal_st in ("approved", "paid"):
            return "already_sold"
        return "invalid_transition"
    if decision == "approve":
        return _approve_pending_deal(deal, commissions)
    if decision == "reject":
        return _reject_pending_deal(deal, commissions)
    return "invalid_action"


def _approve_pending_deal(
    commission_record: Dict[str, Any],
    commissions: List[Dict[str, Any]],
) -> Optional[str]:
    stamp = iso_z(utcnow())
    commission_record["status"] = "approved"
    commission_record["approved_at"] = stamp
    save_express_commissions(commissions)
    land_code = str(commission_record.get("land_code") or "").strip()
    partner_phone = str(commission_record.get("partner_phone") or "").strip()
    if land_code:
        assignments = load_express_assignments() or []
        if mark_assignments_sold_for_land(assignments, land_code, sold_at=stamp):
            save_express_assignments(assignments)
        try:
            _mark_land_sold(land_code)
        except Exception:
            pass
        if partner_phone:
            try:
                from .partner_missions import complete_mission
                complete_mission(partner_phone, land_code=land_code)
            except Exception:
                pass
        try:
            from app.closing.deal_bridge import maybe_sync_deal_on_commission_status
            maybe_sync_deal_on_commission_status(
                partner_phone=partner_phone,
                land_code=land_code,
                commission_id=str(commission_record.get("id") or ""),
                commission_status="approved",
                sale_amount=int(commission_record.get("sale_amount") or 0),
            )
        except Exception:
            pass
    try:
        commission_amount = int(commission_record.get("commission_amount") or 0)
        sale_amount = int(commission_record.get("sale_amount") or 0)
        if partner_phone:
            partners = load_express_partners() or []
            for p in partners if isinstance(partners, list) else []:
                if str(p.get("phone") or "").strip() != partner_phone:
                    continue
                p["total_income"] = int(p.get("total_income", 0) or 0) + commission_amount
                p["approved_sales_count"] = int(p.get("approved_sales_count", 0) or 0) + 1
                p["total_approved_sales"] = int(p.get("total_approved_sales", 0) or 0) + sale_amount
                p["last_updated"] = stamp
                break
            save_express_partners(partners)
    except Exception:
        pass
    try:
        from .commission_sms import notify_partner_commission_txn
        notify_partner_commission_txn(
            partner_phone=partner_phone,
            event="commission_approved",
            amount=int(commission_record.get("commission_amount") or 0),
            land_code=land_code,
            commission_type=str(commission_record.get("commission_type") or ""),
            reference_id=str(commission_record.get("id") or ""),
        )
    except Exception:
        pass
    return None


def _reject_pending_deal(
    commission_record: Dict[str, Any],
    commissions: List[Dict[str, Any]],
) -> Optional[str]:
    withdrawals = load_partner_withdrawals() or []
    if not isinstance(withdrawals, list):
        withdrawals = []
    block = commission_reject_blocked_reason(commission_record, withdrawals)
    if block:
        return "blocked"
    stamp = iso_z(utcnow())
    commission_record["status"] = "rejected"
    commission_record["rejected_at"] = stamp
    save_express_commissions(commissions)
    land_code = str(commission_record.get("land_code") or "").strip()
    partner_phone = str(commission_record.get("partner_phone") or "").strip()
    if land_code:
        try:
            assignments = load_express_assignments() or []
            if revert_land_assignments_after_deal_cancel(
                assignments,
                land_code,
                holder_phone=partner_phone,
                from_statuses=frozenset({"in_transaction"}),
            ):
                save_express_assignments(assignments)
        except Exception:
            pass
        try:
            from app.closing.deal_bridge import maybe_sync_deal_on_commission_status
            maybe_sync_deal_on_commission_status(
                partner_phone=partner_phone,
                land_code=land_code,
                commission_id=str(commission_record.get("id") or ""),
                commission_status="rejected",
                sale_amount=int(commission_record.get("sale_amount") or 0),
            )
        except Exception:
            pass
    try:
        from .commission_sms import notify_partner_commission_txn
        notify_partner_commission_txn(
            partner_phone=partner_phone,
            event="commission_rejected",
            amount=int(commission_record.get("commission_amount") or 0),
            land_code=land_code,
            commission_type=str(commission_record.get("commission_type") or ""),
            reference_id=str(commission_record.get("id") or ""),
        )
    except Exception:
        pass
    try:
        from .visit_sms import notify_partner_land_tx_sms
        notify_partner_land_tx_sms(
            partner_phone=partner_phone,
            event="deal_released",
            land_code=land_code,
            land_title="",
        )
    except Exception:
        pass
    return None

