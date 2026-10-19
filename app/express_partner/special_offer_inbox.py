# -*- coding: utf-8 -*-
"""صندوق پیشنهادهای همکار ویژه — آگهی‌های مالک خودش."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from .special_listings import listings_owned_by


def _norm_phone(phone: str) -> str:
    return re.sub(r"[^\d]", "", str(phone or "").strip())


def owned_land_codes(phone: str) -> Set[str]:
    return {
        str(land.get("code") or "").strip()
        for land in listings_owned_by(phone)
        if str(land.get("code") or "").strip()
    }


def offers_for_special_owner(phone: str) -> List[Dict[str, Any]]:
    try:
        from app.commercial.config import commercial_ui_enabled
        if not commercial_ui_enabled():
            return []
        from app.commercial import store
    except Exception:
        return []

    codes = owned_land_codes(phone)
    if not codes:
        return []
    # Offers on owned lands (any partner proposing on owner's listing)
    all_offers = store.list_offers(limit=500)
    out: List[Dict[str, Any]] = []
    for o in all_offers:
        if o.land_code not in codes:
            continue
        if o.status not in ("pending", "countered"):
            continue
        out.append({
            "id": o.id,
            "negotiation_id": o.negotiation_id,
            "land_code": o.land_code,
            "amount": o.amount,
            "terms": o.terms,
            "status": o.status,
            "partner_phone": o.partner_phone,
            "buyer_phone": o.buyer_phone,
            "proposed_by": o.proposed_by,
            "can_accept": o.status in ("pending", "countered"),
            "can_reject": o.status in ("pending", "countered"),
            "can_counter": o.status in ("pending", "countered"),
            "needs_action": True,
            "created_at": o.created_at,
            "updated_at": o.updated_at,
        })
    out.sort(key=lambda x: 0 if x.get("needs_action") else 1)
    return out


_OFFER_STATUS_FA = {
    "pending": "پیشنهاد باز",
    "countered": "پیشنهاد متقابل",
}


def offer_action_path(offer_id: str, action: str) -> str:
    """POST فرم همان دکمه‌های کارت وب: پذیرش، رد، متقابل."""
    return f"/express/partner/inbox-offers/{str(offer_id or '').strip()}/{str(action or '').strip()}"


def offer_pipeline_card(offer: Dict[str, Any] | None) -> Dict[str, Any]:
    """ردیف معامله برای cards. kind جداست تا با کارت بازدید قاطی نشود."""
    row = offer if isinstance(offer, dict) else {}
    oid = str(row.get("id") or "").strip()
    land_code = str(row.get("land_code") or "").strip()
    status = str(row.get("status") or "").strip()
    open_offer = status in ("pending", "countered")
    try:
        amount = int(row.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    title = "پیشنهاد قیمت" if not land_code else f"پیشنهاد قیمت · فایل {land_code}"

    def _flag(name: str) -> bool:
        if name in row:
            return bool(row.get(name))
        return open_offer

    return {
        "kind": "offer",
        "id": oid,
        "pipeline_tab": "deals",
        "land_code": land_code,
        "title": title,
        "amount": amount,
        "terms": str(row.get("terms") or "").strip(),
        "status": status,
        "status_label": _OFFER_STATUS_FA.get(status, status),
        "partner_phone": str(row.get("partner_phone") or "").strip(),
        "buyer_phone": str(row.get("buyer_phone") or "").strip(),
        "proposed_by": str(row.get("proposed_by") or "").strip(),
        "negotiation_id": str(row.get("negotiation_id") or "").strip(),
        "can_accept": _flag("can_accept"),
        "can_reject": _flag("can_reject"),
        "can_counter": _flag("can_counter"),
        "needs_action": bool(row.get("needs_action")) if "needs_action" in row else open_offer,
        "created_at": str(row.get("created_at") or "").strip(),
        "updated_at": str(row.get("updated_at") or row.get("created_at") or "").strip(),
        "return_to": "visits",
        "action_path": offer_action_path(oid, "{action}"),
        "actions": {
            "accept": offer_action_path(oid, "accept"),
            "reject": offer_action_path(oid, "reject"),
            "counter": offer_action_path(oid, "counter"),
        },
    }


def offer_pipeline_cards(offers: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for raw in offers or []:
        if not isinstance(raw, dict):
            continue
        card = offer_pipeline_card(raw)
        oid = str(card.get("id") or "").strip()
        if not oid or oid in seen:
            continue
        seen.add(oid)
        out.append(card)
    return out


def apply_special_offer_action(
    *,
    owner_phone: str,
    offer_id: str,
    action: str,
    amount: int = 0,
    terms: str = "",
) -> tuple:
    """action: accept | reject | counter"""
    try:
        from app.commercial.config import commercial_ui_enabled
        from app.commercial.service import get_offer, propose_counter, respond_offer

        if not commercial_ui_enabled():
            return None, "disabled"
    except Exception:
        return None, "unavailable"

    offer = get_offer(offer_id)
    if not offer:
        return None, "not_found"
    if offer.land_code not in owned_land_codes(owner_phone):
        return None, "forbidden"

    act = (action or "").strip().lower()
    if act in ("accept", "reject"):
        out = respond_offer(offer_id, action=act, actor_key=owner_phone)
        if not out:
            return None, "failed"
        return out, None
    if act == "counter":
        counter = propose_counter(
            offer_id=offer_id,
            amount=amount,
            terms=terms,
            proposed_by="special",
            actor_key=owner_phone,
        )
        if not counter:
            return None, "failed"
        return counter, None
    return None, "invalid_action"
