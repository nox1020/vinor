# -*- coding: utf-8 -*-
"""درخواست برداشت پورسانت همکار اکسپرس."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

RESERVE_STATUSES = frozenset({"pending", "approved", "processing"})
ACTIVE_WITHDRAWAL_STATUSES = frozenset({"pending", "approved", "processing", "rejected"})
PARTNER_CANCELLABLE_WITHDRAWAL_STATUSES = frozenset({"pending"})
# از موجودی قابل برداشت کسر می‌شود: در انتظار بررسی + تأیید ادمین + در حال پردازش
WITHDRAWABLE_RESERVE_STATUSES = RESERVE_STATUSES
LOCK_RESERVE_STATUSES = RESERVE_STATUSES


def _amount_int(v: Any) -> int:
    try:
        return max(0, int(str(v).replace(",", "").strip() or "0"))
    except Exception:
        return 0


def _commission_status(c: Dict[str, Any]) -> str:
    return (str(c.get("status") or "pending")).strip()


def approved_gross_commission_total(
    commissions: List[Dict[str, Any]], phone: str
) -> int:
    ph = (phone or "").strip()
    total = 0
    for c in commissions:
        if not isinstance(c, dict):
            continue
        if str(c.get("partner_phone") or "").strip() != ph:
            continue
        if _commission_status(c) == "approved":
            total += _amount_int(c.get("commission_amount"))
    return total


def _withdrawal_status(w: Dict[str, Any]) -> str:
    return (str(w.get("status") or "pending")).strip().lower()


def _active_withdrawal_ids(withdrawals: List[Dict[str, Any]], phone: str) -> set:
    ph = (phone or "").strip()
    out: set = set()
    for w in withdrawals:
        if not isinstance(w, dict):
            continue
        if str(w.get("phone") or "").strip() != ph:
            continue
        if _withdrawal_status(w) in LOCK_RESERVE_STATUSES:
            wid = str(w.get("id") or "").strip()
            if wid:
                out.add(wid)
    return out


def _partner_commissions_for_phone(
    commissions: List[Dict[str, Any]], phone: str
) -> List[Dict[str, Any]]:
    ph = (phone or "").strip()
    return [
        c
        for c in commissions
        if isinstance(c, dict) and str(c.get("partner_phone") or "").strip() == ph
    ]


def _approved_commission_candidates(
    commissions: List[Dict[str, Any]],
    phone: str,
    withdrawal_id: str = "",
    withdrawals: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    wid = (withdrawal_id or "").strip()
    active_ids = _active_withdrawal_ids(withdrawals or [], phone) if withdrawals is not None else set()
    mine: List[Dict[str, Any]] = []
    for c in _partner_commissions_for_phone(commissions, phone):
        if _commission_status(c) != "approved":
            continue
        linked = str(c.get("withdrawal_id") or "").strip()
        if linked and linked != wid and linked in active_ids:
            continue
        mine.append(c)
    mine.sort(
        key=lambda x: (
            0 if wid and str(x.get("withdrawal_id") or "").strip() == wid else 1,
            _amount_int(x.get("commission_amount")),
            x.get("approved_at") or x.get("created_at") or "",
        )
    )
    return mine


def apply_paid_withdrawal_to_commissions(
    commissions: List[Dict[str, Any]],
    phone: str,
    amount: int,
    withdrawal_id: str,
    paid_at: str,
    withdrawals: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """پورسانت approved را FIFO به paid تبدیل می‌کند (پشتیبانی از برداشت جزئی)."""
    ph = (phone or "").strip()
    remaining = max(0, _amount_int(amount))
    wid = (withdrawal_id or "").strip()
    if not ph or remaining <= 0:
        return 0

    allocated = 0
    for c in _approved_commission_candidates(commissions, ph, wid, withdrawals):
        if remaining <= 0:
            break
        amt = _amount_int(c.get("commission_amount"))
        if amt <= 0:
            continue
        take = min(amt, remaining)
        if take <= 0:
            continue
        if take >= amt:
            c["status"] = "paid"
            c["paid_at"] = paid_at
            c["commission_amount"] = 0
            if wid:
                c["withdrawal_id"] = wid
        else:
            c["commission_amount"] = amt - take
            c["partial_paid_total"] = _amount_int(c.get("partial_paid_total")) + take
            if c["commission_amount"] <= 0:
                c["status"] = "paid"
                c["paid_at"] = paid_at
                c["commission_amount"] = 0
                if wid:
                    c["withdrawal_id"] = wid
        remaining -= take
        allocated += take
    return allocated


def reconcile_paid_withdrawals(
    commissions: List[Dict[str, Any]],
    withdrawals: List[Dict[str, Any]],
    phone: str,
) -> bool:
    """درخواست‌های paid بدون تخصیص را روی پورسانت‌ها اعمال می‌کند."""
    ph = (phone or "").strip()
    if not ph:
        return False
    changed = False
    paid_rows = [
        w
        for w in withdrawals
        if isinstance(w, dict)
        and str(w.get("phone") or "").strip() == ph
        and _withdrawal_status(w) == "paid"
    ]
    paid_rows.sort(key=lambda x: x.get("updated_at") or x.get("created_at") or "")
    for w in paid_rows:
        wid = str(w.get("id") or "").strip()
        target = _amount_int(w.get("amount"))
        if target <= 0 or not wid:
            continue
        already = _amount_int(w.get("commission_allocated_amount"))
        need = max(0, target - already)
        if need <= 0:
            continue
        paid_at = str(w.get("updated_at") or w.get("created_at") or "")
        got = apply_paid_withdrawal_to_commissions(
            commissions, ph, need, wid, paid_at, withdrawals
        )
        if got > 0:
            w["commission_allocated_amount"] = already + got
            changed = True
    return changed


def link_withdrawal_to_commissions(
    commissions: List[Dict[str, Any]],
    phone: str,
    amount: int,
    withdrawal_id: str,
    withdrawals: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """پس از تأیید ادمین: پورسانت approved را به درخواست برداشت وصل می‌کند (جزئی هم)."""
    ph = (phone or "").strip()
    remaining = max(0, _amount_int(amount))
    wid = (withdrawal_id or "").strip()
    if not ph or not wid or remaining <= 0:
        return 0

    linked = 0
    for c in _approved_commission_candidates(commissions, ph, wid, withdrawals):
        if remaining <= 0:
            break
        if str(c.get("withdrawal_id") or "").strip():
            continue
        amt = _amount_int(c.get("commission_amount"))
        if amt <= 0:
            continue
        take = min(amt, remaining)
        c["withdrawal_id"] = wid
        remaining -= take
        linked += take
    return linked


def release_withdrawal_commissions(
    commissions: List[Dict[str, Any]], withdrawal_id: str
) -> None:
    wid = (withdrawal_id or "").strip()
    if not wid:
        return
    for c in commissions:
        if not isinstance(c, dict):
            continue
        if (str(c.get("withdrawal_id") or "").strip() == wid and _commission_status(c) == "approved"):
            c.pop("withdrawal_id", None)


def approved_commission_total(
    commissions: List[Dict[str, Any]],
    withdrawals: Optional[List[Dict[str, Any]]] = None,
    phone: Optional[str] = None,
) -> int:
    """پورسانت approved منهای برداشت‌های فعال (pending/approved/processing)."""
    ph = (phone or "").strip()
    if not ph:
        return 0
    gross = approved_gross_commission_total(commissions, ph)
    reserved = withdrawable_reserve_total(withdrawals or [], ph)
    return max(0, gross - reserved)


def _withdrawal_reserve_total(
    withdrawals: List[Dict[str, Any]], phone: str, statuses: frozenset
) -> int:
    ph = (phone or "").strip()
    total = 0
    for w in withdrawals:
        if not isinstance(w, dict):
            continue
        if str(w.get("phone") or "").strip() != ph:
            continue
        st = (str(w.get("status") or "pending")).strip().lower()
        if st in statuses:
            total += _amount_int(w.get("amount"))
    return total


def reserved_withdrawal_total(
    withdrawals: List[Dict[str, Any]], phone: str
) -> int:
    """مجموع درخواست‌های فعال (برای آمار «در جریان»)."""
    return _withdrawal_reserve_total(withdrawals, phone, LOCK_RESERVE_STATUSES)


def withdrawable_reserve_total(
    withdrawals: List[Dict[str, Any]], phone: str
) -> int:
    """مبلغی که از موجودی قابل برداشت کم می‌شود (تأییدشده + در حال پردازش)."""
    return _withdrawal_reserve_total(withdrawals, phone, WITHDRAWABLE_RESERVE_STATUSES)


def pending_withdrawal_only_total(
    withdrawals: List[Dict[str, Any]], phone: str
) -> int:
    return _withdrawal_reserve_total(withdrawals, phone, frozenset({"pending"}))


def paid_withdrawal_total(
    withdrawals: List[Dict[str, Any]], phone: str
) -> int:
    ph = (phone or "").strip()
    total = 0
    for w in withdrawals:
        if not isinstance(w, dict):
            continue
        if str(w.get("phone") or "").strip() != ph:
            continue
        if (str(w.get("status") or "")).strip() == "paid":
            total += _amount_int(w.get("amount"))
    return total


def partner_commission_dashboard(
    commissions: List[Dict[str, Any]],
    withdrawals: List[Dict[str, Any]],
    phone: str,
) -> Dict[str, Any]:
    """آمار یکپارچه صفحه پورسانت.

    موجودی قابل برداشت = پورسانت approved − درخواست‌های فعال برداشت.
    """
    ph = (phone or "").strip()
    pending_amount = pending_count = 0
    approved_gross_amount = approved_gross_count = 0
    paid_amount = paid_count = 0

    for c in commissions:
        if not isinstance(c, dict):
            continue
        if str(c.get("partner_phone") or "").strip() != ph:
            continue
        st = _commission_status(c)
        amt = _amount_int(c.get("commission_amount"))
        if st == "pending":
            pending_amount += amt
            pending_count += 1
        elif st == "approved":
            approved_gross_amount += amt
            approved_gross_count += 1
            partial = _amount_int(c.get("partial_paid_total"))
            if partial:
                paid_amount += partial
        elif st == "paid":
            paid_amount += amt + _amount_int(c.get("partial_paid_total"))
            paid_count += 1

    in_withdrawal_amount = reserved_withdrawal_total(withdrawals, ph)
    withdrawable_reserve = withdrawable_reserve_total(withdrawals, ph)
    pending_wd_only = pending_withdrawal_only_total(withdrawals, ph)
    in_withdrawal_count = sum(
        1
        for w in withdrawals
        if isinstance(w, dict)
        and str(w.get("phone") or "").strip() == ph
        and _withdrawal_status(w) in LOCK_RESERVE_STATUSES
    )
    paid_wd_amount = paid_withdrawal_total(withdrawals, ph)
    paid_wd_count = sum(
        1
        for w in withdrawals
        if isinstance(w, dict)
        and str(w.get("phone") or "").strip() == ph
        and _withdrawal_status(w) == "paid"
    )
    approved_amount = approved_commission_total(commissions, withdrawals, ph)
    withdrawable = approved_amount
    locked_available = approved_amount
    confirmed_amount = approved_gross_amount + paid_amount
    confirmed_count = approved_gross_count + paid_count

    return {
        "total_confirmed_amount": confirmed_amount,
        "total_confirmed_count": confirmed_count,
        "pending_amount": pending_amount,
        "pending_count": pending_count,
        "approved_amount": approved_amount,
        "approved_gross_amount": approved_gross_amount,
        "approved_count": approved_gross_count,
        "paid_amount": paid_amount,
        "paid_count": paid_count,
        "withdrawable_balance": withdrawable,
        "locked_available_balance": locked_available,
        "in_withdrawal_amount": in_withdrawal_amount,
        "withdrawable_reserve_amount": withdrawable_reserve,
        "pending_withdrawal_amount": pending_wd_only,
        "in_withdrawal_count": in_withdrawal_count,
        "received_amount": paid_wd_amount,
        "received_count": paid_wd_count,
        "commission_paid_amount": paid_amount,
        "commission_paid_count": paid_count,
        "paid_withdrawal_amount": paid_wd_amount,
        "paid_withdrawal_count": paid_wd_count,
    }


def withdrawable_balance(
    commissions: List[Dict[str, Any]],
    withdrawals: List[Dict[str, Any]],
    phone: str,
) -> int:
    return approved_commission_total(commissions, withdrawals, phone)


def available_for_new_withdrawal(
    commissions: List[Dict[str, Any]],
    withdrawals: List[Dict[str, Any]],
    phone: str,
) -> int:
    return withdrawable_balance(commissions, withdrawals, phone)


def status_label(status: str) -> str:
    s = (status or "pending").strip()
    return {
        "pending": "در انتظار بررسی",
        "approved": "تأیید شده",
        "processing": "در حال پردازش",
        "paid": "پرداخت‌شده",
        "rejected": "رد شده",
        "cancelled": "لغو شده",
    }.get(s, s)


def withdrawals_for_phone(
    withdrawals: List[Dict[str, Any]], phone: str
) -> List[Dict[str, Any]]:
    ph = (phone or "").strip()
    out: List[Dict[str, Any]] = []
    for w in withdrawals:
        if not isinstance(w, dict):
            continue
        if str(w.get("phone") or "").strip() != ph:
            continue
        out.append(partner_row_dict(w))
    out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return out


def active_withdrawals_for_phone(
    withdrawals: List[Dict[str, Any]], phone: str
) -> List[Dict[str, Any]]:
    return [
        w
        for w in withdrawals_for_phone(withdrawals, phone)
        if (w.get("status") or "") in ACTIVE_WITHDRAWAL_STATUSES
    ]


def withdrawal_to_txn_row(w: Dict[str, Any]) -> Dict[str, Any]:
    bank = (w.get("bank_summary") or "حساب بانکی").strip()
    amt = _amount_int(w.get("amount"))
    return {
        "txn_type": "withdrawal",
        "created_at": w.get("updated_at") or w.get("created_at") or "",
        "status": "withdrawal",
        "commission_amount": -amt if amt > 0 else 0,
        "withdrawal_amount": amt,
        "bank_summary": bank,
        "withdrawal_id": w.get("id"),
        "_txn_label": f"برداشت به {bank}",
        "cancellable": False,
    }


def withdrawal_request_to_txn_row(w: Dict[str, Any]) -> Dict[str, Any]:
    bank = (w.get("bank_summary") or "حساب بانکی").strip()
    amt = _amount_int(w.get("amount"))
    st = (str(w.get("status") or "pending")).strip()
    return {
        "txn_type": "withdrawal_request",
        "created_at": w.get("created_at") or w.get("updated_at") or "",
        "status": st,
        "commission_amount": -amt if amt > 0 else 0,
        "withdrawal_amount": amt,
        "bank_summary": bank,
        "withdrawal_id": w.get("id"),
        "withdrawal_status_label": status_label(st),
        "_txn_label": f"درخواست برداشت به {bank}",
        "cancellable": st in PARTNER_CANCELLABLE_WITHDRAWAL_STATUSES,
    }


def cancel_partner_withdrawal(
    withdrawals: List[Dict[str, Any]],
    phone: str,
    withdrawal_id: str,
    commissions: Optional[List[Dict[str, Any]]] = None,
    cancelled_at: str = "",
) -> Tuple[bool, Optional[str]]:
    ph = (phone or "").strip()
    wid = (withdrawal_id or "").strip()
    if not ph or not wid:
        return False, "not_found"
    for w in withdrawals:
        if not isinstance(w, dict):
            continue
        if str(w.get("id") or "").strip() != wid:
            continue
        if str(w.get("phone") or "").strip() != ph:
            return False, "not_found"
        st = _withdrawal_status(w)
        if st not in PARTNER_CANCELLABLE_WITHDRAWAL_STATUSES:
            return False, "not_cancellable"
        w["status"] = "cancelled"
        w["updated_at"] = cancelled_at or w.get("updated_at") or w.get("created_at") or ""
        w["cancelled_at"] = w["updated_at"]
        w["cancelled_by"] = "partner"
        if commissions is not None:
            release_withdrawal_commissions(commissions, wid)
        return True, None
    return False, "not_found"


def commission_to_txn_row(c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """ردیف نمایشی تراکنش پورسانت — رویداد تاریخی، نه ماندهٔ زنده."""
    if not isinstance(c, dict):
        return None
    st = _commission_status(c)
    amt = _amount_int(c.get("commission_amount"))
    partial = _amount_int(c.get("partial_paid_total"))
    row = dict(c)
    row["txn_type"] = "commission"

    if st == "pending":
        row["created_at"] = c.get("created_at") or ""
        row["commission_amount"] = amt
        return row

    if st == "approved":
        original = amt + partial
        if original <= 0:
            return None
        row["commission_amount"] = original
        row["created_at"] = c.get("approved_at") or c.get("created_at") or ""
        row["status"] = "approved"
        row["_txn_phase"] = "approval"
        if partial > 0:
            row["partial_paid_display"] = partial
        return row

    if st == "paid":
        total = amt + partial
        if total <= 0:
            return None
        row["commission_amount"] = total
        row["created_at"] = c.get("paid_at") or c.get("approved_at") or c.get("created_at") or ""
        row["status"] = "paid"
        return row

    if st == "rejected":
        row["created_at"] = c.get("created_at") or ""
        row["commission_amount"] = amt
        return row

    row["created_at"] = c.get("created_at") or ""
    return row


def build_partner_txn_feed(
    commissions: List[Dict[str, Any]],
    withdrawals: List[Dict[str, Any]],
    phone: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    ph = (phone or "").strip()
    for c in commissions:
        if not isinstance(c, dict):
            continue
        if str(c.get("partner_phone") or "").strip() != ph:
            continue
        row = commission_to_txn_row(c)
        if row:
            rows.append(row)
    for w in withdrawals_for_phone(withdrawals, phone):
        st = (str(w.get("status") or "pending")).strip()
        if st == "paid":
            rows.append(withdrawal_to_txn_row(w))
        else:
            rows.append(withdrawal_request_to_txn_row(w))
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return rows


def partner_row_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    amt = _amount_int(row.get("amount"))
    st = (str(row.get("status") or "pending")).strip()
    return {
        "id": row.get("id"),
        "amount": amt,
        "status": st,
        "status_label": status_label(st),
        "bank_summary": row.get("bank_summary") or "",
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
    }


def admin_row_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    amt = _amount_int(row.get("amount"))
    return {
        "id": row.get("id"),
        "phone": row.get("phone") or "",
        "partner_name": row.get("partner_name") or "",
        "amount": amt,
        "bank_account_id": row.get("bank_account_id") or "",
        "bank_summary": row.get("bank_summary") or "",
        "bank_name": row.get("bank_name") or "",
        "masked_pan": row.get("masked_pan") or "",
        "holder_name": row.get("holder_name") or "",
        "status": (row.get("status") or "pending").strip(),
        "status_label": status_label(str(row.get("status") or "pending")),
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
        "admin_note": row.get("admin_note") or "",
    }


def validate_new_request(
    amount_raw: Any,
    bank_account_id: str,
    partner_phone: str,
    bank_rows: List[Dict[str, Any]],
    commissions: List[Dict[str, Any]],
    withdrawals: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    ph = (partner_phone or "").strip()
    acc_id = (bank_account_id or "").strip()
    amount = _amount_int(amount_raw)

    if amount < 10000:
        return None, "min_amount"
    if not acc_id:
        return None, "missing_bank"

    bank_rec = None
    for r in bank_rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("phone") or "").strip() != ph:
            continue
        if str(r.get("id") or "").strip() == acc_id:
            bank_rec = r
            break
    if not bank_rec:
        return None, "invalid_bank"

    available = available_for_new_withdrawal(commissions, withdrawals, ph)
    if amount > available:
        return None, "insufficient_balance"

    rec: Dict[str, Any] = {
        "id": uuid.uuid4().hex[:16],
        "phone": ph,
        "amount": amount,
        "bank_account_id": acc_id,
        "bank_summary": str(bank_rec.get("bank_name") or "") + " · " + (
            f"{bank_rec.get('pan_prefix4', '')[:4]} **** **** {str(bank_rec.get('pan_last4') or '')[-4:]}"
        ).strip(" ·"),
        "bank_name": bank_rec.get("bank_name") or "",
        "masked_pan": (
            f"{str(bank_rec.get('pan_prefix4') or '')[:4]} **** **** "
            f"{str(bank_rec.get('pan_last4') or '')[-4:]}"
        ),
        "holder_name": bank_rec.get("holder_name") or "",
        "status": "pending",
        "created_at": None,
        "updated_at": None,
        "admin_note": "",
    }
    return rec, None
