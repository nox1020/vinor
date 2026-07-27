# -*- coding: utf-8 -*-
"""تراکنش‌های پرداخت Vinor Plus — JSON store."""
from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional

STATUS_PENDING = "pending"
STATUS_PAID = "paid"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def new_transaction_id() -> str:
    return secrets.token_hex(12)


def load_all() -> List[Dict[str, Any]]:
    from app.utils.storage import load_zarinpal_plus_transactions

    items = load_zarinpal_plus_transactions() or []
    return items if isinstance(items, list) else []


def save_all(items: List[Dict[str, Any]]) -> None:
    from app.utils.storage import save_zarinpal_plus_transactions

    save_zarinpal_plus_transactions(items if isinstance(items, list) else [])


def find_by_id(txn_id: str) -> Optional[Dict[str, Any]]:
    tid = str(txn_id or "").strip()
    if not tid:
        return None
    for row in load_all():
        if isinstance(row, dict) and str(row.get("id") or "") == tid:
            return row
    return None


def find_by_authority(authority: str) -> Optional[Dict[str, Any]]:
    auth = str(authority or "").strip()
    if not auth:
        return None
    for row in load_all():
        if isinstance(row, dict) and str(row.get("authority") or "").strip() == auth:
            return row
    return None


def upsert(row: Dict[str, Any]) -> Dict[str, Any]:
    items = load_all()
    rid = str(row.get("id") or "").strip()
    if not rid:
        rid = new_transaction_id()
        row = dict(row)
        row["id"] = rid
    replaced = False
    out: List[Dict[str, Any]] = []
    for existing in items:
        if isinstance(existing, dict) and str(existing.get("id") or "") == rid:
            out.append(row)
            replaced = True
        elif isinstance(existing, dict):
            out.append(existing)
    if not replaced:
        out.append(row)
    save_all(out)
    return row


def create_pending(
    *,
    phone: str,
    partner_name: str,
    amount_toman: int,
    description: str,
) -> Dict[str, Any]:
    now = _utc_now_iso()
    row = {
        "id": new_transaction_id(),
        "phone": str(phone or "").strip(),
        "partner_name": str(partner_name or "").strip(),
        "amount_toman": int(amount_toman),
        "description": str(description or "").strip(),
        "status": STATUS_PENDING,
        "authority": "",
        "ref_id": "",
        "verify_code": None,
        "verify_message": "",
        "created_at": now,
        "updated_at": now,
        "paid_at": "",
    }
    return upsert(row)


def mark_failed(txn: Dict[str, Any], *, message: str = "", verify_code: Any = None) -> Dict[str, Any]:
    row = dict(txn)
    row["status"] = STATUS_FAILED
    row["verify_message"] = str(message or "").strip()
    row["verify_code"] = verify_code
    row["updated_at"] = _utc_now_iso()
    return upsert(row)


def mark_cancelled(txn: Dict[str, Any], *, message: str = "") -> Dict[str, Any]:
    row = dict(txn)
    row["status"] = STATUS_CANCELLED
    row["verify_message"] = str(message or "").strip()
    row["updated_at"] = _utc_now_iso()
    return upsert(row)


def mark_paid(
    txn: Dict[str, Any],
    *,
    ref_id: Any,
    verify_code: Any,
    verify_message: str = "",
    authority: str = "",
) -> Dict[str, Any]:
    row = dict(txn)
    row["status"] = STATUS_PAID
    if authority:
        row["authority"] = authority
    row["ref_id"] = str(ref_id or "").strip()
    row["verify_code"] = verify_code
    row["verify_message"] = str(verify_message or "").strip()
    now = _utc_now_iso()
    row["updated_at"] = now
    row["paid_at"] = now
    return upsert(row)


def attach_authority(txn: Dict[str, Any], authority: str) -> Dict[str, Any]:
    row = dict(txn)
    row["authority"] = str(authority or "").strip()
    row["updated_at"] = _utc_now_iso()
    return upsert(row)


def plus_grant_applied(txn: Dict[str, Any]) -> bool:
    return bool(txn.get("plus_grant_applied"))


def mark_plus_grant_applied(txn: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(txn)
    row["plus_grant_applied"] = True
    row["updated_at"] = _utc_now_iso()
    return upsert(row)
