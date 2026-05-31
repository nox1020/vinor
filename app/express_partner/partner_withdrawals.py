# -*- coding: utf-8 -*-
"""درخواست برداشت پورسانت همکار اکسپرس."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

RESERVE_STATUSES = frozenset({"pending", "approved", "processing"})


def _amount_int(v: Any) -> int:
    try:
        return max(0, int(str(v).replace(",", "").strip() or "0"))
    except Exception:
        return 0


def approved_commission_total(commissions: List[Dict[str, Any]]) -> int:
    total = 0
    for c in commissions:
        if not isinstance(c, dict):
            continue
        st = (str(c.get("status") or "pending")).strip()
        if st == "approved":
            total += _amount_int(c.get("commission_amount"))
    return total


def reserved_withdrawal_total(
    withdrawals: List[Dict[str, Any]], phone: str
) -> int:
    ph = (phone or "").strip()
    total = 0
    for w in withdrawals:
        if not isinstance(w, dict):
            continue
        if str(w.get("phone") or "").strip() != ph:
            continue
        st = (str(w.get("status") or "pending")).strip()
        if st in RESERVE_STATUSES:
            total += _amount_int(w.get("amount"))
    return total


def withdrawable_balance(
    commissions: List[Dict[str, Any]],
    withdrawals: List[Dict[str, Any]],
    phone: str,
) -> int:
    approved = approved_commission_total(commissions)
    reserved = reserved_withdrawal_total(withdrawals, phone)
    return max(0, approved - reserved)


def status_label(status: str) -> str:
    s = (status or "pending").strip()
    return {
        "pending": "در انتظار بررسی",
        "approved": "تأیید شده",
        "processing": "در حال پردازش",
        "paid": "پرداخت‌شده",
        "rejected": "رد شده",
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


def apply_paid_withdrawal_to_commissions(
    commissions: List[Dict[str, Any]],
    phone: str,
    amount: int,
    withdrawal_id: str,
    paid_at: str,
) -> int:
    """پورسانت‌های تأییدشده را به‌ترتیب FIFO به paid تبدیل می‌کند."""
    ph = (phone or "").strip()
    remaining = max(0, _amount_int(amount))
    if not ph or remaining <= 0:
        return 0

    mine: List[Dict[str, Any]] = []
    for c in commissions:
        if not isinstance(c, dict):
            continue
        if str(c.get("partner_phone") or "").strip() != ph:
            continue
        if (str(c.get("status") or "")).strip() != "approved":
            continue
        mine.append(c)
    mine.sort(key=lambda x: x.get("approved_at") or x.get("created_at") or "")

    allocated = 0
    for c in mine:
        if remaining <= 0:
            break
        amt = _amount_int(c.get("commission_amount"))
        if amt <= 0 or amt > remaining:
            continue
        c["status"] = "paid"
        c["paid_at"] = paid_at
        if withdrawal_id:
            c["withdrawal_id"] = withdrawal_id
        remaining -= amt
        allocated += amt
    return allocated


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

    available = withdrawable_balance(commissions, withdrawals, ph)
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
