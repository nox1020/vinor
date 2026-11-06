# -*- coding: utf-8 -*-
"""شارژ کیف پول مالک یا همکار از زرین‌پال. هر authority فقط یک‌بار موجودی را زیاد می‌کند."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.utils.dates import iso_z, utcnow

from .commission_escrow import TOPUP_SOURCE, WALLET_CHARGE_PATH
from .deal_wallet import commission_store_lock
from .zarinpal_client import payment_request, payment_verify, start_pay_url
from .zarinpal_config import effective_merchant_id, get_zarinpal_settings, payment_flow_active

TOPUP_PRESETS = (100_000, 500_000, 1_000_000, 5_000_000)
MIN_TOPUP = 1_000


def _amount(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _rows():
    from app.utils.storage import load_express_commissions

    rows = load_express_commissions() or []
    return rows if isinstance(rows, list) else []


def find_topup_by_authority(rows, authority: str):
    auth = str(authority or "").strip()
    if not auth:
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("source") or "") != TOPUP_SOURCE:
            continue
        if str(row.get("authority") or "").strip() == auth:
            return row
    return None


def find_topup_by_ref(rows, ref_id: str):
    ref = str(ref_id or "").strip()
    if not ref:
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("source") or "") != TOPUP_SOURCE:
            continue
        if str(row.get("ref_id") or "").strip() == ref and str(row.get("status") or "") == "approved":
            return row
    return None


def begin_wallet_topup(*, phone: str, amount: int) -> Tuple[bool, Optional[str], str]:
    from flask import url_for

    need = _amount(amount)
    if need < MIN_TOPUP:
        return False, None, "مبلغ شارژ خیلی کم است."
    if not payment_flow_active():
        return False, None, "درگاه پرداخت فعال نیست."
    cfg = get_zarinpal_settings()
    from app.utils.storage import save_express_commissions

    with commission_store_lock():
        rows = _rows()
        best = 0
        for row in rows:
            if isinstance(row, dict):
                try:
                    best = max(best, int(row.get("id") or 0))
                except (TypeError, ValueError):
                    continue
        stamp = iso_z(utcnow())
        rec = {
            "id": best + 1,
            "commission_type": "manual_adjustment",
            "partner_phone": str(phone or "").strip(),
            "land_code": "wallet",
            "sale_amount": 0,
            "commission_pct": 0,
            "commission_amount": need,
            "status": "pending",
            "created_at": stamp,
            "source": TOPUP_SOURCE,
            "authority": "",
            "ref_id": "",
        }
        rows.append(rec)
        save_express_commissions(rows)
        txn_id = rec["id"]
    callback = url_for("express_partner.wallet_zarinpal_callback", _external=True)
    req = payment_request(
        amount_toman=need,
        callback_url=callback,
        description="شارژ کیف پول وینور",
        metadata={"mobile": phone, "order_id": str(txn_id)},
        merchant_id=effective_merchant_id(cfg),
        sandbox=bool(cfg.get("sandbox")),
    )
    if not req.get("ok"):
        return False, None, "شروع پرداخت ممکن نشد."
    authority = str(req.get("authority") or "").strip()
    with commission_store_lock():
        rows = _rows()
        for row in rows:
            if isinstance(row, dict) and int(row.get("id") or 0) == int(txn_id):
                row["authority"] = authority
                break
        save_express_commissions(rows)
    return True, start_pay_url(authority, sandbox=bool(cfg.get("sandbox"))), ""


def complete_wallet_topup(authority: str, status_param: str) -> Dict[str, Any]:
    from app.utils.storage import save_express_commissions

    auth = str(authority or "").strip()
    if not auth:
        return {"ok": False, "reason": "missing_authority"}
    with commission_store_lock():
        rows = _rows()
        row = find_topup_by_authority(rows, auth)
        if row is None:
            return {"ok": False, "reason": "unknown_authority"}
        if str(row.get("status") or "") == "approved" and str(row.get("ref_id") or "").strip():
            return {"ok": True, "idempotent": True, "amount": _amount(row.get("commission_amount"))}
        if str(status_param or "").strip().upper() not in ("OK", "1"):
            row["status"] = "rejected"
            row["updated_at"] = iso_z(utcnow())
            save_express_commissions(rows)
            return {"ok": False, "reason": "cancelled"}
        cfg = get_zarinpal_settings()
        verified = payment_verify(
            amount_toman=_amount(row.get("commission_amount")),
            authority=auth,
            merchant_id=effective_merchant_id(cfg),
            sandbox=bool(cfg.get("sandbox")),
        )
        if not verified.get("ok"):
            row["status"] = "rejected"
            row["updated_at"] = iso_z(utcnow())
            save_express_commissions(rows)
            return {"ok": False, "reason": "verify_failed"}
        ref = str(verified.get("ref_id") or "").strip()
        prior = find_topup_by_ref(rows, ref)
        if prior is not None and prior is not row:
            return {"ok": True, "idempotent": True, "amount": _amount(prior.get("commission_amount"))}
        stamp = iso_z(utcnow())
        row["status"] = "approved"
        row["approved_at"] = stamp
        row["updated_at"] = stamp
        row["ref_id"] = ref
        save_express_commissions(rows)
        return {"ok": True, "idempotent": False, "amount": _amount(row.get("commission_amount")), "ref_id": ref}
