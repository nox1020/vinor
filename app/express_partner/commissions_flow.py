# -*- coding: utf-8 -*-
"""منطق مشترک جریان بازدید → معامله → پورسانت → برداشت."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

PENDING_STATUS = "pending"
APPROVED_STATUS = "approved"
PAID_STATUS = "paid"
REJECTED_STATUS = "rejected"

ACTIVE_COMMISSION_STATUSES = frozenset({PENDING_STATUS, APPROVED_STATUS, PAID_STATUS})
LOCKED_WITHDRAWAL_STATUSES = frozenset({"pending", "approved", "processing"})

ADMIN_COMMISSION_TRANSITIONS: Dict[str, frozenset] = {
    PENDING_STATUS: frozenset({PENDING_STATUS, APPROVED_STATUS, REJECTED_STATUS}),
    APPROVED_STATUS: frozenset({APPROVED_STATUS, REJECTED_STATUS}),
    PAID_STATUS: frozenset({PAID_STATUS}),
    REJECTED_STATUS: frozenset({REJECTED_STATUS}),
}


def _amount_int(v: Any) -> int:
    try:
        return max(0, int(str(v).replace(",", "").strip() or "0"))
    except Exception:
        return 0


def _commission_status(c: Dict[str, Any]) -> str:
    return (str(c.get("status") or PENDING_STATUS)).strip().lower()


def commission_status_label(status: str) -> str:
    st = (status or PENDING_STATUS).strip().lower()
    labels = {
        PENDING_STATUS: "در انتظار تأیید",
        APPROVED_STATUS: "تأیید شده — در موجودی",
        PAID_STATUS: "پرداخت‌شده",
        REJECTED_STATUS: "رد شده",
    }
    return labels.get(st, st or "—")


def commission_status_hint(status: str, *, is_referral: bool = False) -> str:
    st = (status or PENDING_STATUS).strip().lower()
    if is_referral:
        hints = {
            PENDING_STATUS: "پورسانت دعوت همکار — در انتظار تأیید (درخواست‌های قدیمی).",
            APPROVED_STATUS: "در موجودی قابل برداشت همکار است.",
            PAID_STATUS: "از طریق درخواست برداشت واریز شده است.",
            REJECTED_STATUS: "این پورسانت رد شده است.",
        }
    else:
        hints = {
            PENDING_STATUS: "پس از تأیید، مبلغ به موجودی همکار اضافه می‌شود.",
            APPROVED_STATUS: "همکار می‌تواند درخواست برداشت ثبت کند.",
            PAID_STATUS: "واریز از مسیر «مالی / برداشت» انجام شده است.",
            REJECTED_STATUS: "معامله لغو شده — فایل و بازدید در صورت نیاز بازگردانده می‌شود.",
        }
    return hints.get(st, "")


def commission_filter_bucket(status: str) -> str:
    st = (status or PENDING_STATUS).strip().lower()
    if st == PENDING_STATUS:
        return "pending"
    if st == APPROVED_STATUS:
        return "approved"
    if st == PAID_STATUS:
        return "paid"
    if st == REJECTED_STATUS:
        return "rejected"
    return "other"


def admin_can_transition_commission(old_status: str, new_status: str) -> bool:
    old = (old_status or PENDING_STATUS).strip().lower()
    new = (new_status or "").strip().lower()
    if old == new:
        return True
    if new == PAID_STATUS:
        return False
    allowed = ADMIN_COMMISSION_TRANSITIONS.get(old, frozenset({old}))
    return new in allowed


def commission_linked_to_active_withdrawal(
    commission: Dict[str, Any], withdrawals: List[Dict[str, Any]]
) -> bool:
    wid = str(commission.get("withdrawal_id") or "").strip()
    if not wid:
        return False
    for w in withdrawals or []:
        if not isinstance(w, dict):
            continue
        if str(w.get("id") or "").strip() != wid:
            continue
        if (str(w.get("status") or "")).strip().lower() in LOCKED_WITHDRAWAL_STATUSES:
            return True
    return False


def commission_reject_blocked_reason(
    commission: Dict[str, Any], withdrawals: Optional[List[Dict[str, Any]]] = None
) -> Optional[str]:
    st = _commission_status(commission)
    if st == PAID_STATUS:
        return "پورسانت پرداخت‌شده قابل رد نیست."
    if st == REJECTED_STATUS:
        return "این پورسانت قبلاً رد شده است."
    if st == APPROVED_STATUS and commission_linked_to_active_withdrawal(
        commission, withdrawals or []
    ):
        return "این پورسانت به درخواست برداشت فعال متصل است. ابتدا برداشت را رد یا لغو کنید."
    return None


def admin_commission_row_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    st = _commission_status(row)
    is_referral = str(row.get("commission_type") or "").strip() == "referral"
    amt = _amount_int(row.get("commission_amount"))
    sale = _amount_int(row.get("sale_amount"))
    pct = row.get("commission_pct")
    try:
        pct_f = float(pct) if pct is not None else None
    except (TypeError, ValueError):
        pct_f = None
    return {
        "id": row.get("id"),
        "partner_phone": str(row.get("partner_phone") or "").strip(),
        "partner_name": str(row.get("partner_name") or "").strip(),
        "land_code": str(row.get("land_code") or "").strip(),
        "land_title": str(row.get("land_title") or "").strip(),
        "sale_amount": sale,
        "commission_pct": pct_f,
        "commission_amount": amt,
        "commission_type": str(row.get("commission_type") or "").strip(),
        "is_referral": is_referral,
        "referred_name": str(row.get("referred_name") or "").strip(),
        "referred_phone": str(row.get("referred_phone") or "").strip(),
        "status": st,
        "status_label": commission_status_label(st),
        "status_hint": commission_status_hint(st, is_referral=is_referral),
        "filter_bucket": commission_filter_bucket(st),
        "needs_action": st == PENDING_STATUS,
        "is_editable": st in (PENDING_STATUS, APPROVED_STATUS),
        "can_reject": st in (PENDING_STATUS, APPROVED_STATUS),
        "withdrawal_id": str(row.get("withdrawal_id") or "").strip(),
        "created_at": row.get("created_at") or "",
        "approved_at": row.get("approved_at") or "",
        "rejected_at": row.get("rejected_at") or "",
        "paid_at": row.get("paid_at") or "",
        "updated_at": row.get("updated_at") or "",
    }


def commission_blocks_new_deal_record(
    commissions: List[Dict[str, Any]], partner_phone: str, land_code: str
) -> bool:
    """آیا رکورد پورسانت فعال برای این همکار+فایل وجود دارد؟"""
    ph = (partner_phone or "").strip()
    code = str(land_code or "").strip()
    if not ph or not code:
        return False
    for c in commissions:
        if not isinstance(c, dict):
            continue
        if str(c.get("partner_phone") or "").strip() != ph:
            continue
        if str(c.get("land_code") or "").strip() != code:
            continue
        if (str(c.get("status") or "pending")).strip() in ACTIVE_COMMISSION_STATUSES:
            return True
    return False


def revert_land_assignments_after_deal_cancel(
    assignments: List[Dict[str, Any]],
    land_code: str,
    *,
    holder_phone: Optional[str] = None,
    from_statuses: Optional[frozenset] = None,
    target_status: str = "active",
) -> bool:
    """بازگرداندن وضعیت انتساب‌ها پس از لغو/رد معامله."""
    code = str(land_code or "").strip()
    if not code:
        return False
    allowed = from_statuses or frozenset({"in_transaction", "sold"})
    holder = (holder_phone or "").strip()
    changed = False
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for a in assignments:
        if not isinstance(a, dict):
            continue
        if str(a.get("land_code") or "").strip() != code:
            continue
        cur = (str(a.get("status") or "active")).strip().lower()
        if cur not in allowed:
            continue
        if holder:
            th = str(a.get("transaction_holder") or "").strip()
            if th and th != holder:
                continue
        a["status"] = target_status
        a["updated_at"] = stamp
        a.pop("transaction_holder", None)
        a.pop("transaction_started_at", None)
        if target_status != "sold":
            a.pop("sold_at", None)
        changed = True
    return changed
