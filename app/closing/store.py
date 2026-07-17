# -*- coding: utf-8 -*-
"""Closing JSON stores — fail-open, gated by closing_enabled."""
from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from app.closing.config import closing_enabled
from app.closing.interfaces import Contract, Deal, Payment, Settlement, SettlementParty

_LOCK = threading.Lock()
_DEALS = "closing_deals.json"
_CONTRACTS = "closing_contracts.json"
_PAYMENTS = "closing_payments.json"
_SETTLEMENTS = "closing_settlements.json"

DEAL_STATUSES = frozenset(
    {"draft", "in_transaction", "contracted", "settling", "closed", "cancelled"}
)
CONTRACT_DOC_STATUSES = frozenset({"draft", "sent", "signed", "void"})
PAYMENT_STATUSES = frozenset({"planned", "due", "paid", "waived", "cancelled"})
SETTLEMENT_STATUSES = frozenset({"open", "partial", "settled", "cancelled"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path(file_name: str, app=None) -> str:
    from app.utils.storage import data_dir

    return os.path.join(data_dir(app), file_name)


def _load_raw(file_name: str, app=None) -> List[dict[str, Any]]:
    from app.utils.storage import _load

    data = _load(_path(file_name, app))
    return data if isinstance(data, list) else []


def _save_raw(file_name: str, rows: List[dict[str, Any]], app=None) -> None:
    from app.utils.storage import _save

    _save(_path(file_name, app), rows)


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _norm_phone(phone: str) -> str:
    raw = (phone or "").strip()
    if not raw:
        return ""
    try:
        from app.services.sms import normalize_iran_mobile

        return normalize_iran_mobile(raw) or raw
    except Exception:
        return raw


# ── Deals ──────────────────────────────────────────────────────────────────


def upsert_deal(
    *,
    land_code: str,
    partner_phone: str,
    buyer_phone: str = "",
    assignment_status: str = "",
    commission_id: str = "",
    reservation_id: str = "",
    offer_id: str = "",
    sale_amount: int = 0,
    status: str = "draft",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    app=None,
) -> Optional[Deal]:
    """Create or update Deal by partner+land (+ commission_id when present). Never mutates assignment."""
    if not closing_enabled():
        return None
    code = str(land_code or "").strip()
    pp = _norm_phone(partner_phone)
    if not code or not pp:
        return None
    st = (status or "draft").strip() or "draft"
    if st not in DEAL_STATUSES:
        st = "draft"
    try:
        amt = int(sale_amount or 0)
    except (TypeError, ValueError):
        amt = 0
    now = _now_iso()
    cid = str(commission_id or "").strip()
    try:
        with _LOCK:
            rows = _load_raw(_DEALS, app)
            for i, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                same_partner_land = (
                    _norm_phone(str(row.get("partner_phone") or "")) == pp
                    and str(row.get("land_code") or "").strip() == code
                )
                same_commission = cid and str(row.get("commission_id") or "").strip() == cid
                active = str(row.get("status") or "") not in ("closed", "cancelled")
                if same_commission or (same_partner_land and active and not cid):
                    deal = Deal.from_dict(row)
                    if buyer_phone:
                        deal.buyer_phone = _norm_phone(buyer_phone)
                    if assignment_status:
                        deal.assignment_status = assignment_status.strip()
                    if cid:
                        deal.commission_id = cid
                    if reservation_id:
                        deal.reservation_id = str(reservation_id).strip()
                    if offer_id:
                        deal.offer_id = str(offer_id).strip()
                    if amt > 0:
                        deal.sale_amount = amt
                    deal.status = st
                    if notes:
                        deal.notes = notes.strip()
                    if metadata:
                        deal.metadata.update(dict(metadata))
                    deal.updated_at = now
                    rows[i] = deal.to_dict()
                    _save_raw(_DEALS, rows, app)
                    return deal
            deal = Deal(
                id=_new_id(),
                land_code=code,
                partner_phone=pp,
                buyer_phone=_norm_phone(buyer_phone),
                assignment_status=(assignment_status or "").strip(),
                commission_id=cid,
                reservation_id=str(reservation_id or "").strip(),
                offer_id=str(offer_id or "").strip(),
                sale_amount=max(0, amt),
                status=st,
                notes=(notes or "").strip(),
                created_at=now,
                updated_at=now,
                metadata=dict(metadata or {}),
            )
            rows.append(deal.to_dict())
            _save_raw(_DEALS, rows, app)
            return deal
    except Exception:
        return None


def get_deal(deal_id: str, *, app=None) -> Optional[Deal]:
    if not closing_enabled():
        return None
    did = (deal_id or "").strip()
    if not did:
        return None
    try:
        for row in _load_raw(_DEALS, app):
            if isinstance(row, dict) and str(row.get("id") or "") == did:
                return Deal.from_dict(row)
    except Exception:
        return None
    return None


def update_deal_status(deal_id: str, status: str, *, app=None) -> Optional[Deal]:
    if not closing_enabled():
        return None
    did = (deal_id or "").strip()
    st = (status or "").strip()
    if not did or st not in DEAL_STATUSES:
        return None
    try:
        with _LOCK:
            rows = _load_raw(_DEALS, app)
            for i, row in enumerate(rows):
                if isinstance(row, dict) and str(row.get("id") or "") == did:
                    deal = Deal.from_dict(row)
                    deal.status = st
                    deal.updated_at = _now_iso()
                    rows[i] = deal.to_dict()
                    _save_raw(_DEALS, rows, app)
                    return deal
    except Exception:
        return None
    return None


def patch_deal(
    deal_id: str,
    *,
    reservation_id: str | None = None,
    offer_id: str | None = None,
    buyer_phone: str | None = None,
    assignment_status: str | None = None,
    commission_id: str | None = None,
    sale_amount: int | None = None,
    status: str | None = None,
    notes: str | None = None,
    app=None,
) -> Optional[Deal]:
    if not closing_enabled():
        return None
    did = (deal_id or "").strip()
    if not did:
        return None
    try:
        with _LOCK:
            rows = _load_raw(_DEALS, app)
            for i, row in enumerate(rows):
                if isinstance(row, dict) and str(row.get("id") or "") == did:
                    deal = Deal.from_dict(row)
                    if reservation_id is not None:
                        deal.reservation_id = str(reservation_id).strip()
                    if offer_id is not None:
                        deal.offer_id = str(offer_id).strip()
                    if buyer_phone is not None:
                        deal.buyer_phone = _norm_phone(buyer_phone)
                    if assignment_status is not None:
                        deal.assignment_status = assignment_status.strip()
                    if commission_id is not None:
                        deal.commission_id = str(commission_id).strip()
                    if sale_amount is not None:
                        try:
                            deal.sale_amount = max(0, int(sale_amount))
                        except (TypeError, ValueError):
                            pass
                    if status is not None and status.strip() in DEAL_STATUSES:
                        deal.status = status.strip()
                    if notes is not None:
                        deal.notes = notes.strip()
                    deal.updated_at = _now_iso()
                    rows[i] = deal.to_dict()
                    _save_raw(_DEALS, rows, app)
                    return deal
    except Exception:
        return None
    return None


def list_deals(
    *,
    partner_phone: str = "",
    land_code: str = "",
    status: str = "",
    commission_id: str = "",
    limit: int = 200,
    app=None,
) -> List[Deal]:
    if not closing_enabled():
        return []
    pp = _norm_phone(partner_phone)
    lc = str(land_code or "").strip()
    st = (status or "").strip()
    cid = str(commission_id or "").strip()
    try:
        rows = _load_raw(_DEALS, app)
    except Exception:
        return []
    out: List[Deal] = []
    for row in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        if pp and _norm_phone(str(row.get("partner_phone") or "")) != pp:
            continue
        if lc and str(row.get("land_code") or "").strip() != lc:
            continue
        if st and str(row.get("status") or "").strip() != st:
            continue
        if cid and str(row.get("commission_id") or "").strip() != cid:
            continue
        out.append(Deal.from_dict(row))
        if len(out) >= max(1, int(limit or 200)):
            break
    return out


# ── Contracts ──────────────────────────────────────────────────────────────


def create_contract(
    *,
    deal_id: str,
    title: str = "",
    document_status: str = "draft",
    document_ref: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    app=None,
) -> Optional[Contract]:
    if not closing_enabled():
        return None
    did = (deal_id or "").strip()
    if not did:
        return None
    ds = (document_status or "draft").strip() or "draft"
    if ds not in CONTRACT_DOC_STATUSES:
        ds = "draft"
    now = _now_iso()
    contract = Contract(
        id=_new_id(),
        deal_id=did,
        title=(title or "").strip() or "قرارداد",
        document_status=ds,
        document_ref=(document_ref or "").strip(),
        notes=(notes or "").strip(),
        created_at=now,
        updated_at=now,
        metadata=dict(metadata or {}),
    )
    try:
        with _LOCK:
            rows = _load_raw(_CONTRACTS, app)
            rows.append(contract.to_dict())
            _save_raw(_CONTRACTS, rows, app)
        return contract
    except Exception:
        return None


def get_contract(contract_id: str, *, app=None) -> Optional[Contract]:
    if not closing_enabled():
        return None
    cid = (contract_id or "").strip()
    if not cid:
        return None
    try:
        for row in _load_raw(_CONTRACTS, app):
            if isinstance(row, dict) and str(row.get("id") or "") == cid:
                return Contract.from_dict(row)
    except Exception:
        return None
    return None


def update_contract_document(
    contract_id: str,
    *,
    document_status: str = "",
    document_ref: str = "",
    title: str = "",
    app=None,
) -> Optional[Contract]:
    if not closing_enabled():
        return None
    cid = (contract_id or "").strip()
    if not cid:
        return None
    try:
        with _LOCK:
            rows = _load_raw(_CONTRACTS, app)
            for i, row in enumerate(rows):
                if isinstance(row, dict) and str(row.get("id") or "") == cid:
                    c = Contract.from_dict(row)
                    if document_status and document_status.strip() in CONTRACT_DOC_STATUSES:
                        c.document_status = document_status.strip()
                        if c.document_status == "signed" and not c.signed_at:
                            c.signed_at = _now_iso()
                    if document_ref:
                        c.document_ref = document_ref.strip()
                    if title:
                        c.title = title.strip()
                    c.updated_at = _now_iso()
                    rows[i] = c.to_dict()
                    _save_raw(_CONTRACTS, rows, app)
                    return c
    except Exception:
        return None
    return None


def list_contracts(
    *,
    deal_id: str = "",
    limit: int = 100,
    app=None,
) -> List[Contract]:
    if not closing_enabled():
        return []
    did = (deal_id or "").strip()
    try:
        rows = _load_raw(_CONTRACTS, app)
    except Exception:
        return []
    out: List[Contract] = []
    for row in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        if did and str(row.get("deal_id") or "").strip() != did:
            continue
        out.append(Contract.from_dict(row))
        if len(out) >= max(1, int(limit or 100)):
            break
    return out


# ── Payments ───────────────────────────────────────────────────────────────


def create_payment(
    *,
    deal_id: str,
    amount: int,
    contract_id: str = "",
    due_at: str = "",
    status: str = "planned",
    milestone_label: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    app=None,
) -> Optional[Payment]:
    if not closing_enabled():
        return None
    did = (deal_id or "").strip()
    try:
        amt = int(amount or 0)
    except (TypeError, ValueError):
        amt = 0
    if not did or amt <= 0:
        return None
    st = (status or "planned").strip() or "planned"
    if st not in PAYMENT_STATUSES:
        st = "planned"
    now = _now_iso()
    pay = Payment(
        id=_new_id(),
        deal_id=did,
        contract_id=(contract_id or "").strip(),
        amount=amt,
        due_at=(due_at or "").strip(),
        status=st,
        milestone_label=(milestone_label or "").strip(),
        notes=(notes or "").strip(),
        created_at=now,
        updated_at=now,
        metadata=dict(metadata or {}),
    )
    try:
        with _LOCK:
            rows = _load_raw(_PAYMENTS, app)
            rows.append(pay.to_dict())
            _save_raw(_PAYMENTS, rows, app)
        return pay
    except Exception:
        return None


def get_payment(payment_id: str, *, app=None) -> Optional[Payment]:
    if not closing_enabled():
        return None
    pid = (payment_id or "").strip()
    if not pid:
        return None
    try:
        for row in _load_raw(_PAYMENTS, app):
            if isinstance(row, dict) and str(row.get("id") or "") == pid:
                return Payment.from_dict(row)
    except Exception:
        return None
    return None


def update_payment_status(
    payment_id: str,
    status: str,
    *,
    app=None,
) -> Optional[Payment]:
    if not closing_enabled():
        return None
    pid = (payment_id or "").strip()
    st = (status or "").strip()
    if not pid or st not in PAYMENT_STATUSES:
        return None
    try:
        with _LOCK:
            rows = _load_raw(_PAYMENTS, app)
            for i, row in enumerate(rows):
                if isinstance(row, dict) and str(row.get("id") or "") == pid:
                    pay = Payment.from_dict(row)
                    pay.status = st
                    if st == "paid" and not pay.paid_at:
                        pay.paid_at = _now_iso()
                    pay.updated_at = _now_iso()
                    rows[i] = pay.to_dict()
                    _save_raw(_PAYMENTS, rows, app)
                    return pay
    except Exception:
        return None
    return None


def list_payments(
    *,
    deal_id: str = "",
    contract_id: str = "",
    status: str = "",
    limit: int = 100,
    app=None,
) -> List[Payment]:
    if not closing_enabled():
        return []
    did = (deal_id or "").strip()
    cid = (contract_id or "").strip()
    st = (status or "").strip()
    try:
        rows = _load_raw(_PAYMENTS, app)
    except Exception:
        return []
    out: List[Payment] = []
    for row in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        if did and str(row.get("deal_id") or "").strip() != did:
            continue
        if cid and str(row.get("contract_id") or "").strip() != cid:
            continue
        if st and str(row.get("status") or "").strip() != st:
            continue
        out.append(Payment.from_dict(row))
        if len(out) >= max(1, int(limit or 100)):
            break
    return out


# ── Settlements ────────────────────────────────────────────────────────────


def create_settlement(
    *,
    deal_id: str,
    parties: list[dict[str, Any]] | list[SettlementParty] | None = None,
    withdrawal_id: str = "",
    status: str = "open",
    total_amount: int = 0,
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    app=None,
) -> Optional[Settlement]:
    if not closing_enabled():
        return None
    did = (deal_id or "").strip()
    if not did:
        return None
    parsed: List[SettlementParty] = []
    for p in parties or []:
        if isinstance(p, SettlementParty):
            parsed.append(p)
        elif isinstance(p, dict):
            parsed.append(SettlementParty.from_dict(p))
    st = (status or "open").strip() or "open"
    if st not in SETTLEMENT_STATUSES:
        st = "open"
    try:
        total = int(total_amount or 0)
    except (TypeError, ValueError):
        total = 0
    if total <= 0 and parsed:
        total = sum(p.amount for p in parsed)
    now = _now_iso()
    settlement = Settlement(
        id=_new_id(),
        deal_id=did,
        parties=parsed,
        withdrawal_id=str(withdrawal_id or "").strip(),
        status=st,
        total_amount=max(0, total),
        notes=(notes or "").strip(),
        created_at=now,
        updated_at=now,
        metadata=dict(metadata or {}),
    )
    try:
        with _LOCK:
            rows = _load_raw(_SETTLEMENTS, app)
            rows.append(settlement.to_dict())
            _save_raw(_SETTLEMENTS, rows, app)
        return settlement
    except Exception:
        return None


def get_settlement(settlement_id: str, *, app=None) -> Optional[Settlement]:
    if not closing_enabled():
        return None
    sid = (settlement_id or "").strip()
    if not sid:
        return None
    try:
        for row in _load_raw(_SETTLEMENTS, app):
            if isinstance(row, dict) and str(row.get("id") or "") == sid:
                return Settlement.from_dict(row)
    except Exception:
        return None
    return None


def update_settlement_status(
    settlement_id: str,
    status: str,
    *,
    withdrawal_id: str = "",
    app=None,
) -> Optional[Settlement]:
    if not closing_enabled():
        return None
    sid = (settlement_id or "").strip()
    st = (status or "").strip()
    if not sid or st not in SETTLEMENT_STATUSES:
        return None
    try:
        with _LOCK:
            rows = _load_raw(_SETTLEMENTS, app)
            for i, row in enumerate(rows):
                if isinstance(row, dict) and str(row.get("id") or "") == sid:
                    s = Settlement.from_dict(row)
                    s.status = st
                    if withdrawal_id:
                        s.withdrawal_id = str(withdrawal_id).strip()
                    s.updated_at = _now_iso()
                    rows[i] = s.to_dict()
                    _save_raw(_SETTLEMENTS, rows, app)
                    return s
    except Exception:
        return None
    return None


def list_settlements(
    *,
    deal_id: str = "",
    status: str = "",
    limit: int = 100,
    app=None,
) -> List[Settlement]:
    if not closing_enabled():
        return []
    did = (deal_id or "").strip()
    st = (status or "").strip()
    try:
        rows = _load_raw(_SETTLEMENTS, app)
    except Exception:
        return []
    out: List[Settlement] = []
    for row in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        if did and str(row.get("deal_id") or "").strip() != did:
            continue
        if st and str(row.get("status") or "").strip() != st:
            continue
        out.append(Settlement.from_dict(row))
        if len(out) >= max(1, int(limit or 100)):
            break
    return out
