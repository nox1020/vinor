# -*- coding: utf-8 -*-
"""بلوکهٔ پورسانت هنگام انتشار فروش.

مبلغ اعلامی از موجودی قابل برداشت کم نمی‌شود؛ فقط از موجودی قابل استفاده
(برداشت و انتشار بعدی) کنار گذاشته می‌شود. فروش همان مبلغ را خرج می‌کند
و لغو یا انقضای آگهی، اگر معاملهٔ باز نباشد، آن را آزاد می‌کند.
"""
from __future__ import annotations

import contextvars
from typing import Any, Dict, List, Optional, Tuple

from app.utils.dates import iso_z, utcnow

_LAST_DETAIL: contextvars.ContextVar = contextvars.ContextVar("escrow_hold_detail", default=None)

HOLD_TYPE = "escrow_hold"
STATUS_HELD = "held"
STATUS_RELEASED = "released"
STATUS_SETTLED = "settled"
HOLD_SOURCE = "sale_publish_escrow"
TOPUP_SOURCE = "wallet_zarinpal"
WALLET_CHARGE_PATH = "/express/partner/wallet/charge"

_OPEN_DEAL_STATUSES = frozenset({"in_transaction"})


def commission_amount_for(price_total: Any, pct: Any) -> int:
    try:
        price = int(price_total or 0)
    except (TypeError, ValueError):
        price = 0
    try:
        rate = float(pct or 0)
    except (TypeError, ValueError):
        rate = 0.0
    if price <= 0 or rate <= 0:
        return 0
    return int(round(price * (rate / 100.0)))


def is_hold(row: Dict[str, Any] | None) -> bool:
    return isinstance(row, dict) and str(row.get("commission_type") or "") == HOLD_TYPE


def _amount(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _phones_match(left: Any, right: Any) -> bool:
    from .partner_withdrawals import partner_phones_match

    return partner_phones_match(left, right)


def _code(value: Any) -> str:
    return str(value or "").strip()


def held_rows(commissions: List[Dict[str, Any]] | None, phone: str = "") -> List[Dict[str, Any]]:
    out = []
    for row in commissions or []:
        if not is_hold(row):
            continue
        if str(row.get("status") or "") != STATUS_HELD:
            continue
        if phone and not _phones_match(row.get("partner_phone"), phone):
            continue
        out.append(row)
    return out


def held_total(commissions: List[Dict[str, Any]] | None, phone: str) -> int:
    return sum(_amount(row.get("commission_amount")) for row in held_rows(commissions, phone))


def find_hold(
    commissions: List[Dict[str, Any]] | None,
    land_code: str,
    phone: str = "",
) -> Optional[Dict[str, Any]]:
    code = _code(land_code)
    if not code:
        return None
    for row in held_rows(commissions, phone):
        if _code(row.get("land_code")) == code:
            return row
    return None


def available_balance(
    commissions: List[Dict[str, Any]] | None,
    withdrawals: List[Dict[str, Any]] | None,
    phone: str,
) -> int:
    from .partner_withdrawals import withdrawable_balance

    gross = int(withdrawable_balance(commissions or [], withdrawals or [], phone))
    return max(0, gross - held_total(commissions, phone))


def wallet_parts(
    commissions: List[Dict[str, Any]] | None,
    withdrawals: List[Dict[str, Any]] | None,
    phone: str,
) -> Dict[str, int]:
    from .partner_withdrawals import withdrawable_balance

    total = int(withdrawable_balance(commissions or [], withdrawals or [], phone))
    blocked = held_total(commissions, phone)
    return {
        "wallet_total": total,
        "wallet_blocked": blocked,
        "wallet_available": max(0, total - blocked),
    }


def shortfall_message(required: int, available: int) -> str:
    from .deal_wallet import toman_fa

    need = max(0, int(required or 0))
    have = max(0, int(available or 0))
    short = max(0, need - have)
    return (
        f"برای انتشار، پورسانت {toman_fa(need)} باید در کیف پول بلوکه شود. "
        f"موجودی قابل استفاده: {toman_fa(have)}. کمبود: {toman_fa(short)}."
    )


def _next_id(commissions: List[Dict[str, Any]]) -> int:
    best = 0
    for row in commissions:
        if not isinstance(row, dict):
            continue
        try:
            best = max(best, int(row.get("id") or 0))
        except (TypeError, ValueError):
            continue
    return best + 1


def ensure_hold(
    commissions: List[Dict[str, Any]],
    withdrawals: List[Dict[str, Any]] | None,
    *,
    phone: str,
    land_code: str,
    amount: int,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """بلوکه را بساز یا به مبلغ جدید برسان. تکرار با همان مبلغ ردیف تازه نمی‌سازد."""
    need = _amount(amount)
    code = _code(land_code)
    owner = str(phone or "").strip()
    have = available_balance(commissions, withdrawals, owner)
    current = find_hold(commissions, code, owner)
    held_now = _amount(current.get("commission_amount")) if current else 0
    detail = {
        "required_amount": need,
        "balance": have,
        "shortfall": 0,
        "held_amount": held_now,
        "charge_path": WALLET_CHARGE_PATH,
    }
    if not code or not owner:
        return "invalid", detail
    if current and held_now == need:
        detail["idempotent"] = True
        return None, detail
    delta = need - held_now
    if delta > 0 and have < delta:
        detail["shortfall"] = delta - have
        detail["balance"] = have
        detail["message"] = shortfall_message(need, have + held_now)
        return "wallet_insufficient", detail
    stamp = iso_z(utcnow())
    if current is None:
        if need == 0:
            detail["idempotent"] = True
            return None, detail
        commissions.append({
            "id": _next_id(commissions),
            "commission_type": HOLD_TYPE,
            "partner_phone": owner,
            "land_code": code,
            "sale_amount": 0,
            "commission_pct": 0,
            "commission_amount": need,
            "status": STATUS_HELD,
            "created_at": stamp,
            "updated_at": stamp,
            "source": HOLD_SOURCE,
        })
    else:
        current["commission_amount"] = need
        current["updated_at"] = stamp
        if need == 0:
            current["status"] = STATUS_RELEASED
            current["released_at"] = stamp
            current["release_reason"] = "amount_zero"
    detail["held_amount"] = need
    detail["balance"] = available_balance(commissions, withdrawals, owner)
    detail["idempotent"] = False
    return None, detail


def listing_has_open_deal(land_code: str) -> bool:
    code = _code(land_code)
    if not code:
        return False
    try:
        from app.utils.storage import load_express_assignments
    except Exception:
        return False
    rows = load_express_assignments() or []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if _code(row.get("land_code")) != code:
            continue
        if str(row.get("status") or "").strip().lower() in _OPEN_DEAL_STATUSES:
            return True
    return False


def release_hold(
    commissions: List[Dict[str, Any]],
    land_code: str,
    *,
    reason: str,
    force: bool = False,
) -> bool:
    """آزاد کردن بلوکه. معاملهٔ باز مانع است مگر force."""
    if not force and listing_has_open_deal(land_code):
        return False
    row = find_hold(commissions, land_code)
    if row is None:
        return False
    stamp = iso_z(utcnow())
    row["status"] = STATUS_RELEASED
    row["released_at"] = stamp
    row["updated_at"] = stamp
    row["release_reason"] = str(reason or "").strip() or "released"
    return True


def settle_hold(
    commissions: List[Dict[str, Any]],
    land_code: str,
    *,
    deal_id: Any,
    deal_amount: int,
) -> Dict[str, int]:
    """بلوکه را مصرف کن. باقی‌مانده آزاد می‌شود؛ کمبود جداگانه از موجودی می‌رود."""
    row = find_hold(commissions, land_code)
    held = _amount(row.get("commission_amount")) if row else 0
    pay = _amount(deal_amount)
    consumed = min(held, pay)
    remainder = max(0, held - pay)
    extra = max(0, pay - held)
    if row is not None:
        stamp = iso_z(utcnow())
        row["status"] = STATUS_SETTLED
        row["settled_at"] = stamp
        row["updated_at"] = stamp
        row["settled_deal_id"] = str(deal_id or "")
        row["consumed_amount"] = consumed
        row["released_remainder"] = remainder
    return {"consumed": consumed, "remainder": remainder, "extra": extra}


def last_hold_detail() -> Dict[str, Any]:
    raw = _LAST_DETAIL.get()
    return dict(raw) if isinstance(raw, dict) else {}


def reserve_publish_hold(*, phone: str, land_code: str, amount: int) -> Tuple[Optional[str], Dict[str, Any]]:
    from app.utils.storage import load_express_commissions, load_partner_withdrawals, save_express_commissions

    from .deal_wallet import commission_store_lock

    with commission_store_lock():
        commissions = load_express_commissions() or []
        if not isinstance(commissions, list):
            commissions = []
        withdrawals = load_partner_withdrawals() or []
        if not isinstance(withdrawals, list):
            withdrawals = []
        err, detail = ensure_hold(
            commissions,
            withdrawals,
            phone=phone,
            land_code=land_code,
            amount=amount,
        )
        _LAST_DETAIL.set(dict(detail))
        if err is None and not detail.get("idempotent"):
            save_express_commissions(commissions)
        return err, detail


def release_publish_hold(land_code: str, *, reason: str, force: bool = False) -> bool:
    from app.utils.storage import load_express_commissions, save_express_commissions

    from .deal_wallet import commission_store_lock

    with commission_store_lock():
        commissions = load_express_commissions() or []
        if not isinstance(commissions, list):
            return False
        changed = release_hold(commissions, land_code, reason=reason, force=force)
        if changed:
            save_express_commissions(commissions)
        return changed


def listings_missing_hold(lands: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    """آگهی‌های زنده‌ای که هنوز بلوکه ندارند. خودبه‌خود از انتشار خارج نمی‌شوند."""
    from app.listings.service import is_published_for_sale, owner_phone
    from app.utils.storage import load_ads_cached, load_express_commissions

    if lands is None:
        lands = load_ads_cached() or []
    commissions = load_express_commissions() or []
    if not isinstance(commissions, list):
        commissions = []
    report = []
    for land in lands or []:
        if not isinstance(land, dict) or not is_published_for_sale(land):
            continue
        code = _code(land.get("code"))
        if not code or find_hold(commissions, code):
            continue
        extras = land.get("extras") if isinstance(land.get("extras"), dict) else {}
        stored = _amount(extras.get("express_commission_amount"))
        if stored <= 0:
            stored = commission_amount_for(
                land.get("price_total") or land.get("price"),
                extras.get("express_commission_pct"),
            )
        if stored <= 0:
            continue
        report.append({
            "land_code": code,
            "owner_phone": owner_phone(land),
            "required_amount": stored,
            "title": str(land.get("title") or ""),
        })
    return report
