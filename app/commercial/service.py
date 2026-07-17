# -*- coding: utf-8 -*-
"""Public Commercial service — negotiation / offer / counter / reservation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Tuple

from app.commercial import store
from app.commercial.activity_hook import record_commercial_event
from app.commercial.config import (
    commercial_activity_hook_enabled,
    commercial_ai_tools_enabled,
    commercial_buyer_ui_enabled,
    commercial_enabled,
    commercial_ui_enabled,
    commercial_visit_bridge_enabled,
    commercial_workflow_enabled,
)
from app.commercial.interfaces import CounterOffer, Negotiation, Offer, Reservation


def commercial_status() -> dict[str, Any]:
    return {
        "commercial_enabled": commercial_enabled(),
        "commercial_ui_enabled": commercial_ui_enabled(),
        "commercial_buyer_ui_enabled": commercial_buyer_ui_enabled(),
        "commercial_ai_tools_enabled": commercial_ai_tools_enabled(),
        "commercial_activity_hook_enabled": commercial_activity_hook_enabled(),
        "commercial_workflow_enabled": commercial_workflow_enabled(),
        "commercial_visit_bridge_enabled": commercial_visit_bridge_enabled(),
        "phase": 3,
    }


def start_negotiation(
    *,
    land_code: str,
    partner_phone: str,
    buyer_phone: str = "",
    visit_request_id: str = "",
    contact_id: str = "",
    source: str = "manual",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
) -> Optional[Negotiation]:
    neg = store.create_negotiation(
        land_code=land_code,
        partner_phone=partner_phone,
        buyer_phone=buyer_phone,
        visit_request_id=visit_request_id,
        contact_id=contact_id,
        source=source,
        notes=notes,
        metadata=metadata,
    )
    if neg is not None:
        record_commercial_event(
            action="commercial_negotiation_opened",
            actor_key=neg.partner_phone,
            entity_type="negotiation",
            entity_id=neg.id,
            land_code=neg.land_code,
            summary=f"Negotiation opened for land {neg.land_code}",
            payload={"buyer_phone": neg.buyer_phone, "source": neg.source},
            subjects=[("negotiation", neg.id), ("partner", neg.partner_phone)],
        )
    return neg


def propose_offer(
    *,
    negotiation_id: str = "",
    land_code: str = "",
    partner_phone: str = "",
    buyer_phone: str = "",
    amount: int,
    terms: str = "",
    proposed_by: str = "partner",
    notes: str = "",
    visit_request_id: str = "",
) -> Optional[Offer]:
    nid = (negotiation_id or "").strip()
    if not nid:
        neg = start_negotiation(
            land_code=land_code,
            partner_phone=partner_phone,
            buyer_phone=buyer_phone,
            visit_request_id=visit_request_id,
            source="manual" if proposed_by != "ai" else "ai",
        )
        if neg is None:
            return None
        nid = neg.id
        land_code = land_code or neg.land_code
        partner_phone = partner_phone or neg.partner_phone
        buyer_phone = buyer_phone or neg.buyer_phone
    else:
        neg = store.get_negotiation(nid)
        if neg is None:
            return None
        land_code = land_code or neg.land_code
        partner_phone = partner_phone or neg.partner_phone
        buyer_phone = buyer_phone or neg.buyer_phone

    offer = store.create_offer(
        negotiation_id=nid,
        amount=amount,
        terms=terms,
        proposed_by=proposed_by,
        land_code=land_code,
        partner_phone=partner_phone,
        buyer_phone=buyer_phone,
        notes=notes,
    )
    if offer is not None:
        record_commercial_event(
            action="commercial_offer_proposed",
            actor_key=partner_phone or offer.partner_phone,
            entity_type="offer",
            entity_id=offer.id,
            land_code=offer.land_code,
            summary=f"Offer {offer.amount} proposed",
            payload={"negotiation_id": nid, "amount": offer.amount},
            subjects=[("offer", offer.id), ("negotiation", nid)],
        )
    return offer


def respond_offer(
    offer_id: str,
    *,
    action: str,
    actor_key: str = "",
) -> Optional[Offer]:
    """action: accept | reject | withdraw"""
    act = (action or "").strip().lower()
    status_map = {"accept": "accepted", "reject": "rejected", "withdraw": "withdrawn"}
    st = status_map.get(act)
    if not st:
        return None
    offer = store.update_offer_status(offer_id, st)
    if offer is None:
        return None
    if st == "accepted":
        store.update_negotiation_status(offer.negotiation_id, "accepted")
    elif st == "rejected":
        # keep negotiation open for further offers
        pass
    record_commercial_event(
        action="commercial_offer_responded",
        actor_key=actor_key or offer.partner_phone,
        entity_type="offer",
        entity_id=offer.id,
        land_code=offer.land_code,
        summary=f"Offer {st}",
        payload={"status": st, "negotiation_id": offer.negotiation_id},
        subjects=[("offer", offer.id), ("negotiation", offer.negotiation_id)],
    )
    return offer


def propose_counter(
    *,
    offer_id: str,
    amount: int,
    terms: str = "",
    proposed_by: str = "buyer",
    notes: str = "",
    actor_key: str = "",
) -> Optional[CounterOffer]:
    offer = store.get_offer(offer_id)
    if offer is None or offer.status not in ("pending", "countered"):
        return None
    counter = store.create_counter(
        offer_id=offer.id,
        negotiation_id=offer.negotiation_id,
        amount=amount,
        terms=terms,
        proposed_by=proposed_by,
        notes=notes,
    )
    if counter is None:
        return None
    store.update_offer_status(offer.id, "countered")
    record_commercial_event(
        action="commercial_offer_responded",
        actor_key=actor_key or proposed_by,
        entity_type="counter_offer",
        entity_id=counter.id,
        land_code=offer.land_code,
        summary=f"Counter {counter.amount}",
        payload={"offer_id": offer.id, "amount": counter.amount},
        subjects=[("offer", offer.id), ("counter_offer", counter.id)],
    )
    return counter


def hold_reservation(
    *,
    offer_id: str,
    hold_note: str = "",
    expires_hours: int = 48,
    actor_key: str = "",
) -> Optional[Reservation]:
    """Soft reservation from accepted offer. Never touches assignment/commission."""
    offer = store.get_offer(offer_id)
    if offer is None:
        return None
    if offer.status != "accepted":
        # auto-accept if still pending when partner explicitly reserves
        if offer.status == "pending":
            offer = store.update_offer_status(offer_id, "accepted") or offer
            store.update_negotiation_status(offer.negotiation_id, "accepted")
        else:
            return None
    expires = (
        datetime.now(timezone.utc) + timedelta(hours=max(1, int(expires_hours or 48)))
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = store.create_reservation(
        negotiation_id=offer.negotiation_id,
        offer_id=offer.id,
        land_code=offer.land_code,
        partner_phone=offer.partner_phone,
        buyer_phone=offer.buyer_phone,
        expires_at=expires,
        hold_note=hold_note,
    )
    if res is not None:
        record_commercial_event(
            action="commercial_reservation_held",
            actor_key=actor_key or offer.partner_phone,
            entity_type="reservation",
            entity_id=res.id,
            land_code=res.land_code,
            summary="Soft reservation held",
            payload={"offer_id": offer.id, "expires_at": expires},
            subjects=[("reservation", res.id), ("offer", offer.id)],
        )
    return res


def release_reservation(
    reservation_id: str,
    *,
    actor_key: str = "",
) -> Optional[Reservation]:
    res = store.update_reservation_status(reservation_id, "released")
    if res is not None:
        record_commercial_event(
            action="commercial_reservation_held",
            actor_key=actor_key or res.partner_phone,
            entity_type="reservation",
            entity_id=res.id,
            land_code=res.land_code,
            summary="Reservation released",
            payload={"status": "released"},
        )
    return res


def convert_reservation(
    reservation_id: str,
    *,
    actor_key: str = "",
) -> Optional[Reservation]:
    """Mark reservation converted and optionally link Closing Deal (no mark-in-tx)."""
    res = store.update_reservation_status(reservation_id, "converted")
    if res is None:
        return None
    record_commercial_event(
        action="commercial_reservation_held",
        actor_key=actor_key or res.partner_phone,
        entity_type="reservation",
        entity_id=res.id,
        land_code=res.land_code,
        summary="Reservation converted",
        payload={"status": "converted"},
    )
    try:
        from app.closing.deal_bridge import maybe_link_reservation_to_deal

        maybe_link_reservation_to_deal(
            reservation_id=res.id,
            partner_phone=res.partner_phone,
            land_code=res.land_code,
            offer_id=res.offer_id,
            buyer_phone=res.buyer_phone,
        )
    except Exception:
        pass
    return res


def list_partner_negotiations(partner_phone: str, *, limit: int = 200) -> List[Negotiation]:
    return store.list_negotiations(partner_phone=partner_phone, limit=limit)


def list_partner_offers(partner_phone: str, *, limit: int = 200) -> List[Offer]:
    return store.list_offers(partner_phone=partner_phone, limit=limit)


def list_buyer_offers(buyer_phone: str, *, limit: int = 200) -> List[Offer]:
    return store.list_offers(buyer_phone=buyer_phone, limit=limit)


def get_offer(offer_id: str) -> Optional[Offer]:
    return store.get_offer(offer_id)


def get_negotiation(negotiation_id: str) -> Optional[Negotiation]:
    return store.get_negotiation(negotiation_id)


def list_offer_counters(offer_id: str) -> List[CounterOffer]:
    return store.list_counters(offer_id=offer_id)


def list_partner_reservations(partner_phone: str, *, limit: int = 100) -> List[Reservation]:
    return store.list_reservations(partner_phone=partner_phone, limit=limit)
