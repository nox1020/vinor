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
        })
    out.sort(key=lambda x: 0 if x.get("needs_action") else 1)
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
