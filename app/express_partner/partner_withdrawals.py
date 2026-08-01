# -*- coding: utf-8 -*-
"""درخواست برداشت پورسانت همکار اکسپرس."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

RESERVE_STATUSES = frozenset({"pending", "approved", "processing"})
# فعال = از موجودی قابل برداشت کم می‌شود (رد شده و لغوشده فعال نیستند)
ACTIVE_WITHDRAWAL_STATUSES = RESERVE_STATUSES
ADMIN_OPEN_STATUSES = frozenset({"pending", "approved", "processing"})
PARTNER_CANCELLABLE_WITHDRAWAL_STATUSES = frozenset({"pending"})

# انتقال‌های مجاز وضعیت در پنل ادمین
ADMIN_STATUS_TRANSITIONS: Dict[str, frozenset] = {
    "pending": frozenset({"pending", "approved", "rejected"}),
    "approved": frozenset({"approved", "processing", "paid", "rejected"}),
    "processing": frozenset({"processing", "paid", "rejected"}),
    "rejected": frozenset({"rejected"}),
    "paid": frozenset({"paid"}),
    "cancelled": frozenset({"cancelled"}),
}
# از موجودی قابل برداشت کسر می‌شود: در انتظار بررسی + تأیید ادمین + در حال پردازش
WITHDRAWABLE_RESERVE_STATUSES = RESERVE_STATUSES
LOCK_RESERVE_STATUSES = RESERVE_STATUSES

# کف برداشت پورسانت (تومان)
MIN_WITHDRAWAL_AMOUNT = 10_000_000

COMMISSION_TYPE_MANUAL_ADJUSTMENT = "manual_adjustment"


def _amount_int(v: Any) -> int:
    try:
        return max(0, int(str(v).replace(",", "").strip() or "0"))
    except Exception:
        return 0


def _commission_status(c: Dict[str, Any]) -> str:
    return (str(c.get("status") or "pending")).strip()


def normalize_partner_phone(phone: str) -> str:
    try:
        from app.services.notifications import _normalize_user_id

        return _normalize_user_id(phone or "")
    except Exception:
        return (phone or "").strip()


def partner_phones_match(a: str, b: str) -> bool:
    na = normalize_partner_phone(a)
    nb = normalize_partner_phone(b)
    return bool(na and nb and na == nb)


def _signed_amount_int(v: Any) -> int:
    try:
        return int(str(v).replace(",", "").strip() or "0")
    except (TypeError, ValueError):
        return 0


def _approved_line_amount(c: Dict[str, Any]) -> int:
    if (str(c.get("commission_type") or "")).strip() == COMMISSION_TYPE_MANUAL_ADJUSTMENT:
        return _signed_amount_int(c.get("commission_amount"))
    return _amount_int(c.get("commission_amount"))


def approved_gross_commission_total(
    commissions: List[Dict[str, Any]], phone: str
) -> int:
    total = 0
    for c in commissions:
        if not isinstance(c, dict):
            continue
        if not partner_phones_match(c.get("partner_phone"), phone):
            continue
        if _commission_status(c) == "approved":
            total += _approved_line_amount(c)
    return total


def _withdrawal_status(w: Dict[str, Any]) -> str:
    return (str(w.get("status") or "pending")).strip().lower()


def _active_withdrawal_ids(withdrawals: List[Dict[str, Any]], phone: str) -> set:
    out: set = set()
    for w in withdrawals:
        if not isinstance(w, dict):
            continue
        if not partner_phones_match(w.get("phone"), phone):
            continue
        if _withdrawal_status(w) in LOCK_RESERVE_STATUSES:
            wid = str(w.get("id") or "").strip()
            if wid:
                out.add(wid)
    return out


def _partner_commissions_for_phone(
    commissions: List[Dict[str, Any]], phone: str
) -> List[Dict[str, Any]]:
    return [
        c
        for c in commissions
        if isinstance(c, dict) and partner_phones_match(c.get("partner_phone"), phone)
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
        # همیشه مبلغ برداشت‌شده را در partial_paid_total نگه دار تا
        # ردیف تاریخی تراکنش (و آمار درآمد) بعد از صفر شدن commission_amount گم نشود.
        c["partial_paid_total"] = _amount_int(c.get("partial_paid_total")) + take
        left = amt - take
        if left <= 0:
            c["status"] = "paid"
            c["paid_at"] = paid_at
            c["commission_amount"] = 0
            if wid:
                c["withdrawal_id"] = wid
        else:
            c["commission_amount"] = left
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
        and partner_phones_match(w.get("phone"), phone)
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


def apply_manual_balance_target(
    commissions: List[Dict[str, Any]],
    withdrawals: List[Dict[str, Any]],
    phone: str,
    target_withdrawable: int,
    note: str = "",
    *,
    created_at: str = "",
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """تنظیم موجودی قابل برداشت با ثبت تعدیل دستی (پورسانت approved)."""
    ph = (phone or "").strip()
    if not ph:
        return False, "invalid_phone", None
    target = max(0, _amount_int(target_withdrawable))
    current = approved_commission_total(commissions, withdrawals, ph)
    delta = target - current
    if delta == 0:
        return False, "no_change", None

    new_id = (
        max([int(x.get("id", 0) or 0) for x in commissions if isinstance(x, dict)], default=0) or 0
    ) + 1
    now = (created_at or "").strip() or (datetime.utcnow().isoformat() + "Z")
    rec: Dict[str, Any] = {
        "id": new_id,
        "commission_type": COMMISSION_TYPE_MANUAL_ADJUSTMENT,
        "partner_phone": ph,
        "land_code": "manual",
        "sale_amount": 0,
        "commission_pct": 0,
        "commission_amount": delta,
        "status": "approved",
        "created_at": now,
        "approved_at": now,
        "admin_note": (note or "").strip(),
        "adjustment_target": target,
        "adjustment_previous": current,
    }
    commissions.append(rec)
    return True, "ok", rec


def _withdrawal_reserve_total(
    withdrawals: List[Dict[str, Any]], phone: str, statuses: frozenset
) -> int:
    total = 0
    for w in withdrawals:
        if not isinstance(w, dict):
            continue
        if not partner_phones_match(w.get("phone"), phone):
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
    total = 0
    for w in withdrawals:
        if not isinstance(w, dict):
            continue
        if not partner_phones_match(w.get("phone"), phone):
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
    pending_amount = pending_count = 0
    approved_gross_amount = approved_gross_count = 0
    paid_amount = paid_count = 0

    for c in commissions:
        if not isinstance(c, dict):
            continue
        if not partner_phones_match(c.get("partner_phone"), phone):
            continue
        st = _commission_status(c)
        if st == "pending":
            amt = _amount_int(c.get("commission_amount"))
            pending_amount += amt
            pending_count += 1
        elif st == "approved":
            amt = _approved_line_amount(c)
            approved_gross_amount += amt
            approved_gross_count += 1
            partial = _amount_int(c.get("partial_paid_total"))
            if partial:
                paid_amount += partial
        elif st == "paid":
            line = _amount_int(c.get("commission_amount")) + _amount_int(c.get("partial_paid_total"))
            if line <= 0:
                line = _estimate_commission_display_amount(c)
            paid_amount += line
            paid_count += 1

    in_withdrawal_amount = reserved_withdrawal_total(withdrawals, phone)
    withdrawable_reserve = withdrawable_reserve_total(withdrawals, phone)
    pending_wd_only = pending_withdrawal_only_total(withdrawals, phone)
    in_withdrawal_count = sum(
        1
        for w in withdrawals
        if isinstance(w, dict)
        and partner_phones_match(w.get("phone"), phone)
        and _withdrawal_status(w) in LOCK_RESERVE_STATUSES
    )
    paid_wd_amount = paid_withdrawal_total(withdrawals, phone)
    paid_wd_count = sum(
        1
        for w in withdrawals
        if isinstance(w, dict)
        and partner_phones_match(w.get("phone"), phone)
        and _withdrawal_status(w) == "paid"
    )
    approved_amount = approved_commission_total(commissions, withdrawals, phone)
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


def admin_can_transition(old_status: str, new_status: str) -> bool:
    old = (old_status or "pending").strip().lower()
    new = (new_status or "").strip().lower()
    if old == new:
        return True
    allowed = ADMIN_STATUS_TRANSITIONS.get(old)
    return bool(allowed and new in allowed)


def admin_status_options(old_status: str) -> List[Dict[str, str]]:
    """گزینه‌های select ادمین بر اساس وضعیت فعلی."""
    old = (old_status or "pending").strip().lower()
    keys = ADMIN_STATUS_TRANSITIONS.get(old, frozenset({old}))
    order = ("pending", "approved", "processing", "paid", "rejected", "cancelled")
    out: List[Dict[str, str]] = []
    for key in order:
        if key in keys:
            out.append({"value": key, "label": status_label(key)})
    return out


def withdrawal_filter_bucket(status: str) -> str:
    st = (status or "pending").strip().lower()
    if st == "pending":
        return "pending"
    if st == "approved":
        return "approved"
    if st == "processing":
        return "processing"
    if st == "paid":
        return "paid"
    if st in ("rejected", "cancelled"):
        return "closed"
    return "other"


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
    out: List[Dict[str, Any]] = []
    for w in withdrawals:
        if not isinstance(w, dict):
            continue
        if not partner_phones_match(w.get("phone"), phone):
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
        "bank_name": w.get("bank_name") or "",
        "masked_pan": w.get("masked_pan") or "",
        "holder_name": w.get("holder_name") or "",
        "bank_account_id": w.get("bank_account_id") or "",
        "commission_allocated_amount": _amount_int(w.get("commission_allocated_amount")),
        "admin_note": w.get("admin_note") or "",
        "withdrawal_id": w.get("id"),
        "_txn_label": "برداشت",
        "_txn_meta": bank,
        "cancellable": False,
        "updated_at": w.get("updated_at") or w.get("created_at") or "",
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
        "bank_name": w.get("bank_name") or "",
        "masked_pan": w.get("masked_pan") or "",
        "holder_name": w.get("holder_name") or "",
        "bank_account_id": w.get("bank_account_id") or "",
        "commission_allocated_amount": _amount_int(w.get("commission_allocated_amount")),
        "admin_note": w.get("admin_note") or "",
        "withdrawal_id": w.get("id"),
        "withdrawal_status_label": status_label(st),
        "_txn_label": "درخواست برداشت",
        "_txn_meta": bank,
        "cancellable": st in PARTNER_CANCELLABLE_WITHDRAWAL_STATUSES,
        "updated_at": w.get("updated_at") or "",
        "cancelled_at": w.get("cancelled_at") or "",
        "cancelled_by": w.get("cancelled_by") or "",
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
        if not partner_phones_match(w.get("phone"), phone):
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


def _estimate_commission_display_amount(c: Dict[str, Any]) -> int:
    """بازسازی مبلغ نمایشی وقتی commission_amount صفر شده و partial هم خالی است."""
    sale = _amount_int(c.get("sale_amount"))
    pct_raw = c.get("commission_pct")
    if sale <= 0 or pct_raw is None or str(pct_raw).strip() == "":
        return 0
    try:
        return max(0, int(round(sale * float(pct_raw) / 100.0)))
    except (TypeError, ValueError):
        return 0


def commission_to_txn_row(c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """ردیف نمایشی تراکنش پورسانت — رویداد تاریخی، نه ماندهٔ زنده."""
    if not isinstance(c, dict):
        return None
    st = _commission_status(c)
    is_adj = (str(c.get("commission_type") or "")).strip() == COMMISSION_TYPE_MANUAL_ADJUSTMENT
    # تعدیل دستی می‌تواند منفی باشد؛ بقیهٔ پورسانت‌ها غیرمنفی‌اند.
    amt = _signed_amount_int(c.get("commission_amount")) if is_adj else _amount_int(c.get("commission_amount"))
    partial = _amount_int(c.get("partial_paid_total"))
    row = dict(c)
    row["txn_type"] = "commission"

    if st == "pending":
        row["created_at"] = c.get("created_at") or ""
        row["commission_amount"] = amt
        return row

    if st == "approved":
        if is_adj:
            if amt == 0:
                return None
            row["commission_amount"] = amt
            row["created_at"] = c.get("approved_at") or c.get("created_at") or ""
            row["status"] = "approved"
            row["_txn_phase"] = "approval"
            return row
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
            total = _estimate_commission_display_amount(c)
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


def _txn_status_label(row: Dict[str, Any]) -> str:
    txn_type = (row.get("txn_type") or "commission").strip()
    st = (str(row.get("status") or "pending")).strip()
    if txn_type == "withdrawal":
        return "واریز شد"
    if txn_type == "withdrawal_request":
        return str(row.get("withdrawal_status_label") or status_label(st))
    if st == "approved" and row.get("_txn_phase") == "approval":
        return "تأیید پورسانت"
    if st == "pending":
        return "در انتظار تأیید"
    if st == "approved":
        return "تأیید شده"
    if st == "paid":
        return "پرداخت‌شده"
    if st == "rejected":
        return "رد شده"
    return status_label(st)


def _txn_type_title(row: Dict[str, Any]) -> str:
    txn_type = (row.get("txn_type") or "commission").strip()
    if txn_type == "withdrawal":
        return "واریز برداشت"
    if txn_type == "withdrawal_request":
        return "درخواست برداشت"
    if (str(row.get("commission_type") or "")).strip() == COMMISSION_TYPE_MANUAL_ADJUSTMENT:
        return "تعدیل موجودی"
    if (str(row.get("commission_type") or "")).strip() == "referral":
        return "پورسانت دعوت"
    return "پورسانت فروش"


def partner_txn_detail(row: Dict[str, Any]) -> Dict[str, Any]:
    """دادهٔ نمایش جزئیات تراکنش در مودال همکار."""
    txn_type = (row.get("txn_type") or "commission").strip()
    st = (str(row.get("status") or "pending")).strip()
    is_wd = txn_type in ("withdrawal", "withdrawal_request")
    if is_wd:
        raw_amt = _amount_int(row.get("withdrawal_amount"))
        amt = raw_amt
        amount_sign = "-"
    else:
        raw_amt = _signed_amount_int(row.get("commission_amount"))
        amt = abs(raw_amt)
        amount_sign = "-" if raw_amt < 0 else "+"

    fields: List[Dict[str, Any]] = []
    wallet_fields: List[Dict[str, Any]] = []
    dates: List[Dict[str, Any]] = []

    if is_wd:
        wid = str(row.get("withdrawal_id") or "").strip()
        bank_name = str(row.get("bank_name") or "").strip()
        masked_pan = str(row.get("masked_pan") or "").strip()
        holder = str(row.get("holder_name") or "").strip()
        bank_summary = str(row.get("bank_summary") or "").strip()
        allocated = _amount_int(row.get("commission_allocated_amount"))

        if bank_name:
            wallet_fields.append({"label": "بانک", "value": bank_name})
        if masked_pan:
            wallet_fields.append({"label": "شماره کارت", "value": masked_pan})
        elif bank_summary:
            wallet_fields.append({"label": "حساب مقصد", "value": bank_summary})
        if holder:
            wallet_fields.append({"label": "صاحب حساب", "value": holder})
        if bank_summary and masked_pan:
            wallet_fields.append({"label": "خلاصه حساب", "value": bank_summary})

        fields.append({"label": "مبلغ برداشت", "value": amt, "format": "toman"})
        if allocated > 0:
            fields.append({"label": "پورسانت تخصیص‌یافته", "value": allocated, "format": "toman"})
        if wid:
            fields.append({"label": "شناسه درخواست", "value": wid})
        admin_note = str(row.get("admin_note") or "").strip()
        if admin_note:
            fields.append({"label": "یادداشت پشتیبانی", "value": admin_note})
        cancelled_by = str(row.get("cancelled_by") or "").strip()
        if cancelled_by:
            fields.append({"label": "لغو توسط", "value": "شما" if cancelled_by == "partner" else cancelled_by})

        if row.get("created_at"):
            dates.append({"label": "تاریخ درخواست", "value": str(row.get("created_at") or "")})
        updated = str(row.get("updated_at") or "").strip()
        created = str(row.get("created_at") or "").strip()
        if updated and updated != created:
            label = "تاریخ واریز" if txn_type == "withdrawal" else "آخرین بروزرسانی"
            dates.append({"label": label, "value": updated})
        if row.get("cancelled_at"):
            dates.append({"label": "تاریخ لغو", "value": str(row.get("cancelled_at") or "")})
    else:
        comm_type = (str(row.get("commission_type") or "")).strip()
        land = str(row.get("land_code") or "").strip()
        if comm_type == "referral":
            fields.append({"label": "نوع", "value": "پورسانت دعوت"})
            referred_name = str(row.get("referred_name") or "").strip()
            referred = str(row.get("referred_phone") or row.get("referral_phone") or "").strip()
            if referred_name:
                fields.append({"label": "نام همکار", "value": referred_name})
            if referred:
                wallet_fields.append({"label": "همکار دعوت‌شده", "value": referred})
        elif comm_type == COMMISSION_TYPE_MANUAL_ADJUSTMENT:
            fields.append({"label": "نوع", "value": "تعدیل دستی موجودی"})
            prev = row.get("adjustment_previous")
            tgt = row.get("adjustment_target")
            if prev is not None:
                fields.append({"label": "موجودی قبلی", "value": _amount_int(prev), "format": "toman"})
            if tgt is not None:
                fields.append({"label": "موجودی هدف", "value": _amount_int(tgt), "format": "toman"})
            adj_note = str(row.get("admin_note") or "").strip()
            if adj_note:
                fields.append({"label": "یادداشت ادمین", "value": adj_note})
        elif "visit" in comm_type.lower():
            fields.append({"label": "نوع", "value": "پورسانت (بایگانی)"})
            if land and land != "referral":
                fields.append({"label": "کد ملک", "value": land})
        elif land and land != "referral":
            fields.append({"label": "کد ملک", "value": land})

        sale = _amount_int(row.get("sale_amount"))
        if sale > 0:
            fields.append({"label": "مبلغ فروش", "value": sale, "format": "toman"})
        pct_raw = row.get("commission_pct")
        if pct_raw is not None and str(pct_raw).strip() != "":
            try:
                fields.append({"label": "درصد پورسانت", "value": f"{float(pct_raw):g}٪"})
            except Exception:
                pass
        fields.append({
            "label": "مبلغ تعدیل" if (str(row.get("commission_type") or "")).strip() == COMMISSION_TYPE_MANUAL_ADJUSTMENT else "مبلغ پورسانت",
            "value": raw_amt,
            "format": "toman",
        })
        partial = _amount_int(row.get("partial_paid_display"))
        if partial > 0 and raw_amt >= 0:
            fields.append({"label": "واریز شده از این پورسانت", "value": partial, "format": "toman"})
            remaining = max(0, amt - partial)
            if remaining > 0 and st == "approved":
                fields.append({"label": "مانده قابل برداشت", "value": remaining, "format": "toman"})

        linked = row.get("_linked_withdrawal") if isinstance(row.get("_linked_withdrawal"), dict) else {}
        wid = str(row.get("withdrawal_id") or linked.get("id") or "").strip()
        if wid or linked:
            if wid:
                wallet_fields.append({"label": "شناسه برداشت مرتبط", "value": wid})
            link_bank = str(linked.get("bank_summary") or row.get("bank_summary") or "").strip()
            link_name = str(linked.get("bank_name") or "").strip()
            link_pan = str(linked.get("masked_pan") or "").strip()
            if link_name:
                wallet_fields.append({"label": "بانک مقصد", "value": link_name})
            if link_pan:
                wallet_fields.append({"label": "کارت مقصد", "value": link_pan})
            elif link_bank:
                wallet_fields.append({"label": "حساب مقصد", "value": link_bank})
            link_amt = _amount_int(linked.get("amount"))
            if link_amt > 0:
                wallet_fields.append({"label": "مبلغ درخواست برداشت", "value": link_amt, "format": "toman"})
            link_st = str(linked.get("status") or "").strip()
            if link_st:
                wallet_fields.append({"label": "وضعیت برداشت", "value": status_label(link_st)})

        if row.get("created_at"):
            dates.append({"label": "تاریخ ثبت", "value": str(row.get("created_at") or "")})
        if row.get("approved_at"):
            dates.append({"label": "تاریخ تأیید", "value": str(row.get("approved_at") or "")})
        if row.get("paid_at"):
            dates.append({"label": "تاریخ پرداخت", "value": str(row.get("paid_at") or "")})
        cid = row.get("id")
        if cid is not None and str(cid).strip() != "":
            fields.append({"label": "شناسه پورسانت", "value": str(cid)})

    wallet_title = "حساب بانکی / کیف پول" if is_wd else "اطلاعات برداشت مرتبط"
    if not wallet_fields:
        wallet_title = ""

    return {
        "txn_type": txn_type,
        "title": _txn_type_title(row),
        "description": (str(row.get("_txn_meta") or row.get("_txn_label") or "")).strip(),
        "amount": amt,
        "amount_sign": amount_sign,
        "status": st,
        "status_label": _txn_status_label(row),
        "fields": fields,
        "wallet_fields": wallet_fields,
        "wallet_title": wallet_title,
        "dates": dates,
        "primary_date": str(row.get("created_at") or ""),
        "cancellable": bool(row.get("cancellable")),
        "withdrawal_id": str(row.get("withdrawal_id") or ""),
    }


def partner_txn_kind(row: Dict[str, Any]) -> str:
    txn_type = (row.get("txn_type") or "commission").strip()
    if txn_type in ("withdrawal", "withdrawal_request"):
        return "withdrawal"
    return "commission"


def partner_txn_filter_bucket(row: Dict[str, Any]) -> str:
    """bucket فیلتر UI: pending | approved | paid | closed."""
    txn_type = (row.get("txn_type") or "commission").strip()
    st = (str(row.get("status") or "pending")).strip()
    if txn_type == "withdrawal":
        return "paid"
    if txn_type == "withdrawal_request":
        if st in ("cancelled", "rejected"):
            return "closed"
        if st in ("approved", "processing"):
            return "approved"
        return "pending"
    if st == "rejected":
        return "closed"
    if st in ("pending", "approved", "paid"):
        return st
    return "pending"


def partner_txn_feed_summary(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = {
        "all": len(rows),
        "pending": 0,
        "approved": 0,
        "paid": 0,
        "withdrawal": 0,
        "closed": 0,
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        bucket = row.get("_txn_filter") or partner_txn_filter_bucket(row)
        kind = row.get("_txn_kind") or partner_txn_kind(row)
        if kind == "withdrawal":
            summary["withdrawal"] += 1
        if bucket in summary:
            summary[bucket] += 1
    return summary


def build_partner_txn_feed(
    commissions: List[Dict[str, Any]],
    withdrawals: List[Dict[str, Any]],
    phone: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for c in commissions:
        if not isinstance(c, dict):
            continue
        if not partner_phones_match(c.get("partner_phone"), phone):
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
    wd_by_id: Dict[str, Dict[str, Any]] = {}
    for w in withdrawals_for_phone(withdrawals, phone):
        if not isinstance(w, dict):
            continue
        wid = str(w.get("id") or "").strip()
        if wid:
            wd_by_id[wid] = w
    for r in rows:
        if not isinstance(r, dict):
            continue
        wid = str(r.get("withdrawal_id") or "").strip()
        if wid and wid in wd_by_id:
            w = wd_by_id[wid]
            r["_linked_withdrawal"] = {
                "id": wid,
                "bank_summary": w.get("bank_summary") or "",
                "bank_name": w.get("bank_name") or "",
                "masked_pan": w.get("masked_pan") or "",
                "amount": _amount_int(w.get("amount")),
                "status": w.get("status") or "",
            }
        r["_txn_kind"] = partner_txn_kind(r)
        r["_txn_filter"] = partner_txn_filter_bucket(r)
        r["_txn_detail"] = partner_txn_detail(r)
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
    st = (str(row.get("status") or "pending")).strip().lower()
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
        "status": st,
        "status_label": status_label(st),
        "filter_bucket": withdrawal_filter_bucket(st),
        "is_active": st in ACTIVE_WITHDRAWAL_STATUSES,
        "is_editable": st in ADMIN_OPEN_STATUSES,
        "status_options": admin_status_options(st),
        "commission_allocated_amount": _amount_int(row.get("commission_allocated_amount")),
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
    ph = normalize_partner_phone(partner_phone)
    acc_id = (bank_account_id or "").strip()
    amount = _amount_int(amount_raw)

    if amount < MIN_WITHDRAWAL_AMOUNT:
        return None, "min_amount"
    if not acc_id:
        return None, "missing_bank"

    bank_rec = None
    for r in bank_rows:
        if not isinstance(r, dict):
            continue
        if not partner_phones_match(r.get("phone"), ph):
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
