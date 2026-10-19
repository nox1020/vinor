# -*- coding: utf-8 -*-
"""انتقال پورسانت معامله از کیف پول مالک به مشاور، در همان تأیید نهایی."""
from __future__ import annotations

import contextvars
import os
import threading
from contextlib import contextmanager
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from app.utils.dates import iso_z, to_fa_digits, utcnow

PAYOUT_SOURCE = "deal_final_payout"
WALLET_CHARGE_PATH = "/express/partner/commissions"
WALLET_INSUFFICIENT = "wallet_insufficient"

_DETAIL: contextvars.ContextVar = contextvars.ContextVar("deal_wallet_detail", default=None)
_LOCK_DEPTH = 0
_LOCK_HANDLE = None
_LOCK_GUARD = threading.Lock()


def set_wallet_detail(detail: Optional[Dict[str, Any]]) -> None:
    _DETAIL.set(dict(detail) if isinstance(detail, dict) else None)


def wallet_detail() -> Dict[str, Any]:
    raw = _DETAIL.get()
    return dict(raw) if isinstance(raw, dict) else {}


def toman_fa(amount: int) -> str:
    grouped = f"{int(amount):,}".replace(",", "،")
    return to_fa_digits(grouped) + " تومان"


def wallet_insufficient_message(required: int, balance: int) -> str:
    need = max(0, int(required or 0))
    have = max(0, int(balance or 0))
    shortfall = max(0, need - have)
    return (
        f"برای تأیید نهایی، ابتدا کیف پول خود را به مبلغ پورسانت ({toman_fa(need)}) شارژ کنید. "
        f"کمبود: {toman_fa(shortfall)}."
    )


def commit_guard(stage: str) -> None:
    """نقطهٔ آزمایش. شکست این‌جا تراکنش را برمی‌گرداند."""
    del stage


@contextmanager
def commission_store_lock(app=None):
    """قفل فایل پورسانت تا دو تأیید هم‌زمان دو بار پول جابه‌جا نکنند."""
    global _LOCK_DEPTH, _LOCK_HANDLE
    import fcntl

    with _LOCK_GUARD:
        _LOCK_DEPTH += 1
        if _LOCK_DEPTH == 1:
            from app.utils.storage import ensure_file

            path = ensure_file(
                "EXPRESS_COMMISSIONS_FILE",
                "express_commissions.json",
                [],
                app,
            ) + ".lock"
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            handle = open(path, "a+", encoding="utf-8")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except Exception:
                handle.close()
                _LOCK_DEPTH -= 1
                raise
            _LOCK_HANDLE = handle
    try:
        yield
    finally:
        with _LOCK_GUARD:
            _LOCK_DEPTH -= 1
            if _LOCK_DEPTH == 0 and _LOCK_HANDLE is not None:
                try:
                    fcntl.flock(_LOCK_HANDLE.fileno(), fcntl.LOCK_UN)
                finally:
                    _LOCK_HANDLE.close()
                    _LOCK_HANDLE = None


def _amount(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _same_id(row: Dict[str, Any], deal_id: Any) -> bool:
    return str(row.get("id")) == str(deal_id)


def _next_commission_id(commissions: List[Dict[str, Any]]) -> int:
    best = 0
    for row in commissions:
        if not isinstance(row, dict):
            continue
        try:
            best = max(best, int(row.get("id") or 0))
        except (TypeError, ValueError):
            continue
    return best + 1


def find_deal_payout(commissions: List[Dict[str, Any]], deal_id: Any) -> Optional[Dict[str, Any]]:
    key = str(deal_id or "").strip()
    if not key:
        return None
    for row in commissions or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("source") or "").strip() != PAYOUT_SOURCE:
            continue
        if str(row.get("payout_deal_id") or "").strip() == key:
            return row
    return None


def card_wallet_fields(
    commissions: List[Dict[str, Any]] | None,
    withdrawals: List[Dict[str, Any]] | None,
    *,
    owner_phone: str,
    required: int,
    can_finalize: bool,
) -> Dict[str, Any]:
    from .partner_withdrawals import withdrawable_balance

    amount = _amount(required)
    balance = 0
    if str(owner_phone or "").strip():
        try:
            balance = int(withdrawable_balance(commissions or [], withdrawals or [], owner_phone))
        except Exception:
            balance = 0
    shortfall = max(0, amount - balance)
    ready = bool(can_finalize) and shortfall <= 0
    code = ""
    message = ""
    if can_finalize and shortfall > 0:
        code = WALLET_INSUFFICIENT
        message = wallet_insufficient_message(amount, balance)
    return {
        "required_commission": amount,
        "owner_wallet_balance": balance,
        "can_final_confirm": ready,
        "wallet_shortfall": shortfall if can_finalize else 0,
        "wallet_error": code,
        "final_confirm_message": message,
        "wallet_charge_path": WALLET_CHARGE_PATH if message else "",
    }


def _stage_payout(
    commissions: List[Dict[str, Any]],
    withdrawals: List[Dict[str, Any]],
    deal: Dict[str, Any],
    *,
    owner_phone: str,
) -> Tuple[Optional[str], Dict[str, Any]]:
    from .partner_withdrawals import withdrawable_balance

    amount = _amount(deal.get("commission_amount"))
    status = str(deal.get("status") or "").strip().lower()
    existing = find_deal_payout(commissions, deal.get("id"))
    settled = bool(existing) or bool(deal.get("payout_settled")) or amount == 0
    if status in ("approved", "paid") and settled:
        balance = 0
        if owner_phone:
            balance = int(withdrawable_balance(commissions, withdrawals, owner_phone))
        return None, {
            "idempotent": True,
            "transferred": False,
            "required_amount": amount,
            "balance": balance,
            "shortfall": 0,
        }
    if status in ("approved", "paid"):
        return "already_sold", {}
    if status != "pending":
        return "invalid_transition", {}

    balance = int(withdrawable_balance(commissions, withdrawals, owner_phone)) if owner_phone else 0
    if balance < amount:
        shortfall = amount - balance
        message = wallet_insufficient_message(amount, balance)
        detail = {
            "idempotent": False,
            "transferred": False,
            "error": WALLET_INSUFFICIENT,
            "required_amount": amount,
            "balance": balance,
            "shortfall": shortfall,
            "message": message,
        }
        return WALLET_INSUFFICIENT, detail

    stamp = iso_z(utcnow())
    payout_id = 0
    if amount > 0:
        payout_id = _next_commission_id(commissions)
        commissions.append({
            "id": payout_id,
            "commission_type": "manual_adjustment",
            "partner_phone": owner_phone,
            "land_code": str(deal.get("land_code") or "").strip(),
            "sale_amount": 0,
            "commission_pct": 0,
            "commission_amount": -amount,
            "status": "approved",
            "created_at": stamp,
            "approved_at": stamp,
            "source": PAYOUT_SOURCE,
            "payout_deal_id": str(deal.get("id") or ""),
            "counterparty_phone": str(deal.get("partner_phone") or "").strip(),
            "admin_note": "انتقال پورسانت معامله به مشاور",
        })
    deal["status"] = "approved"
    deal["approved_at"] = stamp
    deal["payout_settled"] = True
    deal["owner_payout_id"] = payout_id
    deal["payout_owner_phone"] = owner_phone
    balance_after = balance - amount
    return None, {
        "idempotent": False,
        "transferred": amount > 0,
        "required_amount": amount,
        "balance": balance_after,
        "shortfall": 0,
        "payout_id": payout_id,
    }


def _apply_advisor_stats(partners: List[Dict[str, Any]], deal: Dict[str, Any], stamp: str) -> None:
    if deal.get("advisor_stats_applied"):
        return
    phone = str(deal.get("partner_phone") or "").strip()
    amount = _amount(deal.get("commission_amount"))
    try:
        sale = int(deal.get("sale_amount") or 0)
    except (TypeError, ValueError):
        sale = 0
    if phone:
        for partner in partners:
            if not isinstance(partner, dict):
                continue
            if str(partner.get("phone") or "").strip() != phone:
                continue
            partner["total_income"] = int(partner.get("total_income", 0) or 0) + amount
            partner["approved_sales_count"] = int(partner.get("approved_sales_count", 0) or 0) + 1
            partner["total_approved_sales"] = int(partner.get("total_approved_sales", 0) or 0) + sale
            partner["last_updated"] = stamp
            break
    deal["advisor_stats_applied"] = True


def finalize_deal_payout(*, deal_id: Any, owner_phone: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """پورسانت pending را فقط بعد از کسر موجودی مالک approved می‌کند.

    اعتبار مشاور همان رکورد معامله است؛ ردیف دوم ساخته نمی‌شود.
    برداشتِ در جریان از موجودی قابل برداشت کم شده است.
    """
    from app.utils import storage

    from .commissions_flow import mark_assignments_sold_for_land

    set_wallet_detail(None)
    owner = str(owner_phone or "").strip()
    with commission_store_lock():
        commissions = storage.load_express_commissions() or []
        if not isinstance(commissions, list):
            return "failed", {}
        withdrawals = storage.load_partner_withdrawals() or []
        if not isinstance(withdrawals, list):
            withdrawals = []
        deal = next(
            (row for row in commissions if isinstance(row, dict) and _same_id(row, deal_id)),
            None,
        )
        if deal is None:
            return "not_found", {}
        snapshot = deepcopy(commissions)
        partners = storage.load_express_partners() or []
        if not isinstance(partners, list):
            partners = []
        partners_snapshot = deepcopy(partners)
        assignments = storage.load_express_assignments() or []
        if not isinstance(assignments, list):
            assignments = []
        assignments_snapshot = deepcopy(assignments)

        err, detail = _stage_payout(commissions, withdrawals, deal, owner_phone=owner)
        if err:
            set_wallet_detail(detail)
            return err, detail
        if detail.get("idempotent"):
            set_wallet_detail(detail)
            land_code = str(deal.get("land_code") or "").strip()
            detail["land_code"] = land_code
            detail["partner_phone"] = str(deal.get("partner_phone") or "").strip()
            detail["commission_id"] = deal.get("id")
            detail["sale_amount"] = deal.get("sale_amount") or 0
            if land_code:
                try:
                    stamp = str(deal.get("approved_at") or "") or iso_z(utcnow())
                    if mark_assignments_sold_for_land(assignments, land_code, sold_at=stamp):
                        storage.save_express_assignments(assignments)
                except Exception:
                    pass
            return None, detail

        stamp = str(deal.get("approved_at") or "")
        try:
            commit_guard("staged")
            _apply_advisor_stats(partners, deal, stamp)
            storage.save_express_partners(partners)
            storage.save_express_commissions(commissions)
            land_code = str(deal.get("land_code") or "").strip()
            if land_code and mark_assignments_sold_for_land(assignments, land_code, sold_at=stamp):
                storage.save_express_assignments(assignments)
            commit_guard("saved")
        except Exception:
            storage.save_express_partners(partners_snapshot)
            storage.save_express_commissions(snapshot)
            storage.save_express_assignments(assignments_snapshot)
            set_wallet_detail(None)
            return "failed", {}

        detail["land_code"] = land_code
        detail["partner_phone"] = str(deal.get("partner_phone") or "").strip()
        detail["commission_id"] = deal.get("id")
        detail["sale_amount"] = deal.get("sale_amount") or 0
        set_wallet_detail(detail)
        return None, detail
