# -*- coding: utf-8 -*-
"""Commercial JSON stores — fail-open, gated by commercial_enabled."""
from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from app.commercial.config import commercial_enabled
from app.commercial.interfaces import CounterOffer, Negotiation, Offer, Reservation

_LOCK = threading.Lock()
_NEGOTIATIONS = "commercial_negotiations.json"
_OFFERS = "commercial_offers.json"
_COUNTERS = "commercial_counters.json"
_RESERVATIONS = "commercial_reservations.json"


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


# ── Negotiations ───────────────────────────────────────────────────────────


def create_negotiation(
    *,
    land_code: str,
    partner_phone: str,
    buyer_phone: str = "",
    visit_request_id: str = "",
    contact_id: str = "",
    source: str = "manual",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    app=None,
) -> Optional[Negotiation]:
    if not commercial_enabled():
        return None
    code = str(land_code or "").strip()
    pp = _norm_phone(partner_phone)
    if not code or not pp:
        return None
    now = _now_iso()
    neg = Negotiation(
        id=_new_id(),
        land_code=code,
        partner_phone=pp,
        buyer_phone=_norm_phone(buyer_phone),
        visit_request_id=(visit_request_id or "").strip(),
        contact_id=(contact_id or "").strip(),
        status="open",
        source=(source or "manual").strip() or "manual",
        notes=(notes or "").strip(),
        created_at=now,
        updated_at=now,
        metadata=dict(metadata or {}),
    )
    try:
        with _LOCK:
            rows = _load_raw(_NEGOTIATIONS, app)
            # reuse open negotiation for same partner+land+buyer
            for i, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                if (
                    str(row.get("partner_phone") or "").strip() == pp
                    and str(row.get("land_code") or "").strip() == code
                    and str(row.get("status") or "") == "open"
                    and (
                        not neg.buyer_phone
                        or _norm_phone(str(row.get("buyer_phone") or "")) == neg.buyer_phone
                    )
                ):
                    existing = Negotiation.from_dict(row)
                    if visit_request_id and not existing.visit_request_id:
                        existing.visit_request_id = visit_request_id
                    if contact_id and not existing.contact_id:
                        existing.contact_id = contact_id
                    existing.updated_at = now
                    rows[i] = existing.to_dict()
                    _save_raw(_NEGOTIATIONS, rows, app)
                    return existing
            rows.append(neg.to_dict())
            _save_raw(_NEGOTIATIONS, rows, app)
        return neg
    except Exception:
        return None


def get_negotiation(negotiation_id: str, *, app=None) -> Optional[Negotiation]:
    if not commercial_enabled():
        return None
    nid = (negotiation_id or "").strip()
    if not nid:
        return None
    try:
        for row in _load_raw(_NEGOTIATIONS, app):
            if isinstance(row, dict) and str(row.get("id") or "") == nid:
                return Negotiation.from_dict(row)
    except Exception:
        return None
    return None


def update_negotiation_status(
    negotiation_id: str,
    status: str,
    *,
    app=None,
) -> Optional[Negotiation]:
    if not commercial_enabled():
        return None
    nid = (negotiation_id or "").strip()
    st = (status or "").strip()
    if not nid or st not in ("open", "accepted", "rejected", "expired", "cancelled"):
        return None
    try:
        with _LOCK:
            rows = _load_raw(_NEGOTIATIONS, app)
            for i, row in enumerate(rows):
                if isinstance(row, dict) and str(row.get("id") or "") == nid:
                    neg = Negotiation.from_dict(row)
                    neg.status = st
                    neg.updated_at = _now_iso()
                    rows[i] = neg.to_dict()
                    _save_raw(_NEGOTIATIONS, rows, app)
                    return neg
    except Exception:
        return None
    return None


def list_negotiations(
    *,
    partner_phone: str = "",
    buyer_phone: str = "",
    land_code: str = "",
    status: str = "",
    limit: int = 200,
    app=None,
) -> List[Negotiation]:
    if not commercial_enabled():
        return []
    pp = _norm_phone(partner_phone)
    bp = _norm_phone(buyer_phone)
    lc = str(land_code or "").strip()
    st = (status or "").strip()
    try:
        rows = _load_raw(_NEGOTIATIONS, app)
    except Exception:
        return []
    out: List[Negotiation] = []
    for row in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        if pp and _norm_phone(str(row.get("partner_phone") or "")) != pp:
            continue
        if bp and _norm_phone(str(row.get("buyer_phone") or "")) != bp:
            continue
        if lc and str(row.get("land_code") or "").strip() != lc:
            continue
        if st and str(row.get("status") or "").strip() != st:
            continue
        out.append(Negotiation.from_dict(row))
        if len(out) >= max(1, int(limit or 200)):
            break
    return out


# ── Offers ─────────────────────────────────────────────────────────────────


def create_offer(
    *,
    negotiation_id: str,
    amount: int,
    terms: str = "",
    proposed_by: str = "partner",
    land_code: str = "",
    partner_phone: str = "",
    buyer_phone: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    app=None,
) -> Optional[Offer]:
    if not commercial_enabled():
        return None
    nid = (negotiation_id or "").strip()
    try:
        amt = int(amount or 0)
    except (TypeError, ValueError):
        amt = 0
    if not nid or amt <= 0:
        return None
    now = _now_iso()
    offer = Offer(
        id=_new_id(),
        negotiation_id=nid,
        amount=amt,
        terms=(terms or "").strip(),
        proposed_by=(proposed_by or "partner").strip() or "partner",
        status="pending",
        land_code=str(land_code or "").strip(),
        partner_phone=_norm_phone(partner_phone),
        buyer_phone=_norm_phone(buyer_phone),
        notes=(notes or "").strip(),
        created_at=now,
        updated_at=now,
        metadata=dict(metadata or {}),
    )
    try:
        with _LOCK:
            rows = _load_raw(_OFFERS, app)
            rows.append(offer.to_dict())
            _save_raw(_OFFERS, rows, app)
        return offer
    except Exception:
        return None


def get_offer(offer_id: str, *, app=None) -> Optional[Offer]:
    if not commercial_enabled():
        return None
    oid = (offer_id or "").strip()
    if not oid:
        return None
    try:
        for row in _load_raw(_OFFERS, app):
            if isinstance(row, dict) and str(row.get("id") or "") == oid:
                return Offer.from_dict(row)
    except Exception:
        return None
    return None


def update_offer_status(
    offer_id: str,
    status: str,
    *,
    app=None,
) -> Optional[Offer]:
    if not commercial_enabled():
        return None
    oid = (offer_id or "").strip()
    st = (status or "").strip()
    if not oid or st not in (
        "pending",
        "countered",
        "accepted",
        "rejected",
        "withdrawn",
        "expired",
    ):
        return None
    try:
        with _LOCK:
            rows = _load_raw(_OFFERS, app)
            for i, row in enumerate(rows):
                if isinstance(row, dict) and str(row.get("id") or "") == oid:
                    offer = Offer.from_dict(row)
                    offer.status = st
                    offer.updated_at = _now_iso()
                    rows[i] = offer.to_dict()
                    _save_raw(_OFFERS, rows, app)
                    return offer
    except Exception:
        return None
    return None


def list_offers(
    *,
    negotiation_id: str = "",
    partner_phone: str = "",
    buyer_phone: str = "",
    land_code: str = "",
    status: str = "",
    limit: int = 200,
    app=None,
) -> List[Offer]:
    if not commercial_enabled():
        return []
    nid = (negotiation_id or "").strip()
    pp = _norm_phone(partner_phone)
    bp = _norm_phone(buyer_phone)
    lc = str(land_code or "").strip()
    st = (status or "").strip()
    try:
        rows = _load_raw(_OFFERS, app)
    except Exception:
        return []
    out: List[Offer] = []
    for row in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        if nid and str(row.get("negotiation_id") or "").strip() != nid:
            continue
        if pp and _norm_phone(str(row.get("partner_phone") or "")) != pp:
            continue
        if bp and _norm_phone(str(row.get("buyer_phone") or "")) != bp:
            continue
        if lc and str(row.get("land_code") or "").strip() != lc:
            continue
        if st and str(row.get("status") or "").strip() != st:
            continue
        out.append(Offer.from_dict(row))
        if len(out) >= max(1, int(limit or 200)):
            break
    return out


# ── Counters ───────────────────────────────────────────────────────────────


def create_counter(
    *,
    offer_id: str,
    negotiation_id: str,
    amount: int,
    terms: str = "",
    proposed_by: str = "buyer",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    app=None,
) -> Optional[CounterOffer]:
    if not commercial_enabled():
        return None
    oid = (offer_id or "").strip()
    nid = (negotiation_id or "").strip()
    try:
        amt = int(amount or 0)
    except (TypeError, ValueError):
        amt = 0
    if not oid or not nid or amt <= 0:
        return None
    now = _now_iso()
    counter = CounterOffer(
        id=_new_id(),
        offer_id=oid,
        negotiation_id=nid,
        amount=amt,
        terms=(terms or "").strip(),
        proposed_by=(proposed_by or "buyer").strip() or "buyer",
        status="pending",
        notes=(notes or "").strip(),
        created_at=now,
        updated_at=now,
        metadata=dict(metadata or {}),
    )
    try:
        with _LOCK:
            rows = _load_raw(_COUNTERS, app)
            rows.append(counter.to_dict())
            _save_raw(_COUNTERS, rows, app)
        return counter
    except Exception:
        return None


def list_counters(
    *,
    offer_id: str = "",
    negotiation_id: str = "",
    limit: int = 100,
    app=None,
) -> List[CounterOffer]:
    if not commercial_enabled():
        return []
    oid = (offer_id or "").strip()
    nid = (negotiation_id or "").strip()
    try:
        rows = _load_raw(_COUNTERS, app)
    except Exception:
        return []
    out: List[CounterOffer] = []
    for row in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        if oid and str(row.get("offer_id") or "").strip() != oid:
            continue
        if nid and str(row.get("negotiation_id") or "").strip() != nid:
            continue
        out.append(CounterOffer.from_dict(row))
        if len(out) >= max(1, int(limit or 100)):
            break
    return out


# ── Reservations (soft hold — never touch assignment) ──────────────────────


def create_reservation(
    *,
    negotiation_id: str,
    offer_id: str,
    land_code: str,
    partner_phone: str,
    buyer_phone: str = "",
    expires_at: str = "",
    hold_note: str = "",
    metadata: dict[str, Any] | None = None,
    app=None,
) -> Optional[Reservation]:
    if not commercial_enabled():
        return None
    nid = (negotiation_id or "").strip()
    oid = (offer_id or "").strip()
    code = str(land_code or "").strip()
    pp = _norm_phone(partner_phone)
    if not nid or not oid or not code or not pp:
        return None
    now = _now_iso()
    res = Reservation(
        id=_new_id(),
        negotiation_id=nid,
        offer_id=oid,
        land_code=code,
        partner_phone=pp,
        buyer_phone=_norm_phone(buyer_phone),
        status="held",
        expires_at=(expires_at or "").strip(),
        hold_note=(hold_note or "").strip(),
        created_at=now,
        updated_at=now,
        metadata=dict(metadata or {}),
    )
    try:
        with _LOCK:
            rows = _load_raw(_RESERVATIONS, app)
            rows.append(res.to_dict())
            _save_raw(_RESERVATIONS, rows, app)
        return res
    except Exception:
        return None


def update_reservation_status(
    reservation_id: str,
    status: str,
    *,
    app=None,
) -> Optional[Reservation]:
    if not commercial_enabled():
        return None
    rid = (reservation_id or "").strip()
    st = (status or "").strip()
    if not rid or st not in ("held", "expired", "released", "converted"):
        return None
    try:
        with _LOCK:
            rows = _load_raw(_RESERVATIONS, app)
            for i, row in enumerate(rows):
                if isinstance(row, dict) and str(row.get("id") or "") == rid:
                    res = Reservation.from_dict(row)
                    res.status = st
                    res.updated_at = _now_iso()
                    rows[i] = res.to_dict()
                    _save_raw(_RESERVATIONS, rows, app)
                    return res
    except Exception:
        return None
    return None


def get_reservation(reservation_id: str, *, app=None) -> Optional[Reservation]:
    if not commercial_enabled():
        return None
    rid = (reservation_id or "").strip()
    if not rid:
        return None
    try:
        for row in _load_raw(_RESERVATIONS, app):
            if isinstance(row, dict) and str(row.get("id") or "") == rid:
                return Reservation.from_dict(row)
    except Exception:
        return None
    return None


def list_reservations(
    *,
    partner_phone: str = "",
    buyer_phone: str = "",
    land_code: str = "",
    status: str = "",
    limit: int = 100,
    app=None,
) -> List[Reservation]:
    if not commercial_enabled():
        return []
    pp = _norm_phone(partner_phone)
    bp = _norm_phone(buyer_phone)
    lc = str(land_code or "").strip()
    st = (status or "").strip()
    try:
        rows = _load_raw(_RESERVATIONS, app)
    except Exception:
        return []
    out: List[Reservation] = []
    for row in reversed(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        if pp and _norm_phone(str(row.get("partner_phone") or "")) != pp:
            continue
        if bp and _norm_phone(str(row.get("buyer_phone") or "")) != bp:
            continue
        if lc and str(row.get("land_code") or "").strip() != lc:
            continue
        if st and str(row.get("status") or "").strip() != st:
            continue
        out.append(Reservation.from_dict(row))
        if len(out) >= max(1, int(limit or 100)):
            break
    return out
